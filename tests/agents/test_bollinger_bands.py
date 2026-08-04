"""Tests for the BollingerBandsAgent (mean reversion)."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from tradefarm.agents.base import AgentState
from tradefarm.agents.bollinger_bands import BollingerBandsAgent
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import RiskManager


def _make_agent(
    *, symbol: str = "SPY", period: int = 20, num_std: float = 2.0, size_pct: float = 0.20
) -> BollingerBandsAgent:
    book = VirtualBook(agent_id=1, cash=1000.0)
    state = AgentState(id=1, name="agent-001", strategy="mean_reversion_bb", book=book)
    risk = RiskManager(starting_capital=1000.0)
    return BollingerBandsAgent(
        state, risk, symbol=symbol, period=period, num_std=num_std, size_pct=size_pct
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
    assert BollingerBandsAgent.strategy_name == "mean_reversion_bb"


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
    # Only 10 bars < period → no decision.
    closes = [100.0] * 10
    out = asyncio.run(agent.decide(_series(closes), {"SPY": 100.0}))
    assert out == []


def test_zero_std_returns_empty() -> None:
    """A perfectly flat window has std=0; bands would collapse to the
    mean, so refuse to make a degenerate call."""
    agent = _make_agent()
    closes = [100.0] * 30  # std = 0
    out = asyncio.run(agent.decide(_series(closes), {"SPY": 100.0}))
    assert out == []


# ---------------------------------------------------------------------------
# Band math
# ---------------------------------------------------------------------------


def test_bands_known_input() -> None:
    """Hand-check the band math for a small constant-variance window."""
    agent = _make_agent(period=5, num_std=1.0)
    closes = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
    mid, upper, lower = agent._bands(closes)
    # mean = 14, std (pop) = sqrt(8) ≈ 2.828
    assert mid == pytest.approx(14.0)
    assert upper == pytest.approx(14.0 + 2.828427, rel=1e-4)
    assert lower == pytest.approx(14.0 - 2.828427, rel=1e-4)


# ---------------------------------------------------------------------------
# Long entry — close below lower band
# ---------------------------------------------------------------------------


def test_close_below_lower_band_buys() -> None:
    """Last close is well below the lower band → buy."""
    # 20 bars stable around 100, then a sharp down day. The 20-bar mean
    # stays ~100 with a small std; the new low is many sigmas below.
    closes = [100.0 + (i % 2) * 0.5 for i in range(20)]  # tight range 100-100.5
    closes.append(80.0)  # 20+ std below the mean
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.symbol == "SPY"
    assert sig.side == "buy"
    assert "oversold" in sig.reason


def test_close_above_upper_band_no_new_long() -> None:
    """Close above the upper band is overbought — but with no existing
    long there's nothing to sell. The agent WAITs (mean reversion is
    long-biased; we don't initiate shorts in this sandbox)."""
    closes = [100.0 + (i % 2) * 0.5 for i in range(20)]
    closes.append(200.0)  # way above
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


def test_close_inside_bands_waits() -> None:
    """Close between mid and upper band (no extreme) → no signal."""
    closes = [100.0 + (i % 2) * 0.5 for i in range(20)]
    closes.append(100.5)  # right at the mean
    agent = _make_agent(period=20)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert out == []


# ---------------------------------------------------------------------------
# Long exit — close above upper band with a held long
# ---------------------------------------------------------------------------


def test_close_above_upper_band_sells_existing_long() -> None:
    """Close above upper band AND agent has a long → exit to flat."""
    closes = [100.0 + (i % 2) * 0.5 for i in range(20)]
    closes.append(200.0)  # breakout above upper band
    agent = _make_agent(period=20)
    agent.state.book.record_fill("SPY", "buy", 2, 100.0)
    out = asyncio.run(agent.decide(_series(closes), {"SPY": closes[-1]}))
    assert len(out) == 1
    sig = out[0]
    assert sig.side == "sell"
    assert sig.qty == 2  # full close
    assert "overbought" in sig.reason


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def test_buy_quantity_uses_cash_not_equity() -> None:
    closes = [100.0 + (i % 2) * 0.5 for i in range(20)]
    closes.append(80.0)
    agent = _make_agent(period=20, size_pct=0.25)
    px = closes[-1]
    out = asyncio.run(agent.decide(_series(closes), {"SPY": px}))
    expected = pytest.approx(0.25 * 1000.0 / px, rel=1e-3)
    assert float(out[0].qty) == expected
