"""Stream-control router — dashboard-driven commands for the broadcast app.

The dashboard's BroadcastPanel and the stream-side useStreamCommands hook
both POST to ``/stream/cmd``. Each request is forwarded to the in-process
EventBus via ``publish_event`` so any /ws subscriber (the broadcast app's
useLiveEvents listener) receives it.

Why route control commands through the same bus rather than a separate
channel: the stream app already maintains a single WS subscription for live
data, so re-using it keeps the broadcast wire to one socket per viewer.
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tradefarm.api.events import publish_event

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/stream", tags=["stream"])

ALLOWED_TYPES: frozenset[str] = frozenset({
    "stream_scene",
    "stream_banner",
    "stream_audio",
    "stream_preroll",
    "stream_rotation",
    "stream_layout",
    "stream_crt",
    "stream_cadence",
    "stream_fullscreen",
    "stream_state",
})


class StreamCmd(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/cmd")
async def stream_cmd(cmd: StreamCmd) -> dict[str, bool]:
    if cmd.type not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail=f"unknown stream cmd type: {cmd.type}")
    await publish_event(cmd.type, cmd.payload)
    log.info("stream_cmd", type=cmd.type, keys=sorted(cmd.payload.keys()))
    return {"ok": True}
