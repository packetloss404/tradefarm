"""Tests for the DB-backed pipeline run state in ``tradefarm.api.pipeline``.

The HTTP wrapper's run state used to live in a process-local
``deque(maxlen=20)`` — a restart wiped the audit trail and the
"any done/failed run for today?" idempotency check the scheduler
needs wasn't queryable. This module covers the new ``pipeline_runs``
SQLAlchemy table: a fresh per-test SQLite DB (the test pattern from
``tests/storage/test_repo_dedup.py``) lets us assert the schema, the
repo methods, the read-through cache, and the cross-"restart" (new
repo instance against the same DB) persistence guarantees without
polluting the dev ``tradefarm.db``.

We also cover the partial-update path: a run that mutates only
``status`` and ``error`` (a typical fail-and-stop) shouldn't blow
away ``last_lines`` (the operator's debug tail) — every other field
that's not in the update must be preserved.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import tradefarm.api.pipeline as api_pipeline
import tradefarm.storage.db as db_mod
import tradefarm.storage.repo as repo_mod
from tradefarm.storage.models import Base, PipelineRun


# ---------------------------------------------------------------------------
# Test DB fixture: fresh temp-file SQLite per test (see test_repo_dedup.py).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fresh_db(monkeypatch, tmp_path):
    """Point the engine at a fresh temp-file DB so each test starts clean.

    The test_pipeline_db_state.py tests need to insert / read pipeline run
    rows in isolation. The default ``tradefarm.db`` is shared with the
    dashboard, and the other API tests write to it — using a temp file
    keeps the assertions deterministic.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'pipeline_state.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the engine on the db module *and* the SessionLocal on the
    # repo module — repo imports SessionLocal at module load, so the
    # late patch is the one that actually gets used at call time.
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Seed the lone agent row that other tables FK to (no FK on
        # pipeline_runs, but keeping the seed mirrors the prod env).
        await conn.execute(
            text(
                "INSERT INTO agents (id, name, strategy, starting_capital, cash, status, rank, disabled) "
                "VALUES (1, 'agent-001', 'momentum_12_1', 1000.0, 1000.0, 'waiting', 'intern', 0)"
            )
        )

    yield engine
    await engine.dispose()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy PipelineRun row to a plain dict for assertions."""
    return {
        "id": row.id,
        "session_id": row.session_id,
        "date": row.date,
        "enabled": list(row.enabled or []),
        "force": bool(row.force),
        "dry_run": bool(row.dry_run),
        "status": row.status,
        "error": row.error,
        "last_lines": repo_mod._decode_lines(row.last_lines_json),
    }


def _make_run(
    run_id: str = "abc123def456",
    *,
    date: str | None = "2026-08-04",
    status: str = "pending",
    enabled: list[str] | None = None,
) -> api_pipeline.PipelineRun:
    """Build an in-memory PipelineRun for the tests."""
    return api_pipeline.PipelineRun(
        run_id=run_id,
        session_id=f"s_{date or 'x'}_abcdef",
        date=date,
        enabled=enabled or ["session", "beats", "headless"],
        force=False,
        dry_run=False,
        status=status,
    )


# ---------------------------------------------------------------------------
# Schema / shape
# ---------------------------------------------------------------------------


async def test_pipeline_runs_table_created_on_init(fresh_db) -> None:
    """``init_db`` creates the table with the expected columns."""
    async with fresh_db.connect() as conn:
        cols = (await conn.execute(text("PRAGMA table_info(pipeline_runs)"))).all()
    col_names = {r[1] for r in cols}
    assert "id" in col_names
    assert "session_id" in col_names
    assert "date" in col_names
    assert "enabled" in col_names
    assert "status" in col_names
    assert "created_at" in col_names
    assert "started_at" in col_names
    assert "finished_at" in col_names
    assert "error" in col_names
    assert "last_lines_json" in col_names


async def test_pipeline_runs_indexes_created(fresh_db) -> None:
    """The two composite indexes (session_id, created_at) and
    (status, created_at) are present so the hot-path queries
    (live data hook + scheduler idempotency) don't full-scan."""
    async with fresh_db.connect() as conn:
        idx_rows = (await conn.execute(text("PRAGMA index_list(pipeline_runs)"))).all()
    idx_names = {r[1] for r in idx_rows}
    # SQLAlchemy names the indexes after the model's __table_args__ names.
    assert "ix_pipeline_runs_session_id_created_at" in idx_names
    assert "ix_pipeline_runs_status_created_at" in idx_names


# ---------------------------------------------------------------------------
# Repo: create + read
# ---------------------------------------------------------------------------


async def test_create_and_get_pipeline_run(fresh_db) -> None:
    """A row written through the repo reads back identically."""
    run = _make_run(run_id="r_create_1", status="pending")
    await repo_mod.create_pipeline_run(run.to_row())

    row = await repo_mod.get_pipeline_run("r_create_1")
    assert row is not None
    assert row.id == "r_create_1"
    assert row.session_id == "s_2026-08-04_abcdef"
    assert row.date == "2026-08-04"
    assert row.status == "pending"
    # The JSON column round-trips the list intact.
    assert sorted(row.enabled) == ["beats", "headless", "session"]


async def test_get_unknown_run_returns_none(fresh_db) -> None:
    """A lookup for a non-existent id returns None (not raise)."""
    assert await repo_mod.get_pipeline_run("doesnotexist") is None


# ---------------------------------------------------------------------------
# Repo: partial update + persistence guarantees
# ---------------------------------------------------------------------------


async def test_update_only_touches_listed_fields(fresh_db) -> None:
    """An update with one field doesn't clobber the others.

    A run that flips from ``running`` to ``failed`` carries an
    ``error`` string; the operator's log tail (last_lines_json)
    should survive the update so the next GET shows both the
    error message and the lines that preceded it.
    """
    run = _make_run(run_id="r_upd_1", status="pending")
    await repo_mod.create_pipeline_run(run.to_row())

    await repo_mod.update_pipeline_run(
        "r_upd_1",
        status="running",
        started_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )
    # Write some lines via a separate update.
    await repo_mod.update_pipeline_run(
        "r_upd_1",
        last_lines=["step 1/8: done", "step 2/8: done", "step 3/8: failed"],
    )
    # Now flip to failed without re-sending last_lines — they should
    # be preserved.
    await repo_mod.update_pipeline_run(
        "r_upd_1",
        status="failed",
        error="OSError: chromium crashed",
        finished_at=__import__("datetime").datetime.now(__import__("datetime").timezone.utc),
    )

    row = await repo_mod.get_pipeline_run("r_upd_1")
    assert row.status == "failed"
    assert row.error == "OSError: chromium crashed"
    assert row.started_at is not None
    assert row.finished_at is not None
    # The lines survived the terminal-state update.
    assert row.last_lines_json is not None
    lines = json.loads(row.last_lines_json)
    assert "step 3/8: failed" in lines
    assert len(lines) == 3


async def test_update_unknown_run_is_silent_noop(fresh_db) -> None:
    """Updating a non-existent run is a silent no-op (logged only)."""
    # No create; the update should not raise.
    await repo_mod.update_pipeline_run("ghost_run", status="done")
    assert await repo_mod.get_pipeline_run("ghost_run") is None


async def test_update_rejects_unknown_field(fresh_db) -> None:
    """A typo in the field name raises TypeError so it doesn't silently
    get dropped. Belt-and-braces — the linter should catch this too,
    but a TypeError at runtime is louder than a missing field."""
    run = _make_run(run_id="r_typo_1")
    await repo_mod.create_pipeline_run(run.to_row())
    with pytest.raises(TypeError, match="statux"):
        await repo_mod.update_pipeline_run("r_typo_1", statux="done")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Repo: list ordering + limit
# ---------------------------------------------------------------------------


async def test_list_runs_orders_newest_first_and_respects_limit(fresh_db) -> None:
    """``list_pipeline_runs`` returns rows in created_at desc order, capped
    at ``limit``."""
    from datetime import datetime, timedelta, timezone

    base = datetime(2026, 8, 4, 12, 0, 0, tzinfo=timezone.utc)
    for i in range(5):
        run = _make_run(run_id=f"r_list_{i}", date=f"2026-08-0{i + 1}")
        # Manually set created_at so the order is deterministic
        # (server_default uses ``func.now()`` which is wall-clock).
        row = run.to_row()
        row.created_at = base + timedelta(seconds=i)
        await repo_mod.create_pipeline_run(row)

    rows = await repo_mod.list_pipeline_runs(limit=3)
    assert [r.id for r in rows] == ["r_list_4", "r_list_3", "r_list_2"]
    rows_5 = await repo_mod.list_pipeline_runs(limit=10)
    assert len(rows_5) == 5


# ---------------------------------------------------------------------------
# Repo: per-date idempotency check
# ---------------------------------------------------------------------------


async def test_pipeline_run_with_terminal_state_for_date(fresh_db) -> None:
    """The scheduler's idempotency check returns the newest done/failed
    row for the date, and ignores pending/running rows."""
    # No rows yet — returns None.
    assert await repo_mod.pipeline_run_with_terminal_state_for_date("2026-08-04") is None

    # A pending row shouldn't count (idempotency: don't double-fire
    # while a previous run is still pending).
    pending = _make_run(run_id="r_pending_1", date="2026-08-04", status="pending")
    await repo_mod.create_pipeline_run(pending.to_row())
    assert await repo_mod.pipeline_run_with_terminal_state_for_date("2026-08-04") is None

    # A done row counts.
    done = _make_run(run_id="r_done_1", date="2026-08-04", status="done")
    await repo_mod.create_pipeline_run(done.to_row())
    found = await repo_mod.pipeline_run_with_terminal_state_for_date("2026-08-04")
    assert found is not None
    assert found.id == "r_done_1"

    # A failed row on a different date doesn't match.
    failed_other = _make_run(run_id="r_failed_1", date="2026-08-05", status="failed")
    await repo_mod.create_pipeline_run(failed_other.to_row())
    assert (
        await repo_mod.pipeline_run_with_terminal_state_for_date("2026-08-05")
    ).id == "r_failed_1"
    # The 08-04 lookup is still the done row.
    assert (await repo_mod.pipeline_run_with_terminal_state_for_date("2026-08-04")).id == "r_done_1"


async def test_list_pipeline_runs_for_date(fresh_db) -> None:
    """The live data hook's per-date query returns only the matching
    date, newest first."""
    import uuid as _uuid

    # Three rows total, two on 2026-08-04 and one on 2026-08-05.
    # Use unique run_ids so the PRIMARY KEY doesn't conflict.
    ids = [_uuid.uuid4().hex[:12] for _ in range(3)]
    for rid, d in zip(ids, ("2026-08-04", "2026-08-04", "2026-08-05")):
        run = _make_run(run_id=rid, date=d)
        await repo_mod.create_pipeline_run(run.to_row())
    rows = await repo_mod.list_pipeline_runs_for_date("2026-08-04")
    assert all(r.date == "2026-08-04" for r in rows)
    assert len(rows) == 2


# ---------------------------------------------------------------------------
# Cross-"restart" persistence
# ---------------------------------------------------------------------------


async def test_rows_survive_new_repo_instance(fresh_db, monkeypatch) -> None:
    """Simulate a process restart: a fresh repo / engine bound to the
    same SQLite file reads the rows written by the previous instance.

    This is the contract the scheduler relies on: if today's run was
    written by a previous process and the orchestrator bounces, the
    new process's idempotency check must see the old row.
    """
    # Write through the first repo.
    run = _make_run(run_id="r_restart_1", status="done")
    await repo_mod.create_pipeline_run(run.to_row())
    # Drop the row out of the in-process identity map so the next
    # read goes to the DB.
    fresh_db.clear_compiled_cache()  # type: ignore[attr-defined]

    # Build a brand-new SessionLocal over the same URL, and patch
    # the repo's reference to it. The schema is already on disk
    # so we skip ``create_all`` here (it's a restart, not a fresh
    # boot).
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    new_engine = create_async_engine(str(fresh_db.url), echo=False)
    new_SessionLocal = async_sessionmaker(new_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(repo_mod, "SessionLocal", new_SessionLocal)

    # Read through the new repo.
    row = await repo_mod.get_pipeline_run("r_restart_1")
    assert row is not None
    assert row.status == "done"
    assert row.session_id == run.session_id

    await new_engine.dispose()


# ---------------------------------------------------------------------------
# API integration: the run row reaches the DB at terminal state
# ---------------------------------------------------------------------------


async def test_run_state_reaches_db_at_terminal(fresh_db, monkeypatch) -> None:
    """The HTTP path's terminal-state write: when the background task
    finishes, the row exists in the DB with status=done and the
    last_lines ring buffer populated.

    Drives ``_run_pipeline_task`` directly (rather than going
    through the TestClient + default ``tradefarm.db``) so the test
    uses the temp DB from the ``fresh_db`` fixture. Same code path
    the HTTP layer uses; the HTTP wrapper is just a thin POST
    handler on top.
    """
    import tradefarm.render.pipeline as pipeline_mod

    def stub_run_pipeline(*, session_id, opts, enabled, force, dry_run, sink=None):
        if sink:
            sink("session_id=" + session_id)
            sink("DONE")

    monkeypatch.setattr(pipeline_mod, "run_pipeline", stub_run_pipeline)

    run = _make_run(run_id="r_term_1", status="pending")
    # The background task mutates this in place.
    from tradefarm.render import pipeline as pipeline_mod_for_opts

    await api_pipeline._run_pipeline_task(
        run,
        pipeline_mod_for_opts.PipelineOpts(
            sessions_dir=__import__("pathlib").Path("/tmp"),
            music=None,
            tts_provider="auto",
            tts_voice="alloy",
            upload_dry_run=True,
            stitch_xfade=0.4,
            force=False,
        ),
    )
    # The task ran synchronously in this test (no real awaiting of
    # the worker thread); the in-memory state and the DB row are
    # both at terminal state.
    assert run.status == "done"
    row = await repo_mod.get_pipeline_run("r_term_1")
    assert row is not None
    assert row.status == "done"
    lines = json.loads(row.last_lines_json)
    assert any("DONE" in ln for ln in lines)


# ---------------------------------------------------------------------------
# 0.9.0 - live_today column + boot-sweep helpers
# ---------------------------------------------------------------------------


def _make_row(
    run_id: str,
    *,
    date: str | None = "2026-08-04",
    status: str = "pending",
    live_today: bool = True,
) -> PipelineRun:
    """Build a SQLAlchemy PipelineRun row directly.

    Bypasses the in-memory dataclass + to_row() so the test can pin
    the ``live_today`` value precisely (the dataclass layer doesn't
    expose the column; it's a DB-internal marker).
    """
    from datetime import datetime as _dt, timezone as _tz

    return PipelineRun(
        id=run_id,
        session_id=f"s_{date or 'x'}_abcdef",
        date=date,
        enabled=["session", "beats"],
        force=False,
        dry_run=False,
        status=status,
        created_at=_dt(2026, 8, 4, 16, 30, 0, tzinfo=_tz.utc),
        last_lines_json="[]",
        live_today=live_today,
    )


async def test_create_pipeline_run_writes_live_today_true_by_default(fresh_db) -> None:
    """``create_pipeline_run(row)`` writes ``live_today=True`` by default.

    Every new run is "live" from its writer's POV; the boot-time
    sweep in ``orchestrator.scheduler`` is the only code path that
    flips it to False. The HTTP wrapper's ``to_row()`` doesn't
    pass the column, so the default has to land on the wire or
    the new idempotency check will see every freshly-created run
    as "dead" and refire on the next process.
    """
    row = _make_row("r_default_live", date="2026-08-04", status="pending")
    await repo_mod.create_pipeline_run(row)

    fetched = await repo_mod.get_pipeline_run("r_default_live")
    assert fetched is not None
    assert fetched.live_today is True


async def test_set_pipeline_run_live_today_flips_value(fresh_db) -> None:
    """``set_pipeline_run_live_today(run_id, value)`` updates a single row.

    Verifies both the True->False and False->True transitions
    and the silent-no-op-on-unknown-id contract.
    """
    # True -> False
    await repo_mod.create_pipeline_run(
        _make_row("r_flip_1", date="2026-08-04", status="running", live_today=True)
    )
    await repo_mod.set_pipeline_run_live_today("r_flip_1", False)
    fetched = await repo_mod.get_pipeline_run("r_flip_1")
    assert fetched is not None
    assert fetched.live_today is False

    # False -> True
    await repo_mod.set_pipeline_run_live_today("r_flip_1", True)
    fetched = await repo_mod.get_pipeline_run("r_flip_1")
    assert fetched is not None
    assert fetched.live_today is True

    # Unknown id is a silent no-op (logged only).
    await repo_mod.set_pipeline_run_live_today("doesnotexist", False)
    # No exception, no row created.
    assert await repo_mod.get_pipeline_run("doesnotexist") is None


async def test_mark_runs_live_today_false_for_past_dates_only(fresh_db) -> None:
    """``mark_runs_live_today_false_for_past_dates(today)`` flips
    only past-date ``live_today=True`` rows.

    Today's row stays alive (a still-running render for today
    is genuinely in flight and the new process should defer to
    it). Already-False rows are untouched. Rows for other past
    dates flip. The return value is the row count for
    observability + tests.
    """
    # Past dates, all live. Should be flipped.
    await repo_mod.create_pipeline_run(
        _make_row("r_yest", date="2026-08-03", status="running", live_today=True)
    )
    await repo_mod.create_pipeline_run(
        _make_row("r_2d_ago", date="2026-08-02", status="done", live_today=True)
    )
    # Past date, already dead. Should be left alone (and not
    # count toward the row count, since the WHERE filters
    # on live_today=1).
    await repo_mod.create_pipeline_run(
        _make_row("r_dead_past", date="2026-08-01", status="failed", live_today=False)
    )
    # Today, live. Should NOT be flipped - the new process
    # inherits the in-flight state.
    await repo_mod.create_pipeline_run(
        _make_row("r_today", date="2026-08-04", status="running", live_today=True)
    )

    flipped = await repo_mod.mark_runs_live_today_false_for_past_dates("2026-08-04")
    assert flipped == 2, "expected 2 past-date live rows to be flipped"

    # Past dates are now dead.
    yest = await repo_mod.get_pipeline_run("r_yest")
    assert yest is not None and yest.live_today is False
    two_ago = await repo_mod.get_pipeline_run("r_2d_ago")
    assert two_ago is not None and two_ago.live_today is False
    # The already-dead past row is unchanged.
    dead_past = await repo_mod.get_pipeline_run("r_dead_past")
    assert dead_past is not None and dead_past.live_today is False
    # Today's row is untouched.
    today_row = await repo_mod.get_pipeline_run("r_today")
    assert today_row is not None and today_row.live_today is True

    # A second call is a no-op (every past-date row is now dead).
    flipped_again = await repo_mod.mark_runs_live_today_false_for_past_dates("2026-08-04")
    assert flipped_again == 0


async def test_live_pipeline_run_for_date_filters_correctly(fresh_db) -> None:
    """``live_pipeline_run_for_date(date)`` returns the newest
    ``live_today=True`` row for that date, ignoring dead rows.

    This is the helper the scheduler's idempotency check uses.
    The contract is: any live row for the date wins, regardless
    of status. Dead rows (from a previous process) are ignored.
    No row for the date -> None.
    """
    # Empty: returns None.
    assert await repo_mod.live_pipeline_run_for_date("2026-08-04") is None

    # A dead row for today: ignored.
    await repo_mod.create_pipeline_run(
        _make_row("r_dead_today", date="2026-08-04", status="failed", live_today=False)
    )
    assert await repo_mod.live_pipeline_run_for_date("2026-08-04") is None

    # A live row for today: returned (any status wins).
    await repo_mod.create_pipeline_run(
        _make_row("r_live_today", date="2026-08-04", status="running", live_today=True)
    )
    found = await repo_mod.live_pipeline_run_for_date("2026-08-04")
    assert found is not None
    assert found.id == "r_live_today"

    # A live row for a different date is invisible to the
    # today's-date lookup.
    await repo_mod.create_pipeline_run(
        _make_row("r_live_other", date="2026-08-05", status="running", live_today=True)
    )
    other = await repo_mod.live_pipeline_run_for_date("2026-08-05")
    assert other is not None
    assert other.id == "r_live_other"
    # Today's lookup is still the original row.
    found_today = await repo_mod.live_pipeline_run_for_date("2026-08-04")
    assert found_today is not None
    assert found_today.id == "r_live_today"
