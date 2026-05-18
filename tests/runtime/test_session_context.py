import asyncio

import pytest

from tradefarm.runtime.session_context import (
    current_session_id,
    reset_session_id,
    set_session_id,
)


def test_unset_returns_none() -> None:
    assert current_session_id() is None


def test_set_and_reset_roundtrip() -> None:
    token = set_session_id("s_abc123")
    try:
        assert current_session_id() == "s_abc123"
    finally:
        reset_session_id(token)
    assert current_session_id() is None


def test_rejects_empty_string() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        set_session_id("")


def test_concurrent_tasks_have_isolated_session_ids() -> None:
    async def task_with_session(sid: str) -> str | None:
        token = set_session_id(sid)
        try:
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            return current_session_id()
        finally:
            reset_session_id(token)

    async def run_both() -> tuple[str | None, str | None]:
        return await asyncio.gather(
            task_with_session("s_one"),
            task_with_session("s_two"),
        )

    a, b = asyncio.run(run_both())
    assert a == "s_one"
    assert b == "s_two"


def test_unset_task_does_not_leak_from_setter_sibling() -> None:
    async def setter() -> None:
        token = set_session_id("s_leak_test")
        await asyncio.sleep(0)
        reset_session_id(token)

    async def observer() -> str | None:
        await asyncio.sleep(0)
        return current_session_id()

    async def run_both() -> str | None:
        # Sibling tasks share NO context unless explicitly copied;
        # observer should never see setter's value
        _, observed = await asyncio.gather(setter(), observer())
        return observed

    assert asyncio.run(run_both()) is None
