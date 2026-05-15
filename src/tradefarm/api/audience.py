"""Audience-interactivity HTTP endpoints.

Dashboard-driven operations on top of :class:`AudienceCoordinator` and
:class:`PredictionsBoard`. The orchestrator is reached via
``request.app.state.orchestrator`` — same pattern as :mod:`stream_control`
and :mod:`admin`.

Endpoints:
- ``GET  /audience/pin-requests``               — list pending pin requests
- ``POST /audience/pin-requests/{id}/approve``  — operator approves a pin
- ``POST /audience/pin-requests/{id}/reject``   — operator rejects a pin
- ``GET  /audience/predictions``                — current state of both predictions
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/audience", tags=["audience"])


def _audience(request: Request):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="orchestrator not ready")
    aud = getattr(orch, "_audience", None)
    if aud is None:
        raise HTTPException(status_code=503, detail="audience coordinator not running")
    return aud


def _predictions(request: Request):
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        raise HTTPException(status_code=503, detail="orchestrator not ready")
    board = getattr(orch, "_predictions", None)
    if board is None:
        raise HTTPException(status_code=503, detail="predictions board not running")
    return board


@router.get("/pin-requests")
async def pin_requests(request: Request) -> list[dict[str, Any]]:
    """Return pending pin requests, newest first."""
    aud = _audience(request)
    return aud.pending_requests()


class _ApproveBody(BaseModel):
    # Optional manual resolution: dashboard sends this when the original
    # agent_query couldn't be auto-resolved and the operator picked an agent
    # in the inline picker.
    agent_id: int | None = None


@router.post("/pin-requests/{request_id}/approve")
async def approve_pin_request(
    request_id: str,
    request: Request,
    body: _ApproveBody | None = None,
) -> dict[str, bool]:
    aud = _audience(request)
    override = body.agent_id if body else None
    ok = await aud.approve_pin_request(request_id, agent_id_override=override)
    if not ok:
        raise HTTPException(status_code=404, detail="pin request not found")
    return {"ok": True}


@router.post("/pin-requests/{request_id}/reject")
async def reject_pin_request(request_id: str, request: Request) -> dict[str, bool]:
    aud = _audience(request)
    ok = await aud.reject_pin_request(request_id)
    if not ok:
        raise HTTPException(status_code=404, detail="pin request not found")
    return {"ok": True}


@router.get("/predictions")
async def predictions(request: Request) -> list[dict[str, Any]]:
    """Return the current state of both predictions."""
    board = _predictions(request)
    return board.snapshot()
