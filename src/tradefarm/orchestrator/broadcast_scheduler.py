"""Pure-Python presentation scheduler for Broadcast OS moments.

The scheduler intentionally does not publish events or know about the live
orchestrator. It only arbitrates which ``BroadcastMoment`` objects may occupy
presentation outputs at a given time.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from time import monotonic
from typing import Literal

from tradefarm.orchestrator.broadcast_os import BroadcastMoment, BroadcastOutput

Clock = Callable[[], float]

MomentState = Literal["active", "queued", "preempted"]


@dataclass(frozen=True, slots=True)
class EnqueueResult:
    """Outcome from adding a moment to the scheduler queue."""

    accepted: bool
    moment: BroadcastMoment
    reason: str
    replaced: BroadcastMoment | None = None
    dropped: tuple[BroadcastMoment, ...] = ()


@dataclass(frozen=True, slots=True)
class ScheduledMoment:
    """A moment occupying (or contending for) one or more presentation outputs.

    ``state`` distinguishes a moment that is live (``"active"``), one that was
    enqueued but blocked by an equal-or-higher-priority slot (``"queued"``), and
    one that was bumped off its output by a higher-priority moment
    (``"preempted"``). The dashboard's slot/queue indicator reads this directly.
    """

    moment: BroadcastMoment
    outputs: tuple[BroadcastOutput, ...]
    started_at: float
    expires_at: float
    preempted: tuple[BroadcastMoment, ...] = ()
    state: MomentState = "active"


@dataclass(frozen=True, slots=True)
class _QueueItem:
    moment: BroadcastMoment
    enqueued_at: float
    sequence: int


def _priority(moment: BroadcastMoment) -> int:
    return max(0, min(100, int(moment.priority)))


def _ttl_sec(moment: BroadcastMoment) -> int:
    return max(1, int(moment.ttl_sec))


def _outputs(moment: BroadcastMoment) -> tuple[BroadcastOutput, ...]:
    return tuple(dict.fromkeys(moment.outputs))


class BroadcastScheduler:
    """Arbitrate Broadcast OS moments across output slots.

    Queue order is priority first, then enqueue time. An active moment blocks
    equal- or lower-priority queued moments on overlapping outputs until its
    TTL expires. A higher-priority moment preempts lower-priority active
    moments that occupy any output it needs.
    """

    def __init__(self, *, max_queue_size: int = 32, clock: Clock = monotonic) -> None:
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be at least 1")
        self.max_queue_size = max_queue_size
        self._clock = clock
        self._sequence = 0
        self._queued: dict[str, _QueueItem] = {}
        self._active_by_output: dict[BroadcastOutput, ScheduledMoment] = {}

    @property
    def queued(self) -> tuple[BroadcastMoment, ...]:
        """Queued moments in dispatch order."""

        return tuple(item.moment for item in self._ordered_queue())

    @property
    def active_slots(self) -> dict[BroadcastOutput, ScheduledMoment]:
        """Active output slots keyed by output name."""

        return dict(self._active_by_output)

    @property
    def active_moments(self) -> tuple[ScheduledMoment, ...]:
        """Unique active moments, sorted by activation time."""

        return self._unique_scheduled(self._active_by_output.values())

    def enqueue(self, moment: BroadcastMoment, *, now: float | None = None) -> EnqueueResult:
        """Add or replace a queued moment without dispatching it."""

        at = self._now(now)
        self.expire(now=at)
        if self._is_active(moment.id):
            return EnqueueResult(False, moment, "active")

        replaced: BroadcastMoment | None = None
        existing = self._queued.get(moment.id)
        if existing is None:
            self._sequence += 1
            item = _QueueItem(moment=moment, enqueued_at=at, sequence=self._sequence)
        else:
            replaced = existing.moment
            item = _QueueItem(
                moment=moment, enqueued_at=existing.enqueued_at, sequence=existing.sequence
            )
        self._queued[moment.id] = item

        dropped = self._trim_queue()
        accepted = moment.id not in {dropped_moment.id for dropped_moment in dropped}
        reason = "dropped"
        if accepted:
            reason = "replaced" if replaced is not None else "queued"
        return EnqueueResult(accepted, moment, reason, replaced=replaced, dropped=dropped)

    def submit(
        self, moment: BroadcastMoment, *, now: float | None = None
    ) -> tuple[ScheduledMoment, ...]:
        """Enqueue a moment and return every moment that can start now."""

        at = self._now(now)
        self.enqueue(moment, now=at)
        return self.drain(now=at)

    def submit_slots(
        self, moment: BroadcastMoment, *, now: float | None = None
    ) -> tuple[ScheduledMoment, ...]:
        """Submit a moment and return every slot-state change it caused.

        Returns the newly ``"active"`` moments (with their ``preempted`` lists),
        a ``"preempted"`` entry per bumped moment, and a ``"queued"`` entry for
        ``moment`` itself if it could not start now. This is what the broadcast
        layer fans out as ``broadcast_slot`` events so the dashboard reflects
        the real queue/preemption state instead of always reporting active.
        """

        at = self._now(now)
        activated = self.submit(moment, now=at)
        slots: list[ScheduledMoment] = list(activated)

        seen_preempted: set[str] = set()
        for active in activated:
            for bumped in active.preempted:
                if bumped.id in seen_preempted:
                    continue
                seen_preempted.add(bumped.id)
                slots.append(
                    ScheduledMoment(
                        moment=bumped,
                        outputs=_outputs(bumped),
                        started_at=at,
                        expires_at=at,
                        state="preempted",
                    )
                )

        if self._is_queued(moment.id):
            slots.append(
                ScheduledMoment(
                    moment=moment,
                    outputs=_outputs(moment),
                    started_at=at,
                    expires_at=at,
                    state="queued",
                )
            )
        return tuple(slots)

    def drain(self, *, now: float | None = None) -> tuple[ScheduledMoment, ...]:
        """Start all queued moments whose output slots are available."""

        at = self._now(now)
        self.expire(now=at)
        scheduled: list[ScheduledMoment] = []

        while True:
            item = self._next_ready_item()
            if item is None:
                break
            self._queued.pop(item.moment.id, None)
            scheduled.append(self._activate(item.moment, now=at))

        return tuple(scheduled)

    def expire(self, *, now: float | None = None) -> tuple[ScheduledMoment, ...]:
        """Expire active output slots whose TTL has elapsed."""

        at = self._now(now)
        expired_ids = {
            active.moment.id
            for active in self._active_by_output.values()
            if active.expires_at <= at
        }
        if not expired_ids:
            return ()

        expired = [
            active for active in self._active_by_output.values() if active.moment.id in expired_ids
        ]
        for output, active in list(self._active_by_output.items()):
            if active.moment.id in expired_ids:
                self._active_by_output.pop(output, None)
        return self._unique_scheduled(expired)

    def _now(self, now: float | None) -> float:
        return self._clock() if now is None else float(now)

    def _ordered_queue(self) -> tuple[_QueueItem, ...]:
        return tuple(
            sorted(
                self._queued.values(),
                key=lambda item: (-_priority(item.moment), item.enqueued_at, item.sequence),
            )
        )

    def _trim_queue(self) -> tuple[BroadcastMoment, ...]:
        dropped: list[BroadcastMoment] = []
        while len(self._queued) > self.max_queue_size:
            worst = min(
                self._queued.values(),
                key=lambda item: (_priority(item.moment), -item.enqueued_at, -item.sequence),
            )
            dropped.append(worst.moment)
            self._queued.pop(worst.moment.id, None)
        return tuple(dropped)

    def _is_active(self, moment_id: str) -> bool:
        return any(active.moment.id == moment_id for active in self._active_by_output.values())

    def _is_queued(self, moment_id: str) -> bool:
        return moment_id in self._queued

    def _next_ready_item(self) -> _QueueItem | None:
        for item in self._ordered_queue():
            if self._can_activate(item.moment):
                return item
        return None

    def _can_activate(self, moment: BroadcastMoment) -> bool:
        candidate_priority = _priority(moment)
        for output in _outputs(moment):
            active = self._active_by_output.get(output)
            if active is not None and _priority(active.moment) >= candidate_priority:
                return False
        return True

    def _activate(self, moment: BroadcastMoment, *, now: float) -> ScheduledMoment:
        outputs = _outputs(moment)
        preempted = self._preempt_lower_priority(outputs, _priority(moment))
        scheduled = ScheduledMoment(
            moment=moment,
            outputs=outputs,
            started_at=now,
            expires_at=now + _ttl_sec(moment),
            preempted=preempted,
        )
        for output in outputs:
            self._active_by_output[output] = scheduled
        return scheduled

    def _preempt_lower_priority(
        self,
        outputs: tuple[BroadcastOutput, ...],
        candidate_priority: int,
    ) -> tuple[BroadcastMoment, ...]:
        preempted: dict[str, BroadcastMoment] = {}
        for output in outputs:
            active = self._active_by_output.get(output)
            if active is not None and _priority(active.moment) < candidate_priority:
                preempted[active.moment.id] = active.moment
        if not preempted:
            return ()

        for output, active in list(self._active_by_output.items()):
            if active.moment.id in preempted:
                self._active_by_output.pop(output, None)
        return tuple(preempted.values())

    def _unique_scheduled(
        self, scheduled: Iterable[ScheduledMoment]
    ) -> tuple[ScheduledMoment, ...]:
        by_key: dict[tuple[str, float], ScheduledMoment] = {}
        for active in scheduled:
            by_key[(active.moment.id, active.started_at)] = active
        return tuple(
            sorted(by_key.values(), key=lambda active: (active.started_at, active.moment.id))
        )
