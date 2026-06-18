"""Tests for the hand-rolled idempotent migration helpers in storage/db.py.

ISSUE #8b (migration hardening): the schema-change helpers
(_ensure_columns / _ensure_indexes) re-run every boot, so they must be
airtight against re-runs and a misdetected dialect. These tests assert that
init_db() runs twice cleanly, the expected migrated columns/indexes exist, and
the schema_version ledger is recorded exactly once.

Uses a per-test temp-file SQLite DB (no network). A file path — not
`:memory:` — is used so the connection-per-call pattern in init_db sees the
same database across both invocations.
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def migration_db(monkeypatch, tmp_path):
    """Point db.engine at a fresh temp-file SQLite DB for this test."""
    import tradefarm.storage.db as db_mod

    url = f"sqlite+aiosqlite:///{tmp_path / 'migrate.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)

    yield engine
    await engine.dispose()


async def _table_info(engine, table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
    return {r[1] for r in rows}


async def _index_names(engine, table: str) -> set[str]:
    async with engine.connect() as conn:
        rows = (await conn.execute(text(f"PRAGMA index_list({table})"))).all()
    return {r[1] for r in rows}


async def test_init_db_is_idempotent(migration_db):
    """init_db() must run twice without raising (re-applied every boot)."""
    from tradefarm.storage.db import init_db

    await init_db()
    # Second boot against the same (now-migrated) DB — the guards must no-op.
    await init_db()


async def test_migrated_columns_exist(migration_db):
    """The append-only column migrations land on the relevant tables."""
    from tradefarm.storage.db import init_db

    await init_db()

    assert {"rank", "rank_updated_at"}.issubset(await _table_info(migration_db, "agents"))
    assert {"session_id", "broker_order_id"}.issubset(await _table_info(migration_db, "trades"))
    assert "session_id" in await _table_info(migration_db, "pnl_snapshots")
    assert "session_id" in await _table_info(migration_db, "agent_notes")


async def test_migrated_indexes_exist(migration_db):
    """The mirrored indexes are created on existing DBs."""
    from tradefarm.storage.db import init_db

    await init_db()

    trade_idx = await _index_names(migration_db, "trades")
    assert "ix_trades_session_id" in trade_idx
    assert "uq_trades_broker_order_id" in trade_idx
    assert "ix_trades_agent_id" in trade_idx
    assert "ix_trades_executed_at" in trade_idx


async def test_schema_version_recorded_exactly_once(migration_db):
    """schema_version is stamped, and a re-boot does not duplicate the row."""
    from tradefarm.storage.db import SCHEMA_VERSION, init_db

    await init_db()
    await init_db()  # idempotent stamp — no second row

    async with migration_db.connect() as conn:
        rows = (await conn.execute(text("SELECT version FROM schema_version"))).all()

    assert [r[0] for r in rows] == [SCHEMA_VERSION]
