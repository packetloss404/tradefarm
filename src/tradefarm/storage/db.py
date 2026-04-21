"""Async SQLAlchemy engine + session + a tiny idempotent migration helper.

`create_all` only handles *missing tables*. When we add new columns to an
existing table (e.g. Phase 2 added `agents.rank`), older DB files need a
manual ALTER. `_ensure_columns` is the minimal-viable fix: a list of
(table, column, DDL-fragment) tuples we re-apply on every boot. SQLite
ignores duplicates gracefully via a pre-check on `PRAGMA table_info`.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tradefarm.config import settings
from tradefarm.storage.models import Base

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


# (table, column, sqlite DDL fragment — just the "type + defaults" part)
# Only append-only migrations belong here. Never drop or rename.
_COLUMN_MIGRATIONS: tuple[tuple[str, str, str], ...] = (
    # Phase 2 — agent academy ranks
    ("agents", "rank", "VARCHAR(16) NOT NULL DEFAULT 'intern'"),
    ("agents", "rank_updated_at", "DATETIME"),
)


async def _ensure_columns(conn) -> None:
    for table, column, ddl in _COLUMN_MIGRATIONS:
        rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
        existing = {r[1] for r in rows}  # r[1] is the column name in PRAGMA output
        if column in existing:
            continue
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
