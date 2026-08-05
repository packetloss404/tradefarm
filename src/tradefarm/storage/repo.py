from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import cast

import structlog
from sqlalchemy import CursorResult, func, select, update
from sqlalchemy.exc import IntegrityError

from tradefarm.execution.virtual_book import VirtualBook
from tradefarm.runtime.clock import now_utc
from tradefarm.runtime.money import D
from tradefarm.runtime.session_context import current_session_id
from tradefarm.storage import journal  # re-exported for downstream callers
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent, PnlSnapshot, PipelineRun, Position, Trade

log = structlog.get_logger(__name__)

__all__ = [
    "upsert_agent",
    "record_trade",
    "record_fill_atomic",
    "snapshot_pnl",
    "sync_positions",
    "strategy_summary",
    "strategy_equity_timeseries",
    "get_all_agents_with_disabled",
    "set_agent_disabled",
    "set_agents_disabled_bulk",
    "get_disabled_agent_ids",
    "create_pipeline_run",
    "update_pipeline_run",
    "get_pipeline_run",
    "list_pipeline_runs",
    "list_pipeline_runs_for_date",
    "pipeline_run_with_terminal_state_for_date",
    "live_pipeline_run_for_date",
    "set_pipeline_run_live_today",
    "mark_runs_live_today_false_for_past_dates",
    "journal",
]


async def upsert_agent(
    agent_id: int, name: str, strategy: str, starting_capital: float | Decimal
) -> None:
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
        capital = D(starting_capital)
        session.add(
            Agent(
                id=agent_id,
                name=name,
                strategy=strategy,
                starting_capital=capital,
                cash=capital,
                status="waiting",
            )
        )
        await session.commit()


async def record_trade(
    agent_id: int,
    symbol: str,
    side: str,
    qty: float | Decimal,
    price: float | Decimal,
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
                qty=D(qty),
                price=D(price),
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


async def record_fill_atomic(
    agent_id: int,
    book: VirtualBook,
    symbol: str,
    side: str,
    qty: float | Decimal,
    price: float | Decimal,
    reason: str,
    broker_order_id: str | None = None,
) -> None:
    """Persist a Trade row AND re-sync this agent's positions in ONE transaction.

    Issue #8c: the in-tick fill path previously called ``record_trade`` then
    ``sync_positions`` in two separate ``SessionLocal()`` sessions. A crash
    between them left the DB with a trade row but stale positions (or vice
    versa). This commits both writes together — they land atomically or not
    at all.

    Dedupe semantics match ``record_trade`` (CLAUDE.md gotcha #7): a duplicate
    ``broker_order_id`` hits the UNIQUE constraint and we swallow the
    IntegrityError. In that case the fill was already recorded by a prior
    write, so we do NOT re-sync positions here — the original atomic write
    already persisted the matching position state, and the in-memory ``book``
    passed in is the source of truth the live caller keeps current regardless.
    ``None`` ``broker_order_id`` skips dedupe (SQLite treats NULLs as distinct).
    """
    async with SessionLocal() as session:
        try:
            session.add(
                Trade(
                    agent_id=agent_id,
                    symbol=symbol,
                    side=side,
                    qty=D(qty),
                    price=D(price),
                    reason=reason,
                    session_id=current_session_id(),
                    broker_order_id=broker_order_id,
                )
            )
            # Flush the Trade insert NOW so a duplicate broker_order_id raises
            # here (inside the try) rather than via the autoflush triggered by
            # the Position SELECT below — that autoflush would escape this
            # guard and surface as an unhandled IntegrityError.
            await session.flush()
            # Replace this agent's positions table with current book state, in
            # the same unit of work as the Trade insert.
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
        except IntegrityError:
            # UNIQUE(broker_order_id) — fill already recorded by an earlier
            # atomic write (optimistic-then-reconcile, or a restart replay).
            # The whole transaction (trade + position sync) rolls back; the
            # prior write's positions stand. Idempotent.
            await session.rollback()
            log.info("fill_already_recorded", broker_order_id=broker_order_id, symbol=symbol)


async def get_all_agents_with_disabled() -> list[dict]:
    """Return every agent row as a slim dict for the admin toggle list.

    Only the columns the admin UI needs are returned (``id``, ``name``,
    ``strategy``, ``disabled``, ``cash``); the cash is coerced to float at
    this JSON boundary (it's stored as Decimal / NUMERIC(20, 6)).
    Ordered by id so the UI is stable across polls.
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(Agent.id, Agent.name, Agent.strategy, Agent.disabled, Agent.cash).order_by(
                    Agent.id
                )
            )
        ).all()
    return [
        {
            "id": int(rid),
            "name": str(rname),
            "strategy": str(rstrat),
            "disabled": bool(rdisabled),
            "cash": float(rcash) if rcash is not None else 0.0,
        }
        for rid, rname, rstrat, rdisabled, rcash in rows
    ]


async def set_agent_disabled(agent_id: int, disabled: bool) -> None:
    """Flip the per-agent ``disabled`` flag.

    No-op (silently) when the agent id doesn't exist — the API layer is
    expected to validate the range before calling. SQLite/Postgres both
    treat ``0``/``1`` as falsy/truthy for the Boolean column.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(Agent).where(Agent.id == agent_id))
        ).scalar_one_or_none()
        if existing is None:
            return
        existing.disabled = bool(disabled)
        await session.commit()


async def set_agents_disabled_bulk(agent_ids: list[int], disabled: bool) -> list[int]:
    """Flip the ``disabled`` flag on a batch of agent ids.

    Returns the subset of ids that actually matched an agent row (any
    unknown ids are silently dropped — the API layer is expected to
    validate the range; this is a "best effort update what's there" path).
    """
    if not agent_ids:
        return []
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(Agent).where(Agent.id.in_(agent_ids))
                )
            )
            .scalars()
            .all()
        )
        for a in rows:
            a.disabled = bool(disabled)
        await session.commit()
        return [a.id for a in rows]


async def get_disabled_agent_ids() -> set[int]:
    """Return the set of agent ids that are currently disabled.

    Used by the orchestrator's tick to skip decisions for disabled agents
    without forcing a settings reload. The 100-row agents table is small
    enough that one SELECT per tick (every ~30s) is well within the
    per-tick budget.
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Agent.id).where(Agent.disabled.is_(True)))
        ).all()
    return {int(rid) for (rid,) in rows}


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


# ---------------------------------------------------------------------------
# VOD pipeline run state — DB-backed replacement for the in-memory _RUNS deque.
# The HTTP wrapper (``tradefarm.api.pipeline``) keeps a small in-process cache
# for hot reads; every write goes through here so a backend restart
# preserves the audit trail.
# ---------------------------------------------------------------------------


def _decode_lines(raw: str | None) -> list[str]:
    """Parse the JSON-encoded ring buffer from ``pipeline_runs.last_lines_json``.

    Tolerates the empty / malformed case (returns []) so a row that was
    inserted by a pre-1.0 schema (or via raw DDL during a debug session)
    never crashes the read path.
    """
    if not raw:
        return []
    try:
        out = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return out if isinstance(out, list) else []


def _encode_lines(lines: list[str]) -> str:
    """Serialise a list[str] into the JSON string the column stores.

    Defensive: a None input (caller passed no buffer) writes the
    empty-list encoding rather than NULL, so reads always see a
    valid JSON string.
    """
    return json.dumps(list(lines) if lines else [])


async def create_pipeline_run(run: PipelineRun, *, live_today: bool = True) -> None:
    """Insert a new pipeline run row.

    The row's ``id`` is set by the caller (the HTTP wrapper currently
    uses ``uuid4().hex[:12]`` to match the legacy in-memory id shape;
    the orchestrator's scheduler loop does the same). No dedupe here —
    a duplicate ``id`` will raise ``IntegrityError``, which is the
    caller's signal that they should generate a fresh id and retry.
    The ``enabled`` list is serialised to JSON by SQLAlchemy's ``JSON``
    column type. ``last_lines_json`` is taken as-is from the input
    row (the caller — ``api.pipeline.PipelineRun.to_row()`` — fills
    it from its in-memory ring buffer at the call site).

    ``live_today`` defaults to True. Every new run is "live" from
    its writer's POV; the boot-time sweep in
    ``orchestrator.scheduler`` flips stale past-date rows to False
    on a fresh process. Callers that already set the column on the
    input ``run`` row (e.g. an in-memory dataclass via ``to_row()``)
    can pass ``live_today=False`` to override the default — the
    explicit kwarg always wins over the input row's value.
    """
    async with SessionLocal() as session:
        # If the caller passed the in-memory dataclass (it has
        # ``last_lines``), translate to the column. If they passed
        # the SQLAlchemy row, ``last_lines_json`` is already there.
        last_lines_json = getattr(run, "last_lines_json", None)
        if last_lines_json is None and hasattr(run, "last_lines"):
            last_lines_json = _encode_lines(run.last_lines or [])
        # Same translation for the per-step timings roll-up. The
        # in-memory dataclass carries ``step_timings``; the column
        # is ``step_timings_json``. The caller is expected to
        # write the column directly if they're passing a SQLAlchemy
        # row.
        step_timings_json = getattr(run, "step_timings_json", None)
        if step_timings_json is None and hasattr(run, "step_timings"):
            step_timings_json = _encode_lines(run.step_timings or [])
        # Status defaults to "pending" via the model's server_default
        # + Python default — preserve whatever the caller set, defaulting
        # to "pending" if empty.
        status = (getattr(run, "status", None) or "pending")
        # Honour an explicit column on the input row first, then
        # the kwarg, then True. Most callers (the HTTP wrapper's
        # ``to_row()`` + the orchestrator's ``_kick_vod_run``) leave
        # the column unset and rely on the True default.
        incoming_live = getattr(run, "live_today", None)
        effective_live = live_today if incoming_live is None else bool(incoming_live)
        row = PipelineRun(
            id=run.id,
            session_id=run.session_id,
            date=run.date,
            enabled=list(getattr(run, "enabled", None) or []),
            force=bool(getattr(run, "force", False)),
            dry_run=bool(getattr(run, "dry_run", False)),
            status=status,
            created_at=getattr(run, "created_at", None) or now_utc(),
            started_at=getattr(run, "started_at", None),
            finished_at=getattr(run, "finished_at", None),
            error=getattr(run, "error", None),
            last_lines_json=last_lines_json or "[]",
            step_timings_json=step_timings_json,
            live_today=effective_live,
        )
        session.add(row)
        await session.commit()


async def update_pipeline_run(run_id: str, **fields: object) -> None:
    """Partial update of a pipeline run row.

    Recognised fields: ``status``, ``started_at``, ``finished_at``,
    ``error``, ``enabled``, ``force``, ``dry_run``, ``last_lines``.
    Anything else raises ``TypeError`` (mirrors the project's "no
    silent typos" style) so a renamed column is loud, not silent.

    ``last_lines`` is accepted as a list[str] and serialised through
    the JSON column; ``enabled`` is also serialised. ``started_at`` /
    ``finished_at`` accept ``datetime`` or ISO strings.
    """
    if not fields:
        return
    # Coerce the ring-buffer arg into the column shape. Doing it
    # outside the session loop keeps the hot path (one row update) cheap.
    if "last_lines" in fields:
        fields["last_lines_json"] = _encode_lines(fields.pop("last_lines"))  # type: ignore[arg-type]
    if "enabled" in fields:
        # JSON column coerces list → string under SQLite, so write the
        # JSON-encoded form explicitly for cross-dialect consistency.
        raw = fields["enabled"]
        if isinstance(raw, list):
            fields["enabled"] = list(raw)
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
        ).scalar_one_or_none()
        if existing is None:
            # Silent no-op: the scheduler / HTTP wrapper should treat an
            # unknown id as a stale write (the run was probably wiped
            # by a manual cleanup). Not raising keeps the per-step
            # retry loop robust to a half-deleted row.
            log.info("update_pipeline_run_not_found", run_id=run_id)
            return
        for k, v in fields.items():
            if not hasattr(existing, k):
                raise TypeError(f"PipelineRun has no column {k!r}")
            setattr(existing, k, v)
        await session.commit()


async def get_pipeline_run(run_id: str) -> PipelineRun | None:
    """Return the run row by id, or None if no such row.

    The shape returned is the SQLAlchemy model — callers that need a
    plain dict should call ``to_dict()`` on it (the api.pipeline layer
    already has a helper for this).
    """
    async with SessionLocal() as session:
        return (
            await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
        ).scalar_one_or_none()


async def list_pipeline_runs(*, limit: int = 20) -> list[PipelineRun]:
    """Return the most recent N runs, newest first.

    Mirrors the in-memory deque's bounded behaviour: the API surface
    only ever shows the last ``limit`` runs (default 20), so an old
    run that fell off the bottom of the cache is still queryable
    directly via ``get_pipeline_run``.
    """
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def list_pipeline_runs_for_date(date: str) -> list[PipelineRun]:
    """Return all run rows whose ``date`` column equals ``date`` (ISO).

    The orchestrator's daily scheduler uses this to compute the
    per-day idempotency check; the HTTP layer uses it for the live
    data hook ("show me today's run state"). Newest first.
    """
    async with SessionLocal() as session:
        rows = (
            (
                await session.execute(
                    select(PipelineRun)
                    .where(PipelineRun.date == date)
                    .order_by(PipelineRun.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
    return list(rows)


async def pipeline_run_with_terminal_state_for_date(date: str) -> PipelineRun | None:
    """Return the newest pipeline run for ``date`` whose status is
    ``done`` or ``failed`` — the per-day idempotency check the
    scheduler reads before kicking off a new run.

    Returns None if no such row exists (no run today, or every run
    today is still ``pending``/``running``). The status filter
    matters: a ``running`` row also satisfies the "don't double-fire"
    predicate via the broader call below.
    """
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(PipelineRun)
                .where(PipelineRun.date == date)
                .where(PipelineRun.status.in_(("done", "failed")))
                .order_by(PipelineRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def live_pipeline_run_for_date(date: str) -> PipelineRun | None:
    """Return the newest pipeline run for ``date`` whose ``live_today``
    flag is True — the post-0.9.0 per-day idempotency check the
    scheduler reads before kicking off a new run.

    After the boot-time sweep in ``orchestrator.scheduler`` runs,
    every past-date row from a previous process has ``live_today=False``
    (the previous process's "in flight" state is dead). A row with
    ``live_today=True`` for today's date therefore MUST be from the
    current process — the scheduler can skip without separately
    checking ``status in ('done', 'failed')`` or the
    ``status='running'`` in-flight path. Cleaner than the prior
    two-query check; see the 0.9.0 "scheduler power-loss race"
    entry in CHANGELOG.md for the full motivation.

    Returns None if no live row exists for the date. The newest-first
    ordering keeps the result stable when multiple rows exist
    (e.g. an HTTP-wrapper-fired ad-hoc run on the same day).
    """
    async with SessionLocal() as session:
        return (
            await session.execute(
                select(PipelineRun)
                .where(PipelineRun.date == date)
                .where(PipelineRun.live_today.is_(True))
                .order_by(PipelineRun.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


async def set_pipeline_run_live_today(run_id: str, value: bool) -> None:
    """Flip the ``live_today`` flag on a single run row.

    Silent no-op if the run id is unknown (the in-flight row may
    have been wiped by a manual cleanup, or this might be a
    stale write from a prior process's tail). The boot-time
    sweep in ``orchestrator.scheduler`` is the primary writer
    of False; this helper exists for ad-hoc admin operations
    (e.g. the operator decides to refire today's run and
    clears the marker) and for tests.

    Note: this is NOT the path the terminal-state path uses. The
    scheduler keeps ``live_today=True`` on terminal-state rows
    and lets the existing ``status`` filter do the
    "should I refire" work; ``live_today`` is purely the
    "is this from a still-running process" marker.
    """
    async with SessionLocal() as session:
        existing = (
            await session.execute(select(PipelineRun).where(PipelineRun.id == run_id))
        ).scalar_one_or_none()
        if existing is None:
            log.info("set_pipeline_run_live_today_not_found", run_id=run_id)
            return
        existing.live_today = bool(value)
        await session.commit()


async def mark_runs_live_today_false_for_past_dates(today_iso: str) -> int:
    """Flip ``live_today`` to False for every past-date run row.

    Called once per process boot from
    ``orchestrator.scheduler._boot_vod_scheduler`` BEFORE the
    scheduler task starts. A previous process that died mid-run
    left a ``live_today=True`` row at ``status='running'`` for
    some past date; this sweep marks every such row as
    "inherited from a dead process" so the new process's
    idempotency check (which filters on ``live_today=True``) can't
    be fooled by stale state.

    The filter is ``date != today_iso AND live_today = 1`` so
    today's rows are left untouched — a still-running row from
    a previous process for *today* is genuinely "in flight" and
    the new process should defer to it (or, if the new process
    wants to refire, the operator clears the marker via
    ``set_pipeline_run_live_today``).

    Returns the row count (mostly for tests / observability; the
    scheduler logs it on the way out).
    """
    async with SessionLocal() as session:
        # ORM-style `update()` construct + CursorResult cast. SQLAlchemy's
        # async `Result` stub doesn't expose `rowcount`; the underlying
        # sync `CursorResult` does. Cast is safe at runtime (the async
        # wrapper delegates to the sync cursor for row metadata).
        result = await session.execute(
            update(PipelineRun)
            .where(PipelineRun.date != today_iso)
            .where(PipelineRun.live_today.is_(True))
            .values(live_today=False)
        )
        await session.commit()
        cursor = cast(CursorResult, result)
        # CursorResult.rowcount is the row count of the last executed
        # statement on the connection; for an UPDATE that's the
        # matched/updated row count. SQLite returns matched rows (the
        # docs note the same for Postgres).
        return int(cursor.rowcount or 0)
