"""In-process async pub/sub event bus for dashboard server-push.

Envelope: {"type": str, "ts": iso8601_utc, "payload": dict}
Per-subscriber asyncio.Queue; fan-out on publish; drop-on-disconnect.
Slow subscribers (queue > MAX_QUEUE) get dropped by the WS layer.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator

MAX_QUEUE = 100


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def publish(self, event: dict) -> None:
        # Snapshot under lock so unsubscribe during fan-out is safe.
        async with self._lock:
            subs = list(self._subs)
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Full queue => slow client; let WS layer drop it.
                pass

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=MAX_QUEUE * 2)
        async with self._lock:
            self._subs.add(q)
        try:
            yield q
        finally:
            async with self._lock:
                self._subs.discard(q)


bus = EventBus()


async def publish_event(type: str, payload: dict) -> None:
    await bus.publish({"type": type, "ts": _now_iso(), "payload": payload})
