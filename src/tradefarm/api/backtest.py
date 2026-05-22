"""Backtest launcher API.

POST /backtest/run     → kicks off a job (sync reply with job_id)
GET  /backtest/{id}    → progress + accumulated results

Jobs live in memory only; a restart clears them. Fine for a local tool.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tradefarm.agents.backtest import _backtest_async
from tradefarm.data.universe import default_universe

router = APIRouter(prefix="/backtest", tags=["backtest"])

# job_id → state
_JOBS: dict[str, dict[str, Any]] = {}

# Audit fix (H27): unbounded concurrent jobs were a DoS. Cap total
# inflight + cap per-request symbol count + evict completed jobs older
# than _JOB_TTL_SEC so _JOBS doesn't grow forever.
_MAX_INFLIGHT_JOBS = 4
_MAX_SYMBOLS_PER_REQUEST = 500
_JOB_TTL_SEC = 3600  # 1 hour


def _evict_stale_jobs() -> None:
    """Drop completed jobs whose finished_at is older than TTL."""
    now = datetime.now(timezone.utc)
    stale = []
    for jid, job in _JOBS.items():
        finished = job.get("finished_at")
        if not finished:
            continue
        try:
            ts = datetime.fromisoformat(finished)
        except (TypeError, ValueError):
            continue
        if (now - ts).total_seconds() > _JOB_TTL_SEC:
            stale.append(jid)
    for jid in stale:
        _JOBS.pop(jid, None)


def _inflight_count() -> int:
    return sum(1 for j in _JOBS.values() if j.get("status") == "running")


class RunRequest(BaseModel):
    # Empty / omitted → run the default universe.
    symbols: list[str] | None = Field(
        default=None,
        max_length=_MAX_SYMBOLS_PER_REQUEST,
        description=f"Max {_MAX_SYMBOLS_PER_REQUEST} symbols per request.",
    )


@router.post("/run")
async def run(req: RunRequest) -> dict[str, Any]:
    _evict_stale_jobs()
    if _inflight_count() >= _MAX_INFLIGHT_JOBS:
        raise HTTPException(
            429,
            f"too many inflight backtests (cap {_MAX_INFLIGHT_JOBS}); "
            "wait for one to finish",
        )
    symbols = [s.strip().upper() for s in (req.symbols or default_universe()) if s.strip()]
    if not symbols:
        raise HTTPException(400, "no symbols to backtest")
    if len(symbols) > _MAX_SYMBOLS_PER_REQUEST:
        raise HTTPException(
            400, f"too many symbols: {len(symbols)} > {_MAX_SYMBOLS_PER_REQUEST}",
        )
    job_id = uuid4().hex[:12]
    _JOBS[job_id] = {
        "job_id": job_id,
        "status": "running",
        "total": len(symbols),
        "done": 0,
        "symbols": symbols,
        "current": None,
        "results": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": None,
    }
    asyncio.create_task(_run_job(job_id, symbols))
    return {"job_id": job_id, "total": len(symbols), "status": "running"}


async def _run_job(job_id: str, symbols: list[str]) -> None:
    job = _JOBS[job_id]
    for s in symbols:
        job["current"] = s
        try:
            result = await _backtest_async(s)
        except Exception as e:
            result = {"symbol": s, "error": str(e)}
        job["results"].append(result)
        job["done"] += 1
    job["status"] = "done"
    job["current"] = None
    job["finished_at"] = datetime.now(timezone.utc).isoformat()


@router.get("/{job_id}")
async def status(job_id: str) -> dict[str, Any]:
    job = _JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "job_id unknown (maybe evicted on restart)")
    return job


@router.get("")
async def list_jobs() -> list[dict[str, Any]]:
    """Recent jobs, newest first — useful for reopening the modal after navigating away."""
    out = sorted(
        _JOBS.values(),
        key=lambda j: j["started_at"],
        reverse=True,
    )
    # Trim per-job payload for the list view.
    return [
        {
            "job_id": j["job_id"],
            "status": j["status"],
            "total": j["total"],
            "done": j["done"],
            "started_at": j["started_at"],
            "finished_at": j["finished_at"],
        }
        for j in out[:20]
    ]


@router.delete("/{job_id}")
async def cancel(job_id: str) -> dict[str, str]:
    """Forget the job. Running work is not interrupted (no clean cancel path into
    the LSTM loop), but the job is removed so status endpoints 404."""
    _JOBS.pop(job_id, None)
    return {"status": "deleted"}
