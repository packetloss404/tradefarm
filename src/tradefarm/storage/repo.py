from __future__ import annotations

from datetime import datetime, timedelta

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.runtime.clock import now_utc
from tradefarm.runtime.session_context import current_session_id
from tradefarm.storage import journal  # re-exported for downstream callers
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent, PnlSnapshot, Position, Trade

log = structlog.get_logger(__name__)

__all__ = [
    "upsert_agent",
    "record_trade",
    "snapshot_pnl",
    "sync_positions",
    "strategy_summary",
    "strategy_equity_timeseries",
    "journal",
]


async def upsert_agent(agent_id: int, name: str, strategy: str, starting_capital: float) -> None:
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if existing is not None:
            dirty = False
            if existing.strategy != strategy:
                # Strategy reassignment on restart (e.g. LSTM model trained since last run).
                existing.strategy = strategy
                dirty = True
            if existing.name != name:
                # Display-name refresh — names.py is the source of truth, so a
                # rename rule change should propagate to historical DB rows too.
                existing.name = name
                dirty = True
            if dirty:
                await session.commit()
            return
        session.add(
            Agent(
                id=agent_id,
                name=name,
                strategy=strategy,
                starting_capital=starting_capital,
                cash=starting_capital,
                status="waiting",
            )
        )
        await session.commit()


async def record_trade(
    agent_id: int,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    reason: str,
    broker_order_id: str | None = None,
) -> None:
    """Persist one Trade row.

    ``broker_order_id`` is written so the DB-level UNIQUE constraint
    (``uq_trades_broker_order_id``) becomes the restart-safe dedupe for
    reconciled/broker fills (CLAUDE.md gotcha #7). A second write with the
    same id hits that constraint; we swallow the IntegrityError and treat
    the trade as already recorded rather than raising. ``None`` (sim fills
    with no broker id, or callers that pass nothing) skips dedupe — SQLite
    treats NULLs as distinct under UNIQUE, so NULL ``broker_order_id`` rows
    are never deduped (matching db.py's partial index, which is scoped
    ``WHERE broker_order_id IS NOT NULL``).
    """
    async with SessionLocal() as session:
        session.add(
            Trade(
                agent_id=agent_id,
                symbol=symbol,
                side=side,
                qty=qty,
                price=price,
                reason=reason,
                session_id=current_session_id(),
                broker_order_id=broker_order_id,
            )
        )
        try:
            await session.commit()
        except IntegrityError:
            # UNIQUE(broker_order_id) violation — this fill was already
            # recorded (e.g. optimistic write then reconcile, or a
            # process restart replaying the reconcile path). Idempotent.
            await session.rollback()
            log.info("trade_already_recorded", broker_order_id=broker_order_id, symbol=symbol)


async def snapshot_pnl(agent_id: int, book: VirtualBook, marks: dict[str, float]) -> None:
    async with SessionLocal() as session:
        session.add(
            PnlSnapshot(
                agent_id=agent_id,
                equity=book.equity(marks),
                realized_pnl=book.realized_pnl,
                unrealized_pnl=book.unrealized_pnl(marks),
                session_id=current_session_id(),
            )
        )
        await session.commit()


async def sync_positions(agent_id: int, book: VirtualBook) -> None:
    """Replace this agent's positions table with current book state."""
    async with SessionLocal() as session:
        existing = (
            (await session.execute(select(Position).where(Position.agent_id == agent_id)))
            .scalars()
            .all()
        )
        for p in existing:
            await session.delete(p)
        for sym, vp in book.positions.items():
            if vp.qty != 0:
                session.add(
                    Position(agent_id=agent_id, symbol=sym, qty=vp.qty, avg_price=vp.avg_price)
                )
        await session.commit()


async def strategy_summary() -> list[dict]:
    """Per-strategy attribution: aggregates latest pnl snapshot per agent, then
    groups by strategy. 'today' is UTC (midnight UTC boundary).

    Filters out replay-session rows (session_id IS NOT NULL) so the live
    dashboard doesn't inflate after the operator runs `session.run`. The
    replay-aware REST paths short-circuit elsewhere via manifest reads."""
    async with SessionLocal() as session:
        # Latest LIVE snapshot timestamp per agent.
        latest = (
            select(PnlSnapshot.agent_id, func.max(PnlSnapshot.taken_at).label("ts"))
            .where(PnlSnapshot.session_id.is_(None))
            .group_by(PnlSnapshot.agent_id)
            .subquery()
        )
        rows = (
            await session.execute(
                select(
                    Agent.id,
                    Agent.name,
                    Agent.strategy,
                    PnlSnapshot.equity,
                    PnlSnapshot.realized_pnl,
                    PnlSnapshot.unrealized_pnl,
                )
                .join(latest, latest.c.agent_id == Agent.id, isouter=True)
                .join(
                    PnlSnapshot,
                    (PnlSnapshot.agent_id == latest.c.agent_id)
                    & (PnlSnapshot.taken_at == latest.c.ts),
                    isouter=True,
                )
            )
        ).all()

        midnight_utc = datetime.combine(now_utc().date(), datetime.min.time())
        trade_rows = (
            await session.execute(
                select(Agent.strategy, func.count(Trade.id))
                .join(Trade, Trade.agent_id == Agent.id)
                .where(Trade.executed_at >= midnight_utc)
                .where(Trade.session_id.is_(None))  # live only
                .group_by(Agent.strategy)
            )
        ).all()
        trades_today_by_strat = {s: int(c) for s, c in trade_rows}

    by_strat: dict[str, dict] = {}
    for agent_id, name, strat, equity, rpnl, upnl in rows:
        bucket = by_strat.setdefault(
            strat,
            {
                "agents": [],
                "equity_total": 0.0,
                "realized": 0.0,
                "unrealized": 0.0,
            },
        )
        eq = float(equity) if equity is not None else 0.0
        r = float(rpnl) if rpnl is not None else 0.0
        u = float(upnl) if upnl is not None else 0.0
        bucket["agents"].append((name, eq, r + u))
        bucket["equity_total"] += eq
        bucket["realized"] += r
        bucket["unrealized"] += u

    out: list[dict] = []
    for strat, b in by_strat.items():
        agents = b["agents"]
        wins = sum(1 for _, _, pnl in agents if pnl > 0)
        best = max(agents, key=lambda a: a[1]) if agents else (None, 0.0, 0.0)
        worst = min(agents, key=lambda a: a[1]) if agents else (None, 0.0, 0.0)
        out.append(
            {
                "strategy": strat,
                "agent_count": len(agents),
                "realized_pnl_total": b["realized"],
                "unrealized_pnl_total": b["unrealized"],
                "equity_total": b["equity_total"],
                "trades_today": trades_today_by_strat.get(strat, 0),
                "win_rate": (wins / len(agents)) if agents else 0.0,
                "best_agent_name": best[0],
                "worst_agent_name": worst[0],
            }
        )
    return out


async def strategy_equity_timeseries(days: int = 7) -> list[dict]:
    """For each (day, strategy), sum of each agent's last snapshot that day. UTC day boundary.

    Live-only (session_id IS NULL) — replay-session snapshots are
    excluded so a `session.run` doesn't contaminate the dashboard's
    multi-day chart."""
    cutoff = now_utc().date() - timedelta(days=days)
    async with SessionLocal() as session:
        sub = (
            select(
                PnlSnapshot.agent_id,
                func.date(PnlSnapshot.taken_at).label("d"),
                func.max(PnlSnapshot.taken_at).label("ts"),
            )
            .where(func.date(PnlSnapshot.taken_at) >= cutoff)
            .where(PnlSnapshot.session_id.is_(None))  # live only
            .group_by(PnlSnapshot.agent_id, func.date(PnlSnapshot.taken_at))
            .subquery()
        )
        rows = (
            await session.execute(
                select(sub.c.d, Agent.strategy, func.sum(PnlSnapshot.equity).label("equity"))
                .join(
                    PnlSnapshot,
                    (PnlSnapshot.agent_id == sub.c.agent_id) & (PnlSnapshot.taken_at == sub.c.ts),
                )
                .join(Agent, Agent.id == sub.c.agent_id)
                .group_by(sub.c.d, Agent.strategy)
                .order_by(sub.c.d, Agent.strategy)
            )
        ).all()
    return [{"date": str(d), "strategy": s, "equity_total": float(e)} for d, s, e in rows]
