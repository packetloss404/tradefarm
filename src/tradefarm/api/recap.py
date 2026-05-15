"""Recap v2 — end-of-day highlight reel aggregator.

Single REST endpoint that assembles the day's highlights into one structured
JSON response. The stream's ``RecapScene`` renders a 30-second card sequence
from this payload; the dashboard's "Closing Recap" macro also pokes it.

Shape contract (see Recap v2 ticket / frontend agent):

    {
      "date": "YYYY-MM-DD",                 # ET calendar date
      "session_pnl_pct": float,             # roster equity vs starting cap, %
      "session_total_equity": float,        # current total roster equity
      "total_fills": int,                   # count of Trade rows today
      "biggest_fill": {...} | None,         # largest |notional| fill today
      "top_winners": [{...}, ...],          # up to 3 best CLOSED outcomes
      "biggest_loss": {...} | None,         # worst CLOSED outcome (skip if >= 0)
      "promotions": [{...}, ...],           # rank-up events today
      "predictions": [{...}, ...],          # pick-winner + spy-direction
    }

The aggregator is split into one helper per section so unit tests can hit
each without spinning up the full app. ``build_recap`` is the assembler;
``GET /recap/today`` just wires the live orchestrator + DB session in.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tradefarm.academy import RANK_ORDER
from tradefarm.academy import promotions_repo
from tradefarm.config import settings
from tradefarm.market.hours import ET
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import AgentNote, Trade

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/recap", tags=["recap"])


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _today_et_bounds() -> tuple[datetime, datetime]:
    """Return (start, end) of the current ET trading day as UTC datetimes.

    ``start`` is midnight America/New_York for the local calendar date
    (handles DST automatically); ``end`` is the current UTC instant. Both
    are returned as timezone-aware UTC datetimes ready to feed SQLAlchemy
    filters on ``Trade.executed_at`` / ``AgentNote.outcome_closed_at``.
    """
    now_et = datetime.now(tz=ET)
    midnight_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = midnight_et.astimezone(timezone.utc)
    end_utc = datetime.now(timezone.utc)
    return start_utc, end_utc


def _iso_utc(dt: datetime | None) -> str | None:
    """Format ``dt`` as an ISO-8601 string with a Z suffix (UTC).

    SQLite returns naive datetimes for ``server_default=func.now()`` columns.
    We treat those as already-UTC (which they are, per SQLAlchemy's NOW()
    semantics on aiosqlite) and append Z. Aware datetimes are converted
    to UTC first.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        # SQLite-naive: already UTC by convention. Append Z.
        return dt.replace(microsecond=0).isoformat() + "Z"
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _strip_naive(dt: datetime) -> datetime:
    """Return a *naive* UTC datetime for DB-filter comparisons.

    SQLAlchemy on aiosqlite stores ``server_default=func.now()`` columns as
    naive UTC. To avoid `cannot compare naive and aware` errors when filtering
    by a tz-aware ``start_utc``, strip the tzinfo before binding the param.
    """
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _agent_name_lookup(orchestrator: Any) -> dict[int, str]:
    """Mirror ``list_agents``'s name resolution off the live orchestrator."""
    out: dict[int, str] = {}
    if orchestrator is None:
        return out
    for a in getattr(orchestrator, "agents", []) or []:
        state = getattr(a, "state", None)
        if state is None:
            continue
        out[state.id] = state.name
    return out


# ---------------------------------------------------------------------------
# Section aggregators.
# ---------------------------------------------------------------------------


async def _biggest_fill_and_count(
    session_factory: async_sessionmaker,
    start_utc: datetime,
    end_utc: datetime,
    names: dict[int, str],
) -> tuple[dict[str, Any] | None, int]:
    """Return (biggest_fill_payload | None, total_fills_count)."""
    start_naive = _strip_naive(start_utc)
    end_naive = _strip_naive(end_utc)
    async with session_factory() as session:
        # Total fills today.
        total = (await session.execute(
            select(func.count(Trade.id)).where(
                Trade.executed_at >= start_naive,
                Trade.executed_at <= end_naive,
            )
        )).scalar_one()
        # Biggest by |qty * price|.
        notional_expr = func.abs(Trade.qty * Trade.price)
        row = (await session.execute(
            select(Trade)
            .where(
                Trade.executed_at >= start_naive,
                Trade.executed_at <= end_naive,
            )
            .order_by(notional_expr.desc(), Trade.id.desc())
            .limit(1)
        )).scalar_one_or_none()

    if row is None:
        return None, int(total or 0)

    notional = abs(float(row.qty) * float(row.price))
    payload: dict[str, Any] = {
        "agent_id": row.agent_id,
        "agent_name": names.get(row.agent_id),
        "symbol": row.symbol,
        "side": row.side,
        "qty": float(row.qty),
        "price": float(row.price),
        "notional": notional,
        "at": _iso_utc(row.executed_at),
    }
    return payload, int(total or 0)


async def _winners_and_loss(
    session_factory: async_sessionmaker,
    start_utc: datetime,
    end_utc: datetime,
    names: dict[int, str],
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Return (top_winners[:3], biggest_loss | None) from stamped notes."""
    start_naive = _strip_naive(start_utc)
    end_naive = _strip_naive(end_utc)
    async with session_factory() as session:
        # Top winners: outcome_realized_pnl > 0, descending. We explicitly
        # exclude zero/negative outcomes — a "winners podium" with a loss
        # in it reads wrong on stream.
        winners_rows = (await session.execute(
            select(AgentNote)
            .where(
                AgentNote.outcome_realized_pnl.is_not(None),
                AgentNote.outcome_realized_pnl > 0,
                AgentNote.outcome_closed_at >= start_naive,
                AgentNote.outcome_closed_at <= end_naive,
            )
            .order_by(AgentNote.outcome_realized_pnl.desc(), AgentNote.id.desc())
            .limit(3)
        )).scalars().all()

        # Biggest loss: most-negative single closed outcome (skip if pnl >= 0).
        loss_row = (await session.execute(
            select(AgentNote)
            .where(
                AgentNote.outcome_realized_pnl.is_not(None),
                AgentNote.outcome_closed_at >= start_naive,
                AgentNote.outcome_closed_at <= end_naive,
            )
            .order_by(AgentNote.outcome_realized_pnl.asc(), AgentNote.id.asc())
            .limit(1)
        )).scalar_one_or_none()

    winners = [
        {
            "agent_id": r.agent_id,
            "agent_name": names.get(r.agent_id),
            "realized_pnl": float(r.outcome_realized_pnl or 0.0),
            "symbol": r.symbol,
        }
        for r in winners_rows
    ]

    biggest_loss: dict[str, Any] | None = None
    if loss_row is not None and (loss_row.outcome_realized_pnl or 0.0) < 0:
        biggest_loss = {
            "agent_id": loss_row.agent_id,
            "agent_name": names.get(loss_row.agent_id),
            "realized_pnl": float(loss_row.outcome_realized_pnl or 0.0),
            "symbol": loss_row.symbol,
        }
    return winners, biggest_loss


async def _promotions_today(
    start_utc: datetime,
    end_utc: datetime,
) -> list[dict[str, Any]]:
    """Rank-ups today (skip demotions). Uses ``promotions_repo.recent``.

    ``recent`` returns rows sorted newest-first. We filter to today's ET
    window and to events where ``to_rank`` is *higher* than ``from_rank``
    per ``RANK_ORDER``.
    """
    # 36 hours covers any prior-session promotions that might still be inside
    # the ET-midnight window (e.g. just-after-midnight ET when UTC is ~04:00).
    rows = await promotions_repo.recent(hours=36, limit=200)
    rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
    out: list[dict[str, Any]] = []
    for r in rows:
        at_iso = r.get("at")
        if not at_iso:
            continue
        # promotions_repo returns isoformat strings; parse back.
        try:
            at_dt = datetime.fromisoformat(at_iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        if at_dt.tzinfo is None:
            at_dt = at_dt.replace(tzinfo=timezone.utc)
        if at_dt < start_utc or at_dt > end_utc:
            continue
        from_idx = rank_idx.get(r.get("from_rank", ""), -1)
        to_idx = rank_idx.get(r.get("to_rank", ""), -1)
        if to_idx <= from_idx:
            continue  # demotion or same — skip
        out.append({
            "agent_id": r.get("agent_id"),
            "agent_name": r.get("agent_name"),
            "from": r.get("from_rank"),
            "to": r.get("to_rank"),
            "at": _iso_utc(at_dt),
        })
    # Order newest-first to match the rest of the API surface.
    out.sort(key=lambda d: d.get("at") or "", reverse=True)
    return out


def _predictions_for_recap(orchestrator: Any) -> list[dict[str, Any]]:
    """Map the board's snapshot into recap shape (drop locks_at/reveals_at/options)."""
    board = getattr(orchestrator, "_predictions", None)
    if board is None:
        return []
    raw = []
    try:
        raw = board.snapshot() or []
    except Exception as e:  # pragma: no cover — defensive
        log.warning("recap_predictions_snapshot_failed", error=str(e))
        return []
    out: list[dict[str, Any]] = []
    for p in raw:
        tally = dict(p.get("tally") or {})
        total_votes = sum(int(v) for v in tally.values())
        out.append({
            "id": p.get("id"),
            "question": p.get("question"),
            "winning_option": p.get("winning_option"),
            "tally": tally,
            "total_votes": total_votes,
            "status": p.get("status"),
        })
    return out


def _session_equity(orchestrator: Any) -> tuple[float, float]:
    """Return (session_total_equity, session_pnl_pct) for the live roster."""
    if orchestrator is None:
        return 0.0, 0.0
    agents = list(getattr(orchestrator, "agents", []) or [])
    marks = getattr(orchestrator, "last_marks", {}) or {}
    total_equity = 0.0
    for a in agents:
        state = getattr(a, "state", None)
        if state is None:
            continue
        book = getattr(state, "book", None)
        if book is None:
            continue
        try:
            total_equity += float(book.equity(marks))
        except Exception:
            continue
    starting_total = float(len(agents)) * float(settings.agent_starting_capital)
    if starting_total <= 0:
        return float(total_equity), 0.0
    pnl_pct = (total_equity - starting_total) / starting_total * 100.0
    return float(total_equity), float(pnl_pct)


# ---------------------------------------------------------------------------
# Top-level assembler.
# ---------------------------------------------------------------------------


async def build_recap(
    orchestrator: Any,
    *,
    session_factory: async_sessionmaker | None = None,
    bounds: tuple[datetime, datetime] | None = None,
) -> dict[str, Any]:
    """Assemble the recap payload. Pure-ish: all I/O via injected dependencies.

    ``session_factory`` defaults to the global ``SessionLocal``; tests inject
    a per-test factory pointed at an in-memory SQLite. ``bounds`` overrides
    the ET-today window — useful for tests that seed rows around a fixed
    timestamp.
    """
    sf = session_factory or SessionLocal
    start_utc, end_utc = bounds or _today_et_bounds()
    names = _agent_name_lookup(orchestrator)

    biggest_fill, total_fills = await _biggest_fill_and_count(
        sf, start_utc, end_utc, names,
    )
    top_winners, biggest_loss = await _winners_and_loss(
        sf, start_utc, end_utc, names,
    )
    promotions = await _promotions_today(start_utc, end_utc)
    predictions = _predictions_for_recap(orchestrator)
    session_total_equity, session_pnl_pct = _session_equity(orchestrator)

    # Date in ET calendar terms (the window's start, converted back to ET).
    date_et = start_utc.astimezone(ET).date().isoformat()

    return {
        "date": date_et,
        "session_pnl_pct": session_pnl_pct,
        "session_total_equity": session_total_equity,
        "total_fills": total_fills,
        "biggest_fill": biggest_fill,
        "top_winners": top_winners,
        "biggest_loss": biggest_loss,
        "promotions": promotions,
        "predictions": predictions,
    }


# ---------------------------------------------------------------------------
# Route.
# ---------------------------------------------------------------------------


@router.get("/today")
async def recap_today(request: Request) -> dict[str, Any]:
    """Aggregated highlight reel for the current ET trading day."""
    orch = getattr(request.app.state, "orchestrator", None)
    return await build_recap(orch)
