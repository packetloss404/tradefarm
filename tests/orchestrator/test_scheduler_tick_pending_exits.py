"""Scheduler tick → pending-exit lifecycle integration.

Audit fix (O): in simulated mode the reconciler never runs, so the
in-tick sell-fill MUST clear ``_pending_exits[(agent_id, symbol)]``
before tick_once() returns; otherwise re-entries on the same symbol
are blocked for the full PENDING_EXIT_TTL_SEC window.

Audit fix (H19): on a fully-flat sell-fill, the RiskManager's trailing
``_peak`` (and ``_peak_seeded_at``) must be cleared so a re-entry starts
fresh rather than inheriting the prior cycle's high-water mark.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pandas as pd
import pytest

from tradefarm.agents.base import Agent, AgentState, Signal
from tradefarm.execution.broker import SimulatedBroker
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.risk.manager import RiskLimits, RiskManager


class _StubAgent(Agent):
    """Minimal agent that emits whatever signals the test queues. Holds a
    real VirtualBook + RiskManager so the scheduler's risk-exit branch
    exercises the actual code path."""

    strategy_name = "stub_v1"

    def __init__(
        self,
        agent_id: int,
        symbol: str,
        starting_capital: float,
        risk_limits: RiskLimits | None = None,
    ) -> None:
        book = VirtualBook(agent_id=agent_id, cash=starting_capital)
        state = AgentState(
            id=agent_id,
            name=f"agent-{agent_id:03d}",
            strategy=self.strategy_name,
            book=book,
        )
        risk = RiskManager(
            starting_capital=starting_capital,
            limits=risk_limits or RiskLimits(),
        )
        super().__init__(state, risk)
        self.symbol = symbol
        self.queued: list[Signal] = []

    async def decide(self, bars, marks):
        out = list(self.queued)
        self.queued.clear()
        return out


def _bars_with_close(symbol: str, close: float) -> pd.DataFrame:
    """Build a one-row bar frame with the given adjusted_close, so
    ``orch._load_bars`` (patched) returns deterministic marks."""
    return pd.DataFrame(
        {
            "date": [datetime(2026, 5, 1).date()],
            "open": [close],
            "high": [close],
            "low": [close],
            "close": [close],
            "adjusted_close": [close],
            "volume": [1_000_000],
        }
    )


@pytest.fixture
def patched_persistence(monkeypatch):
    """Stub every DB-writing helper the scheduler calls. Lets us run
    tick_once() without a real SQLAlchemy session."""
    from tradefarm.orchestrator import scheduler as sch
    from tradefarm.storage import journal as journal_mod
    from tradefarm.storage import repo as repo_mod

    async def _noop(*_a, **_kw):
        return None

    async def _note(*_a, **_kw):
        return 1  # pretend a note id

    monkeypatch.setattr(repo_mod, "record_trade", _noop)
    monkeypatch.setattr(repo_mod, "record_fill_atomic", _noop)
    monkeypatch.setattr(repo_mod, "snapshot_pnl", _noop)
    monkeypatch.setattr(repo_mod, "sync_positions", _noop)
    monkeypatch.setattr(repo_mod, "upsert_agent", _noop)
    # Per-agent disable set read on every tick by the scheduler (added
    # alongside the per-agent admin toggle endpoints). The pending-exit
    # tests pre-date that wiring; stub the new repo call so they don't
    # need a live DB to run.
    async def _no_disabled_ids():
        return set()

    monkeypatch.setattr(repo_mod, "get_disabled_agent_ids", _no_disabled_ids)
    monkeypatch.setattr(journal_mod, "write_note", _note)

    async def _close(*_a, **_kw):
        return None

    monkeypatch.setattr(journal_mod, "close_outcome", _close)
    # Also stub publish_event so the WS bus isn't touched.
    monkeypatch.setattr(sch, "publish_event", AsyncMock())
    yield


async def test_tick_clears_pending_exits_after_simulated_sell_fill(
    patched_persistence, monkeypatch
):
    """Audit-O: a risk-driven sell that fills in-tick under
    SimulatedBroker MUST leave ``_pending_exits`` empty by the time
    tick_once() returns."""
    # Tight SL so the risk-exit branch fires on the mark drop.
    agent = _StubAgent(
        agent_id=0,
        symbol="SPY",
        starting_capital=10_000.0,
        risk_limits=RiskLimits(
            stop_loss_pct=0.05,
            trailing_stop_pct=0.5,
            take_profit_pct=0.5,
            max_hold_days=30,
        ),
    )
    # Pre-seed an open position at $100 (5 shares = $500 notional).
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    agent.state.book.record_fill("SPY", "buy", 5, 100.0, at=t0)

    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    # Patch _load_bars to return a frame with adjusted_close=80 → -20% → SL.
    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 80.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    result = await orch.tick_once()

    # Risk-exit fired AND the in-tick fill cleared the guard.
    assert result["fills"] >= 1
    assert (agent.state.id, "SPY") not in orch._pending_exits, (
        "Audit-O: scheduler must clear _pending_exits on in-tick sell fill"
    )
    # Position is fully closed.
    pos = agent.state.book.positions.get("SPY")
    assert pos is None or abs(pos.qty) < 1e-9


async def test_tick_resets_risk_peak_on_reopen(patched_persistence, monkeypatch):
    """Audit-H19: after the position has been fully closed (in-tick
    sell-fill), the RiskManager's trailing ``_peak`` for that symbol
    must be cleared, so a re-entry doesn't inherit the prior peak."""
    agent = _StubAgent(
        agent_id=0,
        symbol="SPY",
        starting_capital=10_000.0,
        risk_limits=RiskLimits(
            stop_loss_pct=0.05,
            trailing_stop_pct=0.5,
            take_profit_pct=0.5,
            max_hold_days=30,
        ),
    )
    # Pre-seed an open position + walk the peak up so it has real state.
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    agent.state.book.record_fill("SPY", "buy", 5, 100.0, at=t0)
    # Force the peak to 120 by calling should_exit ourselves.
    agent.risk.should_exit("SPY", agent.state.book.positions["SPY"], 120.0, now=t0)
    assert agent.risk._peak.get("SPY") == 120.0

    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    # Drop mark to 80 → SL fires → in-tick sell-fill flattens position.
    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 80.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    await orch.tick_once()

    # Audit-H19: peak cleared by the scheduler's `clear_peak` invocation
    # in the in-tick sell-fill branch.
    assert "SPY" not in agent.risk._peak, (
        "Audit-H19: RiskManager._peak must be cleared on full close"
    )
    assert "SPY" not in agent.risk._peak_seeded_at

    # Now re-enter SPY at 102 on the NEXT tick — drop to 100 should not
    # trigger trailing-stop (it would if peak were still 120 stale).
    t1 = t0 + timedelta(days=1)
    agent.state.book.record_fill("SPY", "buy", 5, 102.0, at=t1)
    pos = agent.state.book.positions["SPY"]
    trig = agent.risk.should_exit("SPY", pos, 100.0, now=t1 + timedelta(minutes=1))
    # Either no trigger, or anything that ISN'T a trailing-stop (the bug
    # would otherwise instantly trip trailing-stop off the stale 120 peak).
    assert trig is None or trig.kind != "trailing-stop"
