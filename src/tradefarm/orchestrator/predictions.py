"""Audience predictions — pick-winner + spy-direction.

Two singleton predictions for the v1 broadcast:

- ``pick-winner``  : "Pick today's winner agent". Free-form option text — the
                     agent universe is dynamic so we don't pre-enumerate.
- ``spy-direction``: "Will SPY close green?". Options ``["up", "down"]``.

Lifecycle keyed off the ET wall clock:

- pre-9:30 ET    → ``open``     (accept votes)
- 9:30 ET        → ``locked``   (votes rejected, tally frozen)
- 16:00 ET       → ``revealed`` (winning option resolved + published)
- post-17:00 ET  → reset to ``open`` for the next session

State is in-memory only. One vote per voter (per prediction) — late votes
update the option silently.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

import structlog

from tradefarm.api.events import publish_event
from tradefarm.market.hours import ET

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()

PredictionId = Literal["pick-winner", "spy-direction"]
PredictionStatus = Literal["open", "locked", "revealed"]

# ET boundary times.
LOCK_TIME = time(9, 30)   # 9:30 AM ET → market open
REVEAL_TIME = time(16, 0)  # 4:00 PM ET → market close
RESET_TIME = time(17, 0)   # 5:00 PM ET → next-session reset

POLL_INTERVAL_SEC: float = 30.0
PUBLISH_DEBOUNCE_SEC: float = 1.0
HEARTBEAT_SEC: float = 10.0

SPY_SYMBOL: str = "SPY"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _now_et() -> datetime:
    return datetime.now(tz=ET)


@dataclass
class _Prediction:
    """One prediction (mutated in place across the day)."""

    id: str
    question: str
    options: list[str]
    status: PredictionStatus = "open"
    tally: dict[str, int] = field(default_factory=dict)
    voters: dict[str, str] = field(default_factory=dict)  # voter → option
    winning_option: str | None = None
    locks_at: datetime | None = None  # UTC
    reveals_at: datetime | None = None  # UTC
    last_publish: datetime | None = None  # UTC
    last_heartbeat: datetime | None = None  # UTC

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "question": self.question,
            "options": list(self.options),
            "status": self.status,
            "tally": dict(self.tally),
            "locks_at": self.locks_at.isoformat() if self.locks_at else "",
            "reveals_at": self.reveals_at.isoformat() if self.reveals_at else "",
            "winning_option": self.winning_option,
        }


@dataclass
class PredictionsBoard:
    """Owns the two predictions and their lifecycle."""

    orch: "Orchestrator"
    poll_interval_sec: float = POLL_INTERVAL_SEC
    publish_debounce_sec: float = PUBLISH_DEBOUNCE_SEC
    heartbeat_sec: float = HEARTBEAT_SEC

    _predictions: dict[str, _Prediction] = field(default_factory=dict, init=False, repr=False)
    _session_date: Any = field(default=None, init=False, repr=False)
    _spy_baseline: float | None = field(default=None, init=False, repr=False)
    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    # ------------------------------------------------------------------
    # Lifecycle.
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Spin up the lifecycle loop. Idempotent."""
        if self._task is not None:
            return
        self._seed_session(_now_et())
        self._task = asyncio.create_task(self._run(), name="orch_predictions")
        log.info("predictions_started", interval_sec=self.poll_interval_sec)

    async def stop(self) -> None:
        """Cancel the lifecycle loop and await its exit."""
        self._stopped = True
        t = self._task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopped:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("predictions_loop_failed", error=str(e))
            await asyncio.sleep(self.poll_interval_sec)

    # ------------------------------------------------------------------
    # Session seeding.
    # ------------------------------------------------------------------

    def _seed_session(self, now_et_dt: datetime) -> None:
        """(Re)create both predictions for the current ET session.

        Idempotent within the same session date — only rebuilds when the
        date rolls over. The SPY baseline is also reset.
        """
        session_date = now_et_dt.date()
        if self._session_date == session_date and self._predictions:
            return
        self._session_date = session_date
        self._spy_baseline = None

        locks_at_et = datetime.combine(session_date, LOCK_TIME, tzinfo=ET)
        reveals_at_et = datetime.combine(session_date, REVEAL_TIME, tzinfo=ET)
        locks_at_utc = locks_at_et.astimezone(timezone.utc)
        reveals_at_utc = reveals_at_et.astimezone(timezone.utc)

        agent_names = [a.state.name for a in self.orch.agents]
        self._predictions = {
            "pick-winner": _Prediction(
                id="pick-winner",
                question="Pick today's winner agent",
                options=agent_names,
                locks_at=locks_at_utc,
                reveals_at=reveals_at_utc,
            ),
            "spy-direction": _Prediction(
                id="spy-direction",
                question="Will SPY close green?",
                options=["up", "down"],
                locks_at=locks_at_utc,
                reveals_at=reveals_at_utc,
            ),
        }
        log.info("predictions_seeded", session_date=str(session_date))

    # ------------------------------------------------------------------
    # Public state access.
    # ------------------------------------------------------------------

    def snapshot(self) -> list[dict[str, Any]]:
        """Return current-state payloads for both predictions."""
        return [p.to_payload() for p in self._predictions.values()]

    # ------------------------------------------------------------------
    # Vote ingestion.
    # ------------------------------------------------------------------

    async def record_vote(
        self, prediction_id: str, voter: str, option: str,
    ) -> bool:
        """Record one vote. Returns True if accepted, False if rejected.

        Rejection reasons:
        - Unknown prediction id.
        - Prediction is locked or revealed (not open).
        - Option doesn't match a known option (only enforced when the
          option set is bounded — e.g. ``spy-direction``).

        ``pick-winner`` accepts any free-form text as the option (matching
        is best-effort against agent names at reveal time, and operators
        can manually fix it). One vote per voter — re-voting overwrites.
        """
        pred = self._predictions.get(prediction_id)
        if pred is None:
            return False
        if pred.status != "open":
            log.info(
                "prediction_vote_rejected",
                prediction_id=prediction_id,
                reason="not_open",
                status=pred.status,
            )
            return False

        option = option.strip()
        if not option:
            return False

        # For spy-direction, only "up" / "down" are valid.
        if prediction_id == "spy-direction":
            option = option.lower()
            if option not in ("up", "down"):
                return False

        previous = pred.voters.get(voter)
        if previous == option:
            # No-op re-vote — still publish a heartbeat? No, just drop it.
            return True
        if previous is not None and previous in pred.tally:
            pred.tally[previous] -= 1
            if pred.tally[previous] <= 0:
                pred.tally.pop(previous, None)
        pred.voters[voter] = option
        pred.tally[option] = pred.tally.get(option, 0) + 1
        await self._maybe_publish(pred, force=False)
        return True

    # ------------------------------------------------------------------
    # Lifecycle tick — called every poll_interval_sec from _run() and
    # directly from tests.
    # ------------------------------------------------------------------

    async def tick(self, now_et_dt: datetime | None = None) -> None:
        """Advance the lifecycle one step + emit any due heartbeats."""
        now_et_dt = now_et_dt or _now_et()
        # Track the SPY baseline (first observed mark of the session).
        if self._spy_baseline is None:
            mark = self.orch.last_marks.get(SPY_SYMBOL)
            if mark is not None and mark > 0:
                self._spy_baseline = float(mark)

        # Daily reset after RESET_TIME — start a brand-new session.
        if now_et_dt.time() >= RESET_TIME and self._session_date is not None:
            new_session_date = now_et_dt.date()
            if new_session_date > self._session_date or (
                new_session_date == self._session_date
                and any(p.status == "revealed" for p in self._predictions.values())
            ):
                # Bump session_date to "tomorrow" for the post-17:00 reset on
                # the same calendar day, so we don't immediately re-lock.
                self._session_date = new_session_date + timedelta(days=1)
                self._spy_baseline = None
                self._build_fresh_session()
                return

        # Seed the session if we somehow have none (defensive).
        if not self._predictions:
            self._seed_session(now_et_dt)

        now_t = now_et_dt.time()
        for pred in self._predictions.values():
            # open → locked at 9:30 ET
            if pred.status == "open" and now_t >= LOCK_TIME and now_t < REVEAL_TIME:
                pred.status = "locked"
                await self._maybe_publish(pred, force=True)
                log.info("prediction_locked", id=pred.id, tally=dict(pred.tally))
            # locked → revealed at 16:00 ET
            elif pred.status in ("open", "locked") and now_t >= REVEAL_TIME:
                # Force the lock first (in case we skipped past 9:30 in tests).
                pred.status = "locked"
                pred.winning_option = self._resolve_winner(pred)
                pred.status = "revealed"
                await self._maybe_publish(pred, force=True)
                log.info(
                    "prediction_revealed",
                    id=pred.id,
                    winning_option=pred.winning_option,
                    tally=dict(pred.tally),
                )

        # Emit heartbeats for open predictions on a slow cadence.
        for pred in self._predictions.values():
            if pred.status != "open":
                continue
            now_utc = _utcnow()
            last = pred.last_heartbeat
            if last is None or (now_utc - last).total_seconds() >= self.heartbeat_sec:
                pred.last_heartbeat = now_utc
                await self._maybe_publish(pred, force=True)

    def _build_fresh_session(self) -> None:
        """Tear down the current predictions and reseed (post-17:00 reset)."""
        agent_names = [a.state.name for a in self.orch.agents]
        session_date = self._session_date
        if session_date is None:
            return
        locks_at_et = datetime.combine(session_date, LOCK_TIME, tzinfo=ET)
        reveals_at_et = datetime.combine(session_date, REVEAL_TIME, tzinfo=ET)
        locks_at_utc = locks_at_et.astimezone(timezone.utc)
        reveals_at_utc = reveals_at_et.astimezone(timezone.utc)
        self._predictions = {
            "pick-winner": _Prediction(
                id="pick-winner",
                question="Pick today's winner agent",
                options=agent_names,
                locks_at=locks_at_utc,
                reveals_at=reveals_at_utc,
            ),
            "spy-direction": _Prediction(
                id="spy-direction",
                question="Will SPY close green?",
                options=["up", "down"],
                locks_at=locks_at_utc,
                reveals_at=reveals_at_utc,
            ),
        }
        log.info("predictions_reset", session_date=str(session_date))

    # ------------------------------------------------------------------
    # Winner resolution.
    # ------------------------------------------------------------------

    def _resolve_winner(self, pred: _Prediction) -> str | None:
        if pred.id == "pick-winner":
            return self._resolve_pick_winner()
        if pred.id == "spy-direction":
            return self._resolve_spy_direction()
        return None

    def _resolve_pick_winner(self) -> str | None:
        """Agent with highest realized P&L today.

        Reads the live orchestrator state — uses ``book.realized_pnl`` as a
        proxy for "closed P&L". A more accurate version would aggregate
        outcomes stamped today; that's a refinement for v2.
        """
        marks = getattr(self.orch, "last_marks", {}) or {}
        best_agent = None
        best_pnl = float("-inf")
        for agent in self.orch.agents:
            book = getattr(agent.state, "book", None)
            if book is None:
                continue
            try:
                realized = float(book.realized_pnl)
            except (TypeError, ValueError):
                continue
            # Tie-break: also consider unrealized so a winning open position
            # contributes when no realizations exist yet.
            unrealized = 0.0
            try:
                unrealized = float(book.unrealized_pnl(marks))
            except Exception:
                unrealized = 0.0
            total = realized + unrealized
            if total > best_pnl:
                best_pnl = total
                best_agent = agent
        if best_agent is None:
            return None
        return best_agent.state.name

    def _resolve_spy_direction(self) -> str | None:
        baseline = self._spy_baseline
        marks = getattr(self.orch, "last_marks", {}) or {}
        current = marks.get(SPY_SYMBOL)
        if baseline is None or current is None:
            return None
        return "up" if current >= baseline else "down"

    # ------------------------------------------------------------------
    # Publishing.
    # ------------------------------------------------------------------

    async def _maybe_publish(self, pred: _Prediction, *, force: bool) -> None:
        now = _utcnow()
        if not force and pred.last_publish is not None:
            elapsed = (now - pred.last_publish).total_seconds()
            if elapsed < self.publish_debounce_sec:
                return
        pred.last_publish = now
        await publish_event("prediction_state", pred.to_payload())
