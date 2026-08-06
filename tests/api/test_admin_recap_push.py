"""Tests for the 0.16.0 ``POST /admin/recap/push`` operator manual trigger.

The endpoint publishes a canonical ``BroadcastMoment`` via the
existing ``publish_broadcast_moment`` arbiter and returns the moment
id + a small summary. Two contracts to verify:

1. The publish lands in the installed ledger with the same shape the
   scheduler's poll loop fires (so the stream can't tell a manual
   push from a scheduled push).
2. The per-day idempotency row in ``daily_recap_fired`` is NOT
   written — a manual push is unconditional, the next 4pm still
   fires.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import tradefarm.storage.db as db_mod
import tradefarm.storage.repo as repo_mod
from tradefarm.orchestrator import broadcast_os as bos
from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler
from tradefarm.storage.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def push_db(monkeypatch, tmp_path):
    """Per-test temp-file SQLite so the daily_recap_fired table is
    observable. The endpoint MUST NOT write a row on a manual push;
    the test asserts that by querying the empty post-call table.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'push.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


@pytest.fixture
def push_client(push_db):
    """FastAPI TestClient with a freshly-installed broadcast arbiter.

    No `with` context — the recap admin endpoint doesn't need the
    orchestrator, and the lifespan would just slow the test down.
    """
    from tradefarm.api.main import app

    fresh_ledger = BroadcastRecapLedger()
    fresh_scheduler = BroadcastScheduler()
    bos.install_broadcast_arbiter(fresh_ledger, fresh_scheduler)

    client = TestClient(app)
    yield client, fresh_ledger, push_db

    bos.install_broadcast_arbiter(None, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_admin_recap_push_publishes_canonical_moment(push_client) -> None:
    """A POST to ``/admin/recap/push`` publishes a moment that lands
    in the ledger with the same shape the scheduler's poll loop
    produces: ``kind=day_leader``, ``trigger=daily_recap``,
    ``outputs=("recap_log",)``, ``priority=88``, ``ttl_sec=60``.
    """
    client, ledger, _db = push_client
    r = client.post("/admin/recap/push")
    assert r.status_code == 200
    body = r.json()
    # Response shape: moment_id + date + week_id + pushed_at.
    assert body["moment_id"].startswith("daily-recap-")
    assert body["date"]  # populated
    assert body["week_id"].startswith("2026-W")  # ISO week format
    assert "pushed_at" in body

    # Ledger received exactly one moment, and its shape matches the
    # scheduler's fire path so the stream's mapper is identical.
    assert len(ledger) == 1
    only = ledger.recent_moments()[0]
    assert only.kind == "day_leader"
    assert only.trigger == "daily_recap"
    assert only.outputs == ("recap_log",)
    assert only.priority == 88
    assert only.ttl_sec == 60
    assert only.id == body["moment_id"]


def test_admin_recap_push_does_not_write_idempotency_row(push_client) -> None:
    """The endpoint publishes the moment but DOES NOT write a row to
    ``daily_recap_fired`` — a manual push is unconditional, the next
    4pm still fires. The table is empty after a single push.
    """
    client, _ledger, db_engine = push_client

    r = client.post("/admin/recap/push")
    assert r.status_code == 200
    date = r.json()["date"]

    # Query the (empty) table for the date the push targeted.
    import asyncio
    import sqlalchemy as _sa

    async def _count() -> int:
        async with db_engine.connect() as conn:
            rows = await conn.execute(
                _sa.text("SELECT count(*) FROM daily_recap_fired WHERE date = :d"),
                {"d": date},
            )
        return int(rows.scalar() or 0)

    assert asyncio.run(_count()) == 0


def test_admin_recap_push_returns_each_call_with_unique_id(push_client) -> None:
    """Two consecutive pushes produce two distinct moment_ids so the
    dashboard's "already pushed" toast can disambiguate (and the
    stream's broadcast-moment dedup ring doesn't collapse them into
    a single visible event).
    """
    client, ledger, _db = push_client

    r1 = client.post("/admin/recap/push")
    r2 = client.post("/admin/recap/push")
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["moment_id"] != r2.json()["moment_id"]
    # Both moments are in the ledger.
    assert len(ledger) == 2
