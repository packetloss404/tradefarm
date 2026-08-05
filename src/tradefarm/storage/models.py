from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# Money columns store exact Decimal (asdecimal=True). Precision 20 / scale 6
# comfortably covers 100 agents × low-thousands capital plus fractional
# shares; SQLite stores NUMERIC affinity, Postgres a real NUMERIC(20, 6).
_MONEY = Numeric(20, 6, asdecimal=True)


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    strategy: Mapped[str] = mapped_column(String(64))
    starting_capital: Mapped[Decimal] = mapped_column(_MONEY)
    cash: Mapped[Decimal] = mapped_column(_MONEY)
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Phase 2 (Agent Academy): rank-gated capital. `server_default` ensures
    # rows inserted by older code paths (or `SELECT *` over pre-Phase-2 data)
    # resolve to "intern" without a migration. `rank_updated_at` stays NULL
    # until Phase 4's curriculum flips a rank.
    rank: Mapped[str] = mapped_column(
        String(16),
        default="intern",
        server_default="intern",
    )
    rank_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Per-agent disable flag. The scheduler's tick reads the set of disabled
    # ids once per tick and skips ``decide()`` for them — disabled agents
    # are fully frozen (no new entries AND no risk-driven exits). Operator
    # must re-enable to exit a position. ``server_default="0"`` so existing
    # SQLite/Postgres rows resolve to False without a migration.
    disabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
        nullable=False,
    )

    positions: Mapped[list["Position"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )
    trades: Mapped[list["Trade"]] = relationship(
        back_populates="agent", cascade="all, delete-orphan"
    )


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    qty: Mapped[Decimal] = mapped_column(_MONEY)
    avg_price: Mapped[Decimal] = mapped_column(_MONEY)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[Decimal] = mapped_column(_MONEY)
    price: Mapped[Decimal] = mapped_column(_MONEY)
    executed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    reason: Mapped[str] = mapped_column(String(256), default="")
    # NULL for live trading; set by the session runner to tag every fill
    # produced by a replay so downstream beat detection can pull a single
    # session's worth of activity. Indexed for the "all trades in session
    # X" query pattern.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Reconciler dedupe — the Alpaca reconciler attributes fills back to
    # virtual books on broker_order_id; pairing the column with a UNIQUE
    # constraint at the DB layer means a duplicate reconciler call can't
    # write duplicate Trade rows even if apply_reconciled_fill's
    # in-memory idempotency check missed (e.g. process restart). NULL
    # for sim-broker fills (no broker_order_id) and pre-reconciler rows.
    broker_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    agent: Mapped[Agent] = relationship(back_populates="trades")

    __table_args__ = (UniqueConstraint("broker_order_id", name="uq_trades_broker_order_id"),)


class PnlSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    equity: Mapped[Decimal] = mapped_column(_MONEY)
    realized_pnl: Mapped[Decimal] = mapped_column(_MONEY)
    unrealized_pnl: Mapped[Decimal] = mapped_column(_MONEY)
    taken_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    # NULL for live snapshots; set by the session runner. See Trade.session_id.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class AgentNote(Base):
    """Per-decision journal entry with optional stamped outcome.

    Phase 1 of the Agent Academy: every agent decision writes a note; when the
    position closes (realized PnL delta from the closing fill) we stamp the
    oldest matching entry note with the realized result + trade id.
    """

    __tablename__ = "agent_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # "entry" | "exit" | "observation"
    symbol: Mapped[str] = mapped_column(String(16), index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    # JSON-serialized dict as TEXT for cross-backend portability (SQLite + Postgres).
    note_metadata: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    # Outcome fields (nullable; stamped on close).
    outcome_trade_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_realized_pnl: Mapped[Decimal | None] = mapped_column(_MONEY, nullable=True)
    outcome_closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    # NULL for live notes; set by the session runner. See Trade.session_id.
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class AcademyPromotion(Base):
    """Phase 4 — per-agent rank-change log.

    Written by ``academy.curriculum.evaluate_all``; read by the Promotions
    Board panel and the per-agent promotions endpoint. ``stats_snapshot`` is
    JSON-serialized ``RankStats`` at the time of the change, so we can reason
    about *why* a rank flipped even if thresholds change later.
    """

    __tablename__ = "academy_promotions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    from_rank: Mapped[str] = mapped_column(String(16))
    to_rank: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(256), default="")
    # JSON-serialized RankStats; TEXT for SQLite + Postgres portability.
    stats_snapshot: Mapped[str] = mapped_column(Text, default="")
    at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)

    __table_args__ = (
        # Dedupe: two overlapping curriculum passes (or a process
        # restart + replay) could otherwise write two identical
        # promotion rows for the same threshold crossing, doubling the
        # WS event and the dashboard's promotion-history list.
        UniqueConstraint(
            "agent_id",
            "from_rank",
            "to_rank",
            "at",
            name="uq_academy_promotions_unique_crossing",
        ),
    )


class PipelineRun(Base):
    """VOD pipeline run state — DB-backed replacement for the in-memory
    ``_RUNS`` deque in ``tradefarm.api.pipeline``.

    One row per pipeline run (a `run_id` is a 12-char hex, same shape
    the old in-memory deque used). Status moves through
    ``pending -> running -> done | failed``. The same row is also
    written by the orchestrator's daily scheduler loop, which checks
    ``status IN ('done', 'running')`` for the current date as its
    per-day idempotency guard.

    `last_lines_json` is a JSON-encoded list[str] ring buffer
    (capped at 200) mirroring the per-run log tail the HTTP layer
    used to keep in process memory. Storing it here makes a
    backend restart preserve the log for the dashboard.

    `live_today` is the "this run is from the currently-running
    process" marker added in 0.9.0 to fix a power-loss race in
    the scheduler's per-day idempotency check: a previous process
    that died mid-run leaves a ``status='running'`` row that the
    fresh-process scheduler can no longer tell from its own
    freshly-kicked run. On boot, the orchestrator flips every
    ``live_today=True`` row whose ``date`` is not today to
    ``False`` (the previous process's state is dead); the
    idempotency check then filters on ``live_today=True`` for
    today's date and can only see its own runs. The column stays
    ``True`` at terminal state — terminal status (``done`` /
    ``failed``) is what gates "should I refire", ``live_today``
    only gates "is this from a still-running process".
    """

    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(12), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(128))
    # ISO date the run targets (e.g. "2026-08-04"). The scheduler
    # uses this for the "already ran today" idempotency check. NULL
    # for ad-hoc runs against a session_id without a date.
    date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    # JSON-encoded list[str] — the resolved enabled step keys
    # (e.g. ["session", "beats", "headless", ...]). Using the
    # SQLAlchemy JSON type so the dialect handles serialization
    # (TEXT under SQLite, JSONB under Postgres).
    enabled: Mapped[list] = mapped_column(JSON, default=list)
    force: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # pending | running | done | failed. App-level enum, kept as a
    # String for forward-compat (an "awaiting_approval" status can
    # be added later without a migration).
    status: Mapped[str] = mapped_column(
        String(16), default="pending", server_default="pending"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # JSON-encoded list[str] — ring buffer of the last 200 banner
    # lines for the live-log panel. TEXT for SQLite/Postgres
    # portability; the in-memory deque used to be the source of
    # truth for this, but a process restart wiped it.
    last_lines_json: Mapped[str] = mapped_column(Text, default="[]", server_default="[]")
    # 0.9.0 — process-alive marker. See class docstring for the
    # full story. ``server_default="1"`` so rows written by a code
    # path that bypasses the Python default (raw DDL in a debug
    # session, an old repo shim) still resolve to "live" without
    # an explicit write; the new boot-time sweep in
    # ``orchestrator.scheduler`` flips stale past-date rows to 0.
    live_today: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )

    __table_args__ = (
        # Hot path: "all runs for this session" (the live data
        # hook asks this when surfacing a session's pipeline state).
        Index("ix_pipeline_runs_session_id_created_at", "session_id", "created_at"),
        # Hot path: scheduler's per-day idempotency check
        # ("any done/running row for today's date?"). Partial
        # constraint would be cleaner but SQLite doesn't support
        # partial indexes on arbitrary expressions the same way,
        # so a plain composite index over (status, created_at) is
        # the portable compromise — the date filter still wins
        # because the scheduler passes an exact `date = today`.
        Index("ix_pipeline_runs_status_created_at", "status", "created_at"),
    )
