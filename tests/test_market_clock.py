"""Tests for the ``tradefarm.market_clock`` helper.

The helper exposes ``is_market_closed_for_n_minutes(n)`` — the
predicate the daily VOD scheduler reads each minute. The contract:

- True when the current time is at least ``n`` minutes past today's
  NYSE close (4pm ET on a normal day, 1pm ET on a half-day).
- False on weekends and holidays (no session today).
- False before today's session has even opened (a misconfigured
  16:00 schedule can't trip at 09:00).

The function takes an injectable ``dt`` so the tests are
deterministic (no wall-clock dependency).
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


from tradefarm.market_clock import is_market_closed_for_n_minutes

ET = ZoneInfo("America/New_York")


# Helper: build a tz-aware ET datetime for the test.
def _et(y: int, m: int, d: int, h: int, mn: int = 0) -> datetime:
    return datetime(y, m, d, h, mn, tzinfo=ET)


# ---------------------------------------------------------------------------
# Trading day cases
# ---------------------------------------------------------------------------


def test_returns_false_before_close():
    """A 14:00 ET on a normal trading day: market still open, so the
    predicate is False regardless of the offset."""
    dt = _et(2026, 8, 4, 14, 0)  # Tue Aug 4 2026, 2pm ET
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


def test_returns_false_just_before_close():
    """3:59:30pm ET — still within RTH, the predicate is False even
    with a 0-minute offset (the 0 case is "now == close", which
    the operator's wall-clock roundoff might trigger; we want
    False until ``>= close``)."""
    dt = _et(2026, 8, 4, 15, 59)
    assert is_market_closed_for_n_minutes(0, dt=dt) is False


def test_returns_true_at_close_with_zero_offset():
    """Exactly 4:00pm ET with offset=0 — the predicate is True
    (now == close + 0 min)."""
    dt = _et(2026, 8, 4, 16, 0)
    assert is_market_closed_for_n_minutes(0, dt=dt) is True


def test_returns_false_one_minute_before_close_with_5_offset():
    """3:59pm ET with offset=5: only 1 minute past close, not 5.
    The predicate should be False."""
    dt = _et(2026, 8, 4, 15, 59)
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


def test_returns_true_at_5_past_close():
    """4:05pm ET — exactly 5 minutes past close. With offset=5,
    the predicate is True."""
    dt = _et(2026, 8, 4, 16, 5)
    assert is_market_closed_for_n_minutes(5, dt=dt) is True


def test_returns_true_30_minutes_past_close():
    """4:30pm ET with offset=5 — the predicate is True (we're well
    past the cool-off window)."""
    dt = _et(2026, 8, 4, 16, 30)
    assert is_market_closed_for_n_minutes(5, dt=dt) is True


def test_returns_false_at_close_with_5_offset():
    """4:00pm ET with offset=5 — only 0 minutes past close, not 5.
    The predicate is False (we want the cool-off to fully elapse)."""
    dt = _et(2026, 8, 4, 16, 0)
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


# ---------------------------------------------------------------------------
# Weekend / holiday
# ---------------------------------------------------------------------------


def test_returns_false_on_saturday():
    """Saturday — no NYSE session. Predicate is False regardless of
    time-of-day or offset (otherwise the scheduler would treat
    Friday's data as "stale" forever)."""
    dt = _et(2026, 8, 8, 12, 0)  # Sat Aug 8 2026
    assert is_market_closed_for_n_minutes(5, dt=dt) is False
    assert is_market_closed_for_n_minutes(0, dt=dt) is False


def test_returns_false_on_sunday():
    """Sunday — same as Saturday."""
    dt = _et(2026, 8, 9, 23, 0)  # Sun Aug 9 2026
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


def test_returns_false_on_us_holiday():
    """A US holiday (July 4 2026 falls on a Saturday; the NYSE
    observes it on Friday July 3). The NYSE schedule has no
    session on July 3, so the predicate is False."""
    dt = _et(2026, 7, 3, 17, 0)  # Fri Jul 3, observed Independence Day
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


# ---------------------------------------------------------------------------
# Half-day (Christmas Eve / day-after-Thanksgiving)
# ---------------------------------------------------------------------------


def test_returns_true_5_min_past_halfday_close():
    """Christmas Eve is a half-day: NYSE closes at 1:00pm ET. With
    offset=5, the predicate is True at 1:05pm."""
    dt = _et(2026, 12, 24, 13, 5)  # Thu Dec 24 2026, 1:05pm ET
    assert is_market_closed_for_n_minutes(5, dt=dt) is True


def test_returns_false_just_before_halfday_close():
    """12:55pm ET on a half-day with offset=5: only 5 minutes to
    close, not 5 past. Predicate is False."""
    dt = _et(2026, 12, 24, 12, 55)
    assert is_market_closed_for_n_minutes(5, dt=dt) is False


# ---------------------------------------------------------------------------
# Wall-clock fallback
# ---------------------------------------------------------------------------


def test_dt_kwarg_is_optional_returns_bool(monkeypatch) -> None:
    """When ``dt`` is omitted, the function reads the current wall
    clock in ET. The result is bool-shaped (True or False depending
    on the day/time) — we just assert it returns a bool without
    raising.

    We don't assert the specific value because the test's wall
    clock isn't deterministic (CI / slow runners might land in
    a different market phase than the developer). The contract
    under test is "the function doesn't crash on a None dt" and
    "the return type is bool".
    """
    result = is_market_closed_for_n_minutes(5)
    assert isinstance(result, bool)
