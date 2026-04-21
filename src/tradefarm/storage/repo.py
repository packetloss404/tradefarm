from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent, PnlSnapshot, Position, Trade


async def upsert_agent(agent_id: int, name: str, strategy: str, starting_capital: float) -> None:
    async with SessionLocal() as session:
        existing = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
        if existing is not None and existing.strategy != strategy:
            # Strategy reassignment on restart (e.g. LSTM model trained since last run).
            existing.strategy = strategy
            await session.commit()
            return
        if existing is None:
            session.add(Agent(
                id=agent_id, name=name, strategy=strategy,
                starting_capital=starting_capital, cash=starting_capital, status="waiting",
            ))
            await session.commit()


async def record_trade(agent_id: int, symbol: str, side: str, qty: float, price: float, reason: str) -> None:
    async with SessionLocal() as session:
        session.add(Trade(
            agent_id=agent_id, symbol=symbol, side=side, qty=qty, price=price, reason=reason,
        ))
        await session.commit()


async def snapshot_pnl(agent_id: int, book: VirtualBook, marks: dict[str, float]) -> None:
    async with SessionLocal() as session:
        session.add(PnlSnapshot(
            agent_id=agent_id,
            equity=book.equity(marks),
            realized_pnl=book.realized_pnl,
            unrealized_pnl=book.unrealized_pnl(marks),
        ))
        await session.commit()


async def sync_positions(agent_id: int, book: VirtualBook) -> None:
    """Replace this agent's positions table with current book state."""
    async with SessionLocal() as session:
        existing = (await session.execute(select(Position).where(Position.agent_id == agent_id))).scalars().all()
        for p in existing:
            await session.delete(p)
        for sym, vp in book.positions.items():
            if vp.qty != 0:
                session.add(Position(agent_id=agent_id, symbol=sym, qty=vp.qty, avg_price=vp.avg_price))
        await session.commit()


async def strategy_summary() -> list[dict]:
    """Per-strategy attribution: aggregates latest pnl snapshot per agent, then
    groups by strategy. 'today' is UTC (midnight UTC boundary)."""
    async with SessionLocal() as session:
        # Latest snapshot timestamp per agent
        latest = (
            select(PnlSnapshot.agent_id, func.max(PnlSnapshot.taken_at).label("ts"))
            .group_by(PnlSnapshot.agent_id)
            .subquery()
        )
        rows = (await session.execute(
            select(Agent.id, Agent.name, Agent.strategy,
                   PnlSnapshot.equity, PnlSnapshot.realized_pnl, PnlSnapshot.unrealized_pnl)
            .join(latest, latest.c.agent_id == Agent.id, isouter=True)
            .join(PnlSnapshot,
                  (PnlSnapshot.agent_id == latest.c.agent_id) & (PnlSnapshot.taken_at == latest.c.ts),
                  isouter=True)
        )).all()

        midnight_utc = datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time())
        trade_rows = (await session.execute(
            select(Agent.strategy, func.count(Trade.id))
            .join(Trade, Trade.agent_id == Agent.id)
            .where(Trade.executed_at >= midnight_utc)
            .group_by(Agent.strategy)
        )).all()
        trades_today_by_strat = {s: int(c) for s, c in trade_rows}

    by_strat: dict[str, dict] = {}
    for agent_id, name, strat, equity, rpnl, upnl in rows:
        bucket = by_strat.setdefault(strat, {
            "agents": [], "equity_total": 0.0, "realized": 0.0, "unrealized": 0.0,
        })
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
        out.append({
            "strategy": strat,
            "agent_count": len(agents),
            "realized_pnl_total": b["realized"],
            "unrealized_pnl_total": b["unrealized"],
            "equity_total": b["equity_total"],
            "trades_today": trades_today_by_strat.get(strat, 0),
            "win_rate": (wins / len(agents)) if agents else 0.0,
            "best_agent_name": best[0],
            "worst_agent_name": worst[0],
        })
    return out


async def strategy_equity_timeseries(days: int = 7) -> list[dict]:
    """For each (day, strategy), sum of each agent's last snapshot that day. UTC day boundary."""
    cutoff = datetime.now(timezone.utc).date() - timedelta(days=days)
    async with SessionLocal() as session:
        sub = (
            select(
                PnlSnapshot.agent_id,
                func.date(PnlSnapshot.taken_at).label("d"),
                func.max(PnlSnapshot.taken_at).label("ts"),
            )
            .where(func.date(PnlSnapshot.taken_at) >= cutoff)
            .group_by(PnlSnapshot.agent_id, func.date(PnlSnapshot.taken_at))
            .subquery()
        )
        rows = (await session.execute(
            select(sub.c.d, Agent.strategy, func.sum(PnlSnapshot.equity).label("equity"))
            .join(PnlSnapshot,
                  (PnlSnapshot.agent_id == sub.c.agent_id) & (PnlSnapshot.taken_at == sub.c.ts))
            .join(Agent, Agent.id == sub.c.agent_id)
            .group_by(sub.c.d, Agent.strategy)
            .order_by(sub.c.d, Agent.strategy)
        )).all()
    return [{"date": str(d), "strategy": s, "equity_total": float(e)} for d, s, e in rows]
