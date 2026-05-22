from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

from tradefarm.runtime.clock import now_utc

NYSE = mcal.get_calendar("XNYS")
ET = ZoneInfo("America/New_York")

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def now_et() -> datetime:
    return now_utc().astimezone(ET)


def is_market_open(dt: datetime | None = None) -> bool:
    dt = dt or now_et()
    schedule = NYSE.schedule(start_date=dt.date(), end_date=dt.date())
    if schedule.empty:
        return False
    open_ts = schedule.iloc[0]["market_open"].to_pydatetime()
    close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_ts <= dt <= close_ts


def trading_days_between(start: datetime, end: datetime) -> float:
    """Approximate trading days between two timestamps.

    Used by the RiskManager's time-stop so a position opened Friday and
    evaluated Tuesday is counted as ~2 trading days, not 4 wall-clock
    days. Returns a float so partial-day fractions are sensible.

    Implementation: count NYSE schedule rows between start and end,
    inclusive on the start side. Cheap (< 1 ms for spans up to a year).
    """
    if end <= start:
        return 0.0
    schedule = NYSE.schedule(start_date=start.date(), end_date=end.date())
    if schedule.empty:
        return 0.0
    # Count whole-trading-day rows + partial fraction of the trailing
    # in-progress session.
    days = float(len(schedule))
    last_close = schedule.iloc[-1]["market_close"].to_pydatetime()
    if end < last_close:
        # Subtract the unused portion of the last session.
        last_open = schedule.iloc[-1]["market_open"].to_pydatetime()
        session_len = (last_close - last_open).total_seconds()
        elapsed = max(0.0, (end - last_open).total_seconds())
        days -= 1.0 - min(1.0, elapsed / session_len)
    return days


def next_open(dt: datetime | None = None) -> datetime:
    # Earlier version did `dt.date().replace(day=min(dt.day + 10, 28))`,
    # which moves *backward* at month-end (e.g. Sept 30 → Sept 28) and
    # raised "No market open found" after a long weekend. timedelta
    # never wraps months and always advances.
    from datetime import timedelta
    dt = dt or now_et()
    end_date = dt.date() + timedelta(days=10)
    schedule = NYSE.schedule(start_date=dt.date(), end_date=end_date)
    future = schedule[schedule["market_open"] > dt]
    if future.empty:
        raise RuntimeError("No market open found in next 10 days")
    return future.iloc[0]["market_open"].to_pydatetime()
