"""Async SQLAlchemy engine + session + a tiny idempotent migration helper.

`create_all` only handles *missing tables*. When we add new columns to an
existing table (e.g. Phase 2 added `agents.rank`), older DB files need a
manual ALTER. `_ensure_columns` is the minimal-viable fix: a list of
(table, column, DDL-fragment) tuples we re-apply on every boot. SQLite
ignores duplicates gracefully via a pre-check on `PRAGMA table_info`.
"""

from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tradefarm.config import settings
from tradefarm.storage.models import Base

log = structlog.get_logger(__name__)

engine = create_async_engine(settings.database_url, echo=False)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Bumped whenever a hand-rolled migration (a new entry in _COLUMN_MIGRATIONS /
# _INDEX_MIGRATIONS) lands. Recorded in the `schema_version` table on every
# successful init for observability — it is NOT a gate (migrations stay
# idempotent and self-detecting), just a breadcrumb of what code last ran.
# v2: pipeline_runs table added (autonomy sprint). create_all picks it up
# on the next boot; the dedicated ``_ensure_pipeline_runs`` helper is
# defensive against a code path that bypasses create_all (none today, but
# the helper is cheap and matches the existing pattern of belt-and-braces
# index/column guards).
# v3: pipeline_runs.live_today boolean (autonomy polish). Fixes the
# power-loss race in the daily VOD scheduler's per-day idempotency
# check — see PipelineRun docstring in models.py for the full story.
SCHEMA_VERSION = 3


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
    # 0.9.0 — process-alive marker for the VOD scheduler's
    # power-loss-safe idempotency check. See PipelineRun docstring
    # in models.py. Default 1 (=True) so existing rows resolve to
    # "live" until the new boot sweep in orchestrator.scheduler
    # flips past-date rows to 0.
    ("pipeline_runs", "live_today", "BOOLEAN NOT NULL DEFAULT 1"),
)

# (table, column) — indexes to ensure on existing DBs. create_all builds
# them for fresh DBs via index=True on the model; this list mirrors them
# for DBs that already existed before the column landed.
_INDEX_MIGRATIONS: tuple[tuple[str, str], ...] = (
    ("trades", "session_id"),
    ("pnl_snapshots", "session_id"),
    ("agent_notes", "session_id"),
)


def _dialect_name(conn) -> str:
    """Best-effort dialect name for an async connection.

    Reads it off the bound engine's `dialect.name` — the single source of
    truth SQLAlchemy already carries — instead of the fragile triple-nested
    attribute probing the prior code used. Falls back to "sqlite" only if no
    dialect can be resolved at all, which is the conservative default for this
    repo (every supported backend is SQLite or Postgres).
    """
    dialect = getattr(getattr(conn, "engine", None), "dialect", None)
    name = getattr(dialect, "name", None)
    if name in ("sqlite", "postgresql"):
        return name
    if name:
        # Unknown dialect: route through the SQLite path (PRAGMA), which is the
        # only check-then-add path that can't raise on a missing table.
        log.warning("db_unknown_dialect", dialect=name, fallback="sqlite")
        return "sqlite"
    return "sqlite"


async def _table_columns(conn, table: str) -> set[str]:
    """Return {column_name,...} for `table`, or empty set if the table is missing.

    Dialect-dispatch: SQLite uses PRAGMA table_info; Postgres uses
    information_schema.columns. Both return an empty set for a missing table
    (rather than raising), which the migration loop relies on to no-op safely.
    """
    if _dialect_name(conn) == "postgresql":
        rows = (
            await conn.execute(
                text("SELECT column_name FROM information_schema.columns WHERE table_name = :t"),
                {"t": table},
            )
        ).all()
        return {r[0] for r in rows}
    # SQLite path. PRAGMA table_info on an unknown table yields zero rows
    # (never an error), so a misdetected dialect degrades to "table missing"
    # and the column-add is skipped rather than raising on boot.
    rows = (await conn.execute(text(f"PRAGMA table_info({table})"))).all()
    return {r[1] for r in rows}


async def _ensure_columns(conn) -> None:
    # Two layers of idempotency so a re-run or a wrong-dialect dispatch can
    # never raise on boot: (1) check-then-add against introspected columns,
    # and (2) ADD COLUMN IF NOT EXISTS on Postgres (SQLite has no such clause,
    # but the check-then-add already covers it).
    if_not_exists = "IF NOT EXISTS " if _dialect_name(conn) == "postgresql" else ""
    for table, column, ddl in _COLUMN_MIGRATIONS:
        existing = await _table_columns(conn, table)
        if not existing:
            # Table doesn't exist (shouldn't happen after create_all, but be
            # defensive — don't ALTER a non-existent table).
            continue
        if column in existing:
            continue
        await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {if_not_exists}{column} {ddl}"))


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


async def _ensure_schema_version(conn) -> None:
    """Create the `schema_version` table (idempotent) and stamp SCHEMA_VERSION.

    Pure observability: a single-row-per-version ledger of what migration code
    last ran, written only after create_all + the ALTER/index passes succeed.
    Raw DDL (not an ORM model) so it stays decoupled from `models.py`. The
    timestamp default is dialect-portable — CURRENT_TIMESTAMP exists in both
    SQLite and Postgres.
    """
    await conn.execute(
        text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER PRIMARY KEY, "
            "applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
    )
    # Idempotent stamp: INSERT only if this version isn't already recorded, so
    # a clean re-boot doesn't append duplicate rows.
    already = (
        await conn.execute(
            text("SELECT 1 FROM schema_version WHERE version = :v"),
            {"v": SCHEMA_VERSION},
        )
    ).first()
    if already is None:
        await conn.execute(
            text("INSERT INTO schema_version (version) VALUES (:v)"),
            {"v": SCHEMA_VERSION},
        )
        log.info("schema_version_recorded", version=SCHEMA_VERSION)


async def _ensure_pipeline_runs(conn) -> None:
    """Defensive: create the ``pipeline_runs`` table if it's missing.

    ``create_all`` (called in ``init_db`` before this helper) handles the
    normal case — the model is registered in ``Base.metadata`` and
    ``create_all`` is idempotent. This guard exists so a pre-existing
    DB that was bootstrapped against an older version of ``models.py``
    (and somehow lost the table — e.g. a manual ``DROP TABLE``) doesn't
    crash the boot on the first ``INSERT INTO pipeline_runs`` from
    ``repo.create_pipeline_run``. It also covers the test pattern of
    pointing the engine at a pre-existing SQLite file that lacks the
    table (some tests build the engine first, then call ``init_db``).
    """
    # Use a cheap existence check rather than re-running create_all for
    # one table — keeps the per-boot cost near zero for the hot path.
    if _dialect_name(conn) == "postgresql":
        rows = (
            await conn.execute(
                text(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_name = 'pipeline_runs'"
                )
            )
        ).first()
    else:
        rows = (
            await conn.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'pipeline_runs'"
                )
            )
        ).first()
    if rows is None:
        # Import locally to avoid a circular import at module load
        # (models.py imports from sqlalchemy; repo.py imports from here).
        from tradefarm.storage.models import Base

        await conn.run_sync(Base.metadata.tables["pipeline_runs"].create)


async def _ensure_pipeline_runs_live_today(conn) -> None:
    """0.9.0 migration: add the ``live_today`` column to ``pipeline_runs``.

    This is a dedicated helper (rather than just a tuple entry) for
    symmetry with ``_ensure_pipeline_runs`` and so a future "boot
    backfill" pass (e.g. migrating historical ``status='running'``
    rows on a deployed DB) can hang off the same call site. The
    ADD COLUMN itself is idempotent (the tuple's check-then-add
    in ``_ensure_columns`` short-circuits on a re-run), and the
    DEFAULT 1 backfills every existing row to "live" — the new
    boot-time sweep in ``orchestrator.scheduler`` flips past-date
    rows to 0 immediately after this migration lands.

    Returns nothing; the column being present (or already present)
    is the contract.
    """
    existing = await _table_columns(conn, "pipeline_runs")
    if not existing:
        # Table hasn't been created yet (a pre-create_all boot or a
        # DB that lost the table entirely). ``_ensure_pipeline_runs``
        # handles that case; nothing for us to do here — when the
        # table later appears, create_all will include the column
        # from the model's mapped_column definition.
        return
    if "live_today" in existing:
        return
    # Mirrors the tuple entry, kept inline so the column shape is
    # obvious to a future reader. The check-then-add above already
    # makes this a no-op on re-runs, so a duplicate ADD COLUMN can't
    # happen even if a developer wires this in twice by mistake.
    if_not_exists = "IF NOT EXISTS " if _dialect_name(conn) == "postgresql" else ""
    await conn.execute(
        text(
            f"ALTER TABLE pipeline_runs ADD COLUMN {if_not_exists}live_today "
            "BOOLEAN NOT NULL DEFAULT 1"
        )
    )


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _ensure_columns(conn)
        await _ensure_indexes(conn)
        await _ensure_pipeline_runs(conn)
        await _ensure_pipeline_runs_live_today(conn)
        await _ensure_schema_version(conn)
