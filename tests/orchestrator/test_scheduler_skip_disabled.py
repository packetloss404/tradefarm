"""Scheduler skip-disabled-agents integration.

Pins the contract that `repo.get_disabled_agent_ids()` is consulted on
every tick and disabled agents are skipped in `gather()` *and* in the
post-gather risk-exit loop. Disabled agents are intentionally fully
frozen — no new entries AND no risk-driven exits — so an operator who
disables a runaway agent doesn't accidentally crystallize a loss on
the next tick (re-enable is the explicit exit path).
"""

from __future__ import annotations

from datetime import datetime, timezone
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
        self.decide_calls = 0

    async def decide(self, bars, marks):
        self.decide_calls += 1
        out = list(self.queued)
        self.queued.clear()
        return out


def _bars_with_close(symbol: str, close: float) -> pd.DataFrame:
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
    """Stub every DB-writing helper the scheduler calls so the tick can
    run without a real SQLAlchemy session. The `disabled` set is
    injected via ``repo.get_disabled_agent_ids`` so each test can shape
    its own fixture without monkeypatching the repo function itself."""
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
    monkeypatch.setattr(journal_mod, "write_note", _note)

    async def _close(*_a, **_kw):
        return None

    monkeypatch.setattr(journal_mod, "close_outcome", _close)
    monkeypatch.setattr(sch, "publish_event", AsyncMock())
    yield


def _seed_disabled(monkeypatch, ids: set[int]) -> None:
    """Replace `repo.get_disabled_agent_ids` so the tick sees the ids we want."""
    from tradefarm.storage import repo as repo_mod

    async def _fake_disabled_ids():
        return set(ids)

    monkeypatch.setattr(repo_mod, "get_disabled_agent_ids", _fake_disabled_ids)


async def test_gather_skips_decide_for_disabled_agent(patched_persistence, monkeypatch):
    """A disabled agent's decide() is NOT called by the scheduler."""
    _seed_disabled(monkeypatch, {7})

    agent = _StubAgent(agent_id=7, symbol="SPY", starting_capital=10_000.0)
    # Queue a signal — if decide() ran, it would be returned; assert
    # downstream fills that the signal was NOT processed.
    agent.queued.append(Signal("SPY", "buy", 5, reason="would-buy"))
    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 100.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    result = await orch.tick_once()

    assert agent.decide_calls == 0, "disabled agent must not run decide()"
    # No fills from the queued buy (and no risk-exits either, no position).
    assert result["fills"] == 0


async def test_gather_runs_decide_for_enabled_agent(patched_persistence, monkeypatch):
    """An agent NOT in the disabled set runs decide() normally."""
    _seed_disabled(monkeypatch, set())  # nothing disabled

    agent = _StubAgent(agent_id=7, symbol="SPY", starting_capital=10_000.0)
    agent.queued.append(Signal("SPY", "buy", 5, reason="would-buy"))
    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 100.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    await orch.tick_once()

    assert agent.decide_calls == 1, "enabled agent must run decide() exactly once"


async def test_multiple_disabled_agents_all_skipped(patched_persistence, monkeypatch):
    """Every agent in the disabled set is skipped; non-disabled peers still run."""
    _seed_disabled(monkeypatch, {0, 5, 42})

    a_disabled_0 = _StubAgent(agent_id=0, symbol="AAPL", starting_capital=10_000.0)
    a_disabled_5 = _StubAgent(agent_id=5, symbol="NVDA", starting_capital=10_000.0)
    a_disabled_42 = _StubAgent(agent_id=42, symbol="MSFT", starting_capital=10_000.0)
    a_enabled = _StubAgent(agent_id=7, symbol="SPY", starting_capital=10_000.0)
    for a in (a_disabled_0, a_disabled_5, a_disabled_42, a_enabled):
        a.queued.append(Signal("SPY", "buy", 1, reason="noop"))

    orch = Orchestrator(
        agents=[a_disabled_0, a_disabled_5, a_disabled_42, a_enabled],
        broker=SimulatedBroker(),
    )

    async def _fake_load_bars(symbols):
        return {s: _bars_with_close(s, 100.0) for s in symbols}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    await orch.tick_once()

    # Disabled trio: zero decide() invocations.
    assert a_disabled_0.decide_calls == 0
    assert a_disabled_5.decide_calls == 0
    assert a_disabled_42.decide_calls == 0
    # The peer not in the disabled set runs normally.
    assert a_enabled.decide_calls == 1


async def test_disabled_agent_is_exempt_from_risk_exits(patched_persistence, monkeypatch):
    """A disabled agent with an open position under stop-loss distance does NOT get a risk-exit.

    The scheduler's risk-exit loop runs AFTER gather(). For an enabled
    agent, that loop would queue a sell of the open position. For a
    disabled agent, the position is left alone — the operator must
    re-enable to exit. This is the "leave it alone, don't force close on
    a wrong tick" contract documented in `scheduler._tick_once_inner`.
    """
    _seed_disabled(monkeypatch, {0})

    # Tight SL so a non-disabled agent would have exited on the drop.
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
    # Pre-seed an open long position at $100.
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    agent.state.book.record_fill("SPY", "buy", 5, 100.0, at=t0)

    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    # Mark at 80 — would trigger -20% SL on an enabled agent. Because
    # this agent is disabled, neither decide() nor risk-exit fires.
    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 80.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    result = await orch.tick_once()

    # No fills — risk-exit was bypassed.
    assert result["fills"] == 0
    # Position is still open.
    pos = agent.state.book.positions.get("SPY")
    assert pos is not None
    assert abs(pos.qty) > 1e-9
    # And decide() never ran.
    assert agent.decide_calls == 0


async def test_enabled_agent_with_open_position_still_gets_risk_exit(
    patched_persistence, monkeypatch
):
    """Sanity: the same drop with the agent ENABLED still triggers a risk-exit.

    Pins that the disabled-skip is the ONLY thing that changed in the
    risk-exit loop; without the disable, the test mirrors
    `test_scheduler_tick_pending_exits` and exits the position.
    """
    _seed_disabled(monkeypatch, set())  # nothing disabled

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
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    agent.state.book.record_fill("SPY", "buy", 5, 100.0, at=t0)

    orch = Orchestrator(agents=[agent], broker=SimulatedBroker())

    async def _fake_load_bars(symbols):
        return {"SPY": _bars_with_close("SPY", 80.0)}

    monkeypatch.setattr(orch, "_load_bars", _fake_load_bars)

    result = await orch.tick_once()

    # Risk-exit fired and the in-tick fill closed the position.
    assert result["fills"] >= 1
    pos = agent.state.book.positions.get("SPY")
    assert pos is None or abs(pos.qty) < 1e-9
