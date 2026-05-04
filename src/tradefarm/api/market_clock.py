"""Market clock router — exposes the NYSE session phase to the dashboard.

Phases follow the convention used by the rest of the app:
- premarket: 04:00 ET to 09:30 ET on a trading day
- rth:      09:30 ET to 16:00 ET on a trading day
- afterhours: 16:00 ET to 20:00 ET on a trading day
- closed:   weekends, holidays, or any time outside the windows above

The XNYS calendar from pandas-market-calendars handles weekends, holidays,
half-days, etc. We cache it at module load — calendar construction allocates
non-trivially and the contents only change when the project upgrades the
package.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from functools import lru_cache
from typing import Any, Literal
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal
import structlog
from fastapi import APIRouter

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/market", tags=["market"])

ET = ZoneInfo("America/New_York")

PREMARKET_START = time(4, 0)
RTH_START = time(9, 30)
RTH_END = time(16, 0)
AFTERHOURS_END = time(20, 0)

Phase = Literal["premarket", "rth", "afterhours", "closed"]


@lru_cache(maxsize=1)
def _calendar() -> Any:
    return mcal.get_calendar("XNYS")


def _schedule_for(now_utc: datetime) -> pd.DataFrame:
    """Window the calendar around `now_utc`. Wide enough to find the next open
    after a long weekend / holiday cluster without re-querying.
    """
    cal = _calendar()
    start = (now_utc - timedelta(days=4)).date()
    end = (now_utc + timedelta(days=10)).date()
    return cal.schedule(start_date=start, end_date=end)


def _next_open_close(
    schedule: pd.DataFrame, now_utc: datetime,
) -> tuple[datetime | None, datetime | None]:
    next_open: datetime | None = None
    next_close: datetime | None = None
    for _, row in schedule.iterrows():
        mo: datetime = row["market_open"].to_pydatetime()
        mc: datetime = row["market_close"].to_pydatetime()
        if next_open is None and mo > now_utc:
            next_open = mo
        if next_close is None and mc > now_utc:
            next_close = mc
        if next_open is not None and next_close is not None:
            break
    return next_open, next_close


def _phase(now_et: datetime, schedule: pd.DataFrame) -> Phase:
    today = now_et.date()
    is_trading_day = any(idx.date() == today for idx in schedule.index)
    if not is_trading_day:
        return "closed"
    t = now_et.time()
    if PREMARKET_START <= t < RTH_START:
        return "premarket"
    if RTH_START <= t < RTH_END:
        return "rth"
    if RTH_END <= t < AFTERHOURS_END:
        return "afterhours"
    return "closed"


@router.get("/clock")
async def market_clock() -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    schedule = _schedule_for(now_utc)

    phase = _phase(now_et, schedule)
    next_open, next_close = _next_open_close(schedule, now_utc)

    return {
        "phase": phase,
        "server_now": now_utc.isoformat(),
        "opens_at": next_open.isoformat() if next_open is not None else None,
        "closes_at": next_close.isoformat() if next_close is not None else None,
    }
