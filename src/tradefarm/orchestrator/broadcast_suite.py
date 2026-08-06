"""BroadcastSuite — the orchestrator's presentation/interactivity layer.

Extracted from the ``Orchestrator`` god-object (issue #6). The suite OWNS every
always-on presentation sidecar that used to live as a separate field on the
orchestrator:

- ``AutoDirector``    — auto-fires broadcast moments from agent/market state
- ``StreakWatcher``   — broadcasts macros from trade-history patterns
- ``CommentaryLoop``  — Bloomberg-style LLM one-liner every ~45s
- ``YouTubeChatPoller`` — surfaces real audience chat onto the WS bus
- ``PredictionsBoard`` — audience prediction rounds
- ``AudienceCoordinator`` — sentiment + pins + predictions wiring

plus the broadcast recap ledger + slot scheduler (installed as the module-global
arbiter while the suite is running).

The orchestrator keeps a single ``self._broadcast_suite`` and calls
``start()`` / ``stop()`` on it as a unit. Behavior is identical to the prior
inline implementation:

* arbiter is installed on ``start()`` (not at construction), so unit tests that
  build a bare orchestrator don't pollute the module globals;
* dependency order on start — predictions is constructed *before* the audience
  coordinator so the latter can link to it;
* teardown order on stop — sidecars are drained first (they may still emit
  moments during ``stop()``), then the arbiter is uninstalled last so those
  in-flight moments still route through the ledger/scheduler;
* each sidecar's ``start()`` is awaited (not fire-and-forget) so a boot-time
  failure surfaces instead of being swallowed by a discarded ``create_task``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, TypeVar

import structlog

from tradefarm.orchestrator.audience import AudienceCoordinator
from tradefarm.orchestrator.auto_director import AutoDirector
from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler
from tradefarm.orchestrator.commentary_loop import CommentaryLoop
from tradefarm.orchestrator.predictions import PredictionsBoard
from tradefarm.orchestrator.streak_watcher import StreakWatcher
from tradefarm.orchestrator.youtube_chat import YouTubeChatPoller

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()


class _Sidecar(Protocol):
    """Minimal contract for an always-on background coordinator.

    Every sidecar's ``start()`` is a short coroutine that kicks off its own
    internal loop task and returns; awaiting it surfaces any boot-time
    exception instead of stranding it on a discarded ``create_task``.
    """

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


_SidecarT = TypeVar("_SidecarT", bound=_Sidecar)


def attach_crash_logger(task: asyncio.Task, *, name: str) -> asyncio.Task:
    """Attach a done-callback that logs a hard loop crash.

    Issue #6 (low-severity nit): each sidecar's inner ``self._run()`` task is
    spawned fire-and-forget. Without an observer, a crash (rather than a clean
    cancel) surfaces only as a bare "Task exception was never retrieved" warning
    at GC time, with no structured context. This callback logs
    ``background_loop_crashed`` for any non-cancel exception so the failure is
    attributable. Shared so every loop task the suite owns is supervised
    identically.
    """

    def _on_done(t: asyncio.Task) -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            log.error("background_loop_crashed", name=name, error=str(exc))

    task.add_done_callback(_on_done)
    return task


# 0.16.0 — shared daily-recap moment builder. The scheduler and the
# admin ``/recap/push`` endpoint both call this so the two paths
# can't drift on the canonical payload shape. Top-level function (not a
# method on BroadcastSuite) so the admin router can import it without
# dragging the suite's full constructor.
def _build_daily_recap_moment(
    date_str: str,
    *,
    moment_id: str | None = None,
    week_id: str | None = None,
) -> Any:
    """Build the canonical 4pm-ET live recap ``BroadcastMoment``.

    Shape matches the design doc (item 4.5): ``kind="day_leader"`` +
    ``trigger="daily_recap"`` + ``outputs=("recap_log",)`` only. The
    rotator mounts ``LiveRecapScene`` when this moment lands.

    ``date_str`` is the ET ISO date for the headline. ``moment_id`` is
    auto-generated when omitted; the admin path passes one so its
    toast can show it. ``week_id`` is for the ``metadata.week_id``
    field; defaults to the ISO trading week for ``date_str`` (Sunday-
    start, matching the rollup's bucket convention).
    """
    import uuid as _uuid
    from datetime import date as _date

    from tradefarm.orchestrator.broadcast_os import BroadcastMoment
    from tradefarm.session.weekly_rollup import week_id_for as _week_id_for

    resolved_id = moment_id or f"daily-recap-{date_str}-{_uuid.uuid4().hex[:8]}"
    resolved_week = week_id or _week_id_for(_date.fromisoformat(date_str))
    return BroadcastMoment(
        id=resolved_id,
        kind="day_leader",
        title="Closing bell - today's recap",
        priority=88,
        color="neutral",
        trigger="daily_recap",
        outputs=("recap_log",),
        ttl_sec=60,
        metadata={
            "date": date_str,
            "week_id": resolved_week,
        },
    )


class BroadcastSuite:
    """Owns the presentation sidecars + the broadcast arbiter as a unit."""

    def __init__(self, orch: "Orchestrator", *, record_path: Path | None = None) -> None:
        self._orch = orch
        # Broadcast recap ledger + slot scheduler. Constructed here but only
        # INSTALLED as module globals when start() runs (see Orchestrator
        # audit fix C15 — installing at construction polluted test globals).
        # ``record_path`` opts the ledger into NDJSON-on-disk recording;
        # ``close()`` (called by stop()) flushes + releases the handle.
        self.ledger = BroadcastRecapLedger(record_path=record_path)
        self.scheduler = BroadcastScheduler()
        # Presentation/interactivity sidecars (None until start()).
        self.auto_director: AutoDirector | None = None
        self.streak_watcher: StreakWatcher | None = None
        self.commentary_loop: CommentaryLoop | None = None
        self.youtube_chat: YouTubeChatPoller | None = None
        self.predictions: PredictionsBoard | None = None
        self.audience: AudienceCoordinator | None = None
        # 0.16.0 — daily-recap poll task. The suite owns the task; the
        # orchestrator's start_background calls start_daily_recap_scheduler
        # and stop_background calls stop_daily_recap_scheduler so the
        # loop's lifetime is bound to the suite's (not the arbiter's).
        self._daily_recap_task: asyncio.Task | None = None

    async def _start_sidecar(
        self,
        current: _SidecarT | None,
        factory: Callable[[], _SidecarT],
    ) -> _SidecarT:
        """Construct (if absent) and start one always-on sidecar.

        Issue #6: each ``start()`` is AWAITED directly rather than wrapped in
        a discarded ``asyncio.create_task``. The old pattern swallowed any
        exception raised before the sidecar's inner loop spawned ("Task
        exception was never retrieved") and left that sidecar silently dead;
        awaiting lets the error propagate out of ``start()`` at boot.
        ``start()`` itself only kicks off the internal loop task, so awaiting
        does not block on the loop body.
        """
        if current is not None:
            return current
        sidecar = factory()
        await sidecar.start()
        return sidecar

    async def start(self) -> None:
        """Install the arbiter and start every sidecar as a unit. Idempotent.

        Predictions is constructed before the audience coordinator so the
        latter can link to it.
        """
        # Audit fix (Q): install the broadcast arbiter here (not at
        # construction) so unit tests that build a bare suite/orchestrator
        # don't silently pollute the module-global state.
        from tradefarm.orchestrator import broadcast_os as _bos

        _bos.install_broadcast_arbiter(self.ledger, self.scheduler)

        orch = self._orch
        self.auto_director = await self._start_sidecar(
            self.auto_director, lambda: AutoDirector(orch=orch)
        )
        self.streak_watcher = await self._start_sidecar(
            self.streak_watcher, lambda: StreakWatcher(orch=orch)
        )
        self.commentary_loop = await self._start_sidecar(
            self.commentary_loop, lambda: CommentaryLoop(orch=orch)
        )
        # YouTube Live Chat poller — always constructed; the poller itself
        # checks ``settings.youtube_chat_enabled`` and stays dormant when off.
        self.youtube_chat = await self._start_sidecar(
            self.youtube_chat, lambda: YouTubeChatPoller(orch=orch)
        )
        # Audience predictions board — depends on agent list being final.
        self.predictions = await self._start_sidecar(
            self.predictions, lambda: PredictionsBoard(orch=orch)
        )
        # Audience coordinator — wires chat commands into sentiment + pins
        # + predictions. Built AFTER predictions so the link is in place.
        self.audience = await self._start_sidecar(
            self.audience,
            lambda: AudienceCoordinator(orch=orch, predictions=self.predictions),
        )

    async def stop(self) -> None:
        """Drain every sidecar then uninstall the arbiter. Idempotent.

        Each coordinator may still emit broadcast moments during its
        ``stop()`` (e.g. a "stream offline" banner). Those need the arbiter to
        still be installed, so the arbiter is uninstalled LAST — symmetric to
        ``start()``.
        """
        if self.auto_director is not None:
            await self.auto_director.stop()
            self.auto_director = None
        if self.streak_watcher is not None:
            await self.streak_watcher.stop()
            self.streak_watcher = None
        if self.commentary_loop is not None:
            await self.commentary_loop.stop()
            self.commentary_loop = None
        if self.youtube_chat is not None:
            await self.youtube_chat.stop()
            self.youtube_chat = None
        if self.audience is not None:
            await self.audience.stop()
            self.audience = None
        if self.predictions is not None:
            await self.predictions.stop()
            self.predictions = None

        # Audit fix (round 3 U): uninstall the broadcast arbiter AFTER every
        # sidecar has stopped. Uninstalling first would mean in-flight
        # ``publish_broadcast_moment`` calls during stop() bypass the
        # ledger/scheduler. Symmetric to start().
        from tradefarm.orchestrator import broadcast_os as _bos

        _bos.install_broadcast_arbiter(None, None)
        # Flush + close the on-disk record handle AFTER the arbiter is
        # uninstalled so no in-flight writes from a draining sidecar land
        # on a closed file. Idempotent — safe to call on a ledger that
        # was never opted into recording.
        self.ledger.close()

    def close(self) -> None:
        """Flush + close the recap ledger's on-disk record handle. Idempotent.

        Exposed as a separate sync method so callers (tests, the orchestrator
        shutdown path) can release the file handle without going through the
        full async ``stop()`` flow.
        """
        self.ledger.close()

    # ------------------------------------------------------------------
    # 0.16.0 — 4pm ET live recap scheduler.
    #
    # Lives on the suite (not the orchestrator) because the suite already
    # owns the recap ledger + broadcast arbiter; the scheduler is the
    # canonical producer of the recap moments, and operators care about
    # its lifecycle as part of the "presentation layer" rather than the
    # trading scheduler's VOD/tick loops.
    #
    # Pattern follows the VOD scheduler in ``orchestrator.scheduler`` —
    # poll every N seconds, gate on the ET clock + a per-day idempotency
    # row, fire exactly once per NYSE trading day. The 30s interval is
    # tighter than the VOD scheduler's 60s so the operator's "already
    # pushed" toast (after a 4:00:30 push) sees a fresh idempotency row
    # on the next tick.
    # ------------------------------------------------------------------

    async def start_daily_recap_scheduler(self) -> None:
        """Spawn the daily-recap poll loop. Idempotent.

        Mirrors the sidecar pattern: ``start()`` is awaited (not
        fire-and-forget) so a boot-time failure surfaces here. The
        inner poll task is created via ``attach_crash_logger`` so a
        hard loop crash logs ``background_loop_crashed`` rather than
        surfacing as a bare "Task exception was never retrieved" at
        GC time.
        """
        if self._daily_recap_task is not None:
            return
        self._daily_recap_task = asyncio.ensure_future(self.run_daily_recap_scheduler())
        self._daily_recap_task.set_name("orch_daily_recap")
        attach_crash_logger(self._daily_recap_task, name="orch_daily_recap")

    async def stop_daily_recap_scheduler(self) -> None:
        """Cancel the daily-recap poll loop. Idempotent.

        Symmetric to ``start_daily_recap_scheduler``; the orchestrator's
        ``stop_background`` calls this so a clean shutdown doesn't leave
        a poll loop spinning on a now-defunct event bus.
        """
        t = self._daily_recap_task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._daily_recap_task = None

    async def run_daily_recap_scheduler(self) -> None:
        """Poll every 30s; fire the 4pm-ET recap moment once per trading day.

        Master switch: ``settings.daily_recap_enabled`` (env var, default
        True). When False the loop parks forever on an ``asyncio.Event``
        so the operator can ship the code dark and flip the switch
        without a restart — symmetric to ``run_vod_scheduler``'s
        ``vod_pipeline_enabled`` handling.

        Fire condition: ET clock is in [16:00, 16:30) AND
        ``is_market_closed_for_n_minutes(0)`` is True (so a holiday /
        weekend at 16:00 ET doesn't trip the gate) AND no
        ``daily_recap_fired`` row exists for today's ET date.

        Per-day idempotency: the row is written *after*
        ``publish_broadcast_moment`` returns. A row-write failure logs
        + drops (we don't roll back the publish — a duplicate fire on
        the next tick is harmless because ``publish_broadcast_moment``
        is naturally idempotent at the consumer layer: the stream's
        ``seenBroadcastMomentIds`` dedup ring short-circuits the
        second moment for 1.5s and a 30s poll gap is well outside
        the dedup window, so a real second fire would be visible —
        and rare enough that a structured warning is the right
        response rather than a crash).
        """
        from tradefarm.config import settings as _settings

        if not _settings.daily_recap_enabled:
            log.info("daily_recap_scheduler_disabled")
            # Park forever; cancellation is the only way out.
            await asyncio.Event().wait()
            return

        log.info("daily_recap_scheduler_started", poll_sec=30)
        poll_sec = 30
        while True:
            try:
                should = await self._should_fire_daily_recap()
                if should:
                    await self._fire_daily_recap_moment()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                # A transient calendar/DB error shouldn't kill the loop.
                # Log + continue; the next tick (30s later) gets another shot.
                log.exception("daily_recap_scheduler_loop_failed", error=str(exc))
            await asyncio.sleep(poll_sec)

    async def _should_fire_daily_recap(self) -> bool:
        """Return True iff the 4pm-ET recap should fire on this tick.

        Gates, in order:

        1. ET clock is in [16:00, 16:30). A 30-min grace window so a
           slow tick at 16:00:07 doesn't get skipped. After 16:30 we
           stop trying — the next day's auto-fire takes over.
        2. ``is_market_closed_for_n_minutes(0)`` is True. The
           predicate already encodes the holiday calendar (returns
           False on a weekend or holiday even at 16:00 ET) so we
           don't need a separate holiday list.
        3. No ``daily_recap_fired`` row for today — the per-day
           idempotency check. After a successful fire, the row is
           written so a process restart at 16:02 doesn't re-fire.

        All three are best-effort, in-memory checks; an exception in
        any one of them returns False (the loop body catches and
        continues).
        """
        from tradefarm.market.hours import ET as _ET
        from tradefarm.market_clock import is_market_closed_for_n_minutes
        from tradefarm.runtime.clock import now_utc as _runtime_clock_now_utc
        from tradefarm.storage import repo as _repo

        now_et = _runtime_clock_now_utc().astimezone(_ET)
        if not (now_et.hour == 16 and 0 <= now_et.minute < 30):
            return False
        if not is_market_closed_for_n_minutes(0):
            return False
        today = now_et.date().isoformat()
        existing = await _repo.find_daily_recap_for_date(today)
        return existing is None

    async def _fire_daily_recap_moment(self) -> None:
        """Construct + publish the recap moment and write the idempotency row.

        Separated from ``_should_fire_daily_recap`` so the loop's body
        reads as "ask / fire / sleep" and the fire side-effects
        (publish, DB write) are isolated. The publish is unconditional
        here — the caller already decided to fire by calling us.

        The DB write is wrapped in a try/except that LOGS but does NOT
        RAISE. A row-write miss is recoverable (the next tick re-fires
        if the row is still missing), but a publish miss would mean
        the audience never saw the moment. Publish first, write second.
        """
        from tradefarm.market.hours import ET as _ET
        from tradefarm.orchestrator.broadcast_os import publish_broadcast_moment
        from tradefarm.runtime.clock import now_utc as _runtime_clock_now_utc
        from tradefarm.session.weekly_rollup import week_id_for as _week_id_for
        from tradefarm.storage import repo as _repo

        now_et = _runtime_clock_now_utc().astimezone(_ET)
        date_str = now_et.date().isoformat()
        week_id = _week_id_for(now_et.date())
        moment = _build_daily_recap_moment(date_str, week_id=week_id)
        await publish_broadcast_moment(moment, emit_legacy=False)
        log.info(
            "daily_recap_scheduler_fired",
            moment_id=moment.id,
            date=date_str,
            week_id=week_id,
        )
        try:
            await _repo.record_daily_recap_fired(
                date=date_str,
                moment_id=moment.id,
                fired_at=_runtime_clock_now_utc().isoformat(),
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "daily_recap_scheduler_idempotency_write_failed",
                date=date_str,
                moment_id=moment.id,
                error=str(exc),
            )

        # 0.20.0 — snapshot the day's strategy attribution so the
        # /pnl/by-strategy/timeseries endpoint doesn't have to
        # re-aggregate on every chart poll. Wrapped in its own
        # try/except so a snapshot-write failure is non-fatal —
        # the recap moment has already been published; the chart
        # would just fall back to live aggregation for this day.
        try:
            from tradefarm.storage import strategy_attribution as _sa

            n = await _sa.compute_and_store_for_date(now_et.date())
            log.info(
                "strategy_attribution_snapshot_written",
                date=date_str,
                rows=n,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "strategy_attribution_snapshot_write_failed",
                date=date_str,
                error=str(exc),
            )
