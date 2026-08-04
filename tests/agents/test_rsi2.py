"""Tests for the Connors Rsi2Agent."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from tradefarm.agents.base import AgentState
from tradefarm.agents.rsi2 import Rsi2Agent
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import RiskManager


def _make_agent(
    *,
    symbol: str = "SPY",
    period: int = 2,
    oversold: float = 5.0,
    overbought: float = 95.0,
    size_pct: float = 0.20,
) -> Rsi2Agent:
    book = VirtualBook(agent_id=1, cash=1000.0)
    state = AgentState(id=1, name="agent-001", strategy="rsi2", book=book)
    risk = RiskManager(starting_capital=1000.0)
    return Rsi2Agent(
        state,
        risk,
        symbol=symbol,
        period=period,
        oversold=oversold,
        overbought=overbought,
        size_pct=size_pct,
    )


def _series(closes: list[float], symbol: str = "SPY") -> dict[str, pd.DataFrame]:
    n = len(closes)
    return {
        symbol: pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="B"),
                "adjusted_close": closes,
                "open": closes,
                "high": closes,
                "low": closes,
                "volume": [0] * n,
            }
        )
    }


def await_run(coro):
    return asyncio.run(coro)


def test_strategy_name() -> None:
    assert Rsi2Agent.strategy_name == "rsi2"


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_missing_symbol_returns_empty() -> None:
    agent = _make_agent()
    closes = [100.0, 99.0, 98.0]
    out = asyncio.run(agent.decide(_series(closes, symbol="QQQ"), {"QQQ": 98.0}))
    assert out == []


def test_insufficient_history_returns_empty() -> None:
    agent = _make_agent(period=2)
    out = asyncio.run(agent.decide(_series([100.0, 99.0]), {"SPY": 99.0}))
    assert out == []


# ---------------------------------------------------------------------------
# RSI math
# ---------------------------------------------------------------------------


def test_rsi_all_down_is_zero() -> None:
    """All-down window → RSI = 0 (max oversold)."""
    agent = _make_agent(period=2)
    closes = pd.Series([100.0, 99.0, 98.0])
    assert agent._rsi(closes) == 0.0


def test_rsi_all_up_is_hundred() -> None:
    """All-up window → RSI = 100 (max overbought)."""
    agent = _make_agent(period=2)
    closes = pd.Series([98.0, 99.0, 100.0])
    assert agent._rsi(closes) == 100.0


def test_rsi_flat_window_is_50() -> None:
    """A no-change window is the neutral midpoint (avoids div-by-zero)."""
    agent = _make_agent(period=2)
    closes = pd.Series([100.0, 100.0, 100.0])
    assert agent._rsi(closes) == 50.0


def test_rsi_known_value() -> None:
    """Hand-check: gains 2,1; loss 1. avg_gain=1.5, avg_loss=0.5 → rs=3 → rsi=75."""
    agent = _make_agent(period=3)
    closes = pd.Series([100.0, 102.0, 103.0, 102.0])  # diffs: +2, +1, -1
    assert agent._rsi(closes) == pytest.approx(75.0, rel=1e-6)


# ---------------------------------------------------------------------------
# Long entry — RSI(2) deep oversold
# ---------------------------------------------------------------------------


def test_oversold_buys() -> None:
    """Two consecutive big down days → RSI(2) ≈ 0 → buy."""
    closes = [100.0, 95.0, 90.0]  # diffs: -5, -5 → rsi=0
    agent = _make_agent()
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.side == "buy"
    assert "oversold" in sig.reason


def test_midrange_waits() -> None:
    """Mixed up/down day → RSI(2) ~ 50 → no signal."""
    closes = [100.0, 101.0, 100.0]  # diffs: +1, -1 → rs=1 → rsi=50
    agent = _make_agent()
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


# ---------------------------------------------------------------------------
# Long exit — RSI(2) deep overbought
# ---------------------------------------------------------------------------


def test_overbought_sells_existing_long() -> None:
    """Two consecutive big up days → RSI(2) ≈ 100 → sell held long."""
    closes = [90.0, 95.0, 100.0]  # diffs: +5, +5 → rsi=100
    agent = _make_agent()
    agent.state.book.record_fill("SPY", "buy", 2, 90.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.side == "sell"
    assert sig.qty == 2
    assert "overbought" in sig.reason


def test_overbought_no_existing_long_waits() -> None:
    """Overbought with no long → no signal (we don't initiate shorts)."""
    closes = [90.0, 95.0, 100.0]
    agent = _make_agent()
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


# ---------------------------------------------------------------------------
# Threshold tuning
# ---------------------------------------------------------------------------


def test_oversold_threshold_is_configurable() -> None:
    """With oversold=40, the midpoint RSI(2) = 50 no longer fires but
    the all-down zero still does."""
    closes = [100.0, 101.0, 100.0]  # rsi=50
    agent = _make_agent(oversold=40.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


def test_overbought_threshold_is_configurable() -> None:
    """Tighter overbought threshold (e.g. 80) fires on milder up windows."""
    closes = [100.0, 102.0, 105.0]  # diffs +2, +3 → avg_gain=2.5, avg_loss=0 → rsi=100
    agent = _make_agent(overbought=80.0)
    agent.state.book.record_fill("SPY", "buy", 1, 100.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    assert out[0].side == "sell"
