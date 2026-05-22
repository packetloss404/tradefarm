from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
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
from tradefarm.api.audience import router as audience_router
from tradefarm.api.backtest import router as backtest_router
from tradefarm.api.market_clock import router as market_clock_router
from tradefarm.api.recap import router as recap_router
from tradefarm.api.stream_control import router as stream_control_router
from tradefarm.api.ws import router as ws_router
from tradefarm.config import settings
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT
from tradefarm.session import replay_query
from tradefarm.storage import journal, repo
from tradefarm.storage.db import SessionLocal, init_db
from tradefarm.storage.models import PnlSnapshot


def _parse_replay_at(at: str | None) -> datetime | None:
    """Common parsing for the ?at= query param. Accepts ISO 8601 with
    timezone or trailing Z; raises 400 on anything else."""
    if at is None:
        return None
    try:
        return replay_query.parse_iso(at)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid `at`: {exc}") from exc


def _replay_static_meta(orch: Orchestrator) -> tuple[dict[int, dict], list[dict]]:
    """Pull static per-agent metadata (strategy, rank, symbol pin) off
    the orchestrator so replay endpoints can populate fields the
    manifest doesn't carry. Returns (by_id_map, silent_roster_list) —
    the latter so the diorama still shows 100 dots for agents that
    didn't trade in this session."""
    meta_by_id: dict[int, dict] = {}
    roster: list[dict] = []
    for a in orch.agents:
        meta = {
            "id": a.state.id,
            "name": a.state.name,
            "strategy": a.state.strategy,
            "rank": getattr(a.risk, "rank", "intern"),
            "symbol": getattr(a, "symbol", None),
            "starting_capital": getattr(a.state, "starting_capital", 1000.0),
        }
        meta_by_id[a.state.id] = meta
        roster.append(meta)
    return meta_by_id, roster


def _load_replay_manifest(session_id: str) -> dict:
    """Read the on-disk manifest for `session_id`; raise 404 if absent.
    Validates session_id against the safe-id regex before touching disk
    so path-traversal attempts get a 400 instead of leaking the resolved
    file path through a 404 detail."""
    try:
        replay_query._require_safe_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        return replay_query.load_manifest(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"no manifest for session {session_id!r}"
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Phase 2: seed each agent's RiskManager with its persisted rank so the
    # first tick respects rank-gated caps. Missing entries default to intern.
    rank_map = await academy_repo.ranks_by_agent()
    orch = Orchestrator.build_default(rank_map=rank_map)
    # Audit fix (U): wrap the start sequence so a partial init
    # (e.g. persist_initial_state DB error, start_background failing
    # to spawn a task) cleans up instead of leaving orphaned background
    # tasks + an installed broadcast arbiter on the next reload. Without
    # this the lifespan's `finally: stop_background` only ran after a
    # successful yield, so any startup exception leaked everything.
    try:
        await orch.persist_initial_state()
        orch.start_background()
    except Exception:
        # Best-effort teardown of anything that managed to start.
        try:
            await orch.stop_background()
        except Exception:
            pass
        raise
    app.state.orchestrator = orch
    try:
        yield
    finally:
        await orch.stop_background()


app = FastAPI(title="TradeFarm", lifespan=lifespan)


# Audit fix (H28): optional shared-secret middleware. When
# settings.api_shared_secret is set, every state-mutating endpoint
# (POST, PUT, PATCH, DELETE) requires the `X-TradeFarm-Token` header.
# Read-only GETs stay open so the dashboard's polling doesn't require
# threading the secret through every fetch (it can in Phase 2; this
# round is "lock the destructive surface"). /health and /market/clock
# are also exempted. When the secret isn't set, behavior is unchanged
# (open, as before).
from fastapi import Request  # noqa: E402  (kept beside the middleware that uses it)
from fastapi.responses import JSONResponse as _JSONResponse  # noqa: E402


_AUTH_EXEMPT_PREFIXES = ("/health", "/market/clock", "/openapi", "/docs", "/redoc")


@app.middleware("http")
async def _shared_secret_guard(request: Request, call_next):
    secret = getattr(settings, "api_shared_secret", "")
    if not secret:
        return await call_next(request)
    path = request.url.path
    # Always-open: read-only + introspection paths.
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return await call_next(request)
    if any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES):
        return await call_next(request)
    presented = request.headers.get("x-tradefarm-token", "")
    # Constant-time compare so a timing attack can't probe the secret.
    import hmac

    if not hmac.compare_digest(presented.encode("utf-8"), secret.encode("utf-8")):
        return _JSONResponse(
            status_code=401,
            content={"detail": "invalid or missing X-TradeFarm-Token"},
        )
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    # Web dashboard runs on 5179, stream-app dev on 5180, packaged Tauri
    # webview origin varies by platform (`http(s)://tauri.localhost` on
    # Windows, `tauri://localhost` on macOS/Linux).
    #
    # We also allow private/LAN IPv4 ranges so the split-machine topology
    # works (dashboard on workstation, backend on a broadcast VM running
    # `npm run broadcast`). The API is paper-trading-only and binds the LAN
    # interface only when explicitly run as the broadcast flavor.
    allow_origin_regex=(
        r"^("
        r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
        r"|https?://10(\.\d{1,3}){3}(:\d+)?"
        r"|https?://192\.168(\.\d{1,3}){2}(:\d+)?"
        r"|https?://172\.(1[6-9]|2\d|3[01])(\.\d{1,3}){2}(:\d+)?"
        r"|https?://tauri\.localhost"
        r"|tauri://localhost"
        r")$"
    ),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(ws_router)
app.include_router(admin_router)
app.include_router(backtest_router)
app.include_router(market_clock_router)
app.include_router(stream_control_router)
app.include_router(audience_router)
app.include_router(recap_router)


@app.get("/metrics", response_class=PlainTextResponse)
async def metrics(request: Request) -> str:
    """Prometheus-compatible text exposition of the counters the
    operator most often wants to graph: tick rate, LLM cost, error
    rate, broker activity.

    Round-5 audit fix (CC): observability beyond log scraping. Wire
    a Prometheus scraper at this URL with a 30s interval. No labels
    yet — flat counters and gauges. Add labels as use cases appear.
    """
    from tradefarm.agents.lstm_llm_agent import LLM_SKIPS
    from tradefarm.orchestrator.scheduler import JOURNAL_COUNTERS
    from tradefarm.runtime.llm_budget import snapshot as llm_snapshot

    orch = getattr(request.app.state, "orchestrator", None)
    last_tick_ts = 0.0
    if orch is not None and orch.last_tick_at is not None:
        last_tick_ts = orch.last_tick_at.to_pydatetime().timestamp()

    llm = llm_snapshot()
    lines: list[str] = [
        "# HELP tradefarm_last_tick_timestamp_seconds Unix epoch of last completed tick",
        "# TYPE tradefarm_last_tick_timestamp_seconds gauge",
        f"tradefarm_last_tick_timestamp_seconds {last_tick_ts}",
        "# HELP tradefarm_llm_calls_total LLM calls actually made (across all agents)",
        "# TYPE tradefarm_llm_calls_total counter",
        f"tradefarm_llm_calls_total {LLM_SKIPS.get('called', 0)}",
        "# HELP tradefarm_llm_skips_total LLM calls skipped by confidence/budget gate",
        "# TYPE tradefarm_llm_skips_total counter",
        f"tradefarm_llm_skips_total {LLM_SKIPS.get('count', 0)}",
        "# HELP tradefarm_llm_budget_spent_usd Today's LLM spend (USD, UTC day)",
        "# TYPE tradefarm_llm_budget_spent_usd gauge",
        f"tradefarm_llm_budget_spent_usd {llm['usd']}",
        "# HELP tradefarm_llm_budget_blocked_total Calls refused because daily budget exhausted",
        "# TYPE tradefarm_llm_budget_blocked_total counter",
        f"tradefarm_llm_budget_blocked_total {llm['blocked']}",
        "# HELP tradefarm_notes_this_tick Journal notes written in the most recent tick",
        "# TYPE tradefarm_notes_this_tick gauge",
        f"tradefarm_notes_this_tick {JOURNAL_COUNTERS.get('notes_this_tick', 0)}",
        "# HELP tradefarm_outcomes_this_tick Stamped outcomes in the most recent tick",
        "# TYPE tradefarm_outcomes_this_tick gauge",
        f"tradefarm_outcomes_this_tick {JOURNAL_COUNTERS.get('outcomes_this_tick', 0)}",
    ]
    return "\n".join(lines) + "\n"


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness check — always 200 if the process is up.
    The lifespan + uvicorn already give a coarse signal; this exists
    so an external load balancer can probe a sub-millisecond endpoint."""
    return {"status": "ok"}


@app.get("/readiness")
async def readiness(request: Request) -> dict[str, Any]:
    """Readiness check — passes only when the system is actually
    serving correctly: DB reachable, orchestrator started, last tick
    within the expected window. Use this from supervisors (uptime
    monitors, k8s readinessProbe, AWS ELB target health).

    Returns 200 with details on success; 503 (Service Unavailable)
    with a `failed_checks` list on degradation."""
    checks: dict[str, Any] = {}
    ok = True

    # 1. DB connectivity.
    try:
        from sqlalchemy import text

        async with SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as e:  # noqa: BLE001
        checks["db"] = f"error: {type(e).__name__}: {str(e)[:120]}"
        ok = False

    # 2. Orchestrator wired + alive.
    orch = getattr(request.app.state, "orchestrator", None)
    if orch is None:
        checks["orchestrator"] = "not initialized"
        ok = False
    else:
        # Tick freshness vs configured interval (allow 3× as cushion).
        last_tick = getattr(orch, "last_tick_at", None)
        interval = getattr(settings, "auto_tick_interval_sec", 0)
        if interval <= 0:
            checks["orchestrator"] = "ok (auto-tick disabled)"
        elif last_tick is None:
            checks["orchestrator"] = "no tick yet"
            # Don't fail readiness on this — first tick can take a minute.
        else:
            from datetime import datetime, timezone

            age_sec = (
                datetime.now(timezone.utc) - last_tick.to_pydatetime().astimezone(timezone.utc)
            ).total_seconds()
            checks["orchestrator"] = {
                "last_tick_sec_ago": round(age_sec, 1),
                "interval_sec": interval,
            }
            if age_sec > interval * 3:
                checks["orchestrator"] = {
                    **checks["orchestrator"],
                    "status": "stale",
                }
                ok = False

    # 3. Scheduler task alive (if started).
    if orch is not None and orch._task is not None:
        if orch._task.done():
            checks["scheduler_task"] = "dead"
            ok = False
        else:
            checks["scheduler_task"] = "alive"

    payload: dict[str, Any] = {"ok": ok, "checks": checks}
    if not ok:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail=payload)
    return payload


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
async def list_agents(
    at: str | None = Query(None, description="ISO timestamp for historical state (replay mode)."),
    session_id: str | None = Query(
        None, description="Session manifest to read from (replay mode)."
    ),
) -> list[dict]:
    orch: Orchestrator = app.state.orchestrator
    # Replay path: fold the manifest's events up to `at` and shape the
    # response so the static-meta (strategy/rank) comes from the live
    # orchestrator and the dynamic state (positions/cash/PnL) comes from
    # the manifest.
    if session_id is not None:
        at_dt = _parse_replay_at(at)
        manifest = _load_replay_manifest(session_id)
        if at_dt is None:
            at_dt = replay_query.parse_iso(manifest.get("ended_at") or manifest["started_at"])
        snaps, marks = replay_query.fold_to(manifest, at_dt)
        meta_by_id, roster = _replay_static_meta(orch)
        return replay_query.agents_payload(
            snaps,
            marks,
            static_meta_by_id=meta_by_id,
            include_silent=roster,
        )
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
        out.append(
            {
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
                    for s, p in book.positions.items()
                    if p.qty
                },
                "last_lstm": last_lstm,
                "last_decision": last_decision,
            }
        )
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
            0,
            settings.academy_min_trades_junior - stats.n_closed_trades,
        )
    elif next_rank == "senior":
        gaps["trades_needed"] = max(
            0,
            settings.academy_min_trades_senior - stats.n_closed_trades,
        )
        gaps["win_rate_target"] = settings.academy_min_win_rate_senior
    elif next_rank == "principal":
        gaps["trades_needed"] = max(
            0,
            settings.academy_min_trades_principal - stats.n_closed_trades,
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
async def account(
    at: str | None = Query(None, description="ISO timestamp for historical state (replay mode)."),
    session_id: str | None = Query(
        None, description="Session manifest to read from (replay mode)."
    ),
) -> dict:
    orch: Orchestrator = app.state.orchestrator
    if session_id is not None:
        at_dt = _parse_replay_at(at)
        manifest = _load_replay_manifest(session_id)
        if at_dt is None:
            at_dt = replay_query.parse_iso(manifest.get("ended_at") or manifest["started_at"])
        snaps, marks = replay_query.fold_to(manifest, at_dt)
        silent = max(0, len(orch.agents) - len(snaps))
        return replay_query.account_payload(
            snaps,
            marks,
            silent_agent_count=silent,
            last_tick_at=at_dt.isoformat(),
            starting_capital=float(getattr(settings, "agent_starting_capital", 1000.0)),
        )
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
        # Latest snapshot per (agent, day). Audit fix: live-only —
        # exclude replay-tagged snapshots so a session.run doesn't
        # double-stack that day's totals on the dashboard chart.
        sub = (
            select(
                PnlSnapshot.agent_id,
                func.date(PnlSnapshot.taken_at).label("d"),
                func.max(PnlSnapshot.taken_at).label("ts"),
            )
            .where(
                func.date(PnlSnapshot.taken_at) >= cutoff,
                PnlSnapshot.session_id.is_(None),
            )
            .group_by(PnlSnapshot.agent_id, func.date(PnlSnapshot.taken_at))
            .subquery()
        )
        rows = (
            await session.execute(
                select(
                    sub.c.d,
                    func.sum(PnlSnapshot.equity).label("equity"),
                )
                .join(
                    sub,
                    (PnlSnapshot.agent_id == sub.c.agent_id) & (PnlSnapshot.taken_at == sub.c.ts),
                )
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
async def agent_trades(
    agent_id: int,
    limit: int = 20,
    at: str | None = Query(None, description="ISO timestamp for historical trades (replay mode)."),
    session_id: str | None = Query(
        None, description="Session manifest to read from (replay mode)."
    ),
) -> list[dict]:
    if session_id is not None:
        at_dt = _parse_replay_at(at)
        manifest = _load_replay_manifest(session_id)
        if at_dt is None:
            at_dt = replay_query.parse_iso(manifest.get("ended_at") or manifest["started_at"])
        return replay_query.trades_for_agent(manifest, agent_id, at_dt, limit=limit)
    from tradefarm.storage.models import Trade

    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(Trade)
                    .where(
                        Trade.agent_id == agent_id,
                        # Audit fix: live trade-list excludes replay-tagged rows
                        # so the dashboard doesn't mix today's live fills with
                        # any prior `session.run`.
                        Trade.session_id.is_(None),
                    )
                    .order_by(Trade.executed_at.desc())
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
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
    agent_id: int,
    symbol: str,
    k: int = 3,
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
        # Round-5: broker.get_orders is async post-Y migration.
        # SimulatedBroker doesn't have get_orders; the hasattr guard
        # above already filters it out.
        orders = await broker.get_orders(since)
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
