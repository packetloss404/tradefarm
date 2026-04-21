"""Tests for the RiskManager.should_exit risk-based exit rules."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from tradefarm.config import settings
from tradefarm.execution.virtual_book import VirtualBook, VirtualPosition
from tradefarm.risk.manager import RiskLimits, RiskManager


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _fresh_risk(limits: RiskLimits | None = None) -> RiskManager:
    return RiskManager(starting_capital=1000.0, limits=limits or RiskLimits())


def test_position_opened_at_set_on_open_cleared_on_close():
    book = VirtualBook(agent_id=1, cash=1000.0)
    assert "SPY" not in book.positions
    t0 = _now()
    book.record_fill("SPY", "buy", 2, 100.0, at=t0)
    assert book.positions["SPY"].opened_at == t0
    # Add to the position — opened_at should stay the same (not reset).
    book.record_fill("SPY", "buy", 1, 100.0, at=t0 + timedelta(days=1))
    assert book.positions["SPY"].opened_at == t0
    # Fully close — opened_at clears.
    book.record_fill("SPY", "sell", 3, 105.0)
    assert book.positions["SPY"].opened_at is None


def test_stop_loss_fires_below_threshold():
    risk = _fresh_risk()
    pos = VirtualPosition("SPY", qty=1.0, avg_price=100.0, opened_at=_now())
    trig = risk.should_exit("SPY", pos, mark=96.0)  # -4%, past -3% SL
    assert trig is not None
    assert trig.kind == "stop-loss"


def test_take_profit_fires_above_threshold():
    risk = _fresh_risk()
    pos = VirtualPosition("QQQ", qty=1.0, avg_price=100.0, opened_at=_now())
    trig = risk.should_exit("QQQ", pos, mark=106.0)  # +6%, past +5% TP
    assert trig is not None
    assert trig.kind == "take-profit"


def test_time_stop_fires_when_held_too_long():
    risk = _fresh_risk(RiskLimits(max_hold_days=3))
    pos = VirtualPosition("AAPL", qty=1.0, avg_price=100.0, opened_at=_now() - timedelta(days=5))
    trig = risk.should_exit("AAPL", pos, mark=101.0)
    assert trig is not None
    assert trig.kind == "time-stop"


def test_trailing_stop_fires_after_peak():
    risk = _fresh_risk()
    pos = VirtualPosition("NVDA", qty=1.0, avg_price=100.0, opened_at=_now())
    # First observation lifts the peak without firing (inside all thresholds).
    assert risk.should_exit("NVDA", pos, mark=104.0) is None
    # Pull back 2.5% off the peak → trailing-stop.
    trig = risk.should_exit("NVDA", pos, mark=101.4)
    assert trig is not None
    assert trig.kind == "trailing-stop"


def test_no_exit_inside_all_thresholds():
    risk = _fresh_risk()
    pos = VirtualPosition("SPY", qty=1.0, avg_price=100.0, opened_at=_now())
    # mild gain, recent, no triggers
    assert risk.should_exit("SPY", pos, mark=101.5) is None


def test_flat_position_has_no_exit():
    risk = _fresh_risk()
    pos = VirtualPosition("SPY", qty=0.0, avg_price=0.0)
    assert risk.should_exit("SPY", pos, mark=100.0) is None


def test_priority_stop_loss_beats_trailing():
    """If both SL and trailing would fire, the SL reason should be reported
    because it's the more meaningful risk signal (absolute loss vs drawdown)."""
    risk = _fresh_risk()
    pos = VirtualPosition("SPY", qty=1.0, avg_price=100.0, opened_at=_now())
    # First tick: establish a peak of 108
    risk.should_exit("SPY", pos, mark=108.0)
    # Second tick: mark back at 95 — SL (-5%) and trailing (-12% off peak) both fire.
    trig = risk.should_exit("SPY", pos, mark=95.0)
    assert trig is not None
    assert trig.kind == "stop-loss"  # checked first


@pytest.mark.parametrize("sl_pct,mark,kind", [
    (0.03, 96.0, "stop-loss"),
    (0.03, 103.0, None),
    # Wider 10% SL → no SL trigger at -4%. Also widen trailing + disable the
    # time-stop so we're genuinely checking "SL threshold is configurable"
    # without another rule firing incidentally.
    (0.10, 96.0, None),
])
def test_stop_loss_pct_is_configurable(sl_pct: float, mark: float, kind: str | None):
    risk = _fresh_risk(RiskLimits(
        stop_loss_pct=sl_pct,
        take_profit_pct=1.0,       # effectively disabled
        trailing_stop_pct=1.0,     # effectively disabled
        max_hold_days=10_000,      # effectively disabled
    ))
    pos = VirtualPosition("SPY", qty=1.0, avg_price=100.0, opened_at=_now())
    trig = risk.should_exit("SPY", pos, mark=mark)
    if kind is None:
        assert trig is None
    else:
        assert trig is not None and trig.kind == kind


def test_limits_from_settings_reads_config():
    """Default RiskManager() pulls thresholds from settings so the admin-panel
    knobs actually flow through to new managers."""
    original_sl = settings.risk_stop_loss_pct
    original_tp = settings.risk_take_profit_pct
    try:
        settings.risk_stop_loss_pct = 0.10
        settings.risk_take_profit_pct = 0.20
        rm = RiskManager(starting_capital=1000.0)
        assert rm.limits.stop_loss_pct == 0.10
        assert rm.limits.take_profit_pct == 0.20
    finally:
        settings.risk_stop_loss_pct = original_sl
        settings.risk_take_profit_pct = original_tp
