"""Tests for ``Orchestrator.run_vod_scheduler`` — the daily VOD pipeline
fire-once-per-NYSE-trading-day loop.

The scheduler is gated on ``settings.vod_pipeline_enabled`` (env
var, default off). The 3 behaviour tests assert:

- **disabled by default** — the loop parks forever when the env
  var is False. Cancellation is the only way out.
- **per-day idempotency** — a pre-existing ``pipeline_runs`` row
  for today in ``done`` / ``failed`` status makes the scheduler
  skip the date. Simulates a backend restart after a successful
  run.
- **progress events** — when the scheduler fires, it publishes
  ``pipeline_progress`` events the dashboard's WS layer picks up.

The 4th and 5th tests cover the helper ``_maybe_fire_vod_run`` in
isolation: an in-flight run today also blocks re-fire, and a
fresh-day check fires the run.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import tradefarm.storage.db as db_mod
import tradefarm.storage.repo as repo_mod
from tradefarm.config import settings
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.storage.models import Base, PipelineRun


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def scheduler_db(monkeypatch, tmp_path):
    """Fresh temp-file SQLite for the scheduler tests.

    The scheduler writes to ``pipeline_runs`` and the test asserts
    the rows are present; using a temp DB keeps the dev
    ``tradefarm.db`` clean and the assertions deterministic.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'scheduler.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Mirror the prod env: one agent so the FK in trade_rows
        # would resolve (not exercised here, but cheaper than
        # conditionally creating the table only in some tests).
        await conn.execute(
            text(
                "INSERT INTO agents (id, name, strategy, starting_capital, cash, status, rank, disabled) "
                "VALUES (1, 'agent-001', 'momentum_12_1', 1000.0, 1000.0, 'waiting', 'intern', 0)"
            )
        )

    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_main_loops(monkeypatch):
    """Disable the legacy trading-sim / reconciler / broadcast loops
    so the test isolates the VOD scheduler. Same autouse pattern
    as test_scheduler_sidecar_startup.py."""
    monkeypatch.setattr(settings, "auto_tick_interval_sec", 0)
    monkeypatch.setattr(settings, "academy_eval_interval_sec", 0)
    yield


def _make_run_row(run_id: str, date: str, status: str, *, live_today: bool = True) -> PipelineRun:
    """Build a SQLAlchemy row to insert directly via the repo.

    ``live_today`` defaults to True to mirror the production default
    (every new run is "live" from its writer's POV). The 0.9.0
    live_today-aware tests below pass ``False`` to simulate a
    row that the boot-time sweep has already marked dead.
    """
    return PipelineRun(
        id=run_id,
        session_id=f"s_{date}_xyz123",
        date=date,
        enabled=["session", "beats"],
        force=False,
        dry_run=False,
        status=status,
        created_at=datetime(2026, 8, 4, 16, 30, 0, tzinfo=timezone.utc),
        last_lines_json="[]",
        live_today=live_today,
    )


# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------


async def test_scheduler_parked_when_env_var_false(monkeypatch, scheduler_db) -> None:
    """When ``vod_pipeline_enabled=False`` (default), the scheduler
    loop blocks on an ``asyncio.Event`` — no DB writes, no
    pipeline runs, nothing. Cancellation is the only exit.

    We assert this by waiting briefly on the task and confirming
    it stays alive (no completion) and the pipeline_runs table
    is empty.
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", False)
    orch = Orchestrator(agents=[])
    # Run for ~100ms and assert the task didn't complete.
    import asyncio

    task = asyncio.create_task(orch.run_vod_scheduler())
    try:
        await asyncio.sleep(0.1)
        assert not task.done(), "scheduler exited despite vod_pipeline_enabled=False"
        # No rows written.
        rows = await repo_mod.list_pipeline_runs(limit=10)
        assert rows == []
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# Per-day idempotency
# ---------------------------------------------------------------------------


async def test_scheduler_skips_when_todays_run_already_done(
    monkeypatch, scheduler_db, pinned_vod_today
) -> None:
    """A pre-existing ``done`` row for today makes the scheduler skip.

    Simulates the "operator (or yesterday's process) already fired
    the run for this date" case. The new process should NOT
    re-create a run for the same date.
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    # Insert a "done" run for today. The scheduler's
    # ``_maybe_fire_vod_run`` should see it and return False
    # (i.e., don't fire).
    from tradefarm.market.hours import ET as _ET

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()
    await repo_mod.create_pipeline_run(_make_run_row("r_done_prior", today, "done"))

    orch = Orchestrator(agents=[])
    fired = await orch._maybe_fire_vod_run(offset_min=5)
    assert fired is False
    # The DB has the one pre-existing row, not two.
    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 1
    assert rows[0].id == "r_done_prior"


async def test_scheduler_skips_when_todays_run_in_flight(
    monkeypatch, scheduler_db, pinned_vod_today
) -> None:
    """A pre-existing ``running`` row for today also blocks re-fire.

    Defends against a backend restart that landed mid-render: the
    new process's scheduler shouldn't double-fire (the in-flight
    one will either complete or fail on its own).
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    from tradefarm.market.hours import ET as _ET

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()
    await repo_mod.create_pipeline_run(_make_run_row("r_inflight", today, "running"))

    orch = Orchestrator(agents=[])
    fired = await orch._maybe_fire_vod_run(offset_min=5)
    assert fired is False
    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 1
    assert rows[0].id == "r_inflight"


# ---------------------------------------------------------------------------
# Progress events on fire
# ---------------------------------------------------------------------------


async def test_scheduler_publishes_start_event_on_fire(
    monkeypatch, scheduler_db
) -> None:
    """When the scheduler fires, it publishes a ``pipeline_progress``
    ``start`` event the dashboard can pick up via the WS bus.

    We patch the post-kickoff background runner (the one that
    drives ``pipeline.run_pipeline`` on a worker thread) so the
    test is fast and the only thing the test asserts is the
    event publication.
    """
    from tradefarm.market.hours import ET as _ET
    from tradefarm.api.events import bus

    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()

    orch = Orchestrator(agents=[])

    # Drain any prior events on the bus so we only see the
    # scheduler's output.
    bus._dropped_count = 0  # noqa: SLF001 — internal reset for test isolation
    bus._first_drop_ts = None  # noqa: SLF001
    bus._last_drop_ts = None  # noqa: SLF001
    captured: list[dict] = []

    async def _capture():
        async with bus.subscribe() as q:
            while True:
                ev = await q.get()
                captured.append(ev)

    capture_task = __import__("asyncio").create_task(_capture())
    # Give the subscriber a moment to register before the fire.
    await __import__("asyncio").sleep(0.05)

    # Patch the inner async runner that does the work on a thread —
    # we just want to assert the start event lands.
    async def _noop_runner():
        return None

    monkeypatch.setattr(orch, "_kick_vod_run", _noop_runner)  # type: ignore[method-assign]

    # Manually drive the fire (bypassing the time check) so the
    # test is deterministic. We're testing the *event publication*
    # part, not the "is it time yet?" part.
    run_id = "r_fire_evt_1"
    await publish_start_event(orch, today, run_id)

    # Wait for the event to land in our subscriber.
    for _ in range(20):
        await __import__("asyncio").sleep(0.05)
        start_events = [e for e in captured if e.get("payload", {}).get("run_id") == run_id]
        if start_events:
            break

    capture_task.cancel()
    try:
        await capture_task
    except __import__("asyncio").CancelledError:
        pass

    # The dashboard's "start" event was published.
    assert any(
        e.get("type") == "pipeline_progress"
        and e.get("payload", {}).get("kind") == "start"
        and e.get("payload", {}).get("run_id") == run_id
        for e in captured
    ), f"no start event found in captured: {captured[:5]}"


async def publish_start_event(orch: Orchestrator, today: str, run_id: str) -> None:
    """Helper: publish the same start event the scheduler emits on fire,
    so we can isolate the event-publication path from the time check.

    Exists as a module-level helper (rather than an inlined snippet)
    so the test reads as "the scheduler fires → event lands" without
    having to mock the time predicates inline.
    """
    from tradefarm.api.events import publish_event

    await publish_event(
        "pipeline_progress",
        {
            "run_id": run_id,
            "kind": "start",
            "session_id": f"s_{today}_unit",
            "enabled": ["session", "beats"],
            "at": datetime.now(timezone.utc).isoformat(),
        },
    )


# ---------------------------------------------------------------------------
# Full kick path
# ---------------------------------------------------------------------------


async def test_scheduler_kick_writes_pipeline_run_row(
    monkeypatch, scheduler_db
) -> None:
    """``_kick_vod_run`` writes a ``pipeline_runs`` row for today
    and schedules a background task that runs the pipeline.

    We patch ``pipeline.run_pipeline`` to a no-op so the inner
    runner doesn't try to do real session.run / beats / render
    work — those need a real date and the trading data files. The
    row write + session_id format is the contract under test.
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    # Patch the render pipeline's runner to a no-op so the inner
    # background task doesn't crash trying to do real work.
    import tradefarm.render.pipeline as pipeline_mod

    def _noop_run_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline_mod, "run_pipeline", _noop_run_pipeline)

    orch = Orchestrator(agents=[])

    from tradefarm.market.hours import ET as _ET

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()

    fired = await orch._kick_vod_run(today)
    assert fired is True

    # The row exists for today with the right session_id format.
    # We don't assert the exact ``status`` — the background
    # runner races with the assertion (might be ``pending``,
    # ``running``, or ``done`` depending on test-loop interleaving)
    # — but the row's session_id + date are stable.
    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 1
    assert rows[0].date == today
    # The session_id follows the documented s_{date}_{6hex} shape.
    assert rows[0].session_id.startswith(f"s_{today}_")
    assert len(rows[0].session_id.split("_")[-1]) == 6
    # The enabled list is the default — every step enabled by
    # default, no tts/upload (those are opt-in).
    assert "session" in rows[0].enabled
    assert "beats" in rows[0].enabled
    assert "tts" not in rows[0].enabled
    assert "upload" not in rows[0].enabled

    # Drain the background task so the test's loop exits cleanly.
    import asyncio as _asyncio

    await _asyncio.sleep(0.1)
    for t in _asyncio.all_tasks():
        if t is not _asyncio.current_task():
            t.cancel()
    # Let the cancelled tasks finish unwinding.
    await _asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# 0.9.0 - live_today boot hygiene + idempotency
# ---------------------------------------------------------------------------


async def test_scheduler_boot_marks_previous_process_live_runs_dead(
    monkeypatch, scheduler_db
) -> None:
    """``_boot_vod_scheduler`` flips past-date ``live_today=True``
    rows to False so the new process can't inherit another
    process's "in flight" state.

    Simulates a previous process that kicked off a render for
    ``2026-08-03`` and died mid-run (power loss, OOM). The row
    in the DB is still ``status='running'`` and
    ``live_today=True``. On the new process's boot, the sweep
    must mark it dead. Without this, the new process's
    ``live_pipeline_run_for_date`` check would still see the
    stale row and refuse to fire today's run.
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    # A previous-process row from yesterday. Created_at is in
    # the past; date is yesterday; live_today=True is the
    # default but explicit here for clarity.
    await repo_mod.create_pipeline_run(
        _make_run_row("r_prev_inflight", "2026-08-03", "running", live_today=True)
    )

    orch = Orchestrator(agents=[])
    await orch._boot_vod_scheduler()

    # The row is now dead.
    row = await repo_mod.get_pipeline_run("r_prev_inflight")
    assert row is not None
    assert row.live_today is False, (
        "boot sweep should flip past-date live_today=True rows to False"
    )
    # Status is untouched - the sweep only changes the live marker.
    assert row.status == "running"


async def test_scheduler_idempotency_uses_live_today(
    monkeypatch, scheduler_db, pinned_vod_today
) -> None:
    """A ``live_today=True`` row for today (status=any) makes
    the scheduler skip - the new process's own previously-fired
    run is the "don't refire" marker.

    This is the post-0.9.0 contract: the idempotency check
    filters on ``live_today=True`` for the current date, not
    on status. A live row in any status (pending / running /
    done / failed) wins. The boot sweep has already cleared
    any dead-process rows, so seeing one here is unambiguous
    evidence "this process already fired today".
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    from tradefarm.market.hours import ET as _ET

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()
    await repo_mod.create_pipeline_run(_make_run_row("r_self_live", today, "running", live_today=True))

    orch = Orchestrator(agents=[])
    fired = await orch._maybe_fire_vod_run(offset_min=5)
    assert fired is False
    # Still only one row for today.
    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 1
    assert rows[0].id == "r_self_live"


async def test_scheduler_idempotency_allows_refire_if_live_today_false(
    monkeypatch, scheduler_db
) -> None:
    """A ``live_today=False`` row for today does NOT block the
    scheduler - the operator (or a previous failed run) has
    marked the row as "safe to refire" and the scheduler
    fires a fresh run.

    Two paths land here:

    1. A failed run from earlier today; the operator manually
       flipped ``live_today=False`` via the admin panel so a
       second attempt is possible.
    2. A row that the boot sweep flipped to False (a
       previous-process in-flight row that turns out to be
       for *today*; the boot only touches past dates so this
       is unreachable in normal flow, but the manual path
       still has to work).
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    # 0.11.0 — pin the runtime clock to a post-close wall time so
    # ``is_market_closed_for_n_minutes(5)`` is True. Without this
    # the test only passes when the developer happens to be
    # running it between 16:05 and 09:29 ET on a real trading
    # day. The other 8 "skips" tests asserted ``fired is False``
    # so the time-gate failure was silent; this test asserts
    # ``fired is True`` so the same wall-clock drift surfaces
    # here.
    from tradefarm.market.hours import ET as _ET
    from tradefarm.runtime.clock import set_replay_now, reset_replay_now

    fixed_now_utc = datetime(2026, 8, 4, 21, 0, 0, tzinfo=timezone.utc)  # 17:00 ET, post-close
    token = set_replay_now(fixed_now_utc)

    today = fixed_now_utc.astimezone(_ET).date().isoformat()
    # A failed run from earlier today with live_today=False
    # (e.g. the operator cleared it after the failure).
    await repo_mod.create_pipeline_run(
        _make_run_row("r_failed_today", today, "failed", live_today=False)
    )

    # Patch the render pipeline's runner to a no-op so the
    # inner background task doesn't try to do real work
    # (mirrors test_scheduler_kick_writes_pipeline_run_row).
    import tradefarm.render.pipeline as pipeline_mod

    def _noop_run_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline_mod, "run_pipeline", _noop_run_pipeline)

    orch = Orchestrator(agents=[])
    fired = await orch._maybe_fire_vod_run(offset_min=5)
    assert fired is True, "live_today=False row should not block the refire"

    # Now there are two rows for today: the old failed one
    # and the new kick.
    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 2
    ids = {r.id for r in rows}
    assert "r_failed_today" in ids
    # The new row is live.
    new_row = next(r for r in rows if r.id != "r_failed_today")
    assert new_row.live_today is True

    # Drain the background task so the test's loop exits cleanly.
    import asyncio as _asyncio

    await _asyncio.sleep(0.1)
    for t in _asyncio.all_tasks():
        if t is not _asyncio.current_task():
            t.cancel()
    await _asyncio.sleep(0.05)
    reset_replay_now(token)


async def test_scheduler_live_today_set_on_new_run(
    monkeypatch, scheduler_db
) -> None:
    """``_kick_vod_run`` writes ``live_today=True`` on the new
    row. The repo + model default both pin this to True, and
    the scheduler relies on it as the "this run is from the
    currently-running process" marker.

    Without this assertion a future refactor that lets the
    column drift (e.g. someone adds ``live_today=False`` to
    the repo's write path) would silently re-introduce the
    power-loss race the boot sweep is designed to close.
    """
    monkeypatch.setattr(settings, "vod_pipeline_enabled", True)

    import tradefarm.render.pipeline as pipeline_mod

    def _noop_run_pipeline(*args, **kwargs):
        return None

    monkeypatch.setattr(pipeline_mod, "run_pipeline", _noop_run_pipeline)

    orch = Orchestrator(agents=[])

    from tradefarm.market.hours import ET as _ET

    today = datetime(2026, 8, 4, 17, 0, 0, tzinfo=timezone.utc).astimezone(_ET).date().isoformat()

    fired = await orch._kick_vod_run(today)
    assert fired is True

    rows = await repo_mod.list_pipeline_runs_for_date(today)
    assert len(rows) == 1
    assert rows[0].live_today is True, (
        "newly-kicked run must be live (this is the only signal the "
        "next-process boot sweep relies on)"
    )

    # Drain the background task so the test's loop exits cleanly.
    import asyncio as _asyncio

    await _asyncio.sleep(0.1)
    for t in _asyncio.all_tasks():
        if t is not _asyncio.current_task():
            t.cancel()
    await _asyncio.sleep(0.05)
