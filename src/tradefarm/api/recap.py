"""Recap v2 — end-of-day highlight reel aggregator.

Single REST endpoint that assembles the day's highlights into one structured
JSON response. The stream's ``RecapScene`` renders a 30-second card sequence
from this payload; the dashboard's "Closing Recap" macro also pokes it.

Two paths:

1. **Live** (no query params) — uses the live orchestrator's agents, marks,
   and the DB's Trade / AgentNote rows for today's ET window.
2. **Replay** (`?session_id=&at=`) — loads the named session's manifest,
   folds it to the requested timestamp, and shapes the response from the
   folded state. Used by the headless renderer when capturing a recap
   clip for a historical day.

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
each without spinning up the full app. ``build_recap`` is the live-path
assembler; ``build_recap_from_manifest`` is the replay-path assembler;
``GET /recap/today`` routes between them based on the query params.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tradefarm.academy import RANK_ORDER
from tradefarm.academy import promotions_repo
from tradefarm.config import settings
from tradefarm.market.hours import ET
from tradefarm.runtime.clock import now_utc
from tradefarm.session import replay_query
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

    Routes through ``runtime.clock.now_utc()`` so a replay session pinning
    the clock to 2024-03-15 produces a 2024-03-15 ET window — not a
    wall-clock-today window that misses all replayed rows.
    """
    now = now_utc()
    now_et = now.astimezone(ET)
    midnight_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = midnight_et.astimezone(timezone.utc)
    end_utc = now
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
    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
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
        # Total fills today. Audit fix: live recap excludes replay-tagged
        # rows so a session.run doesn't appear in the "today" recap.
        total = (
            await session.execute(
                select(func.count(Trade.id)).where(
                    Trade.executed_at >= start_naive,
                    Trade.executed_at <= end_naive,
                    Trade.session_id.is_(None),
                )
            )
        ).scalar_one()
        # Biggest by |qty * price|.
        notional_expr = func.abs(Trade.qty * Trade.price)
        row = (
            await session.execute(
                select(Trade)
                .where(
                    Trade.executed_at >= start_naive,
                    Trade.executed_at <= end_naive,
                    Trade.session_id.is_(None),
                )
                .order_by(notional_expr.desc(), Trade.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

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
        winners_rows = (
            (
                await session.execute(
                    select(AgentNote)
                    .where(
                        AgentNote.outcome_realized_pnl.is_not(None),
                        AgentNote.outcome_realized_pnl > 0,
                        AgentNote.outcome_closed_at >= start_naive,
                        AgentNote.outcome_closed_at <= end_naive,
                        # Audit fix: live winners exclude replay outcomes.
                        AgentNote.session_id.is_(None),
                    )
                    .order_by(AgentNote.outcome_realized_pnl.desc(), AgentNote.id.desc())
                    .limit(3)
                )
            )
            .scalars()
            .all()
        )

        # Biggest loss: most-negative single closed outcome (skip if pnl >= 0).
        loss_row = (
            await session.execute(
                select(AgentNote)
                .where(
                    AgentNote.outcome_realized_pnl.is_not(None),
                    AgentNote.outcome_closed_at >= start_naive,
                    AgentNote.outcome_closed_at <= end_naive,
                    AgentNote.session_id.is_(None),
                )
                .order_by(AgentNote.outcome_realized_pnl.asc(), AgentNote.id.asc())
                .limit(1)
            )
        ).scalar_one_or_none()

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
        out.append(
            {
                "agent_id": r.get("agent_id"),
                "agent_name": r.get("agent_name"),
                "from": r.get("from_rank"),
                "to": r.get("to_rank"),
                "at": _iso_utc(at_dt),
            }
        )
    # Order newest-first to match the rest of the API surface.
    out.sort(key=lambda d: d.get("at") or "", reverse=True)
    return out


def _predictions_for_recap(orchestrator: Any) -> list[dict[str, Any]]:
    """Map the board's snapshot into recap shape (drop locks_at/reveals_at/options)."""
    board = getattr(orchestrator, "_predictions", None)
    if board is None:
        return []
    raw: list[dict[str, Any]] = []
    try:
        raw = board.snapshot() or []
    except Exception as e:  # pragma: no cover — defensive
        log.warning("recap_predictions_snapshot_failed", error=str(e))
        return []
    out: list[dict[str, Any]] = []
    for p in raw:
        tally = dict(p.get("tally") or {})
        total_votes = sum(int(v) for v in tally.values())
        out.append(
            {
                "id": p.get("id"),
                "question": p.get("question"),
                "winning_option": p.get("winning_option"),
                "tally": tally,
                "total_votes": total_votes,
                "status": p.get("status"),
            }
        )
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
        sf,
        start_utc,
        end_utc,
        names,
    )
    top_winners, biggest_loss = await _winners_and_loss(
        sf,
        start_utc,
        end_utc,
        names,
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
# Replay path.
# ---------------------------------------------------------------------------


def build_recap_from_manifest(
    manifest: dict[str, Any],
    at: datetime,
) -> dict[str, Any]:
    """Replay-mode assembler. Folds the manifest's events up to ``at``
    and shapes the same response contract as ``build_recap`` from the
    folded agent state.

    Inputs are pure (the manifest dict + a target timestamp); no DB
    reads, no orchestrator coupling — the same call works on the
    headless renderer's Playwright capture loop or a debug session
    on a developer's box.

    The biggest_fill + top_winners/losses are derived from the folded
    AgentSnapshots' average-cost PnL math (the same accounting
    `session/beats.py:_apply_fill` uses) so a 2024 session replays
    with the same numbers a live tick would have produced.
    """
    snaps, marks = replay_query.fold_to(manifest, at)
    events = manifest.get("events") or []
    start_at = manifest.get("started_at")

    # Total fills: count `fill` events up to `at`.
    total_fills = 0
    for ev in events:
        if ev.get("kind") != "fill":
            continue
        try:
            t = replay_query.parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if t > at:
            break
        total_fills += 1

    # Biggest fill: largest |qty * price| up to `at`.
    biggest_fill: dict[str, Any] | None = None
    biggest_notional = 0.0
    for ev in events:
        if ev.get("kind") != "fill":
            continue
        try:
            t = replay_query.parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if t > at:
            break
        payload = ev.get("payload") or {}
        try:
            qty = float(payload.get("qty") or 0.0)
            price = float(payload.get("price") or 0.0)
        except (TypeError, ValueError):
            continue
        notional = abs(qty * price)
        if notional > biggest_notional:
            biggest_notional = notional
            biggest_fill = {
                "agent_id": ev.get("agent_id"),
                "agent_name": ev.get("agent_name"),
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "qty": qty,
                "price": price,
                "notional": notional,
                "at": ev.get("t"),
            }

    # Top winners / biggest loss from folded agent snapshots.
    # `equity_for()` already applies marks; we use `realized_pnl` (closed
    # trades only) for the podium so an open mega-winner doesn't always
    # top the chart.
    sorted_by_pnl = sorted(
        snaps.values(),
        key=lambda s: s.realized_pnl,
        reverse=True,
    )
    winners: list[dict[str, Any]] = []
    for snap in sorted_by_pnl:
        if snap.realized_pnl <= 0:
            break
        # The folded snapshot doesn't keep the symbol the gain came
        # from; surface the agent + the realized number. The studio
        # already shows agent cards so symbol lookup is a UI concern.
        winners.append(
            {
                "agent_id": snap.agent_id,
                "agent_name": snap.name,
                "realized_pnl": float(snap.realized_pnl),
                "symbol": None,
            }
        )
        if len(winners) >= 3:
            break

    biggest_loss: dict[str, Any] | None = None
    for snap in sorted_by_pnl:
        if snap.realized_pnl < 0:
            biggest_loss = {
                "agent_id": snap.agent_id,
                "agent_name": snap.name,
                "realized_pnl": float(snap.realized_pnl),
                "symbol": None,
            }
            break

    # Session totals.
    total_equity = 0.0
    starting_total = 0.0
    for snap in snaps.values():
        equity = replay_query.equity_for(snap, marks)
        total_equity += equity
        starting_total += 1000.0  # default starting_capital; fold_to default
    pnl_pct = (
        ((total_equity - starting_total) / starting_total * 100.0)
        if starting_total > 0
        else 0.0
    )

    # Date in ET calendar terms (the manifest's started_at, converted).
    date_et = ""
    if start_at:
        try:
            date_et = replay_query.parse_iso(start_at).astimezone(ET).date().isoformat()
        except ValueError:
            date_et = start_at[:10] if isinstance(start_at, str) else ""

    return {
        "date": date_et,
        "session_pnl_pct": float(pnl_pct),
        "session_total_equity": float(total_equity),
        "total_fills": int(total_fills),
        "biggest_fill": biggest_fill,
        "top_winners": winners,
        "biggest_loss": biggest_loss,
        # The live path also surfaces `promotions` (from the
        # promotions_repo, which is DB-backed) and `predictions` (from
        # the orchestrator's board, in-memory). Neither is in the
        # manifest today, so the replay path returns empty lists —
        # the surface is honest rather than fabricated.
        "promotions": [],
        "predictions": [],
    }


# ---------------------------------------------------------------------------
# Route.
# ---------------------------------------------------------------------------


@router.get("/today")
async def recap_today(
    request: Request,
    session_id: str | None = Query(
        None,
        description="Replay mode: name the session manifest to fold. "
        "If present, the response is built from the manifest instead of "
        "the live orchestrator + DB.",
    ),
    at: str | None = Query(
        None,
        description="Replay mode: ISO-8601 timestamp to fold the manifest up to. "
        "Defaults to manifest.ended_at when omitted.",
    ),
) -> dict[str, Any]:
    """Aggregated highlight reel for the current ET trading day, or for
    a replayed historical day when ``?session_id=`` is provided.

    The headless renderer's recap-scene capture uses the replay form:
    the URL ``/recap/today?session_id=<sid>&at=<iso>`` makes the
    scene a snapshot of the folded manifest state at ``at`` (not a
    live-today card)."""
    if session_id is None:
        # Live path: unchanged.
        orch = getattr(request.app.state, "orchestrator", None)
        return await build_recap(orch)

    # Replay path. Validate session_id before any disk touch.
    try:
        replay_query._require_safe_session_id(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        manifest = replay_query.load_manifest(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail=f"no manifest for session {session_id!r}"
        ) from exc

    # Parse the at timestamp. Fall back to manifest.ended_at.
    at_str = at or manifest.get("ended_at") or manifest.get("started_at")
    if not at_str or not isinstance(at_str, str):
        raise HTTPException(
            status_code=400, detail="missing or invalid `at` timestamp"
        )
    try:
        at_dt = replay_query.parse_iso(at_str)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid `at`: {exc}") from exc

    return build_recap_from_manifest(manifest, at_dt)


# ---------------------------------------------------------------------------
# 0.16.0 — 4pm ET live recap scene endpoints.
#
# Two thin surfaces consumed by the stream's ``LiveRecapScene``:
#
# * ``GET /api/recap/ledger``  — in-memory ``BroadcastRecapLedger.to_payload()``
#   snapshot. The ledger is installed as a module-global by the
#   ``BroadcastSuite.start()``; if the orchestrator isn't running (or the
#   arbiter hasn't been installed), return an empty payload so the stream
#   can still render an "idle" frame.
#
# * ``GET /api/weekly/{week_id}``  — wraps ``weekly_rollup.read_weekly_rollup``.
#   404 when the rollup file is missing (a fresh dev box or a week with no
#   sessions); validates the ``week_id`` regex so a garbage path component
#   doesn't reach the disk layer.
# ---------------------------------------------------------------------------


_WEEK_ID_RE = re.compile(r"^\d{4}-W\d{2}$")


@router.get("/ledger")
async def recap_ledger() -> dict[str, Any]:
    """Return the live broadcast ledger payload for the recap scene.

    The scene reads this on mount + once per minute; the ledger is in-memory
    and updated every time ``publish_broadcast_moment`` is called. When the
    orchestrator isn't running the global ledger is None — we return the
    same empty-shape payload (``max_moments=0``, ``count=0``) the
    ``BroadcastRecapLedger().to_payload()`` produces so the client never
    has to special-case a "no data" response.

    Recent cap is bumped to 20 and top cap to 10 (vs the default 10/5) so
    the scene's "top 3 moves" + "rivalries" sections have enough headroom
    for a full trading day.
    """
    from tradefarm.orchestrator import broadcast_os as _bos

    ledger = _bos.get_broadcast_ledger()
    if ledger is None:
        # Synthesize an empty payload — same shape as a fresh
        # ``BroadcastRecapLedger().to_payload(...)`` call.
        return {
            "max_moments": 0,
            "count": 0,
            "recent": [],
            "top": [],
        }
    return ledger.to_payload(recent_limit=20, top_limit=10)


@router.get("/weekly/{week_id}")
async def weekly_rollup(week_id: str) -> dict[str, Any]:
    """Return the weekly rollup JSON for ``week_id`` (e.g. ``2026-W31``).

    Wraps ``tradefarm.session.weekly_rollup.read_weekly_rollup`` with a
    format check (rejects anything that isn't ``YYYY-WNN``) so a junk
    path component never reaches the disk layer. 404 when the rollup
    file is missing — a fresh dev box or a week with no sessions.

    The rollup is read on every request (no in-memory cache) so a write
    that lands between requests is picked up on the next poll.
    Sessions-dir resolution is delegated to ``read_weekly_rollup`` —
    the default ``replay_query.DEFAULT_SESSIONS_DIR`` is fine for the
    live broadcast VM.
    """
    if not _WEEK_ID_RE.match(week_id):
        raise HTTPException(
            status_code=400,
            detail=f"invalid week_id {week_id!r}; expected YYYY-WNN",
        )
    from tradefarm.session.weekly_rollup import read_weekly_rollup

    rollup = read_weekly_rollup(week_id)
    if rollup is None:
        raise HTTPException(
            status_code=404, detail=f"no weekly rollup for {week_id!r}"
        )
    return rollup
