"""Streak watcher — auto-fires broadcast macros based on patterns in agent
closed-trade history.

Sister to :mod:`tradefarm.orchestrator.auto_director`. Where the auto-director
detects *threshold crossings* (equity vs. starting capital, market moves, rank
flips), this watcher detects *patterns* over the closed-outcome journal:

- ``streak-win3-{agent_id}``  — last 3 closed outcomes all positive
- ``streak-loss5-{agent_id}`` — last 5 closed outcomes all negative
- ``streak-bigwin-day``       — biggest realized win of the current day
- ``streak-bigloss-day``      — biggest realized loss of the current day
- ``streak-awake-{agent_id}`` — first close after a >=60 min quiet stretch

Both watchers publish ``stream_macro_fired`` envelopes (the same wire contract
the dashboard's BroadcastPanel uses for manual macros) and share a 30 min
per-trigger-id cooldown so the same id can't spam the stream.

Semantics note for the win/loss streak detectors: we look at *just* the most
recent N outcomes and require their tail to all be of one sign. We don't
require that the streak be "uninterrupted from the beginning of time" — only
the last N matter. So ``L W W W`` *does* trip the 3-wins detector. This keeps
the predicate stable across long histories.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import structlog

from tradefarm.api.events import publish_event
from tradefarm.storage import journal

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()

POLL_INTERVAL_SEC: float = 10.0
COOLDOWN: timedelta = timedelta(minutes=30)

# How many recent outcomes per agent to fetch for streak detection. Big enough
# to comfortably hold the 5-loss window and to spot the awake-from-quiet
# transition (which only needs the latest two stamped outcomes).
HISTORY_LIMIT: int = 20

WIN_STREAK_LEN: int = 3
LOSS_STREAK_LEN: int = 5

# "Back in action" thresholds. ``QUIET_GAP`` is the minimum gap between the
# previous and latest outcome to count as "long quiet"; ``FRESH_WINDOW`` is
# how recent the latest outcome must be to count as "just happened".
QUIET_GAP: timedelta = timedelta(minutes=60)
FRESH_WINDOW: timedelta = timedelta(seconds=60)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(raw: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp from the journal helper into a tz-aware
    datetime. Returns ``None`` if the value is missing or unparseable.
    """
    if not raw:
        return None
    try:
        # ``recent_outcomes`` emits ``datetime.isoformat()`` output. fromisoformat
        # accepts both naive and offset-bearing strings; assume UTC when naive.
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _closed_outcomes(notes: list[dict]) -> list[dict]:
    """Filter ``recent_outcomes`` rows to those with a stamped realized PnL,
    sorted newest-first (the journal already orders that way, so this is just
    a defensive re-sort + filter).
    """
    closed = [
        n for n in notes
        if n.get("outcome_realized_pnl") is not None
        and n.get("outcome_closed_at") is not None
    ]
    closed.sort(key=lambda n: n.get("outcome_closed_at") or "", reverse=True)
    return closed


@dataclass
class StreakWatcher:
    """Polls each agent's closed-outcome journal and publishes
    ``stream_macro_fired`` envelopes when streak / day-leader patterns appear.
    """

    orch: "Orchestrator"
    poll_interval_sec: float = POLL_INTERVAL_SEC
    cooldown: timedelta = COOLDOWN
    history_limit: int = HISTORY_LIMIT

    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _last_fired_at: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)
    # Cached biggest-of-day leaders, keyed by trigger id. We track both the
    # value (PnL) and the contributing agent id so we can detect a change and
    # build a fresh subtitle.
    _bigwin_leader: tuple[int, float] | None = field(default=None, init=False, repr=False)
    _bigloss_leader: tuple[int, float] | None = field(default=None, init=False, repr=False)
    _day_anchor: datetime | None = field(default=None, init=False, repr=False)
    # Seeds the day-leader cache on the first poll without firing — otherwise a
    # mid-day restart would announce "Trade of the day" for stale, already-known
    # state. Mirrors AutoDirector's rank-snapshot pattern.
    _day_leaders_seeded: bool = field(default=False, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Spin up the background poll loop. Idempotent."""
        if self._task is not None:
            return
        self._task = asyncio.create_task(self._run(), name="orch_streak_watcher")
        log.info("streak_watcher_started", interval_sec=self.poll_interval_sec)

    async def stop(self) -> None:
        """Cancel the poll loop and await its exit."""
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
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.exception("streak_watcher_loop_failed", error=str(e))
            await asyncio.sleep(self.poll_interval_sec)

    async def check_once(self) -> list[str]:
        """Run all detectors once; return the list of macro ids fired."""
        fired: list[str] = []
        now = _utcnow()
        self._maybe_reset_day(now)

        # Per-agent: pull the recent journal once, run all per-agent detectors
        # against the same snapshot.
        per_agent_notes: dict[int, list[dict]] = {}
        for agent in self.orch.agents:
            agent_id = agent.state.id
            notes = await journal.recent_outcomes(agent_id, self.history_limit)
            per_agent_notes[agent_id] = notes

            for macro in self._collect_streak_macros(agent, notes):
                if await self._maybe_fire(macro, now):
                    fired.append(macro["id"])

            awake = self._collect_awake_macro(agent, notes, now)
            if awake is not None and await self._maybe_fire(awake, now):
                fired.append(awake["id"])

        # Cross-agent: biggest gain / loss of the current day.
        for macro in self._collect_day_leader_macros(per_agent_notes, now):
            if await self._maybe_fire(macro, now):
                fired.append(macro["id"])

        return fired

    # ------------------------------------------------------------------
    # Day rollover — reset cached leaders when the UTC date changes.
    # ------------------------------------------------------------------

    def _maybe_reset_day(self, now: datetime) -> None:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if self._day_anchor is None or today > self._day_anchor:
            self._day_anchor = today
            self._bigwin_leader = None
            self._bigloss_leader = None
            # New day → re-seed the leader cache so the new day's first poll
            # doesn't fire on whatever closed before our restart.
            self._day_leaders_seeded = False

    # ------------------------------------------------------------------
    # Per-agent detectors.
    # ------------------------------------------------------------------

    def _collect_streak_macros(self, agent: Any, notes: list[dict]) -> list[dict]:
        closed = _closed_outcomes(notes)
        out: list[dict] = []
        name = agent.state.name
        agent_id = agent.state.id

        # Win streak: last WIN_STREAK_LEN closed outcomes all positive.
        if len(closed) >= WIN_STREAK_LEN and all(
            (n["outcome_realized_pnl"] or 0.0) > 0 for n in closed[:WIN_STREAK_LEN]
        ):
            out.append({
                "id": f"streak-win3-{agent_id}",
                "label": f"{name} on a heater",
                "color": "profit",
                "subtitle": f"{WIN_STREAK_LEN} wins straight",
                "agent_id": agent_id,
                "trigger": "win_streak",
            })

        # Loss streak: last LOSS_STREAK_LEN closed outcomes all negative.
        if len(closed) >= LOSS_STREAK_LEN and all(
            (n["outcome_realized_pnl"] or 0.0) < 0 for n in closed[:LOSS_STREAK_LEN]
        ):
            out.append({
                "id": f"streak-loss5-{agent_id}",
                "label": f"{name} ice cold",
                "color": "loss",
                "subtitle": f"{LOSS_STREAK_LEN} in a row red",
                "agent_id": agent_id,
                "trigger": "loss_streak",
            })

        return out

    def _collect_awake_macro(
        self, agent: Any, notes: list[dict], now: datetime,
    ) -> dict | None:
        closed = _closed_outcomes(notes)
        if len(closed) < 2:
            return None
        latest_closed_at = _parse_dt(closed[0].get("outcome_closed_at"))
        prev_closed_at = _parse_dt(closed[1].get("outcome_closed_at"))
        if latest_closed_at is None or prev_closed_at is None:
            return None
        # Latest must be fresh (within FRESH_WINDOW of now)…
        if (now - latest_closed_at) > FRESH_WINDOW:
            return None
        # …and the previous must be at least QUIET_GAP older than the latest.
        if (latest_closed_at - prev_closed_at) < QUIET_GAP:
            return None

        agent_id = agent.state.id
        name = agent.state.name
        symbol = closed[0].get("symbol") or getattr(agent, "symbol", None)
        subtitle = str(symbol) if symbol else None
        macro: dict = {
            "id": f"streak-awake-{agent_id}",
            "label": f"{name} back in action",
            "color": "neutral",
            "agent_id": agent_id,
            "trigger": "awake",
        }
        if subtitle:
            macro["subtitle"] = subtitle
        return macro

    # ------------------------------------------------------------------
    # Cross-agent detectors — biggest gain / loss of the day.
    # ------------------------------------------------------------------

    def _collect_day_leader_macros(
        self, per_agent_notes: dict[int, list[dict]], now: datetime,
    ) -> list[dict]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        # Flatten all closed outcomes stamped today.
        today_outcomes: list[tuple[int, str, float, dict]] = []
        for agent_id, notes in per_agent_notes.items():
            for n in _closed_outcomes(notes):
                closed_at = _parse_dt(n.get("outcome_closed_at"))
                if closed_at is None or closed_at < day_start:
                    continue
                pnl = float(n.get("outcome_realized_pnl") or 0.0)
                name = self._agent_name(agent_id)
                today_outcomes.append((agent_id, name, pnl, n))

        out: list[dict] = []
        if not today_outcomes:
            return out

        # Biggest gain.
        best = max(today_outcomes, key=lambda r: r[2])
        # Biggest loss.
        worst = min(today_outcomes, key=lambda r: r[2])

        # First poll seeds the leader cache without firing — a mid-day restart
        # shouldn't celebrate a trade that already closed hours ago.
        if not self._day_leaders_seeded:
            if best[2] > 0:
                self._bigwin_leader = (best[0], best[2])
            if worst[2] < 0:
                self._bigloss_leader = (worst[0], worst[2])
            self._day_leaders_seeded = True
            return out

        if best[2] > 0:
            prev = self._bigwin_leader
            if prev is None or best[2] > prev[1]:
                self._bigwin_leader = (best[0], best[2])
                out.append({
                    "id": "streak-bigwin-day",
                    "label": "Trade of the day",
                    "color": "profit",
                    "subtitle": f"{best[1]}: +${best[2]:.0f}",
                    "agent_id": best[0],
                    "trigger": "bigwin_day",
                })

        if worst[2] < 0:
            prev = self._bigloss_leader
            if prev is None or worst[2] < prev[1]:
                self._bigloss_leader = (worst[0], worst[2])
                out.append({
                    "id": "streak-bigloss-day",
                    "label": "Wipeout of the day",
                    "color": "loss",
                    "subtitle": f"{worst[1]}: −${abs(worst[2]):.0f}",
                    "agent_id": worst[0],
                    "trigger": "bigloss_day",
                })

        return out

    def _agent_name(self, agent_id: int) -> str:
        for a in self.orch.agents:
            if a.state.id == agent_id:
                return a.state.name
        return f"agent-{agent_id}"

    # ------------------------------------------------------------------
    # Fire + cooldown bookkeeping (same shape as AutoDirector).
    # ------------------------------------------------------------------

    async def _maybe_fire(self, macro: dict, now: datetime) -> bool:
        macro_id = macro["id"]
        last = self._last_fired_at.get(macro_id)
        if last is not None and (now - last) < self.cooldown:
            return False
        self._last_fired_at[macro_id] = now
        payload: dict = {
            "id": macro_id,
            "label": macro["label"],
        }
        if macro.get("color") is not None:
            payload["color"] = macro["color"]
        if macro.get("subtitle") is not None:
            payload["subtitle"] = macro["subtitle"]
        await publish_event("stream_macro_fired", payload)
        log.info(
            "streak_fire",
            macro_id=macro_id,
            agent_id=macro.get("agent_id"),
            trigger=macro.get("trigger"),
        )
        return True
