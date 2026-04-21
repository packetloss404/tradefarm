from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from tradefarm.api.admin import router as admin_router
from tradefarm.api.backtest import router as backtest_router
from tradefarm.api.ws import router as ws_router
from tradefarm.config import settings
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.storage import repo
from tradefarm.storage.db import SessionLocal, init_db
from tradefarm.storage.models import PnlSnapshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    orch = Orchestrator.build_default()
    await orch.persist_initial_state()
    orch.start_background()
    app.state.orchestrator = orch
    try:
        yield
    finally:
        await orch.stop_background()


app = FastAPI(title="TradeFarm", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5179", "http://127.0.0.1:5179"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ws_router)
app.include_router(admin_router)
app.include_router(backtest_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/llm/stats")
async def llm_stats() -> dict:
    """LLM call counter since boot — useful for estimating API spend."""
    from tradefarm.agents.lstm_llm_agent import LLM_SKIPS
    called = LLM_SKIPS["called"]
    skipped = LLM_SKIPS["count"]
    total = called + skipped
    return {
        "called": called,
        "skipped_low_confidence": skipped,
        "total_decisions": total,
        "skip_rate": (skipped / total) if total else 0.0,
        "threshold": settings.llm_min_confidence,
    }


@app.get("/agents")
async def list_agents() -> list[dict]:
    orch: Orchestrator = app.state.orchestrator
    marks = orch.last_marks
    out = []
    for a in orch.agents:
        book = a.state.book
        equity = book.equity(marks)
        last_lstm = getattr(a, "last_lstm", None) or getattr(a, "last_prediction", None)
        last_decision = None
        if (d := getattr(a, "last_decision", None)) is not None:
            last_decision = {
                "bias": d.bias,
                "predictive": d.predictive,
                "stance": d.stance,
                "size_pct": d.size_pct,
                "reason": d.reason,
            }
        out.append({
            "id": a.state.id,
            "name": a.state.name,
            "strategy": a.state.strategy,
            "status": a.state.status,
            "cash": book.cash,
            "equity": equity,
            "realized_pnl": book.realized_pnl,
            "unrealized_pnl": book.unrealized_pnl(marks),
            "positions": {
                s: {
                    "qty": p.qty,
                    "avg_price": p.avg_price,
                    "mark": marks.get(s, p.avg_price),
                }
                for s, p in book.positions.items() if p.qty
            },
            "last_lstm": last_lstm,
            "last_decision": last_decision,
        })
    return out


@app.post("/tick")
async def tick() -> dict:
    orch: Orchestrator = app.state.orchestrator
    return await orch.tick_once()


@app.get("/account")
async def account() -> dict:
    orch: Orchestrator = app.state.orchestrator
    marks = orch.last_marks
    profit = sum(1 for a in orch.agents if a.state.status == "profit")
    loss = sum(1 for a in orch.agents if a.state.status == "loss")
    waiting = sum(1 for a in orch.agents if a.state.status == "waiting")
    total_equity = sum(a.state.book.equity(marks) for a in orch.agents)
    realized = sum(a.state.book.realized_pnl for a in orch.agents)
    unrealized = sum(a.state.book.unrealized_pnl(marks) for a in orch.agents)
    return {
        "profit_ai": profit,
        "loss_ai": loss,
        "waiting_ai": waiting,
        "total_equity": total_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "last_tick_at": orch.last_tick_at.isoformat() if orch.last_tick_at is not None else None,
    }


@app.get("/pnl/daily")
async def pnl_daily(days: int = 30) -> list[dict]:
    """Aggregate equity per agent's last snapshot per day, summed across agents,
    expressed as % return vs starting capital."""
    cutoff = date.today() - timedelta(days=days)
    async with SessionLocal() as session:
        # Latest snapshot per (agent, day)
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
        rows = (
            await session.execute(
                select(
                    sub.c.d,
                    func.sum(PnlSnapshot.equity).label("equity"),
                )
                .join(sub, (PnlSnapshot.agent_id == sub.c.agent_id) & (PnlSnapshot.taken_at == sub.c.ts))
                .group_by(sub.c.d)
                .order_by(sub.c.d)
            )
        ).all()

    orch: Orchestrator = app.state.orchestrator
    starting_total = len(orch.agents) * 1000.0
    return [
        {
            "date": str(r.d),
            "equity": float(r.equity),
            "pnl_pct": (float(r.equity) - starting_total) / starting_total * 100,
        }
        for r in rows
    ]


@app.get("/pnl/by-strategy")
async def pnl_by_strategy() -> list[dict]:
    return await repo.strategy_summary()


@app.get("/pnl/by-strategy/timeseries")
async def pnl_by_strategy_timeseries(days: int = 7) -> list[dict]:
    return await repo.strategy_equity_timeseries(days)


@app.get("/agents/{agent_id}/trades")
async def agent_trades(agent_id: int, limit: int = 20) -> list[dict]:
    from tradefarm.storage.models import Trade
    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Trade)
            .where(Trade.agent_id == agent_id)
            .order_by(Trade.executed_at.desc())
            .limit(limit)
        )).scalars().all()
    return [
        {
            "id": t.id,
            "symbol": t.symbol,
            "side": t.side,
            "qty": t.qty,
            "price": t.price,
            "executed_at": t.executed_at.isoformat() if t.executed_at else None,
            "reason": t.reason,
        }
        for t in rows
    ]


@app.get("/orders")
async def list_orders(limit: int = 25) -> list[dict]:
    """Recent broker orders. Empty list when EXECUTION_MODE=simulated."""
    if settings.execution_mode != "alpaca_paper":
        return []
    orch: Orchestrator = app.state.orchestrator
    broker = orch.broker
    if not hasattr(broker, "get_orders"):
        return []
    # Pull last 24h of orders; trim to `limit`.
    since = (date.today() - timedelta(days=1)).isoformat() + "T00:00:00+00:00"
    try:
        orders = broker.get_orders(since)
    except Exception:
        return []
    orders.sort(key=lambda o: o.get("submitted_at") or "", reverse=True)
    out = []
    for o in orders[:limit]:
        cid = o.get("client_order_id") or ""
        from tradefarm.execution.alpaca_broker import AlpacaBroker
        agent_id = AlpacaBroker.parse_agent_id(cid)
        out.append({**o, "agent_id": agent_id})
    return out
