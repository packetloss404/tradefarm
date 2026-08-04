"""Round-6 audit fix (MED-minimax): MiniMax retry + base-URL allowlist.

- ``runtime.http.with_retries`` retries transient 5xx / 429 / network
  errors with exponential backoff + jitter. Non-retryable 4xx
  responses bubble immediately.
- ``runtime.http.validate_minimax_base_url`` rejects non-https URLs
  and hosts not in the built-in allowlist (or the
  ``MINIMAX_EXTRA_HOSTS`` env var).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from tradefarm.runtime.http import (
    validate_minimax_base_url,
    with_retries,
)


# ---------------------------------------------------------------------------
# validate_minimax_base_url
# ---------------------------------------------------------------------------


def test_validate_minimax_accepts_builtin_https_host():
    # Built-in host, https — no raise.
    validate_minimax_base_url("https://api.minimax.io/v1")


def test_validate_minimax_accepts_chat_host():
    validate_minimax_base_url("https://api.minimax.chat/v1")


def test_validate_minimax_rejects_http_scheme():
    with pytest.raises(ValueError, match="must use https"):
        validate_minimax_base_url("http://api.minimax.io/v1")


def test_validate_minimax_rejects_unknown_host():
    with pytest.raises(ValueError, match="not in the allowlist"):
        validate_minimax_base_url("https://internal-collector/v1")


def test_validate_minimax_honors_env_extra_hosts(monkeypatch):
    monkeypatch.setenv("MINIMAX_EXTRA_HOSTS", "staging.minimax.io,beta.minimax.io")
    # The env var should be read on every call, not cached.
    validate_minimax_base_url("https://staging.minimax.io/v1")
    validate_minimax_base_url("https://beta.minimax.io/v1")
    # The non-listed host still fails.
    with pytest.raises(ValueError, match="not in the allowlist"):
        validate_minimax_base_url("https://prod.minimax.io/v1")


# ---------------------------------------------------------------------------
# with_retries
# ---------------------------------------------------------------------------


async def test_with_retries_returns_first_success():
    fn = AsyncMock(return_value={"ok": True})
    result = await with_retries(fn, label="t", attempts=3, base_delay=0.0)
    assert result == {"ok": True}
    assert fn.await_count == 1


async def test_with_retries_succeeds_after_2_5xx():
    responses = [
        _resp(503),
        _resp(502),
        _resp(200, payload={"ok": True}),
    ]
    fn = AsyncMock(side_effect=[r for r in responses])
    # Patch asyncio.sleep so the test runs fast.
    with patch("tradefarm.runtime.http.asyncio.sleep", new=AsyncMock()):
        result = await with_retries(fn, label="t", attempts=3, base_delay=0.0)
    # The helper returns whatever ``fn`` returns — for an httpx call
    # that's an httpx.Response, not the parsed body. The caller is
    # responsible for ``.json()`` (matches the production
    # ``_post_chat_completions`` pattern).
    assert result.status_code == 200
    assert result.json() == {"ok": True}
    assert fn.await_count == 3


async def test_with_retries_does_not_retry_4xx_other_than_429():
    """A 401 is the caller's fault; do not retry."""
    fn = AsyncMock(side_effect=_resp(401))
    with pytest.raises(httpx.HTTPStatusError) as ei:
        await with_retries(fn, label="t", attempts=3, base_delay=0.0)
    assert ei.value.response.status_code == 401
    assert fn.await_count == 1


async def test_with_retries_does_retry_429():
    fn = AsyncMock(
        side_effect=[_resp(429), _resp(429), _resp(200, payload={"ok": True})]
    )
    with patch("tradefarm.runtime.http.asyncio.sleep", new=AsyncMock()):
        result = await with_retries(fn, label="t", attempts=3, base_delay=0.0)
    assert result.status_code == 200
    assert result.json() == {"ok": True}
    assert fn.await_count == 3


async def test_with_retries_eventually_raises_on_5xx():
    fn = AsyncMock(side_effect=_resp(503))
    with patch("tradefarm.runtime.http.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.HTTPStatusError) as ei:
            await with_retries(fn, label="t", attempts=2, base_delay=0.0)
    assert ei.value.response.status_code == 503
    assert fn.await_count == 3  # initial + 2 retries


async def test_with_retries_eventually_raises_on_request_error():
    fn = AsyncMock(side_effect=httpx.ConnectError("network down"))
    with patch("tradefarm.runtime.http.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(httpx.ConnectError):
            await with_retries(fn, label="t", attempts=2, base_delay=0.0)
    assert fn.await_count == 3


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resp(status: int, *, payload: dict | None = None):
    """Build an httpx.Response (or HTTPStatusError) for the side_effect chain.

    The successful path returns a real ``httpx.Response`` so callers can
    ``.json()`` it; the error path returns a real ``HTTPStatusError``
    so the retry helper's ``except`` clause catches it.
    """
    if status >= 400:
        request = httpx.Request("POST", "https://api.minimax.io/v1/chat/completions")
        response = httpx.Response(status_code=status, request=request)
        return httpx.HTTPStatusError(
            f"{status} error", request=request, response=response
        )
    # Successful response — a real httpx.Response the caller can .json().
    return httpx.Response(
        status_code=status,
        json=payload or {},
        request=httpx.Request("POST", "https://api.minimax.io/v1/chat/completions"),
    )
