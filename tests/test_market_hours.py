"""Tests for tradefarm.market.hours.trading_days_between.

Round-2 audit flagged: starting mid-session was counted as a full leading
day. Fri 12:00 ET → Tue 12:00 ET across a long weekend (no Mon session)
returned 1.38 when the right answer is ~1.0 (≈0.6 of Friday remaining +
≈0.4 of Tuesday consumed).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from tradefarm.market.hours import trading_days_between

ET = ZoneInfo("America/New_York")


def _et(y: int, m: int, d: int, h: int, mn: int = 0) -> datetime:
    return datetime(y, m, d, h, mn, tzinfo=ET)


def test_full_session_pair_no_partials():
    # Mon 09:30 → Tue 16:00: two full sessions.
    start = _et(2026, 5, 18, 9, 30)
    end = _et(2026, 5, 19, 16, 0)
    assert trading_days_between(start, end) == pytest.approx(2.0, abs=0.02)


def test_mid_session_start_subtracts_leading_fraction():
    # Mon 12:45 ET (≈ half of session elapsed) → Tue 16:00 ET.
    # Session is 9:30→16:00 = 6.5h. 12:45 is 3.25h in, so ~half of
    # Monday remains (≈0.5) plus a full Tuesday → ≈1.5.
    start = _et(2026, 5, 18, 12, 45)
    end = _et(2026, 5, 19, 16, 0)
    result = trading_days_between(start, end)
    assert result == pytest.approx(1.5, abs=0.05)


def test_friday_noon_to_tuesday_noon_across_long_weekend():
    """The round-2 regression case. Memorial Day weekend 2026:
    Mon May 25 is a holiday, so schedule has Fri May 22 + Tue May 26.

    Fri 12:00 ET → Tue 12:00 ET should be ≈1.0 trading days
    (≈0.615 Fri afternoon + ≈0.385 Tue morning), NOT ≈1.38.
    """
    start = _et(2026, 5, 22, 12, 0)
    end = _et(2026, 5, 26, 12, 0)
    result = trading_days_between(start, end)
    # Before the fix this was ~1.385 (full-Fri + 0.385-Tue).
    assert result == pytest.approx(1.0, abs=0.05)


def test_intraday_within_single_session():
    # 11:30 → 14:30 same day = 3h of a 6.5h session ≈ 0.46.
    start = _et(2026, 5, 22, 11, 30)
    end = _et(2026, 5, 22, 14, 30)
    result = trading_days_between(start, end)
    assert result == pytest.approx(3 / 6.5, abs=0.02)


def test_end_before_start_returns_zero():
    start = _et(2026, 5, 22, 12, 0)
    end = _et(2026, 5, 21, 12, 0)
    assert trading_days_between(start, end) == 0.0


def test_purely_weekend_range_returns_zero():
    # Sat 10:00 → Sun 14:00 — no trading days in schedule.
    start = _et(2026, 5, 23, 10, 0)
    end = _et(2026, 5, 24, 14, 0)
    assert trading_days_between(start, end) == 0.0


def test_never_returns_negative():
    """Defensive: even with pathological inputs (start past first close),
    the leading-fraction subtraction is clamped so we don't drop below 0.
    """
    # Start 23:00 ET on a Friday, end 06:00 ET on the following Tuesday.
    # First schedule row (Friday) is already past close at start; Tuesday
    # session hasn't opened by end. Should return 0, not negative.
    start = _et(2026, 5, 22, 23, 0)
    end = _et(2026, 5, 26, 6, 0)
    result = trading_days_between(start, end)
    assert result >= 0.0
