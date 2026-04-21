from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    strategy: Mapped[str] = mapped_column(String(64))
    starting_capital: Mapped[float] = mapped_column(Float)
    cash: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(16), default="waiting")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    # Phase 2 (Agent Academy): rank-gated capital. `server_default` ensures
    # rows inserted by older code paths (or `SELECT *` over pre-Phase-2 data)
    # resolve to "intern" without a migration. `rank_updated_at` stays NULL
    # until Phase 4's curriculum flips a rank.
    rank: Mapped[str] = mapped_column(
        String(16), default="intern", server_default="intern",
    )
    rank_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    positions: Mapped[list["Position"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    trades: Mapped[list["Trade"]] = relationship(back_populates="agent", cascade="all, delete-orphan")


class Position(Base):
    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    qty: Mapped[float] = mapped_column(Float)
    avg_price: Mapped[float] = mapped_column(Float)
    opened_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agent: Mapped[Agent] = relationship(back_populates="positions")


class Trade(Base):
    __tablename__ = "trades"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(8))
    qty: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    executed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    reason: Mapped[str] = mapped_column(String(256), default="")

    agent: Mapped[Agent] = relationship(back_populates="trades")


class PnlSnapshot(Base):
    __tablename__ = "pnl_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    equity: Mapped[float] = mapped_column(Float)
    realized_pnl: Mapped[float] = mapped_column(Float)
    unrealized_pnl: Mapped[float] = mapped_column(Float)
    taken_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


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
    outcome_realized_pnl: Mapped[float | None] = mapped_column(Float, nullable=True)
    outcome_closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


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
