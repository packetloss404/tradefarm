"""VOD pipeline HTTP wrapper — start + poll + WS-progress for the
``tradefarm.render.pipeline`` runner.

The runner is a self-contained CLI. This router lets the VOD studio
fire-and-forget a run with a single POST and watch progress via the
existing WS event bus, without the operator having to leave the
dashboard.

Endpoints
---------

- ``POST /pipeline/run``  — start a new run. Returns a ``run_id`` the
  UI uses to poll status / filter WS events.
- ``GET  /pipeline/runs``  — list all runs (in-memory, last ~20).
- ``GET  /pipeline/runs/{run_id}``  — get a single run's status.

WS events
---------

The runner publishes ``pipeline_progress`` events on the same event
bus the rest of the app uses (``tradefarm.api.events.publish_event``).
Each event has the shape:

    {
      "run_id": "abc123",
      "kind": "start" | "step" | "stdout" | "done" | "fail",
      "line": "...",          // for stdout / step
      "step": "beats",         // for step / done / fail
      "step_index": 2,         // for step
      "step_total": 8,         // for step
      "at": "<iso8601>",
    }

``kind="step"`` fires once per pipeline step (skipped/started/done).
``kind="stdout"`` fires for each banner line (high-cadence, useful
for a live log panel). ``kind="done"`` / ``kind="fail"`` fire on
terminal state.

Runs are kept in-process only (a deque). A restart wipes the list —
that's fine for a paper-trading sandbox; production would push them
to the DB.
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tradefarm.api.events import publish_event
from tradefarm.render import pipeline as pipeline_mod
from tradefarm.runtime.money import D  # noqa: F401  (kept for back-compat)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


@dataclass
class PipelineRun:
    run_id: str
    session_id: str
    date: str | None
    enabled: list[str]
    force: bool
    dry_run: bool
    status: str = "pending"  # pending | running | done | failed
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    last_lines: list[str] = field(default_factory=list)  # ring buffer for the UI

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Last N runs, newest first. Bounded so a long-running process doesn't
# leak memory. Tradeoffs: a restart wipes the list, a busy day may
# evict the run the operator is watching — both fine for a dev sandbox.
_RUNS: deque[PipelineRun] = deque(maxlen=20)


def _get_run(run_id: str) -> PipelineRun:
    for r in _RUNS:
        if r.run_id == run_id:
            return r
    raise HTTPException(404, f"run {run_id} not found")


# ---------------------------------------------------------------------------
# Request body
# ---------------------------------------------------------------------------


class RunRequest(BaseModel):
    date: str | None = Field(
        default=None,
        description="ISO date to simulate (e.g. '2026-08-04'). Generates a session id.",
    )
    session_id: str | None = Field(
        default=None,
        description="Existing session id (resumes at the render step).",
    )
    include_tts: bool = False
    include_upload: bool = False
    skip_headless: bool = False
    force: bool = False
    dry_run: bool = False
    music: str | None = None
    tts_provider: str = "auto"
    tts_voice: str | None = None
    stitch_xfade: float = 0.4


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gen_session_id(d_str: str) -> str:
    return f"s_{d_str}_{uuid.uuid4().hex[:6]}"


def _build_opts(req: RunRequest, sessions_dir: Path) -> pipeline_mod.PipelineOpts:
    return pipeline_mod.PipelineOpts(
        sessions_dir=sessions_dir,
        music=Path(req.music) if req.music else None,
        tts_provider=req.tts_provider,
        tts_voice=req.tts_voice or "alloy",
        upload_dry_run=True,  # never actually upload from the UI; explicit opt-in only
        stitch_xfade=req.stitch_xfade,
        force=req.force,
    )


def _resolve_session_id(req: RunRequest) -> str:
    if req.date:
        return _gen_session_id(req.date)
    if req.session_id:
        return req.session_id
    raise HTTPException(400, "either `date` or `session_id` is required")


def _resolve_enabled(req: RunRequest) -> set[str]:
    enabled = {step.key for step in pipeline_mod.STEPS if step.enabled_by_default}
    if req.include_tts:
        enabled.add("tts")
    if req.include_upload:
        enabled.add("upload")
    if req.skip_headless:
        enabled.discard("headless")
    if req.session_id:
        # Resuming an existing session — the replay step makes no
        # sense, the operator already has the manifest. Mirrors the
        # CLI's auto-skip.
        enabled.discard("session")
    return enabled


# ---------------------------------------------------------------------------
# WS event fan-out for a single run
# ---------------------------------------------------------------------------


def _make_sink(run_id: str, run: PipelineRun) -> "Callable[[str], None]":
    """Build a progress sink for ``run_pipeline`` that publishes to the
    WS event bus AND appends to the run's last_lines ring buffer (so
    the operator polling ``GET /pipeline/runs/{id}`` sees a tail of
    the output without subscribing to WS).
    """

    async def _publish(payload: dict[str, Any]) -> None:
        # publish_event is async; our sink is sync, so we schedule the
        # publish on the running event loop. If no loop is running
        # (shouldn't happen — the runner is called from a background
        # task), we fall back to a synchronous no-op.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(publish_event("pipeline_progress", payload))
        except RuntimeError:
            pass

    def sink(msg: str) -> None:
        # Store the line in the per-run buffer (cap at 200).
        run.last_lines.append(msg)
        if len(run.last_lines) > 200:
            run.last_lines = run.last_lines[-200:]
        # Best-effort WS publish.
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                publish_event(
                    "pipeline_progress",
                    {
                        "run_id": run_id,
                        "kind": "stdout",
                        "line": msg,
                        "at": datetime.now(timezone.utc).isoformat(),
                    },
                )
            )
        except RuntimeError:
            pass

    return sink


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


async def _run_pipeline_task(run: PipelineRun, opts: pipeline_mod.PipelineOpts) -> None:
    """Run the synchronous pipeline on a worker thread so the event
    loop isn't blocked. The progress sink fires WS events for the UI.
    """
    run.status = "running"
    run.started_at = datetime.now(timezone.utc).isoformat()
    await publish_event(
        "pipeline_progress",
        {
            "run_id": run.run_id,
            "kind": "start",
            "session_id": run.session_id,
            "enabled": run.enabled,
            "at": run.started_at,
        },
    )
    sink = _make_sink(run.run_id, run)
    try:
        # pipeline.run_pipeline is synchronous and can take a long
        # time (rendering clips can be minutes). Run it on a thread so
        # the asyncio loop stays responsive.
        await asyncio.to_thread(
            pipeline_mod.run_pipeline,
            session_id=run.session_id,
            opts=opts,
            enabled=set(run.enabled),
            force=run.force,
            dry_run=run.dry_run,
            sink=sink,
        )
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "done",
                "at": run.finished_at,
            },
        )
    except SystemExit as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "fail",
                "error": str(exc),
                "at": run.finished_at,
            },
        )
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "fail",
                "error": run.error,
                "trace": traceback.format_exc()[-2000:],
                "at": run.finished_at,
            },
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/run")
async def start_run(req: RunRequest) -> dict[str, Any]:
    """Kick off a VOD pipeline run. Returns immediately with a
    ``run_id`` the UI uses to poll status and filter WS events.
    """
    sessions_dir = Path("out/sessions")
    session_id = _resolve_session_id(req)
    enabled = _resolve_enabled(req)
    opts = _build_opts(req, sessions_dir)

    run = PipelineRun(
        run_id=uuid.uuid4().hex[:12],
        session_id=session_id,
        date=req.date,
        enabled=sorted(enabled),
        force=req.force,
        dry_run=req.dry_run,
    )
    _RUNS.appendleft(run)  # newest first

    # Fire-and-forget: schedule the background task. The task uses
    # publish_event which already runs in the same loop, so the WS
    # delivery is in-band with the test client's connection.
    asyncio.create_task(_run_pipeline_task(run, opts))

    return {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status,
        "enabled": run.enabled,
    }


@router.get("/runs")
async def list_runs() -> list[dict[str, Any]]:
    """List recent pipeline runs, newest first."""
    return [r.to_dict() for r in _RUNS]


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get a single run's full state, including the last 200 banner
    lines for the live-log panel.
    """
    return _get_run(run_id).to_dict()
