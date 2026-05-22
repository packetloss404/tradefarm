"""Regression tests for RiskManager audit fixes (H17-H21):

H17 — per-symbol cap was per-trade; adds bypassed the cap
H18 — cap anchored to starting_capital, not equity
H19 — trailing peak never reset on re-open
H20 — wall-clock days-held instead of trading days
H21 — _apply_rank_multiplier clobbered explicit caller limits
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.risk.manager import (
    BASE_MAX_POSITION_NOTIONAL_PCT,
    RiskLimits,
    RiskManager,
)


def _book(cash: float = 10000.0) -> VirtualBook:
    return VirtualBook(agent_id=1, cash=cash)


# ----- H17: per-symbol cap counts the existing position too ------------


def test_check_entry_rejects_adds_that_breach_cap():
    rm = RiskManager(starting_capital=10000.0)
    book = _book()
    book.record_fill("AAA", "buy", 20, 100.0)  # $2000 = 20% — within cap
    # Add another $1000 → total $3000 = 30% — over the 25% cap.
    d = rm.check_entry(book, "AAA", qty=10, price=100.0)
    assert not d.allow
    assert "incl. existing" in d.reason


def test_check_entry_allows_first_add_within_cap():
    rm = RiskManager(starting_capital=10000.0)
    book = _book()
    book.record_fill("AAA", "buy", 5, 100.0)  # $500 = 5%
    d = rm.check_entry(book, "AAA", qty=10, price=100.0)  # adds to $1500 = 15%
    assert d.allow


# ----- H18: cap shrinks with equity (clamped by starting) --------------


def test_check_entry_cap_shrinks_with_equity_under_drawdown():
    rm = RiskManager(starting_capital=10000.0)
    book = _book(cash=4000.0)  # equity dropped to $4000
    # 25% of $4000 = $1000.
    d = rm.check_entry(book, "AAA", qty=12, price=100.0, marks={})
    # $1200 > $1000 → reject. Without the fix this would allow $2500.
    assert not d.allow


def test_check_entry_cap_stays_at_starting_when_equity_grew():
    rm = RiskManager(starting_capital=10000.0)
    book = _book(cash=20000.0)
    # $2500 (25% of starting) allowed even though equity is $20k.
    d = rm.check_entry(book, "AAA", qty=25, price=100.0, marks={})
    assert d.allow
    # $2600 still rejected — we clamp at min(starting, equity).
    d2 = rm.check_entry(book, "AAA", qty=26, price=100.0, marks={})
    assert not d2.allow


# ----- H19: trailing peak resets on re-open ----------------------------


def test_trailing_peak_resets_on_position_reopen():
    rm = RiskManager(
        starting_capital=10000.0,
        limits=RiskLimits(
            stop_loss_pct=0.5, trailing_stop_pct=0.02,
            take_profit_pct=0.5, max_hold_days=30,
        ),
    )
    book = _book()
    # Open SPY @ 100, ride to 120, trailing-stop the new peak.
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    book.record_fill("SPY", "buy", 10, 100.0, at=t0)
    pos = book.positions["SPY"]
    rm.should_exit("SPY", pos, 120.0, now=t0 + timedelta(hours=1))
    # Close SPY (record reaches the reconciler's clear_peak path; we
    # simulate by clearing directly).
    book.record_fill("SPY", "sell", 10, 110.0, at=t0 + timedelta(hours=2))
    rm.clear_peak("SPY")
    # Re-open at $102 a day later.
    t1 = t0 + timedelta(days=1)
    book.record_fill("SPY", "buy", 10, 102.0, at=t1)
    pos = book.positions["SPY"]
    # Without the fix the trailing peak would still be 120 from the
    # prior cycle and the very next check would trip a trailing stop.
    trig = rm.should_exit("SPY", pos, 102.0, now=t1 + timedelta(minutes=1))
    assert trig is None or trig.kind != "trailing-stop"


def test_trailing_peak_resets_even_without_explicit_clear():
    """Even if the operator forgets to call clear_peak (e.g. simulated
    broker path), the seeded-at check should detect a re-opened position
    by comparing opened_at to the peak's seeded timestamp."""
    rm = RiskManager(
        starting_capital=10000.0,
        limits=RiskLimits(
            stop_loss_pct=0.5, trailing_stop_pct=0.02,
            take_profit_pct=0.5, max_hold_days=30,
        ),
    )
    book = _book()
    t0 = datetime(2026, 5, 1, 14, 0, tzinfo=timezone.utc)
    book.record_fill("SPY", "buy", 10, 100.0, at=t0)
    pos = book.positions["SPY"]
    rm.should_exit("SPY", pos, 120.0, now=t0 + timedelta(hours=1))
    book.record_fill("SPY", "sell", 10, 110.0, at=t0 + timedelta(hours=2))
    # No clear_peak call here.
    t1 = t0 + timedelta(days=1)
    book.record_fill("SPY", "buy", 10, 102.0, at=t1)
    pos = book.positions["SPY"]
    trig = rm.should_exit("SPY", pos, 102.0, now=t1 + timedelta(minutes=1))
    assert trig is None or trig.kind != "trailing-stop"


# ----- H21: explicit RiskLimits cap honoured ---------------------------


def test_rank_multiplier_does_not_clobber_explicit_cap():
    explicit = RiskLimits(max_position_notional_pct=0.5)
    rm = RiskManager(starting_capital=10000.0, limits=explicit, rank="principal")
    # With explicit limits, the rank multiplier MUST NOT recompute from
    # BASE * multiplier. The cap stays at the caller's 0.5.
    assert rm.limits.max_position_notional_pct == 0.5


def test_rank_multiplier_recomputes_implicit_cap():
    rm = RiskManager(starting_capital=10000.0, rank="principal")
    # No explicit limits: cap should be BASE × multiplier.
    from tradefarm.config import settings
    expected = BASE_MAX_POSITION_NOTIONAL_PCT * settings.rank_multiplier("principal")
    assert rm.limits.max_position_notional_pct == pytest.approx(expected)


# ----- boundary: zero/negative inputs ----------------------------------


def test_check_entry_rejects_zero_qty():
    rm = RiskManager(starting_capital=10000.0)
    book = _book()
    d = rm.check_entry(book, "AAA", qty=0, price=100.0)
    assert not d.allow
    assert "invalid" in d.reason.lower()


def test_check_entry_rejects_zero_price():
    rm = RiskManager(starting_capital=10000.0)
    book = _book()
    d = rm.check_entry(book, "AAA", qty=10, price=0.0)
    assert not d.allow
