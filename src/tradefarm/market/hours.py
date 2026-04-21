from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas_market_calendars as mcal

NYSE = mcal.get_calendar("XNYS")
ET = ZoneInfo("America/New_York")

RTH_OPEN = time(9, 30)
RTH_CLOSE = time(16, 0)


def now_et() -> datetime:
    return datetime.now(tz=ET)


def is_market_open(dt: datetime | None = None) -> bool:
    dt = dt or now_et()
    schedule = NYSE.schedule(start_date=dt.date(), end_date=dt.date())
    if schedule.empty:
        return False
    open_ts = schedule.iloc[0]["market_open"].to_pydatetime()
    close_ts = schedule.iloc[0]["market_close"].to_pydatetime()
    return open_ts <= dt <= close_ts


def next_open(dt: datetime | None = None) -> datetime:
    dt = dt or now_et()
    schedule = NYSE.schedule(start_date=dt.date(), end_date=dt.date().replace(day=min(dt.day + 10, 28)))
    future = schedule[schedule["market_open"] > dt]
    if future.empty:
        raise RuntimeError("No market open found in next 10 days")
    return future.iloc[0]["market_open"].to_pydatetime()
