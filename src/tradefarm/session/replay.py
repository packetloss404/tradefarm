"""Per-day replay engine — runs one historical trading day through the
orchestrator with the injected clock pointing at that day's close.

The caller (session/run.py) is responsible for:
- Having set the session_id ContextVar via runtime.session_context.set_session_id
- Constructing the Orchestrator (typically via Orchestrator.build_default)
- Iterating across days (this module handles one day at a time)
- DB init (so trade/snapshot writes don't fail on missing tables)

Skeleton — implementation lives in this file; see TODOs.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone

from tradefarm.market.hours import ET
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.runtime.clock import reset_replay_now, set_replay_now


async def run_day(orch: Orchestrator, trading_day: date) -> dict:
    """Run one trading day through `orch.tick_once()` with the replay clock
    set to that day's NYSE close (4:00 PM ET, converted to UTC).

    Returns the dict returned by tick_once (typically
    {"fills": N, "blocked": M, "symbols": K}). Per-row data lands in the
    DB tagged with the active session_id; the manifest builder reads it
    from there, not from this return value.

    Implementation notes for the agent:
    - Use tradefarm.runtime.clock.set_replay_now / reset_replay_now to
      pin the clock for the duration of this call. The pattern:
        token = set_replay_now(<aware datetime at NYSE close for trading_day>)
        try: result = await orch.tick_once()
        finally: reset_replay_now(token)
    - NYSE close is 16:00 ET. Use tradefarm.market.hours.ET for the
      timezone (ZoneInfo("America/New_York")).
    - DO NOT touch the session_id ContextVar — that's the runner's job
      and is set once for the entire session, not per-day.
    - tick_once internally calls _load_bars which now consults
      today_utc(), so the bar window will end at `trading_day` once the
      clock is pinned.
    """
    close_et = datetime.combine(trading_day, time(16, 0), tzinfo=ET)
    close_utc = close_et.astimezone(timezone.utc)
    token = set_replay_now(close_utc)
    try:
        result = await orch.tick_once()
    finally:
        reset_replay_now(token)
    return result
