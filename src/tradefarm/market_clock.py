"""Market clock helper for the VOD scheduler.

Small, dependency-free wrapper around ``tradefarm.market.hours`` for the
one question the daily scheduler loop asks every few minutes: is the
NYSE session closed long enough ago that I should kick off today's
pipeline run?

The full phase / next-open / schedule logic lives in
``tradefarm.api.market_clock`` (the dashboard router) and
``tradefarm.market.hours`` (the calendar wrapper). This module just
exposes the per-day "have we crossed the post-close cool-off yet"
predicate, in a callable form the scheduler can `await` cleanly.

Why not just call ``is_market_open()`` + sleep? The scheduler needs
"the session has been closed for N minutes" — not the inverse
"the session is not currently open" (which is also true on weekends,
holidays, and lunch). A holiday at 11:00 ET would return
``is_market_open() == False`` but ``is_market_closed_for_n_minutes(5) ==
False`` too, because the session never opened today. The latter
predicate is what the scheduler wants.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from tradefarm.market.hours import NYSE, ET
from tradefarm.runtime.clock import now_utc

# NYSE RTH close (ET). Used as a default; the real per-day close is read
# from the pandas-market-calendars schedule so half-days (Thanksgiving
# Friday, Christmas Eve) correctly shorten the window.
RTH_CLOSE = time(16, 0)


def _today_close_et(now_et: datetime) -> time | None:
    """Return today's actual RTH close time-of-day (ET), or None if today
    is a holiday / weekend with no NYSE session.

    Mirrors ``tradefarm.api.market_clock._today_close_et`` but kept local
    so this module stays free of FastAPI imports (the scheduler imports
    it at boot, before the API surface is wired up).
    """
    schedule = NYSE.schedule(start_date=now_et.date(), end_date=now_et.date())
    if schedule.empty:
        return None
    close = schedule.iloc[0]["market_close"].to_pydatetime()
    return close.astimezone(ET).time()


def is_market_closed_for_n_minutes(
    n: int, *, dt: datetime | None = None
) -> bool:
    """True when the current NYSE session has been closed for at least
    ``n`` minutes (i.e., it is now at least ``RTH_CLOSE + n min`` ET).

    Returns False on weekends / holidays (no session today) so the
    scheduler doesn't treat a Monday 09:00 as "Sunday's session closed
    17 hours ago" and fire spuriously. Returns False before the session
    has even opened today (premarket, etc.) so a misconfigured 16:00
    scheduler can't trip at 09:00.

    ``dt`` is injectable for tests; defaults to wall-clock-now in ET.
    """
    if dt is None:
        dt = now_utc().astimezone(ET)
    else:
        dt = dt.astimezone(ET)
    today_close = _today_close_et(dt)
    if today_close is None:
        # No NYSE session today — weekend or holiday. Don't fire.
        return False
    close_dt = dt.replace(
        hour=today_close.hour,
        minute=today_close.minute,
        second=0,
        microsecond=0,
    )
    threshold = close_dt + timedelta(minutes=n)
    return dt >= threshold
