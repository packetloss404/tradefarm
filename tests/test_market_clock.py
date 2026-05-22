"""Smoke test for the /market/clock router.

Avoids the full app startup (which would spin up the orchestrator + DB) by
mounting just the router on a fresh FastAPI app.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradefarm.api.market_clock import ET, _next_open_close, _phase, router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_market_clock_returns_one_of_four_phases() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] in {"premarket", "rth", "afterhours", "closed"}


def test_market_clock_server_now_is_iso_utc() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    data = r.json()
    parsed = datetime.fromisoformat(data["server_now"])
    assert parsed.tzinfo is not None


def test_market_clock_open_close_iso_or_null() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    data = r.json()
    for key in ("opens_at", "closes_at"):
        v = data[key]
        if v is None:
            continue
        parsed = datetime.fromisoformat(v)
        assert parsed.tzinfo is not None


# ----- _phase honours per-day close (half-day support) -----------------


def _schedule_row(date_et: datetime, close_hour: int = 16, close_minute: int = 0) -> pd.DataFrame:
    """Build a single-row schedule frame matching pandas-market-calendars'
    shape: DatetimeIndex on the date, tz-aware UTC market_open/close.
    """
    open_ts = pd.Timestamp(
        datetime(date_et.year, date_et.month, date_et.day, 9, 30, tzinfo=ET),
    ).tz_convert("UTC")
    close_ts = pd.Timestamp(
        datetime(date_et.year, date_et.month, date_et.day, close_hour, close_minute, tzinfo=ET),
    ).tz_convert("UTC")
    idx = pd.DatetimeIndex([pd.Timestamp(date_et.date())])
    return pd.DataFrame(
        {"market_open": [open_ts], "market_close": [close_ts]},
        index=idx,
    )


def test_phase_half_day_close_at_1pm_returns_afterhours_at_1330():
    """Day-after-Thanksgiving (and Christmas Eve, sometimes July 3) — NYSE
    closes at 13:00 ET. At 13:30 ET the phase must be 'afterhours', NOT
    'rth'. Without the fix, the broadcast UI showed 'MARKET OPEN' for
    three hours after the bell.
    """
    # Pick an arbitrary trading-day date; the schedule we hand _phase tells
    # it what counts as today.
    date_et = datetime(2026, 11, 27, 13, 30, tzinfo=ET)  # Black Friday 13:30 ET
    schedule = _schedule_row(date_et, close_hour=13, close_minute=0)
    assert _phase(date_et, schedule) == "afterhours"


def test_phase_half_day_still_rth_before_1300():
    date_et = datetime(2026, 11, 27, 12, 30, tzinfo=ET)
    schedule = _schedule_row(date_et, close_hour=13, close_minute=0)
    assert _phase(date_et, schedule) == "rth"


def test_phase_full_day_rth_at_1530():
    date_et = datetime(2026, 5, 22, 15, 30, tzinfo=ET)
    schedule = _schedule_row(date_et, close_hour=16, close_minute=0)
    assert _phase(date_et, schedule) == "rth"


def test_phase_returns_closed_when_date_not_in_schedule():
    # Saturday with an empty schedule.
    sat = datetime(2026, 5, 23, 12, 0, tzinfo=ET)
    schedule = pd.DataFrame(columns=["market_open", "market_close"])
    assert _phase(sat, schedule) == "closed"


# ----- _next_open_close boundary at exact close instant ----------------


def test_next_close_at_exact_close_instant_returns_today_not_tomorrow():
    """At exactly 16:00:00 ET on a trading day, 'next close' should still
    be today's close (the tick we just hit), not tomorrow's. Otherwise the
    dashboard's countdown chip jumps by 17.5 hours for one tick.
    """
    today_et = datetime(2026, 5, 22, 16, 0, tzinfo=ET)
    today_utc = today_et.astimezone(timezone.utc)
    tomorrow_et = today_et + timedelta(days=1)
    sched = pd.concat(
        [
            _schedule_row(today_et),
            _schedule_row(tomorrow_et),
        ]
    )
    sched.index = pd.DatetimeIndex(
        [
            pd.Timestamp(today_et.date()),
            pd.Timestamp(tomorrow_et.date()),
        ]
    )

    _, next_close = _next_open_close(sched, today_utc)
    assert next_close is not None
    # Must be today's close, not tomorrow's.
    assert next_close.astimezone(ET).date() == today_et.date()
