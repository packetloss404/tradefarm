"""WebSocket endpoint that streams EventBus envelopes to the dashboard."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tradefarm.api.events import MAX_QUEUE, bus

router = APIRouter()

HEARTBEAT_SEC = 15


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.websocket("/ws")
async def ws_stream(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"type": "hello", "ts": _now_iso(), "payload": {"subscribed": True}})

    async with bus.subscribe() as q:
        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_SEC)
                await ws.send_json({
                    "type": "heartbeat",
                    "ts": _now_iso(),
                    "payload": {"qsize": q.qsize()},
                })

        hb_task = asyncio.create_task(heartbeat())
        try:
            while True:
                # Drop slow clients: queue backed up past MAX_QUEUE items.
                if q.qsize() > MAX_QUEUE:
                    await ws.close(code=1011, reason="slow client")
                    return
                event = await q.get()
                await ws.send_json(event)
        except WebSocketDisconnect:
            return
        except Exception:
            try:
                await ws.close()
            except Exception:
                pass
            return
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except (asyncio.CancelledError, Exception):
                pass
