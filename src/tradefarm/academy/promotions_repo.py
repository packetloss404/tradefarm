"""Phase 4 — promotions log persistence + query helpers."""
from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import select

from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import AcademyPromotion, Agent

if TYPE_CHECKING:
    from tradefarm.academy.curriculum import PromotionEvent

log = structlog.get_logger()


def stats_to_json(stats: Any) -> str:
    try:
        return json.dumps(asdict(stats) if is_dataclass(stats) else dict(stats), default=str)
    except Exception:
        return ""

def _row(r: AcademyPromotion, name: str | None) -> dict[str, Any]:
    return {"id": r.id, "agent_id": r.agent_id, "agent_name": name,
            "from_rank": r.from_rank, "to_rank": r.to_rank, "reason": r.reason,
            "stats_snapshot": r.stats_snapshot,
            "at": r.at.isoformat() if r.at else None}


async def record(event: "PromotionEvent") -> int | None:
    try:
        async with SessionLocal() as session:
            r = AcademyPromotion(
                agent_id=event.agent_id, from_rank=event.from_rank,
                to_rank=event.to_rank, reason=event.reason,
                stats_snapshot=event.stats_snapshot_json)
            session.add(r)
            await session.commit()
            await session.refresh(r)
            return r.id
    except Exception as e:
        log.warning("promotions_record_failed", agent_id=event.agent_id, error=str(e))
        return None


async def recent(hours: int = 24, limit: int = 100) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, hours))
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(AcademyPromotion, Agent.name)
                .outerjoin(Agent, Agent.id == AcademyPromotion.agent_id)
                .where(AcademyPromotion.at >= cutoff)
                .order_by(AcademyPromotion.at.desc(), AcademyPromotion.id.desc())
                .limit(limit))).all()
    except Exception as e:
        log.warning("promotions_recent_failed", error=str(e))
        return []
    return [_row(p, name) for p, name in rows]


async def for_agent(agent_id: int, hours: int = 24 * 30) -> list[dict[str, Any]]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, hours))
    try:
        async with SessionLocal() as session:
            name = (await session.execute(
                select(Agent.name).where(Agent.id == agent_id))).scalar_one_or_none()
            rows = (await session.execute(
                select(AcademyPromotion)
                .where(AcademyPromotion.agent_id == agent_id, AcademyPromotion.at >= cutoff)
                .order_by(AcademyPromotion.at.desc(), AcademyPromotion.id.desc()))).scalars().all()
    except Exception as e:
        log.warning("promotions_for_agent_failed", agent_id=agent_id, error=str(e))
        return []
    return [_row(r, name) for r in rows]
