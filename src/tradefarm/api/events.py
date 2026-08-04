"""In-process async pub/sub event bus for dashboard server-push.

Envelope: {"type": str, "ts": iso8601_utc, "payload": dict}
Per-subscriber asyncio.Queue; fan-out on publish; drop-on-disconnect.
Slow subscribers (queue > MAX_QUEUE) get dropped by the WS layer.

Round-6 audit fix (B3-WS): events dropped because a subscriber's queue
was full are no longer silently swallowed. ``EventBus`` tracks a
process-wide drop counter and the timestamp of the first drop in the
current window. The dashboard queries ``GET /stream-gap`` after a WS
reconnect to learn how many events were lost and trigger a state
re-fetch.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

MAX_QUEUE = 100


def _now_iso() -> str:
    # Event envelopes carry `ts` — use the injectable clock so events
    # published during a replay session are tagged with the replayed
    # timestamp. Consumers that compare (now - ts) for "age" would
    # otherwise see all replayed events as decades old.
    from tradefarm.runtime.clock import now_utc

    return now_utc().isoformat()


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()
        # Round-6 audit fix (B3-WS): counters for events dropped because
        # a subscriber's queue was at MAX_QUEUE. Atomically reset by
        # consume_dropped(). Tracked under _lock for consistency.
        self._dropped_count: int = 0
        self._first_drop_ts: str | None = None
        self._last_drop_ts: str | None = None

    async def publish(self, event: dict) -> None:
        # Snapshot under lock so unsubscribe during fan-out is safe.
        async with self._lock:
            subs = list(self._subs)
        # Track drops separately so the WS layer can later surface them
        # to the dashboard as a ``stream_gap`` signal. We only need the
        # event ts (not its contents) for the gap report.
        event_ts = str(event.get("ts") or _now_iso())
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Full queue => slow client; let WS layer drop it.
                # Count the loss so the frontend can recover instead of
                # rendering stale state.
                async with self._lock:
                    self._dropped_count += 1
                    if self._first_drop_ts is None:
                        self._first_drop_ts = event_ts
                    self._last_drop_ts = event_ts

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

    async def consume_dropped(self) -> dict:
        """Atomically read+reset the drop counter for the current window.

        Returns a dict shaped like::

            {"dropped": int, "first_drop_ts": str | None, "last_drop_ts": str | None}

        so ``GET /stream-gap`` can serialize it directly. Reset is in
        the same critical section as the read so a concurrent publish
        either counts into the new window or doesn't.
        """
        async with self._lock:
            payload = {
                "dropped": self._dropped_count,
                "first_drop_ts": self._first_drop_ts,
                "last_drop_ts": self._last_drop_ts,
            }
            self._dropped_count = 0
            self._first_drop_ts = None
            self._last_drop_ts = None
        return payload


bus = EventBus()


async def publish_event(type: str, payload: dict) -> None:
    await bus.publish({"type": type, "ts": _now_iso(), "payload": payload})
