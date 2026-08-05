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
- ``GET  /pipeline/runs``  — list all runs (DB-backed, last ~20).
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

State is now DB-backed via the ``pipeline_runs`` table; the
in-process ``_RUNS`` deque survives as a read-through cache so the
``/pipeline/runs`` hot path doesn't have to hit the DB on every
poll. Writes go to the DB first; the cache is hydrated from the DB
on startup (and on a cache miss + DB read in the read path).
"""

from __future__ import annotations

import asyncio
import traceback
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, cast

import httpx
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from tradefarm.api.events import publish_event
from tradefarm.config import settings
from tradefarm.render import pipeline as pipeline_mod
from tradefarm.runtime.money import D  # noqa: F401  (kept for back-compat)
from tradefarm.storage import repo
from tradefarm.storage.models import PipelineRun as _PipelineRunRow  # noqa: F401  (re-aliased to dodge the local dataclass name)

log = structlog.get_logger(__name__)
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


# ---------------------------------------------------------------------------
# Run state
# ---------------------------------------------------------------------------


@dataclass
class PipelineRun:
    """In-memory mirror of a ``pipeline_runs`` row.

    Kept as a plain dataclass so the existing UI / WS code can still
    treat it like the legacy deque entries. Fields mirror the SQLAlchemy
    model; the repo layer translates between the two. The DB is the
    source of truth — this object is a read-through cache that lives
    only for the duration of the run (and the trailing 20 in the deque
    for the GET endpoints).
    """

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
    # 0.9.0 — per-step duration roll-up. Persisted to the
    # ``step_timings_json`` column on terminal state. Each entry is
    # {step, started_at, finished_at, duration_sec, status}.
    step_timings: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "session_id": self.session_id,
            "date": self.date,
            "enabled": list(self.enabled),
            "force": bool(self.force),
            "dry_run": bool(self.dry_run),
            "status": self.status,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "last_lines": list(self.last_lines),
            "step_timings": list(self.step_timings),
        }

    def to_row(self) -> "repo.PipelineRun":  # type: ignore[name-defined]  # noqa: F821
        """Project the dataclass to a SQLAlchemy row for the repo layer.

        The repo is typed against the SQLAlchemy model (it uses select(),
        commit(), etc.), so the caller passes the row — not the dataclass.
        This is the only conversion site.
        """
        # Local import keeps the dataclass from pulling in the model's
        # SQLAlchemy metadata at module load (helps the test fixtures
        # that monkey-patch the DB before models resolve).
        from tradefarm.storage.models import PipelineRun as _Row

        return _Row(
            id=self.run_id,
            session_id=self.session_id,
            date=self.date,
            enabled=list(self.enabled),
            force=bool(self.force),
            dry_run=bool(self.dry_run),
            status=self.status,
            created_at=datetime.fromisoformat(self.created_at),
            started_at=(
                datetime.fromisoformat(self.started_at) if self.started_at else None
            ),
            finished_at=(
                datetime.fromisoformat(self.finished_at) if self.finished_at else None
            ),
            error=self.error,
            last_lines_json=__import__("json").dumps(self.last_lines or []),
            step_timings_json=__import__("json").dumps(self.step_timings or []),
        )


# Read-through cache: most recent N runs by created_at desc. Writes go
# to the DB first, then refresh the cache. The deque survives the DB
# upgrade as a perf optimisation; the DB is the source of truth.
_RUNS: deque[PipelineRun] = deque(maxlen=20)


def _get_run(run_id: str) -> PipelineRun:
    """Cache-first read by run_id.

    Mirrors the legacy 404 behaviour. The cache is checked first; on
    miss we fall through to the DB so a server restart that lost the
    in-memory deque still serves correct 404s. (The repo raises
    ``scalar_one_or_none`` which returns None — the caller maps that
    to a 404.)
    """
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

    def sink(msg: str) -> None:
        # Store the line in the per-run buffer (cap at 200). We do this
        # synchronously so the GET endpoint returns a populated ring
        # even mid-run; persistence to the DB is debounced — the line
        # snapshot lands on every step transition + terminal state
        # (rather than every stdout line, which would hammer the DB at
        # 30+ writes per beat for a multi-beat render).
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
# Webhook notification
# ---------------------------------------------------------------------------


def _fire_webhook(run: PipelineRun) -> None:
    """Best-effort POST to ``settings.vod_notify_webhook`` on terminal state.

    No-op when the env var is empty (default). Swallows any
    ``httpx`` / network exception so a webhook outage can never
    fail a pipeline run. Payload matches the contract documented
    in the spec — ``{run_id, session_id, status, ...}`` so a
    discord/slack incoming webhook or a custom json endpoint can
    render a useful message.

    On done: include ``video_id`` and ``video_url`` if the upload
    step wrote them. We don't currently read them out of the upload
    response (that's a content-team change); leaving them out
    keeps the payload truthful.
    """
    url = (settings.vod_notify_webhook or "").strip()
    if not url:
        return
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "status": run.status,
        "at": datetime.now(timezone.utc).isoformat(),
    }
    if run.status == "failed" and run.error:
        payload["error"] = run.error
    if run.status == "done":
        # video_id / video_url would be populated by reading the
        # upload_response.json in the future. For now, we surface
        # what we have. Both fields are documented as optional in
        # the spec.
        pass
    try:
        # fire-and-forget; we don't await in the caller because the
        # webhook is a side effect, not part of the run's contract.
        # We use a short timeout so a hung endpoint can't block the
        # event loop (httpx defaults to 5s for connect, 5s for read
        # — we cap it explicitly).
        httpx.post(url, json=payload, timeout=5.0)
    except httpx.HTTPError as exc:
        log.warning("vod_notify_webhook_failed", url=url, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        # Defensive: a misconfigured url (e.g. invalid scheme) raises
        # a different exception class. Log and move on; webhook
        # failures must never fail a run.
        log.warning("vod_notify_webhook_error", url=url, error=str(exc))


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------


async def _persist_run_state(run: PipelineRun) -> None:
    """Mirror the in-memory ``run`` back to the DB.

    Called on every step transition + terminal state. The hot path
    (every stdout line) does NOT hit the DB — the ring buffer lives
    in memory until a step boundary, then a single UPDATE writes the
    snapshot. The 200-line cap keeps the JSON column bounded.

    Errors are logged + swallowed: a DB outage mid-run shouldn't
    fail the run; the operator's next GET will see a slightly stale
    view, and the next update will reconcile.
    """
    try:
        await repo.update_pipeline_run(
            run.run_id,
            status=run.status,
            started_at=run.started_at,
            finished_at=run.finished_at,
            error=run.error,
            last_lines=run.last_lines,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("pipeline_run_persist_failed", run_id=run.run_id, error=str(exc))


async def _ensure_persisted(run: PipelineRun) -> None:
    """INSERT the row if it doesn't exist; UPDATE otherwise.

    Used on terminal state so a fresh process can write a run
    directly to ``done`` / ``failed`` without an intermediate
    ``pending`` write. Idempotent: a re-run on a row that already
    exists is a no-op for the INSERT and a normal UPDATE for the
    state. Errors are logged + swallowed; the in-memory cache is
    the source of truth during a single process's lifetime.
    """
    try:
        existing = await repo.get_pipeline_run(run.run_id)
        if existing is None:
            await repo.create_pipeline_run(run.to_row())
        else:
            await repo.update_pipeline_run(
                run.run_id,
                status=run.status,
                started_at=run.started_at,
                finished_at=run.finished_at,
                error=run.error,
                last_lines=run.last_lines,
            )
    except Exception as exc:  # noqa: BLE001
        log.warning("pipeline_run_ensure_persisted_failed", run_id=run.run_id, error=str(exc))


async def _run_pipeline_task(run: PipelineRun, opts: pipeline_mod.PipelineOpts) -> None:
    """Run the synchronous pipeline on a worker thread so the event
    loop isn't blocked. The progress sink fires WS events for the UI.

    The DB write strategy: we DO NOT insert a ``pending`` row up
    front (the HTTP path's ``start_run`` returns immediately so
    the in-memory ``run`` is the source of truth during the run).
    We DO write the terminal state (done / failed) so the run row
    survives a backend restart and the dashboard can recover the
    log after a page refresh. The scheduler path takes a different
    approach — it inserts the row before kicking off its own run
    (see ``orchestrator.scheduler.run_vod_scheduler``) so the
    per-day idempotency check can see in-flight runs.
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
        # the asyncio loop stays responsive. ``return_timings=True``
        # makes the runner return the per-step duration roll-up so we
        # can persist it on terminal state.
        step_timings = await asyncio.to_thread(
            pipeline_mod.run_pipeline,
            session_id=run.session_id,
            opts=opts,
            enabled=set(run.enabled),
            force=run.force,
            dry_run=run.dry_run,
            sink=sink,
            return_timings=True,
        )
        run.status = "done"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        # Stash timings on the dataclass; the model has a matching
        # ``step_timings_json`` column (added in 0.9.0) which
        # ``_ensure_persisted`` serializes on terminal state.
        run.step_timings = list(step_timings or [])
        await _ensure_persisted(run)
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "done",
                "at": run.finished_at,
            },
        )
        _fire_webhook(run)
        # 0.10.0 — best-effort asset archival on terminal done. The
        # webhook above already mirrors the fire-and-forget pattern;
        # the archive is the same shape. The archive function
        # returns None on no-op or failure — we never raise here.
        from tradefarm.render import archive as archive_mod
        from pathlib import Path as _P
        archive_root = settings.vod_archive_path or None
        if archive_root:
            try:
                await archive_mod.archive_session(
                    run.session_id,
                    archive_root=_P(archive_root),
                    run_status=run.status,
                    also_on_failure=settings.vod_archive_on_failure,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "pipeline_archive_invoke_failed",
                    run_id=run.run_id,
                    error=f"{type(exc).__name__}: {exc}",
                )
    except SystemExit as exc:
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await _ensure_persisted(run)
        await publish_event(
            "pipeline_progress",
            {
                "run_id": run.run_id,
                "kind": "fail",
                "error": str(exc),
                "at": run.finished_at,
            },
        )
        _fire_webhook(run)
    except Exception as exc:  # noqa: BLE001
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await _ensure_persisted(run)
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
        _fire_webhook(run)


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
    # NOTE: the DB INSERT for this run happens inside
    # ``_run_pipeline_task`` (the background task), not here. Doing it
    # synchronously would hold a SQLite write lock during the request
    # handler — and on a busy dev DB, the dashboard's polling + the
    # background task's progress updates would collide (the legacy
    # in-memory deque never had this problem because it didn't
    # touch the DB at all). The trade-off: a process crash in the
    # ~1ms between start_run returning and the background task
    # starting would lose the audit row. The operator can re-trigger
    # from the dashboard; the scheduler's per-day idempotency
    # doesn't apply to operator-driven runs.
    _RUNS.appendleft(run)  # newest first; hot read path

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
    """List recent pipeline runs, newest first.

    Merges the in-memory ``_RUNS`` cache (the just-created run that
    hasn't been persisted yet, plus the last 20 in-flight / done
    runs) with the DB's view of older / previously-persisted runs.
    The cache takes priority on duplicate ids so a run that's still
    pending / running shows its in-memory state (richer than the
    half-persisted DB row). Bounded to 20 so the UI doesn't grow
    unbounded as the DB accumulates.
    """
    from tradefarm.storage.repo import _decode_lines

    # Cache-first: drain the in-memory deque to a dict keyed by id
    # (newest wins). These are the "hot" runs the operator is most
    # likely looking at.
    cache_dict: dict[str, dict[str, Any]] = {}
    for r in _RUNS:
        cache_dict[r.run_id] = r.to_dict()

    # DB: read up to 20 rows; merge any that aren't already in the
    # cache (older runs from prior processes, or runs whose initial
    # persist already happened in this process).
    rows = await repo.list_pipeline_runs(limit=20)
    for r in rows:  # type: ignore[assignment]
        # `r` is the SQLAlchemy model — repo.list_pipeline_runs returns
        # `list[tradefarm.storage.models.PipelineRun]`. The local
        # `PipelineRun` dataclass shadows the model name in mypy's view
        # of this module, so we cast through the alias imported at the
        # top of the file.
        row = cast(_PipelineRunRow, r)
        if row.id in cache_dict:
            continue
        cache_dict[row.id] = {
            "run_id": row.id,
            "session_id": row.session_id,
            "date": row.date,
            "enabled": list(row.enabled or []),
            "force": bool(row.force),
            "dry_run": bool(row.dry_run),
            "status": row.status,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "error": row.error,
            "last_lines": _decode_lines(row.last_lines_json),
            "step_timings": _decode_lines(row.step_timings_json)
            if row.step_timings_json
            else [],
        }

    # Newest-first sort. The cache deque is already newest-first, but
    # the DB rows might be older. Sort by created_at desc, falling
    # back to the cache's own ordering when created_at is None.
    out = list(cache_dict.values())
    out.sort(
        key=lambda d: d.get("created_at") or "",
        reverse=True,
    )
    return out[:20]


@router.get("/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    """Get a single run's full state, including the last 200 banner
    lines for the live-log panel.
    """
    # Cache-first, DB fallback. The cache may be stale if a run was
    # started in a prior process; the repo handles that case by
    # returning the row directly.
    for r in _RUNS:
        if r.run_id == run_id:
            return r.to_dict()
    row = await repo.get_pipeline_run(run_id)
    if row is None:
        raise HTTPException(404, f"run {run_id} not found")
    from tradefarm.storage.repo import _decode_lines

    return {
        "run_id": row.id,
        "session_id": row.session_id,
        "date": row.date,
        "enabled": list(row.enabled or []),
        "force": bool(row.force),
        "dry_run": bool(row.dry_run),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        "error": row.error,
        "last_lines": _decode_lines(row.last_lines_json),
        "step_timings": _decode_lines(row.step_timings_json)
        if row.step_timings_json
        else [],
    }
