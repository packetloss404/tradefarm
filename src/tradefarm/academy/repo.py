"""Academy rank persistence (Phase 2).

Thin repo layer around ``Agent.rank`` / ``Agent.rank_updated_at``. Phase 4's
curriculum will log the ``reason`` into a dedicated ``academy_promotions``
table; for Phase 2 we accept the parameter to keep the call-site stable and
just log it via structlog.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import func, select

from tradefarm.academy.ranks import RANK_ORDER, Rank
from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent

log = structlog.get_logger()


async def set_rank(agent_id: int, rank: Rank, reason: str = "") -> None:
    """Persist a rank change for ``agent_id``. No-op if the agent row is
    missing or the rank value is unknown.
    """
    if rank not in RANK_ORDER:
        log.warning("academy_set_rank_unknown", agent_id=agent_id, rank=rank)
        return
    try:
        async with SessionLocal() as session:
            agent = (await session.execute(
                select(Agent).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if agent is None:
                return
            previous = agent.rank
            if previous == rank:
                return
            agent.rank = rank
            agent.rank_updated_at = datetime.now(timezone.utc)
            await session.commit()
        log.info(
            "academy_rank_changed",
            agent_id=agent_id,
            from_rank=previous,
            to_rank=rank,
            reason=reason or "unspecified",
        )
    except Exception as e:
        log.warning("academy_set_rank_failed", agent_id=agent_id, rank=rank, error=str(e))


async def get_rank(agent_id: int) -> Rank:
    """Current persisted rank for ``agent_id``. Defaults to ``intern``."""
    try:
        async with SessionLocal() as session:
            row = (await session.execute(
                select(Agent.rank).where(Agent.id == agent_id)
            )).scalar_one_or_none()
    except Exception as e:
        log.warning("academy_get_rank_failed", agent_id=agent_id, error=str(e))
        return "intern"
    if row is None or row not in RANK_ORDER:
        return "intern"
    return row  # type: ignore[return-value]


async def rank_distribution() -> dict[str, int]:
    """Count of agents per rank. Always returns all four keys (zero-filled)."""
    out: dict[str, int] = {r: 0 for r in RANK_ORDER}
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(Agent.rank, func.count(Agent.id)).group_by(Agent.rank)
            )).all()
    except Exception as e:
        log.warning("academy_rank_distribution_failed", error=str(e))
        return out
    for rank, count in rows:
        if rank in out:
            out[rank] = int(count)
    return out


async def ranks_by_agent() -> dict[int, str]:
    """Snapshot of every agent's current rank (agent_id → rank)."""
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(Agent.id, Agent.rank)
            )).all()
    except Exception as e:
        log.warning("academy_ranks_by_agent_failed", error=str(e))
        return {}
    return {int(aid): (rk if rk in RANK_ORDER else "intern") for aid, rk in rows}
