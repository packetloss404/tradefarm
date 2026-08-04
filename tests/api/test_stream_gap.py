"""Round-6 audit fix (B3-WS): /api/stream-gap endpoint.

Events that get dropped because a subscriber's WebSocket queue is at
MAX_QUEUE are tracked on the EventBus. ``GET /api/stream-gap`` reads +
atomically resets that counter so the frontend can recover from a
stalled-WS reconnect (force a state re-fetch instead of rendering
stale data).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

import tradefarm.api.main as main_mod
from tradefarm.api.events import bus


@pytest.fixture
def app_with_bus():
    """Make sure the FastAPI app is importable and the bus is a real instance."""
    return main_mod.app


async def test_stream_gap_reports_zero_when_no_drops(app_with_bus):
    transport = ASGITransport(app=app_with_bus)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/stream-gap")
    assert r.status_code == 200
    body = r.json()
    assert body["dropped"] == 0
    assert body["first_drop_ts"] is None
    assert body["last_drop_ts"] is None


async def test_stream_gap_counts_dropped_events(app_with_bus):
    """Force the bus to register a drop by filling a small queue."""
    # Save and restore the dropped state around the test.
    saved = (bus._dropped_count, bus._first_drop_ts, bus._last_drop_ts)
    bus._dropped_count = 5
    bus._first_drop_ts = "2026-08-03T22:00:00+00:00"
    bus._last_drop_ts = "2026-08-03T22:00:30+00:00"
    try:
        transport = ASGITransport(app=app_with_bus)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r = await ac.get("/stream-gap")
        assert r.status_code == 200
        body = r.json()
        assert body["dropped"] == 5
        assert body["first_drop_ts"] == "2026-08-03T22:00:00+00:00"
        assert body["last_drop_ts"] == "2026-08-03T22:00:30+00:00"
    finally:
        bus._dropped_count, bus._first_drop_ts, bus._last_drop_ts = saved


async def test_stream_gap_resets_after_read(app_with_bus):
    saved = (bus._dropped_count, bus._first_drop_ts, bus._last_drop_ts)
    bus._dropped_count = 7
    bus._first_drop_ts = "2026-08-03T22:00:00+00:00"
    bus._last_drop_ts = "2026-08-03T22:00:30+00:00"
    try:
        transport = ASGITransport(app=app_with_bus)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r1 = await ac.get("/stream-gap")
        assert r1.json()["dropped"] == 7

        # Second call should see 0 because consume_dropped() resets.
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            r2 = await ac.get("/stream-gap")
        assert r2.json()["dropped"] == 0
        assert r2.json()["first_drop_ts"] is None
        assert r2.json()["last_drop_ts"] is None
    finally:
        bus._dropped_count, bus._first_drop_ts, bus._last_drop_ts = saved


async def test_stream_gap_echoes_since_query_param(app_with_bus):
    transport = ASGITransport(app=app_with_bus)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/stream-gap?since=2026-08-03T22:00:00%2B00:00")
    assert r.status_code == 200
    body = r.json()
    assert body["since"] == "2026-08-03T22:00:00+00:00"
