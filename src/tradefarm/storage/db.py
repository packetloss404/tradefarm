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
    # VOD pivot — session_id tag set by the session runner so replay-produced
    # rows can be filtered out of live dashboards and grouped per session for
    # the daily reel pipeline. NULL on every existing row (i.e., all live data
    # to date); set only by session/run.py going forward.
    ("trades", "session_id", "VARCHAR(64)"),
    ("pnl_snapshots", "session_id", "VARCHAR(64)"),
    ("agent_notes", "session_id", "VARCHAR(64)"),
    # Audit fix: Trade.broker_order_id for reconciler dedupe at the DB
    # layer. The UNIQUE constraint comes via create_all on fresh DBs;
    # this ADD COLUMN handles pre-existing DBs (the constraint is added
    # via a partial unique index since SQLite can't ALTER ADD CONSTRAINT).
    ("trades", "broker_order_id", "VARCHAR(64)"),
)

# (table, column) — indexes to ensure on existing DBs. create_all builds
# them for fresh DBs via index=True on the model; this list mirrors them
# for DBs that already existed before the column landed.
_INDEX_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("trades", "session_id"),
    ("pnl_snapshots", "session_id"),
    ("agent_notes", "session_id"),
)


async def _table_columns(conn, table: str) -> set[str]:
    """Return {column_name,...} for `table`, or empty set if the table is missing.

    SQLite-only (PRAGMA). If the project ever adds Postgres support, swap this
    for ``inspect(conn).get_columns(table)`` and gate the ALTER syntax per
    dialect; the rest of the migration loop is already idempotent.
    """
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
    return {r[1] for r in rows}


async def _ensure_columns(conn) -> None:
    for table, column, ddl in _COLUMN_MIGRATIONS:
        existing = await _table_columns(conn, table)
        if not existing:
            # Table doesn't exist (shouldn't happen after create_all, but be
            # defensive — don't ALTER a non-existent table).
            continue
        if column in existing:
            continue
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


async def _ensure_indexes(conn) -> None:
    # Guarded helper: only create an index if the referenced column exists,
    # so a partial / corrupted upgrade can't brick startup. (Prior bug:
    # `CREATE INDEX IF NOT EXISTS ix_agent_notes_outcome_closed_at` would
    # raise OperationalError on a DB created before that column landed,
    # since IF NOT EXISTS guards the INDEX name, not the column reference.)
    async def _safe_index(
        ddl: str, table: str, column: str, *, unique_where: str | None = None
    ) -> None:
        cols = await _table_columns(conn, table)
        if column not in cols:
            return
        await conn.execute(text(ddl))

    for table, column in _INDEX_MIGRATIONS:
        idx_name = f"ix_{table}_{column}"
        await _safe_index(
            f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table} ({column})",
            table,
            column,
        )
    # Audit fix: partial unique index on Trade.broker_order_id for
    # existing DBs (fresh DBs get the constraint via create_all).
    # Partial-WHERE so the multitude of NULL rows (live trades pre-
    # reconciler + simulated fills) don't all collide on UNIQUE.
    await _safe_index(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_trades_broker_order_id "
        "ON trades(broker_order_id) WHERE broker_order_id IS NOT NULL",
        "trades",
        "broker_order_id",
    )
    # Audit fix: hot-path indexes flagged by storage subagent (`/agents/{id}/trades`
    # ordered by executed_at DESC was a full-table scan).
    await _safe_index(
        "CREATE INDEX IF NOT EXISTS ix_trades_agent_id ON trades(agent_id)",
        "trades",
        "agent_id",
    )
    await _safe_index(
        "CREATE INDEX IF NOT EXISTS ix_trades_executed_at ON trades(executed_at)",
        "trades",
        "executed_at",
    )
    await _safe_index(
        "CREATE INDEX IF NOT EXISTS ix_agent_notes_outcome_closed_at "
        "ON agent_notes(outcome_closed_at)",
        "agent_notes",
        "outcome_closed_at",
    )
    # Round-2 audit fix: AcademyPromotion UNIQUE constraint only fires via
    # create_all on fresh DBs. Pre-existing DBs (incl. the live broadcast VM
    # tradefarm.db at the time this landed) never got the constraint, so a
    # double-evaluate of curriculum could write duplicate promotion rows.
    # Mirror the model's UniqueConstraint here for after-the-fact application.
    cols = await _table_columns(conn, "academy_promotions")
    if {"agent_id", "from_rank", "to_rank", "at"}.issubset(cols):
        await conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_academy_promotions_unique_crossing "
                "ON academy_promotions(agent_id, from_rank, to_rank, at)"
            )
        )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
