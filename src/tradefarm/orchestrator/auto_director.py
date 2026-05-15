"""Auto-director — auto-fires broadcast macros based on agent / market state.

Polls the Orchestrator every ``POLL_INTERVAL_SEC`` seconds and emits the same
``stream_macro_fired`` events the dashboard's BroadcastPanel produces when an
operator clicks a macro. Each macro id has a 30-minute cooldown so the same
trigger can't spam the stream.

Triggers:
- big-win:        agent equity >= +5% vs. starting capital
- crash:          agent equity <= -5% vs. starting capital
- market-surge:   SPY mark moved >= +2% vs. session-baseline
- market-crash:   SPY mark moved <= -2% vs. session-baseline
- promotion:      agent.risk.rank moved up vs. the boot snapshot

The "session" baseline is the first SPY mark observed after start(); it lives
in memory only and resets on restart.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

import structlog

from tradefarm.academy.ranks import RANK_ORDER
from tradefarm.api.events import publish_event
from tradefarm.config import settings

if TYPE_CHECKING:
    from tradefarm.orchestrator.scheduler import Orchestrator

log = structlog.get_logger()

POLL_INTERVAL_SEC: float = 5.0
COOLDOWN: timedelta = timedelta(minutes=30)

BIG_WIN_PCT: float = 0.05
CRASH_PCT: float = -0.05
MARKET_MOVE_PCT: float = 0.02
MARKET_SYMBOL: str = "SPY"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class AutoDirector:
    """Polls Orchestrator state and publishes ``stream_macro_fired`` events."""

    orch: "Orchestrator"
    poll_interval_sec: float = POLL_INTERVAL_SEC
    cooldown: timedelta = COOLDOWN

    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _last_fired_at: dict[str, datetime] = field(default_factory=dict, init=False, repr=False)
    _spy_baseline: float | None = field(default=None, init=False, repr=False)
    _rank_snapshot: dict[int, str] = field(default_factory=dict, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Spin up the background poll loop. Idempotent.

        Marked ``async`` so callers can ``await director.start()`` if they want
        the snapshot taken on the event-loop thread. Internally it only kicks
        off the task — no awaiting.
        """
        if self._task is not None:
            return
        self._snapshot_ranks()
        self._task = asyncio.create_task(self._run(), name="orch_auto_director")
        log.info("auto_director_started", interval_sec=self.poll_interval_sec)

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
                log.exception("auto_director_loop_failed", error=str(e))
            await asyncio.sleep(self.poll_interval_sec)

    def _snapshot_ranks(self) -> None:
        for a in self.orch.agents:
            rank = getattr(getattr(a, "risk", None), "rank", None)
            if rank is None:
                continue
            self._rank_snapshot[a.state.id] = rank

    async def check_once(self) -> list[str]:
        """Run all detectors once; return the list of macro ids fired."""
        fired: list[str] = []
        now = _utcnow()

        for macro in self._collect_agent_pnl_macros():
            if await self._maybe_fire(macro, now):
                fired.append(macro["id"])

        market_macro = self._collect_market_macro()
        if market_macro is not None and await self._maybe_fire(market_macro, now):
            fired.append(market_macro["id"])

        for macro in self._collect_promotion_macros():
            if await self._maybe_fire(macro, now):
                fired.append(macro["id"])

        return fired

    def _collect_agent_pnl_macros(self) -> list[dict]:
        starting = settings.agent_starting_capital
        marks = self.orch.last_marks
        out: list[dict] = []
        for agent in self.orch.agents:
            book = getattr(agent.state, "book", None)
            if book is None or starting <= 0:
                continue
            equity = book.equity(marks)
            pct = (equity - starting) / starting
            symbol = getattr(agent, "symbol", None)
            if pct >= BIG_WIN_PCT:
                subtitle = (
                    f"{symbol} +{pct * 100:.1f}%" if symbol else f"+{pct * 100:.1f}%"
                )
                out.append({
                    "id": f"auto-big-win-{agent.state.id}",
                    "label": f"Big win: {agent.state.name}",
                    "color": "profit",
                    "subtitle": subtitle,
                    "agent_id": agent.state.id,
                    "trigger": "big_win",
                })
            elif pct <= CRASH_PCT:
                subtitle = (
                    f"{symbol} {pct * 100:.1f}%" if symbol else f"{pct * 100:.1f}%"
                )
                out.append({
                    "id": f"auto-crash-{agent.state.id}",
                    "label": f"Crash: {agent.state.name}",
                    "color": "loss",
                    "subtitle": subtitle,
                    "agent_id": agent.state.id,
                    "trigger": "crash",
                })
        return out

    def _collect_market_macro(self) -> dict | None:
        mark = self.orch.last_marks.get(MARKET_SYMBOL)
        if mark is None or mark <= 0:
            return None
        if self._spy_baseline is None:
            self._spy_baseline = mark
            return None
        baseline = self._spy_baseline
        if baseline <= 0:
            return None
        pct = (mark - baseline) / baseline
        if pct >= MARKET_MOVE_PCT:
            return {
                "id": "auto-market-surge",
                "label": "Market surge",
                "color": "profit",
                "subtitle": f"SPY +{pct * 100:.1f}%",
                "agent_id": None,
                "trigger": "market_surge",
            }
        if pct <= -MARKET_MOVE_PCT:
            return {
                "id": "auto-market-crash",
                "label": "Market crash",
                "color": "loss",
                "subtitle": f"SPY −{abs(pct) * 100:.1f}%",
                "agent_id": None,
                "trigger": "market_crash",
            }
        return None

    def _collect_promotion_macros(self) -> list[dict]:
        out: list[dict] = []
        for agent in self.orch.agents:
            rank = getattr(getattr(agent, "risk", None), "rank", None)
            if rank is None:
                continue
            prev = self._rank_snapshot.get(agent.state.id)
            self._rank_snapshot[agent.state.id] = rank
            if prev is None or prev == rank:
                continue
            if prev not in RANK_ORDER or rank not in RANK_ORDER:
                continue
            if RANK_ORDER.index(rank) <= RANK_ORDER.index(prev):
                continue  # demotion or sideways — skip
            out.append({
                "id": f"auto-rank-{agent.state.id}",
                "label": f"Promotion: {agent.state.name}",
                "color": "profit",
                "subtitle": f"{prev} → {rank}",
                "agent_id": agent.state.id,
                "trigger": "promotion",
            })
        return out

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
            "auto_director_fire",
            macro_id=macro_id,
            agent_id=macro.get("agent_id"),
            trigger=macro.get("trigger"),
        )
        return True
