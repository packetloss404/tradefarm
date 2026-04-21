"""Rank enum + pure scoring functions (Phase 2).

- ``compute_stats(agent_id)``: reads Phase 1's stamped journal outcomes and
  derives ``RankStats`` (win_rate, Sharpe, n_closed_trades, weeks_active).
- ``eligible_rank(stats)``: pure function; no DB. Phase 4 will reuse this
  same pair inside the curriculum loop.

The tone classes below match the Phase 2 spec in ``docs/PROJECT_PLAN.md``
(the Rank system table).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

import structlog
from sqlalchemy import select

from tradefarm.config import settings
from tradefarm.storage import journal
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent

log = structlog.get_logger()

Rank = Literal["intern", "junior", "senior", "principal"]

RANK_ORDER: tuple[Rank, ...] = ("intern", "junior", "senior", "principal")

# Tailwind tone classes keyed by rank. Single letter pip is sourced via
# `rank[0].upper()` on the frontend; tone is canonical here so backend can
# also describe ranks in API payloads.
_RANK_TONE: dict[Rank, str] = {
    "intern": "text-zinc-400",
    "junior": "text-sky-400",
    "senior": "text-(--color-profit)",
    "principal": "text-amber-400",
}


def rank_tone(rank: str) -> str:
    return _RANK_TONE.get(rank, "text-zinc-400")  # type: ignore[arg-type]


@dataclass
class RankStats:
    """Per-agent performance stats used for rank eligibility.

    Pulled via :func:`compute_stats`; passed to :func:`eligible_rank`. All
    fields are numeric so Phase 4 can serialize them to the promotions log.
    """

    n_closed_trades: int
    win_rate: float  # fraction in [0.0, 1.0]
    sharpe: float  # annualized (sqrt(252) scalar); 0.0 when undefined
    weeks_active: float  # since Agent.created_at; 0.0 if agent row missing


async def compute_stats(agent_id: int, *, starting_capital: float | None = None) -> RankStats:
    """Compute rank stats for ``agent_id`` from stamped journal outcomes.

    Reads the agent's recent closed outcomes (up to 1000) from
    :func:`journal.recent_outcomes`, filtered to notes with a populated
    ``outcome_realized_pnl``. Win-rate is the fraction of outcomes with
    positive realized PnL. Sharpe is ``mean/std * sqrt(252)`` of realized PnL
    expressed as a fraction of the agent's starting capital (annualization is
    rough — this mirrors the one-sample-per-trade convention used across the
    rest of the codebase and matches ``docs/plan_tech.md`` Phase 2).
    Returns zeros for undefined stats (n<2 or std==0).
    """
    outcomes = await journal.recent_outcomes(agent_id, n=1000)
    closed = [o for o in outcomes if o.get("outcome_realized_pnl") is not None]
    n = len(closed)

    if n == 0:
        return RankStats(
            n_closed_trades=0,
            win_rate=0.0,
            sharpe=0.0,
            weeks_active=await _weeks_active(agent_id),
        )

    pnls = [float(o["outcome_realized_pnl"]) for o in closed]
    wins = sum(1 for p in pnls if p > 0)
    win_rate = wins / n

    # Express returns as a fraction of starting capital so Sharpe is unit-free.
    cap = starting_capital if starting_capital is not None else await _starting_capital(agent_id)
    cap = cap or 1.0  # guard against zero; rare but keeps us safe.
    returns = [p / cap for p in pnls]
    sharpe = _sharpe_annualized(returns)

    return RankStats(
        n_closed_trades=n,
        win_rate=win_rate,
        sharpe=sharpe,
        weeks_active=await _weeks_active(agent_id),
    )


def eligible_rank(stats: RankStats) -> Rank:
    """Pure function: map ``stats`` to the highest rank the agent qualifies for.

    Thresholds come from :mod:`tradefarm.config`.settings so operators can
    tune them from the admin panel (Phase 4). The rule order matches the
    plan (PROJECT_PLAN.md Phase 2):

    - principal: ≥ min_trades_principal AND sharpe ≥ min_sharpe_principal AND weeks_active ≥ 2
    - senior:    ≥ min_trades_senior    AND win_rate ≥ min_win_rate_senior
    - junior:    ≥ min_trades_junior
    - else: intern
    """
    if (
        stats.n_closed_trades >= settings.academy_min_trades_principal
        and stats.sharpe >= settings.academy_min_sharpe_principal
        and stats.weeks_active >= 2.0
    ):
        return "principal"
    if (
        stats.n_closed_trades >= settings.academy_min_trades_senior
        and stats.win_rate >= settings.academy_min_win_rate_senior
    ):
        return "senior"
    if stats.n_closed_trades >= settings.academy_min_trades_junior:
        return "junior"
    return "intern"


def _sharpe_annualized(returns: list[float]) -> float:
    n = len(returns)
    if n < 2:
        return 0.0
    mean = sum(returns) / n
    var = sum((r - mean) ** 2 for r in returns) / (n - 1)  # sample variance
    if var <= 0.0:
        return 0.0
    std = math.sqrt(var)
    return (mean / std) * math.sqrt(252)


async def _weeks_active(agent_id: int) -> float:
    try:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(Agent.created_at).where(Agent.id == agent_id)
            )).scalar_one_or_none()
    except Exception as e:
        log.warning("ranks_weeks_active_failed", agent_id=agent_id, error=str(e))
        return 0.0
    if row is None:
        return 0.0
    created = row
    # Some DB drivers return naive datetimes; treat them as UTC for the delta.
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - created
    return delta.total_seconds() / (86400 * 7)


async def _starting_capital(agent_id: int) -> float:
    try:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(Agent.starting_capital).where(Agent.id == agent_id)
            )).scalar_one_or_none()
    except Exception as e:
        log.warning("ranks_starting_capital_failed", agent_id=agent_id, error=str(e))
        return 0.0
    return float(row) if row is not None else 0.0
