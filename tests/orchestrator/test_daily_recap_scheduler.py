"""Tests for the 0.16.0 4pm-ET live recap scheduler.

The scheduler lives on ``BroadcastSuite`` and polls every 30s. We test
the three pure-ish predicates directly (no event loop spinning) and
verify the end-to-end fire path against a temp-file SQLite so the
``daily_recap_fired`` row is observable:

* ``_should_fire_daily_recap`` returns True at 16:00 ET, False outside
  the [16:00, 16:30) window, False on a holiday (when
  ``is_market_closed_for_n_minutes(0)`` is False), and False after a
  row is already present for today.
* ``_fire_daily_recap_moment`` publishes a ``BroadcastMoment`` with
  the canonical shape and writes the idempotency row.
* The master switch (``settings.daily_recap_enabled=False``) parks the
  loop forever.

The suite owns the ledger + arbiter; we install a fresh arbiter for
each test so the broadcast_moment publication is observable without
polluting module globals between tests.
"""

from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import tradefarm.storage.db as db_mod
import tradefarm.storage.repo as repo_mod
from tradefarm.config import settings
from tradefarm.orchestrator import broadcast_os as bos
from tradefarm.orchestrator.broadcast_suite import (
    BroadcastSuite,
    _build_daily_recap_moment,
)
from tradefarm.storage.models import Base
from tradefarm.storage.repo import (
    find_daily_recap_for_date,
    record_daily_recap_fired,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _StubOrch:
    """Stand-in orchestrator the suite can hold without booting a real one.

    The scheduler doesn't read any agent state — it only needs a reference
    to call the suite's own methods. This stub matches the constructor's
    duck-type (just an attribute the suite can hang off).
    """

    agents: list = []


@pytest_asyncio.fixture
async def daily_recap_db(monkeypatch, tmp_path):
    """Per-test temp-file SQLite so the daily_recap_fired row is observable.

    We point db.engine + db.SessionLocal + repo.SessionLocal at a
    fresh file-backed DB, then ``create_all`` registers the
    ``DailyRecapFired`` model. The shared engine is restored to
    whatever the test caller had at the end of the test.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'daily_recap.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture(autouse=True)
def _isolate_arbiter():
    """Reset the module-global broadcast arbiter around each test.

    The broadcast_moment publication in the scheduler reads the
    installed ledger; without an explicit install the publish path
    bypasses the ledger. We install a fresh one in each test and
    uninstall at the end so a leaked ledger doesn't bleed across
    test boundaries (this was the original audit-findings C15
    concern).
    """
    from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger
    from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler

    fresh_ledger = BroadcastRecapLedger()
    fresh_scheduler = BroadcastScheduler()
    bos.install_broadcast_arbiter(fresh_ledger, fresh_scheduler)
    yield fresh_ledger
    bos.install_broadcast_arbiter(None, None)


@pytest.fixture(autouse=True)
def _disable_other_loops(monkeypatch):
    """Disable unrelated background loops so the tests are deterministic."""
    monkeypatch.setattr(settings, "auto_tick_interval_sec", 0)
    monkeypatch.setattr(settings, "academy_eval_interval_sec", 0)
    yield


# ---------------------------------------------------------------------------
# _should_fire_daily_recap
# ---------------------------------------------------------------------------


def _freeze_now(monkeypatch, iso_utc: str) -> None:
    """Pin ``runtime.clock.now_utc()`` to a specific instant for one test.

    The scheduler reads the wall clock through ``runtime.clock.now_utc``;
    we don't have a swap hook, so we patch the ``_runtime_clock_now_utc``
    symbol in the broadcast_suite module directly. The module imports
    it lazily inside the method, so we patch the source: ``runtime.clock``.
    """
    import tradefarm.runtime.clock as clock_mod

    target = datetime.fromisoformat(iso_utc.replace("Z", "+00:00"))

    def _frozen_now() -> datetime:
        return target

    monkeypatch.setattr(clock_mod, "now_utc", _frozen_now)
    # The broadcast_suite module re-imports now_utc lazily at the call
    # site, so the patched symbol in clock_mod is the one read. Nothing
    # else to wire.


async def test_should_fire_at_1600_et_on_a_trading_day(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """At 16:00 ET on a normal trading day (no prior row), the predicate
    returns True. The 30-min grace window covers a slow tick at 16:00:30.
    """
    # Tuesday 2026-08-04 is a normal NYSE trading day. 16:00 ET = 20:00 UTC.
    _freeze_now(monkeypatch, "2026-08-04T20:00:30+00:00")
    suite = BroadcastSuite(_StubOrch())
    assert await suite._should_fire_daily_recap() is True


async def test_should_not_fire_outside_window(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """Outside [16:00, 16:30) ET, the predicate returns False even on
    a trading day. Verify 15:59:59 (just before) and 16:30:00 (just
    after).
    """
    suite = BroadcastSuite(_StubOrch())

    # 15:59:59 ET = 19:59:59 UTC.
    _freeze_now(monkeypatch, "2026-08-04T19:59:59+00:00")
    assert await suite._should_fire_daily_recap() is False

    # 16:30 ET = 20:30 UTC. After the grace window.
    _freeze_now(monkeypatch, "2026-08-04T20:30:00+00:00")
    assert await suite._should_fire_daily_recap() is False


async def test_should_not_fire_on_holiday(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """A holiday at 16:00 ET must NOT trigger the recap. We mock
    ``is_market_closed_for_n_minutes(0)`` to return False (the
    function's documented "no session today" return value) and verify
    the predicate refuses to fire.

    Patching the symbol the suite module sees: the suite imports
    ``is_market_closed_for_n_minutes`` lazily inside the method via
    ``from tradefarm.market_clock import is_market_closed_for_n_minutes``,
    so we have to patch the source module.
    """
    import tradefarm.market_clock as mclock_mod

    monkeypatch.setattr(mclock_mod, "is_market_closed_for_n_minutes", lambda n: False)

    # 16:00 ET on a Saturday (no market session) — predicate would
    # otherwise be True without the holiday guard.
    _freeze_now(monkeypatch, "2026-08-08T20:00:00+00:00")
    suite = BroadcastSuite(_StubOrch())
    assert await suite._should_fire_daily_recap() is False


async def test_should_not_fire_when_row_already_written(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """A pre-existing ``daily_recap_fired`` row for today makes the
    predicate skip. This is the per-day idempotency contract — a
    restart at 4:02pm must NOT re-fire the moment.
    """
    _freeze_now(monkeypatch, "2026-08-04T20:00:30+00:00")
    # Seed a row for today's ET date. The predicate reads via
    # ``runtime.clock.now_utc()``; the row's date matches.
    today_iso = "2026-08-04"
    await record_daily_recap_fired(
        date=today_iso, moment_id="m_prior", fired_at="2026-08-04T20:00:00+00:00"
    )

    suite = BroadcastSuite(_StubOrch())
    assert await suite._should_fire_daily_recap() is False


# ---------------------------------------------------------------------------
# _fire_daily_recap_moment
# ---------------------------------------------------------------------------


async def test_fire_publishes_canonical_moment_and_writes_row(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """``_fire_daily_recap_moment`` publishes a moment with the
    documented shape AND writes the per-day idempotency row.

    We assert the moment lands in the freshly-installed ledger (so the
    canonical record path is exercised end-to-end) and the row lands in
    ``daily_recap_fired`` (so the next tick sees the dedupe).
    """
    _freeze_now(monkeypatch, "2026-08-04T20:00:30+00:00")
    suite = BroadcastSuite(_StubOrch())
    ledger = _isolate_arbiter  # autouse fixture installs a fresh ledger

    await suite._fire_daily_recap_moment()

    # 1. Ledger has exactly one entry; shape matches the spec.
    assert len(ledger) == 1
    only = ledger.recent_moments()[0]
    assert only.kind == "day_leader"
    assert only.trigger == "daily_recap"
    assert only.outputs == ("recap_log",)
    assert only.priority == 88
    assert only.ttl_sec == 60
    assert only.metadata.get("date") == "2026-08-04"
    # 2026-08-04 is a Tuesday — ISO week 32.
    assert only.metadata.get("week_id") == "2026-W32"

    # 2. Idempotency row is written for the same date.
    row = await find_daily_recap_for_date("2026-08-04")
    assert row is not None
    assert row.moment_id == only.id
    assert row.date == "2026-08-04"


# ---------------------------------------------------------------------------
# Master switch
# ---------------------------------------------------------------------------


async def test_run_parked_when_daily_recap_disabled(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """``settings.daily_recap_enabled=False`` parks the loop forever
    on an ``asyncio.Event``. No DB writes, no moment fires. The
    task is alive (not yet complete) and cancellable.
    """
    monkeypatch.setattr(settings, "daily_recap_enabled", False)
    suite = BroadcastSuite(_StubOrch())

    task = asyncio.create_task(suite.run_daily_recap_scheduler())
    try:
        # Brief wait to let the loop enter its parked state.
        await asyncio.sleep(0.05)
        assert not task.done(), "loop exited despite daily_recap_enabled=False"
        # No row written; the table is empty.
        rows = await repo_mod.find_daily_recap_for_date("2026-08-04")
        assert rows is None
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


# ---------------------------------------------------------------------------
# start / stop lifecycle (orchestrator-facing)
# ---------------------------------------------------------------------------


async def test_start_daily_recap_scheduler_is_idempotent(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """``start_daily_recap_scheduler`` is a no-op on the second call.

    The orchestrator's start_background runs once per process boot; a
    re-entrant call must not double-spawn the task.
    """
    monkeypatch.setattr(settings, "daily_recap_enabled", False)
    suite = BroadcastSuite(_StubOrch())
    await suite.start_daily_recap_scheduler()
    first = suite._daily_recap_task
    assert first is not None
    await suite.start_daily_recap_scheduler()
    assert suite._daily_recap_task is first
    # Cleanup
    await suite.stop_daily_recap_scheduler()


async def test_stop_daily_recap_scheduler_cancels_task(
    monkeypatch, daily_recap_db, _isolate_arbiter
) -> None:
    """``stop_daily_recap_scheduler`` cancels + clears the task."""
    monkeypatch.setattr(settings, "daily_recap_enabled", False)
    suite = BroadcastSuite(_StubOrch())
    await suite.start_daily_recap_scheduler()
    assert suite._daily_recap_task is not None
    await suite.stop_daily_recap_scheduler()
    assert suite._daily_recap_task is None
    # Idempotent — a second call is a no-op.
    await suite.stop_daily_recap_scheduler()


# ---------------------------------------------------------------------------
# Pure helper: _build_daily_recap_moment
# ---------------------------------------------------------------------------


def test_build_daily_recap_moment_default_id_and_week() -> None:
    """The shared helper auto-generates a moment_id and computes
    week_id for the supplied date. Sanity-check the shape so a
    refactor that breaks the canonical payload is loud.
    """
    m = _build_daily_recap_moment("2026-08-05")
    assert m.id.startswith("daily-recap-2026-08-05-")
    assert m.kind == "day_leader"
    assert m.trigger == "daily_recap"
    assert m.outputs == ("recap_log",)
    assert m.priority == 88
    assert m.ttl_sec == 60
    # 2026-08-05 is a Wednesday — ISO week 32.
    assert m.metadata == {"date": "2026-08-05", "week_id": "2026-W32"}


def test_build_daily_recap_moment_respects_explicit_id_and_week() -> None:
    """When the admin path passes an explicit moment_id and week_id,
    the helper honors them verbatim (no auto-generation).
    """
    m = _build_daily_recap_moment(
        "2026-08-05", moment_id="m_explicit", week_id="2026-W99"
    )
    assert m.id == "m_explicit"
    assert m.metadata == {"date": "2026-08-05", "week_id": "2026-W99"}
