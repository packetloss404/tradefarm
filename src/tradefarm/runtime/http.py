"""Shared httpx.AsyncClient — one per-process, reused across LLM /
EODHD / YouTube callers.

Round-5 audit fix (AA): previously every API call instantiated a new
``httpx.AsyncClient``, paying TLS handshake + connection-pool init
cost each time. With 100 agents × 5-min ticks + commentary every 45s
+ YouTube poller, that's hundreds of avoidable connections per hour.

A single long-lived client keeps the HTTP/2 connection pool warm,
reuses TLS sessions, and respects keepalive — measurable latency
+ network win at the cost of one shared resource that needs to be
closed at shutdown.

Usage::

    from tradefarm.runtime.http import shared_client
    async with shared_client() as c:    # noqa — context manager not needed
        ...
    # OR:
    c = await get_shared_client()
    resp = await c.get(...)

Shutdown is handled by ``aclose_shared_client()``, called from
``Orchestrator.stop_background()``.
"""

from __future__ import annotations

import asyncio
import os
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog

_client: httpx.AsyncClient | None = None
_lock: asyncio.Lock | None = None

log = structlog.get_logger(__name__)


def _lazy_lock() -> asyncio.Lock:
    """The Lock itself must be created inside a running event loop;
    importing this module before the loop exists shouldn't fail."""
    global _lock
    if _lock is None:
        _lock = asyncio.Lock()
    return _lock


async def get_shared_client(**client_kwargs: Any) -> httpx.AsyncClient:
    """Return the shared client, constructing it on first call.

    ``client_kwargs`` only takes effect on the first call (subsequent
    callers get the already-built client). Callers needing distinct
    timeouts should pass ``timeout=`` per-request instead of asking
    for a different client.
    """
    global _client
    if _client is not None:
        return _client
    async with _lazy_lock():
        if _client is None:  # double-check under lock
            # Reasonable defaults: 30s timeout, HTTP/2 enabled, 20
            # keepalive connections (matches scheduler's per-tick
            # decision concurrency).
            limits = httpx.Limits(
                max_keepalive_connections=20,
                max_connections=100,
                keepalive_expiry=60.0,
            )
            _client = httpx.AsyncClient(
                timeout=client_kwargs.pop("timeout", 30.0),
                limits=client_kwargs.pop("limits", limits),
                http2=client_kwargs.pop("http2", False),  # h2 dep optional
                **client_kwargs,
            )
        return _client


async def aclose_shared_client() -> None:
    """Close the shared client. Called from Orchestrator.stop_background."""
    global _client
    if _client is not None:
        try:
            await _client.aclose()
        except Exception:  # noqa: BLE001 — never fail shutdown
            pass
        _client = None


# ---------------------------------------------------------------------------
# Round-6 audit fix (MED-minimax): retry + base-URL allowlist helpers.
# ---------------------------------------------------------------------------

# Default retry budget. Mirrors ``EOD_MAX_RETRIES`` (round-3 H25) so the
# LLM and market-data paths share a single operator-tunable knob.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.4  # seconds; 0.4, 0.8, 1.6 with jitter
RETRY_JITTER_CAP = 0.25  # seconds of additional random delay per attempt

# Hosts the operator explicitly trusts for the MiniMax base URL. The
# "minimax.io" + "minimax.chat" pair covers the production endpoints;
# the env var lets operators add staging mirrors without code changes.
_MINIMAX_BUILTIN_HOSTS: frozenset[str] = frozenset(
    {"api.minimax.io", "api.minimax.chat"}
)


def _extra_hosts() -> frozenset[str]:
    """Read MINIMAX_EXTRA_HOSTS (CSV) and return as a frozenset."""
    raw = os.environ.get("MINIMAX_EXTRA_HOSTS", "")
    return frozenset(h.strip() for h in raw.split(",") if h.strip())


def validate_minimax_base_url(url: str) -> None:
    """Validate the MiniMax base URL: https + host in the allowlist.

    Raises ``ValueError`` on construction time when an operator points
    ``minimax_base_url`` at a non-https scheme or an unknown host. The
    bearer token (``Authorization: Bearer <minimax_api_key>``) would
    otherwise leak to whatever URL was provided.
    """
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(
            f"minimax_base_url must use https (got scheme={parsed.scheme!r})"
        )
    host = (parsed.hostname or "").lower()
    allowed = _MINIMAX_BUILTIN_HOSTS | _extra_hosts()
    if host not in allowed:
        raise ValueError(
            f"minimax_base_url host {host!r} is not in the allowlist "
            f"(built-in: {sorted(_MINIMAX_BUILTIN_HOSTS)}; "
            f"set MINIMAX_EXTRA_HOSTS to add staging mirrors)"
        )


async def with_retries(
    fn: Callable[[], Awaitable[Any]],
    *,
    label: str = "request",
    attempts: int = RETRY_ATTEMPTS,
    base_delay: float = RETRY_BASE_DELAY,
) -> Any:
    """Run ``fn`` with exponential backoff + jitter on transient errors.

    Retries on ``httpx.HTTPStatusError`` with 5xx or 429, and on any
    ``httpx.RequestError`` (network / timeout). Non-retryable HTTP
    statuses (4xx other than 429) bubble up immediately. The final
    attempt's exception bubbles to the caller.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts + 1):
        try:
            return await fn()
        except httpx.HTTPStatusError as e:
            last_exc = e
            if e.response.status_code < 500 and e.response.status_code != 429:
                raise
            if attempt == attempts:
                raise
        except httpx.RequestError as e:
            last_exc = e
            if attempt == attempts:
                raise
        delay = base_delay * (2**attempt) + random.uniform(0, RETRY_JITTER_CAP)
        log.info(
            "http_retry",
            label=label,
            attempt=attempt + 1,
            delay=round(delay, 3),
            err=type(last_exc).__name__,
        )
        await asyncio.sleep(delay)
    # Unreachable: the loop either returns or raises. The assert keeps
    # the type-checker happy.
    assert last_exc is not None
    raise last_exc
