"""Tests for the DonchianBreakoutAgent (20-period channel breakout)."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from tradefarm.agents.base import AgentState
from tradefarm.agents.donchian_breakout import DonchianBreakoutAgent
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import RiskManager


def _make_agent(
    *, symbol: str = "SPY", period: int = 20, size_pct: float = 0.20
) -> DonchianBreakoutAgent:
    book = VirtualBook(agent_id=1, cash=1000.0)
    state = AgentState(id=1, name="agent-001", strategy="donchian_breakout", book=book)
    risk = RiskManager(starting_capital=1000.0)
    return DonchianBreakoutAgent(
        state, risk, symbol=symbol, period=period, size_pct=size_pct
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


# ---------------------------------------------------------------------------
# strategy_name
# ---------------------------------------------------------------------------


def test_strategy_name() -> None:
    assert DonchianBreakoutAgent.strategy_name == "donchian_breakout"


# ---------------------------------------------------------------------------
# Guard rails
# ---------------------------------------------------------------------------


def test_missing_symbol_returns_empty() -> None:
    agent = _make_agent()
    closes = [100.0] * 30
    out = asyncio.run(agent.decide(_series(closes, symbol="QQQ"), {"QQQ": 100.0}))
    assert out == []


def test_insufficient_history_returns_empty() -> None:
    agent = _make_agent(period=20)
    # Only 19 bars < period → no decision.
    closes = [100.0] * 19
    out = asyncio.run(agent.decide(_series(closes), {"SPY": 100.0}))
    assert out == []


# ---------------------------------------------------------------------------
# Channel math
# ---------------------------------------------------------------------------


def test_channel_known_input() -> None:
    """Hand-check the channel for an obvious window: max/min over the
    *prior* ``period`` bars (the current bar is the signal bar and is
    excluded from the channel)."""
    agent = _make_agent(period=5)
    closes = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0, 17.0])  # last is current
    upper, lower = agent._channel(closes)
    assert upper == pytest.approx(18.0)  # max of [10,12,14,16,18]
    assert lower == pytest.approx(10.0)  # min of [10,12,14,16,18]


# ---------------------------------------------------------------------------
# Long entry — close above upper band, no existing long
# ---------------------------------------------------------------------------


def test_close_above_upper_band_buys() -> None:
    """Last close prints a fresh high above the 20-bar max → buy."""
    closes = [100.0 + (i % 3) for i in range(20)]  # range ~[100, 102]
    closes.append(120.0)  # breakout above prior 20-bar max
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.symbol == "SPY"
    assert sig.side == "buy"
    assert sig.qty > 0
    assert "breakout" in sig.reason


def test_close_below_lower_band_no_new_long() -> None:
    """Close below the lower band is a breakdown — but with no existing
    long there's nothing to sell. The agent WAITs (long-only sandbox)."""
    closes = [100.0 + (i % 3) for i in range(20)]
    closes.append(50.0)  # way below prior 20-bar min
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


# ---------------------------------------------------------------------------
# Long exit — close below lower band with a held long
# ---------------------------------------------------------------------------


def test_close_below_lower_band_sells_existing_long() -> None:
    """Close below lower band AND agent has a long → exit to flat."""
    closes = [100.0 + (i % 3) for i in range(20)]
    closes.append(50.0)  # breakdown below prior 20-bar min
    agent = _make_agent(period=20)
    agent.state.book.record_fill("SPY", "buy", 2, 100.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.side == "sell"
    assert sig.qty == 2  # full close
    assert "breakdown" in sig.reason


# ---------------------------------------------------------------------------
# Inside the channel — no signal either way
# ---------------------------------------------------------------------------


def test_close_inside_channel_waits_no_long() -> None:
    """Close between lower and upper band, no existing long → no signal."""
    closes = [100.0 + (i % 3) for i in range(20)]  # range [100, 102]
    closes.append(101.0)  # well inside the channel
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


def test_close_inside_channel_waits_with_long() -> None:
    """Close inside the channel, existing long held → no signal (we only
    exit on a breakdown, not on noise)."""
    closes = [100.0 + (i % 3) for i in range(20)]
    closes.append(101.0)
    agent = _make_agent(period=20)
    agent.state.book.record_fill("SPY", "buy", 3, 100.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def test_buy_quantity_uses_cash_not_equity() -> None:
    """size_pct=0.25, cash=1000, px=closes[-1] → qty ≈ 0.25*1000/px."""
    closes = [100.0 + (i % 3) for i in range(20)]
    closes.append(200.0)  # clean breakout
    agent = _make_agent(period=20, size_pct=0.25)
    px = closes[-1]
    out = asyncio.run(agent.decide(_series(closes), {"SPY": px}))
    expected = pytest.approx(0.25 * 1000.0 / px, rel=1e-3)
    assert float(out[0].qty) == expected
