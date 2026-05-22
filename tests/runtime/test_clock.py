import asyncio
from datetime import datetime, timezone

import pytest

from tradefarm.runtime.clock import (
    is_replaying,
    now_utc,
    reset_replay_now,
    set_replay_now,
    today_utc,
)


def test_falls_through_to_wallclock_when_unset() -> None:
    before = datetime.now(timezone.utc)
    actual = now_utc()
    after = datetime.now(timezone.utc)
    assert before <= actual <= after
    assert not is_replaying()


def test_override_is_returned_when_set() -> None:
    fixed = datetime(2026, 5, 15, 14, 30, tzinfo=timezone.utc)
    token = set_replay_now(fixed)
    try:
        assert now_utc() == fixed
        assert today_utc() == fixed.date()
        assert is_replaying()
    finally:
        reset_replay_now(token)


def test_reset_restores_wallclock() -> None:
    fixed = datetime(2025, 1, 1, tzinfo=timezone.utc)
    token = set_replay_now(fixed)
    reset_replay_now(token)
    assert not is_replaying()
    # now_utc should be close to wall clock again
    delta = abs((now_utc() - datetime.now(timezone.utc)).total_seconds())
    assert delta < 1.0


def test_rejects_naive_datetime() -> None:
    naive = datetime(2026, 5, 15, 14, 30)
    with pytest.raises(ValueError, match="tz-aware"):
        set_replay_now(naive)


def test_concurrent_tasks_have_isolated_overrides() -> None:
    """Two asyncio tasks running concurrently should not see each other's override."""

    async def task_with_override(year: int) -> int:
        fixed = datetime(year, 6, 1, tzinfo=timezone.utc)
        token = set_replay_now(fixed)
        try:
            # Yield to the event loop so sibling tasks can interleave
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return now_utc().year
        finally:
            reset_replay_now(token)

    async def run_both() -> tuple[int, int]:
        a, b = await asyncio.gather(
            task_with_override(2024),
            task_with_override(2026),
        )
        return a, b

    a_year, b_year = asyncio.run(run_both())
    assert a_year == 2024
    assert b_year == 2026


def test_parent_override_does_not_leak_into_uncontextualized_call() -> None:
    """After reset, even within the same call stack, the override is gone."""
    fixed = datetime(2030, 1, 1, tzinfo=timezone.utc)
    token = set_replay_now(fixed)
    reset_replay_now(token)
    # And the value is wall-clock, not the fixed value
    assert (
        now_utc().year != 2030
        or abs((now_utc() - datetime.now(timezone.utc)).total_seconds()) < 1.0
    )
