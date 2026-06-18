"""Tests for ``repo.record_trade`` broker_order_id persistence + dedupe.

ISSUE #2: ``record_trade`` previously never accepted/wrote ``broker_order_id``,
so every Trade row stored NULL and the UNIQUE constraint guarding restart-safe
double-counting protection (CLAUDE.md gotcha #7) was inert. These tests assert
the id is persisted and a duplicate write is a safe no-op.

Uses a per-test in-memory SQLite DB (no network, no real broker).
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import func, select


@pytest_asyncio.fixture
async def repo_db(monkeypatch):
    """Point SessionLocal/engine at a fresh in-memory SQLite DB for this test."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.storage.db as db_mod
    import tradefarm.storage.repo as repo_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch both the db module *and* repo's already-imported reference.
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed one agent row so the FK on trades resolves.
    async with SessionLocal() as s:
        s.add(
            Agent(
                id=1,
                name="agent-001",
                strategy="momentum_sma20",
                starting_capital=1000.0,
                cash=1000.0,
                status="waiting",
            )
        )
        await s.commit()

    yield SessionLocal
    await engine.dispose()


async def _trade_count(SessionLocal, broker_order_id: str) -> int:
    from tradefarm.storage.models import Trade

    async with SessionLocal() as s:
        return int(
            (
                await s.execute(
                    select(func.count(Trade.id)).where(Trade.broker_order_id == broker_order_id)
                )
            ).scalar_one()
        )


async def test_record_trade_persists_broker_order_id(repo_db):
    """(a) record_trade writes a non-null broker_order_id."""
    from tradefarm.storage import repo
    from tradefarm.storage.models import Trade

    await repo.record_trade(
        agent_id=1,
        symbol="SPY",
        side="buy",
        qty=10,
        price=400.0,
        reason="entry",
        broker_order_id="broker-abc-123",
    )

    async with repo_db() as s:
        rows = (await s.execute(select(Trade))).scalars().all()
    assert len(rows) == 1
    assert rows[0].broker_order_id == "broker-abc-123"


async def test_duplicate_broker_order_id_is_deduped(repo_db):
    """(b) a second write with the same broker_order_id is a silent no-op."""
    from tradefarm.storage import repo

    oid = "broker-dup-999"
    await repo.record_trade(1, "SPY", "buy", 10, 400.0, "optimistic", broker_order_id=oid)
    # Second call simulates the reconcile path (or a restart replay) writing
    # the same fill again — must not raise and must not create a 2nd row.
    await repo.record_trade(1, "SPY", "buy", 10, 401.5, "reconciled_fill", broker_order_id=oid)

    assert await _trade_count(repo_db, oid) == 1


async def test_null_broker_order_id_allows_multiple_rows(repo_db):
    """NULL broker_order_id skips dedupe — the partial/UNIQUE index ignores NULLs."""
    from tradefarm.storage import repo
    from tradefarm.storage.models import Trade

    await repo.record_trade(1, "SPY", "buy", 10, 400.0, "sim")
    await repo.record_trade(1, "SPY", "buy", 10, 400.0, "sim")

    async with repo_db() as s:
        count = int((await s.execute(select(func.count(Trade.id)))).scalar_one())
    assert count == 2
