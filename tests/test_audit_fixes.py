"""Regression tests for the 20-agent audit's top critical findings.

Covers fixes for:
  - Scheduler / decision_feed / events / auto_director / streak_watcher
    bypassing the injectable clock (replay-mode timestamp corruption)
  - market.hours.next_open arithmetic bug at month-end
  - YouTube OAuth error logging leaking the raw response body
  - Headless renderer session_id path-traversal guard
  - auto_tick_interval_sec default flipped from 0 to 300
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


# ----- clock injection ---------------------------------------------------


def test_events_now_iso_honours_replay_clock():
    """Event envelope `ts` must follow the injectable clock — otherwise
    every replay-mode event ships with wall-clock timestamps that the
    frontend then misinterprets as "decades ago"."""
    from tradefarm.api.events import _now_iso
    from tradefarm.runtime.clock import set_replay_now, reset_replay_now

    pinned = datetime(2026, 5, 15, 20, 0, tzinfo=timezone.utc)
    token = set_replay_now(pinned)
    try:
        assert _now_iso() == pinned.isoformat()
    finally:
        reset_replay_now(token)


def test_decision_feed_now_iso_honours_replay_clock():
    from tradefarm.orchestrator.decision_feed import _now_iso
    from tradefarm.runtime.clock import set_replay_now, reset_replay_now

    pinned = datetime(2025, 11, 27, 14, 30, tzinfo=timezone.utc)
    token = set_replay_now(pinned)
    try:
        assert _now_iso() == pinned.isoformat()
    finally:
        reset_replay_now(token)


def test_auto_director_utcnow_honours_replay_clock():
    from tradefarm.orchestrator.auto_director import _utcnow
    from tradefarm.runtime.clock import set_replay_now, reset_replay_now

    pinned = datetime(2026, 1, 2, 14, 30, tzinfo=timezone.utc)
    token = set_replay_now(pinned)
    try:
        assert _utcnow() == pinned
    finally:
        reset_replay_now(token)


def test_streak_watcher_utcnow_honours_replay_clock():
    from tradefarm.orchestrator.streak_watcher import _utcnow
    from tradefarm.runtime.clock import set_replay_now, reset_replay_now

    pinned = datetime(2025, 6, 17, 16, 45, tzinfo=timezone.utc)
    token = set_replay_now(pinned)
    try:
        assert _utcnow() == pinned
    finally:
        reset_replay_now(token)


def test_clock_helper_falls_back_to_wall_when_no_override():
    """No leakage: when no override is set the helpers return real now."""
    from tradefarm.api.events import _now_iso

    before = datetime.now(timezone.utc)
    ts = datetime.fromisoformat(_now_iso())
    after = datetime.now(timezone.utc)
    assert before <= ts <= after + timedelta(seconds=1)


# ----- market.hours.next_open -------------------------------------------


def test_next_open_handles_month_end_long_weekend():
    """The earlier `dt.date().replace(day=min(dt.day + 10, 28))` arithmetic
    moves backwards at month-end (e.g. Sept 30 → Sept 28) and could raise
    "No market open found" after a holiday-long weekend. timedelta never
    wraps months."""
    from tradefarm.market.hours import next_open

    # Friday before a typical month-end. The function should find next
    # Monday's open without raising regardless of the day-of-month.
    for d in (
        datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc),  # Aug 31
        datetime(2026, 7, 31, 18, 0, tzinfo=timezone.utc),  # Jul 31
        datetime(2027, 1, 31, 18, 0, tzinfo=timezone.utc),  # Jan 31
        datetime(2026, 5, 29, 22, 0, tzinfo=timezone.utc),  # Fri before Memorial Day
    ):
        nxt = next_open(d)
        assert nxt > d
        # And not later than 10 days out (the bound the helper claims).
        assert (nxt - d).days <= 10


# ----- youtube_chat secret-leak guard -----------------------------------


def test_oauth_error_log_does_not_include_raw_body():
    """Regression: the earlier code logged `body=r.text[:300]` on a 4xx
    OAuth response. Google's invalid_grant body can echo the
    client_secret query — should never reach a log line. Verify the
    new code only emits the canonical error code."""
    import inspect
    from tradefarm.orchestrator import youtube_chat

    src = inspect.getsource(youtube_chat.YouTubeChatPoller._refresh_access_token)
    assert "r.text" not in src
    assert "error_code" in src


# ----- headless renderer path-traversal guard ---------------------------


async def test_render_session_rejects_traversal_session_id(tmp_path):
    """The session_id flows into mkdir() — must be sanitised regardless
    of whether the call came from the REST/WS path or the CLI."""
    from tradefarm.render.headless import render_session

    # 0.14.0 — the stream liveness probe (added in round 9) runs
    # BEFORE the path-traversal guard. These post-probe unit
    # tests use `_probe=False` to bypass the live dependency.
    with pytest.raises(ValueError, match="invalid session_id"):
        await render_session("../escape", sessions_dir=tmp_path, _probe=False)


# ----- config default --------------------------------------------------


def test_auto_tick_interval_default_is_300():
    """0 was the old default; that triggered a real "started the backend
    and no data was collected" incident."""
    from tradefarm.config import Settings

    s = Settings(_env_file=None)
    assert s.auto_tick_interval_sec == 300
