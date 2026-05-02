from contextlib import asynccontextmanager
from datetime import date, timedelta

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from tradefarm.academy import (
    RANK_ORDER,
    compute_stats,
    eligible_rank,
    rank_tone,
)
from tradefarm.academy import promotions_repo
from tradefarm.academy import repo as academy_repo
from tradefarm.api.admin import router as admin_router
from tradefarm.api.backtest import router as backtest_router
from tradefarm.api.ws import router as ws_router
from tradefarm.config import settings
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT
from tradefarm.storage import journal, repo
from tradefarm.storage.db import SessionLocal, init_db
from tradefarm.storage.models import PnlSnapshot


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Phase 2: seed each agent's RiskManager with its persisted rank so the
    # first tick respects rank-gated caps. Missing entries default to intern.
    rank_map = await academy_repo.ranks_by_agent()
    orch = Orchestrator.build_default(rank_map=rank_map)
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
    # Web dashboard runs on 5179, stream-app dev on 5180, packaged Tauri
    # webview origin varies by platform (`http(s)://tauri.localhost` on
    # Windows, `tauri://localhost` on macOS/Linux). Use a regex to cover
    # every reasonable local origin without juggling a long allow-list.
    # This API is paper-trading-only and listens on 127.0.0.1; widening
    # CORS does not expose anything external.
    allow_origin_regex=r"^(https?://(localhost|127\.0\.0\.1)(:\d+)?|https?://tauri\.localhost|tauri://localhost)$",
    allow_credentials=False,
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
        # Phase 2: rank is read off the in-process RiskManager. Phase 4 will
        # update it via set_rank() + a rebuild hook; for now it matches DB.
        rank = getattr(a.risk, "rank", "intern")
        # Phase 3: surface the agent's pinned symbol (LSTM / LSTM+LLM agents)
        # so the frontend can ask /retrieval-preview about the right ticker.
        agent_symbol = getattr(a, "symbol", None)
        out.append({
            "id": a.state.id,
            "name": a.state.name,
            "strategy": a.state.strategy,
            "status": a.state.status,
            "rank": rank,
            "symbol": agent_symbol,
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


@app.get("/academy/ranks")
async def academy_ranks() -> dict:
    """Static-ish description of the rank system + live distribution. UI uses
    this for the header strip and the rank-section legend.
    """
    multipliers = {r: settings.rank_multiplier(r) for r in RANK_ORDER}
    distribution = await academy_repo.rank_distribution()
    ranks = [
        {
            "rank": r,
            "tone": rank_tone(r),
            "pip": r[0].upper(),
            "multiplier": multipliers[r],
            "base_cap_pct": BASE_MAX_POSITION_NOTIONAL_PCT,
            "effective_cap_pct": BASE_MAX_POSITION_NOTIONAL_PCT * multipliers[r],
        }
        for r in RANK_ORDER
    ]
    return {
        "ranks": ranks,
        "distribution": distribution,
        "thresholds": {
            "min_trades_junior": settings.academy_min_trades_junior,
            "min_trades_senior": settings.academy_min_trades_senior,
            "min_trades_principal": settings.academy_min_trades_principal,
            "min_win_rate_senior": settings.academy_min_win_rate_senior,
            "min_sharpe_principal": settings.academy_min_sharpe_principal,
            "min_weeks_active_principal": 2.0,
        },
    }


@app.get("/agents/{agent_id}/academy")
async def agent_academy(agent_id: int) -> dict:
    """Current rank + stats + thresholds-to-next for one agent."""
    current = await academy_repo.get_rank(agent_id)
    stats = await compute_stats(agent_id, starting_capital=settings.agent_starting_capital)
    next_eligible = eligible_rank(stats)
    idx = RANK_ORDER.index(current)
    next_rank = RANK_ORDER[idx + 1] if idx + 1 < len(RANK_ORDER) else None

    # Gap description — drives the plain-English tooltip in the UI.
    gaps: dict[str, float | int] = {}
    if next_rank == "junior":
        gaps["trades_needed"] = max(
            0, settings.academy_min_trades_junior - stats.n_closed_trades,
        )
    elif next_rank == "senior":
        gaps["trades_needed"] = max(
            0, settings.academy_min_trades_senior - stats.n_closed_trades,
        )
        gaps["win_rate_target"] = settings.academy_min_win_rate_senior
    elif next_rank == "principal":
        gaps["trades_needed"] = max(
            0, settings.academy_min_trades_principal - stats.n_closed_trades,
        )
        gaps["sharpe_target"] = settings.academy_min_sharpe_principal
        gaps["weeks_needed"] = max(0.0, 2.0 - stats.weeks_active)

    return {
        "agent_id": agent_id,
        "rank": current,
        "tone": rank_tone(current),
        "multiplier": settings.rank_multiplier(current),
        "effective_cap_pct": BASE_MAX_POSITION_NOTIONAL_PCT * settings.rank_multiplier(current),
        "stats": {
            "n_closed_trades": stats.n_closed_trades,
            "win_rate": stats.win_rate,
            "sharpe": stats.sharpe,
            "weeks_active": stats.weeks_active,
        },
        "eligible_rank": next_eligible,
        "next_rank": next_rank,
        "gaps": gaps,
    }


@app.post("/tick")
async def tick() -> dict:
    orch: Orchestrator = app.state.orchestrator
    return await orch.tick_once()


@app.post("/academy/evaluate")
async def academy_evaluate() -> dict:
    """Phase 4 — kick a curriculum pass on demand (admin "Run curriculum pass")."""
    from tradefarm.academy import curriculum
    orch: Orchestrator = app.state.orchestrator
    result = await curriculum.evaluate_all(orch)
    return result.to_dict()


@app.get("/academy/promotions")
async def academy_promotions(hours: int = 24, limit: int = 100) -> list[dict]:
    """Phase 4 — recent rank changes across all agents, newest first."""
    return await promotions_repo.recent(hours=hours, limit=limit)


@app.get("/agents/{agent_id}/promotions")
async def agent_promotions(agent_id: int, hours: int = 24 * 30) -> list[dict]:
    """Phase 4 — per-agent rank change log (default: last 30 days)."""
    return await promotions_repo.for_agent(agent_id, hours=hours)


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
    from tradefarm.orchestrator.scheduler import JOURNAL_COUNTERS
    return {
        "profit_ai": profit,
        "loss_ai": loss,
        "waiting_ai": waiting,
        "total_equity": total_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "last_tick_at": orch.last_tick_at.isoformat() if orch.last_tick_at is not None else None,
        "notes_this_tick": JOURNAL_COUNTERS.get("notes_this_tick", 0),
        "outcomes_this_tick": JOURNAL_COUNTERS.get("outcomes_this_tick", 0),
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


@app.get("/agents/{agent_id}/notes")
async def agent_notes(agent_id: int, limit: int = 20) -> list[dict]:
    """Newest-first journal notes for this agent. Resolved notes include
    outcome_realized_pnl / outcome_closed_at; open notes leave them null.
    """
    return await journal.recent_outcomes(agent_id, n=limit)


@app.get("/agents/{agent_id}/retrieval-preview")
async def agent_retrieval_preview(
    agent_id: int, symbol: str, k: int = 3,
) -> list[dict]:
    """Phase 3 — preview what the LSTM+LLM agent would see as "past similar
    setups" for ``(agent_id, symbol)``. Powers the frontend's "Drawing on"
    block; also handy for manual inspection.

    Honors ``academy_retrieval_enabled`` (returns [] when off).
    """
    from tradefarm.agents import retrieval
    examples = await retrieval.fetch(agent_id, symbol, k=k)
    return [ex.to_dict() for ex in examples]


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
