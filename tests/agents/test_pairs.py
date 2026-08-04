"""Tests for the PairsZScoreAgent (dollar-spread z-score mean reversion)."""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from tradefarm.agents.base import AgentState
from tradefarm.agents.pairs_zscore import PairsZScoreAgent
from tradefarm.data.pairs import PAIRS, pair_for_slot
from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import RiskManager


def _make_agent(
    *,
    symbol_a: str = "KO",
    symbol_b: str = "PEP",
    lookback: int = 60,
    z_entry: float = 2.0,
    z_exit: float = 0.5,
    size_pct: float = 0.20,
) -> PairsZScoreAgent:
    book = VirtualBook(agent_id=1, cash=1000.0)
    state = AgentState(id=1, name="agent-001", strategy="pairs_zscore", book=book)
    risk = RiskManager(starting_capital=1000.0)
    return PairsZScoreAgent(
        state,
        risk,
        symbol_a=symbol_a,
        symbol_b=symbol_b,
        lookback=lookback,
        z_entry=z_entry,
        z_exit=z_exit,
        size_pct=size_pct,
    )


def _bars(closes_a: list[float], closes_b: list[float]) -> dict[str, pd.DataFrame]:
    """Build a 2-symbol bars dict the orchestrator shape expects."""
    def _df(closes: list[float]) -> pd.DataFrame:
        n = len(closes)
        return pd.DataFrame(
            {
                "date": pd.date_range("2024-01-01", periods=n, freq="B"),
                "adjusted_close": closes,
                "open": closes,
                "high": closes,
                "low": closes,
                "volume": [0] * n,
            }
        )

    return {"KO": _df(closes_a), "PEP": _df(closes_b)}


# ---------------------------------------------------------------------------
# pair_for_slot
# ---------------------------------------------------------------------------


def test_pair_for_slot_zero_returns_first() -> None:
    assert pair_for_slot(0) == PAIRS[0]


def test_pair_for_slot_cycles_modulo() -> None:
    n = len(PAIRS)
    for i in range(n * 2):
        assert pair_for_slot(i) == PAIRS[i % n]


def test_pair_for_slot_past_end_cycles() -> None:
    assert pair_for_slot(len(PAIRS)) == PAIRS[0]
    assert pair_for_slot(len(PAIRS) + 1) == PAIRS[1]


# ---------------------------------------------------------------------------
# strategy_name
# ---------------------------------------------------------------------------


def test_strategy_name() -> None:
    assert PairsZScoreAgent.strategy_name == "pairs_zscore"


# ---------------------------------------------------------------------------
# Guard rails — missing input / history / degenerate spread
# ---------------------------------------------------------------------------


def _df_only(closes: list[float]) -> pd.DataFrame:
    n = len(closes)
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n, freq="B"),
            "adjusted_close": closes,
            "open": closes,
            "high": closes,
            "low": closes,
            "volume": [0] * n,
        }
    )


def test_missing_symbol_a_returns_empty() -> None:
    agent = _make_agent(symbol_a="KO", symbol_b="PEP")
    bars = {"PEP": _df_only([100.0] * 60)}  # KO missing
    out = asyncio.run(agent.decide(bars, {"PEP": 100.0}))
    assert out == []


def test_missing_symbol_b_returns_empty() -> None:
    agent = _make_agent(symbol_a="KO", symbol_b="PEP")
    bars = {"KO": _df_only([100.0] * 60)}  # PEP missing
    out = asyncio.run(agent.decide(bars, {"KO": 100.0}))
    assert out == []


def test_insufficient_history_on_a_returns_empty() -> None:
    agent = _make_agent(lookback=60)
    closes_a = [100.0] * 30  # too few
    closes_b = [100.0] * 60
    out = asyncio.run(agent.decide(_bars(closes_a, closes_b), {"KO": 100.0, "PEP": 100.0}))
    assert out == []


def test_insufficient_history_on_b_returns_empty() -> None:
    agent = _make_agent(lookback=60)
    closes_a = [100.0] * 60
    closes_b = [100.0] * 30  # too few
    out = asyncio.run(agent.decide(_bars(closes_a, closes_b), {"KO": 100.0, "PEP": 100.0}))
    assert out == []


def test_zero_std_returns_empty() -> None:
    """Perfectly flat prices on both sides → spread std=0 → degenerate."""
    agent = _make_agent(lookback=60)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    out = asyncio.run(agent.decide(_bars(closes_a, closes_b), {"KO": 100.0, "PEP": 50.0}))
    assert out == []


# ---------------------------------------------------------------------------
# z-score math
# ---------------------------------------------------------------------------


def test_zscore_known_input() -> None:
    """Hand-check: spread = A - B. 59 bars of 50.0, last bar 40.0
    → mean = (59*50+40)/60, pop std computed from the same window."""
    import numpy as np

    agent = _make_agent(lookback=60)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 90.0
    spread = np.array([50.0] * 59 + [40.0])
    expected = float((spread[-1] - spread.mean()) / spread.std(ddof=0))
    z = agent._zscore(
        _bars(closes_a, closes_b)["KO"], _bars(closes_a, closes_b)["PEP"]
    )
    assert z is not None
    assert z == pytest.approx(expected, rel=1e-6)
    # Confirm it is strongly negative
    assert z < -2.0


# ---------------------------------------------------------------------------
# Long entry — z < -z_entry, no held long
# ---------------------------------------------------------------------------


def test_z_below_entry_buys_a() -> None:
    """Spread crashes: A underperforms sharply → z very negative → buy A."""
    agent = _make_agent(lookback=60, z_entry=2.0, size_pct=0.20)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 80.0  # spread 30 vs historical 50 → big z<0
    px_a = 80.0
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": px_a, "PEP": 50.0})
    )
    assert len(out) == 1
    sig = out[0]
    assert sig.symbol == "KO"
    assert sig.side == "buy"
    assert sig.qty > 0
    assert "pairs" in sig.reason


def test_z_below_entry_but_has_long_waits() -> None:
    """Already long A and z is still below -z_entry → don't double up."""
    agent = _make_agent(lookback=60, z_entry=2.0)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 80.0
    # Seed a held long
    agent.state.book.record_fill("KO", "buy", 2, 100.0)
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": 80.0, "PEP": 50.0})
    )
    assert out == []


# ---------------------------------------------------------------------------
# Long exit — z > +z_entry, has long
# ---------------------------------------------------------------------------


def test_z_above_entry_sells_held_long() -> None:
    """Spread reverts past +z_entry → close the A long."""
    agent = _make_agent(lookback=60, z_entry=2.0)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 130.0  # spread 80 vs historical 50 → z strongly positive
    # Seed a long
    agent.state.book.record_fill("KO", "buy", 2, 100.0)
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": 130.0, "PEP": 50.0})
    )
    assert len(out) == 1
    sig = out[0]
    assert sig.symbol == "KO"
    assert sig.side == "sell"
    assert sig.qty == 2  # full close — mirrors held qty
    assert "pairs" in sig.reason


def test_z_above_entry_no_long_waits() -> None:
    """z>+entry but no long held → no signal (long-only sandbox, don't short)."""
    agent = _make_agent(lookback=60, z_entry=2.0)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 130.0
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": 130.0, "PEP": 50.0})
    )
    assert out == []


# ---------------------------------------------------------------------------
# Neutral z
# ---------------------------------------------------------------------------


def test_z_inside_threshold_waits() -> None:
    """|z| < z_entry → no signal in either direction. Use a spread series
    with a non-trivial std so a small last-bar perturbation stays inside
    the ±z_entry band."""
    agent = _make_agent(lookback=60, z_entry=2.0)
    # A alternates 100/99, B flat at 50 → spread alternates 50/49, pop std 0.5.
    closes_a = [100.0 if i % 2 == 0 else 99.0 for i in range(60)]
    closes_b = [50.0] * 60
    closes_a[-1] = 100.0  # last spread = 50.0 (right at mean) → z ~ 1.0
    # No long → no signal
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": 100.0, "PEP": 50.0})
    )
    assert out == []
    # With a long, still no exit signal
    agent.state.book.record_fill("KO", "buy", 1, 100.0)
    out2 = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": 100.0, "PEP": 50.0})
    )
    assert out2 == []


# ---------------------------------------------------------------------------
# Sizing
# ---------------------------------------------------------------------------


def test_buy_quantity_uses_size_pct() -> None:
    """25% size_pct → qty = 0.25 * 1000 / px_a (within 1e-3)."""
    agent = _make_agent(lookback=60, z_entry=2.0, size_pct=0.25)
    closes_a = [100.0] * 60
    closes_b = [50.0] * 60
    closes_a[-1] = 80.0
    px_a = 80.0
    out = asyncio.run(
        agent.decide(_bars(closes_a, closes_b), {"KO": px_a, "PEP": 50.0})
    )
    expected = pytest.approx(0.25 * 1000.0 / px_a, rel=1e-3)
    assert float(out[0].qty) == expected
