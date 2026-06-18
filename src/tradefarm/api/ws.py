"""WebSocket endpoint.

Default mode: stream live EventBus envelopes to the dashboard.

Replay mode: client sends a `{type: "replay", session_id, at, until,
speed}` frame as the first message; backend reads the named session's
manifest and replays its events in the requested time window. The
headless renderer leans on this — it loads stream/?replay=…&at=… with
a high `speed`, captures N seconds, and closes the page.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from tradefarm.api.events import MAX_QUEUE, bus
from tradefarm.session import replay_query

router = APIRouter()

HEARTBEAT_SEC = 15
REPLAY_HANDSHAKE_TIMEOUT_SEC = 0.5  # if no replay frame within this, assume live
# Cap how long a replay can pump real-time. The headless renderer uses
# speed >> 1 so this comes back well under a second per beat.
REPLAY_MAX_WALL_SLEEP_SEC = 0.2


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _maybe_read_replay_handshake(ws: WebSocket) -> dict | None:
    """Wait briefly for a replay frame. Anything else (including timeout
    or non-replay JSON) means the client wants live mode."""
    try:
        frame = await asyncio.wait_for(ws.receive_json(), timeout=REPLAY_HANDSHAKE_TIMEOUT_SEC)
    except (asyncio.TimeoutError, Exception):
        return None
    if isinstance(frame, dict) and frame.get("type") == "replay":
        return frame
    return None


async def _stream_live(ws: WebSocket) -> None:
    async with bus.subscribe() as q:

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_SEC)
                await ws.send_json(
                    {
                        "type": "heartbeat",
                        "ts": _now_iso(),
                        "payload": {"qsize": q.qsize()},
                    }
                )

        hb_task = asyncio.create_task(heartbeat())
        try:
            while True:
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


async def _stream_replay(ws: WebSocket, frame: dict[str, Any]) -> None:
    """Walk the manifest's events in the requested window and emit them
    as if they were live. `speed` divides the wall-clock gap between
    successive events — speed=60 means a 60s manifest gap becomes a 1s
    wall sleep. Speed <= 0 means as-fast-as-possible (no delays)."""

    session_id = frame.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        await ws.send_json(
            {
                "type": "hello",
                "ts": _now_iso(),
                "payload": {"replay": True, "error": "missing session_id"},
            }
        )
        return

    # Path-traversal guard. A WS connection from anywhere CORS allows
    # (the whole LAN, in this project's split-machine topology) can hit
    # this handshake; an unsanitised session_id would let a peer read
    # arbitrary `manifest.json` files anywhere reachable from cwd.
    try:
        replay_query._require_safe_session_id(session_id)
    except ValueError as exc:
        await ws.send_json(
            {
                "type": "hello",
                "ts": _now_iso(),
                "payload": {"replay": True, "error": str(exc)},
            }
        )
        return

    try:
        manifest = replay_query.load_manifest(session_id)
    except FileNotFoundError:
        await ws.send_json(
            {
                "type": "hello",
                "ts": _now_iso(),
                "payload": {"replay": True, "error": f"no manifest for {session_id}"},
            }
        )
        return

    raw_at = frame.get("at") or manifest.get("started_at")
    raw_until = frame.get("until") or manifest.get("ended_at")
    try:
        if not isinstance(raw_at, str):
            raise TypeError("missing 'at' timestamp")
        at_dt = replay_query.parse_iso(raw_at)
        until_dt = replay_query.parse_iso(raw_until) if isinstance(raw_until, str) else None
    except (ValueError, TypeError):
        await ws.send_json(
            {
                "type": "hello",
                "ts": _now_iso(),
                "payload": {"replay": True, "error": "invalid timestamps"},
            }
        )
        return

    try:
        speed = float(frame.get("speed", 60.0))
    except (TypeError, ValueError):
        speed = 60.0

    events = replay_query.events_in_window(manifest, at=at_dt, until=until_dt)

    await ws.send_json(
        {
            "type": "hello",
            "ts": _now_iso(),
            "payload": {
                "replay": True,
                "session_id": session_id,
                "at": at_dt.isoformat(),
                "until": until_dt.isoformat() if until_dt is not None else None,
                "speed": speed,
                "event_count": len(events),
            },
        }
    )

    prev_t: datetime | None = None
    for ev in events:
        try:
            t = replay_query.parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if prev_t is not None and speed > 0:
            gap_sec = (t - prev_t).total_seconds()
            wall_sleep = min(REPLAY_MAX_WALL_SLEEP_SEC, max(0.0, gap_sec / speed))
            if wall_sleep > 0:
                await asyncio.sleep(wall_sleep)
        envelope = replay_query.manifest_event_to_ws_envelope(ev)
        if envelope is None:
            continue
        try:
            await ws.send_json(envelope)
        except (WebSocketDisconnect, RuntimeError):
            return
        prev_t = t

    # Signal end-of-replay so the renderer can stop capturing.
    try:
        await ws.send_json(
            {
                "type": "hello",
                "ts": _now_iso(),
                "payload": {"replay": True, "done": True},
            }
        )
    except (WebSocketDisconnect, RuntimeError):
        return


@router.websocket("/ws")
async def ws_stream(ws: WebSocket) -> None:
    await ws.accept()
    await ws.send_json({"type": "hello", "ts": _now_iso(), "payload": {"subscribed": True}})

    replay_frame = await _maybe_read_replay_handshake(ws)
    if replay_frame is not None:
        try:
            await _stream_replay(ws, replay_frame)
        except WebSocketDisconnect:
            pass
        finally:
            try:
                await ws.close()
            except Exception:
                pass
        return

    await _stream_live(ws)
