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
from typing import Any

import httpx

_client: httpx.AsyncClient | None = None
_lock: asyncio.Lock | None = None


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
