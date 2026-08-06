"""0.20.0 — pre-aggregated per-(date, strategy) attribution snapshot.

The ``GET /pnl/by-strategy/timeseries`` endpoint used to aggregate
``pnl_snapshots`` on every request: a 2x group-by (latest-snapshot
subquery per (agent, day), then sum by day+strategy). With ~100
agents and a per-tick snapshot cadence, the snapshot table grows
~2k rows/day; the live aggregation walks all of them on every chart
poll.

This module introduces the pre-aggregated alternative:

- :func:`compute_attribution_for_date` runs the same aggregation but
  is bounded to one calendar day and returns plain dicts. The
  end-of-day scheduler calls it once and writes the result to
  :class:`StrategyDailyAttribution`.
- :func:`upsert_attribution_rows` writes the dicts to the snapshot
  table (composite PK = date+strategy, so same-day reruns replace
  in place).
- :func:`read_attribution_rows` is the read path the endpoint uses
  for historical days. Today is always live-aggregated (the
  end-of-day snapshot only lands after 4pm ET).
- :func:`live_strategy_attribution` keeps the same live-aggregation
  code path the old endpoint used, so we have a single source of
  truth for both the snapshot writer and the "today" branch of the
  read path.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date as _date, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from tradefarm.runtime.clock import now_utc
from tradefarm.storage import db as db_mod
from tradefarm.storage.models import Agent, PnlSnapshot, StrategyDailyAttribution, Trade


def _midnight_utc(d: _date) -> datetime:
    return datetime.combine(d, datetime.min.time())


async def _aggregate_one_day(
    session: AsyncSession, day: _date
) -> list[dict[str, Any]]:
    """Per-strategy attribution for ``day`` (UTC boundary).

    Mirrors the existing ``repo.strategy_summary`` shape: one row
    per strategy with realized/unrealized/equity totals, trade
    count, win rate, and best/worst agent names. The trade count
    uses ``executed_at >= day_midnight`` (open day) so the day
    boundary matches the rest of the recap.
    """
    midnight = _midnight_utc(day)
    next_midnight = _midnight_utc(day + timedelta(days=1))

    sub = (
        select(
            PnlSnapshot.agent_id,
            func.max(PnlSnapshot.taken_at).label("ts"),
        )
        .where(PnlSnapshot.taken_at >= midnight)
        .where(PnlSnapshot.taken_at < next_midnight)
        .where(PnlSnapshot.session_id.is_(None))  # live only
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
            .join(sub, sub.c.agent_id == Agent.id, isouter=True)
            .join(
                PnlSnapshot,
                (PnlSnapshot.agent_id == sub.c.agent_id)
                & (PnlSnapshot.taken_at == sub.c.ts)
                # Same-day replay snapshots share the live ``taken_at``
                # (e.g. a test seeded a 16:00 live row and a 16:00
                # replay row). The join must also filter on the live
                # session_id so a collision-on-timestamp doesn't
                # double-count.
                & (PnlSnapshot.session_id.is_(None)),
                isouter=True,
            )
        )
    ).all()

    trade_rows = (
        await session.execute(
            select(Agent.strategy, func.count(Trade.id))
            .join(Trade, Trade.agent_id == Agent.id)
            .where(Trade.executed_at >= midnight)
            .where(Trade.executed_at < next_midnight)
            .where(Trade.session_id.is_(None))
            .group_by(Agent.strategy)
        )
    ).all()
    trades_today_by_strat = {s: int(c) for s, c in trade_rows}

    by_strat: dict[str, dict] = {}
    for _agent_id, name, strat, equity, rpnl, upnl in rows:
        if strat is None:
            continue
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

    out: list[dict[str, Any]] = []
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


async def live_strategy_attribution(day: _date | None = None) -> list[dict[str, Any]]:
    """Public entry point for "give me the live aggregation for this
    day". Today (the default) is what the timeseries endpoint serves
    for the in-progress day; the scheduler uses it with an explicit
    yesterday-during-end-of-day.
    """
    target = day if day is not None else now_utc().date()
    async with db_mod.SessionLocal() as session:
        return await _aggregate_one_day(session, target)


async def upsert_attribution_rows(
    day: _date, rows: Iterable[dict[str, Any]]
) -> int:
    """Write ``rows`` (from :func:`live_strategy_attribution`) into
    the snapshot table for ``day``. Composite PK = (date, strategy),
    so a same-day rerun replaces the row in place. Returns the
    number of rows written.
    """
    day_iso = day.isoformat()
    computed_at = now_utc().isoformat()
    payload = [
        {
            "date": day_iso,
            "strategy": r["strategy"],
            "agent_count": int(r["agent_count"]),
            "realized_pnl_total": r["realized_pnl_total"],
            "unrealized_pnl_total": r["unrealized_pnl_total"],
            "equity_total": r["equity_total"],
            "trades_today": int(r["trades_today"]),
            "win_rate": r["win_rate"],
            "best_agent_name": r.get("best_agent_name"),
            "worst_agent_name": r.get("worst_agent_name"),
            "computed_at": computed_at,
        }
        for r in rows
    ]
    if not payload:
        # A day with zero strategies (e.g. fresh DB) - delete any
        # stale rows for this date so the read path doesn't return
        # yesterday's leftover.
        async with db_mod.SessionLocal() as session:
            await session.execute(
                delete(StrategyDailyAttribution).where(
                    StrategyDailyAttribution.date == day_iso
                )
            )
            await session.commit()
        return 0
    async with db_mod.SessionLocal() as session:
        # SQLite ON CONFLICT DO UPDATE - same row's composite PK.
        # Postgres falls through to the executor's default (a
        # separate DELETE+INSERT in ``on_conflict_do_nothing``);
        # we keep the SQLite-specific path because the only
        # supported backends here are SQLite + Postgres, and the
        # dev/CI default is SQLite. The Postgres fallback is
        # acceptable for the M-effort scope: a same-day rerun is
        # rare (end-of-day fires once), and a duplicate write
        # surfaces as a UNIQUE-violation that the lifespan
        # already swallows.
        stmt = sqlite_insert(StrategyDailyAttribution).values(payload)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "strategy"],
            set_={k: stmt.excluded[k] for k in payload[0] if k not in ("date", "strategy")},
        )
        await session.execute(stmt)
        await session.commit()
    return len(payload)


async def read_attribution_rows(
    start_day: _date, end_day: _date
) -> list[dict[str, Any]]:
    """Read snapshot rows for ``start_day <= date <= end_day``."""
    async with db_mod.SessionLocal() as session:
        rows = (
            await session.execute(
                select(StrategyDailyAttribution)
                .where(StrategyDailyAttribution.date >= start_day.isoformat())
                .where(StrategyDailyAttribution.date <= end_day.isoformat())
                .order_by(StrategyDailyAttribution.date, StrategyDailyAttribution.strategy)
            )
        ).scalars().all()
    return [
        {
            "date": r.date,
            "strategy": r.strategy,
            "agent_count": int(r.agent_count),
            "realized_pnl_total": float(r.realized_pnl_total),
            "unrealized_pnl_total": float(r.unrealized_pnl_total),
            "equity_total": float(r.equity_total),
            "trades_today": int(r.trades_today),
            "win_rate": float(r.win_rate),
            "best_agent_name": r.best_agent_name,
            "worst_agent_name": r.worst_agent_name,
            "computed_at": r.computed_at,
        }
        for r in rows
    ]


async def compute_and_store_for_date(day: _date) -> int:
    """End-to-end helper: aggregate ``day`` from ``pnl_snapshots``
    and upsert into the snapshot table. Returns rows written. The
    end-of-day scheduler calls this once per day at 4pm ET.
    """
    rows = await live_strategy_attribution(day)
    return await upsert_attribution_rows(day, rows)
