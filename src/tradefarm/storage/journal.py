"""Agent journal (Phase 1 of Agent Academy).

Every decision writes a note via :func:`write_note`; when a position closes,
:func:`close_outcome` stamps the **oldest unstamped `entry` note** for
``(agent_id, symbol)`` with the realized PnL and the closing trade id.

Partial-exit rule
-----------------
One note gets stamped per *full flat-out* of a position, not per partial exit.
``close_outcome`` is only called by the scheduler when a fill produces a
non-zero realized PnL from ``VirtualPosition.apply_fill``; the scheduler fires
it once per closing fill. If the user partially closes (e.g. sells half of a
long), that partial exit's realized PnL stamps the oldest unstamped entry —
but a subsequent fill closing the remainder will find the next oldest entry,
or nothing (returns ``None``) if no other entries exist. Callers should only
invoke ``close_outcome`` on the fill that realized PnL; the function is
idempotent and safe against missing context.

Backtest / no-session safety
----------------------------
All writers swallow unknown-agent errors (returns ``None``). This keeps the
backtest path — which constructs agents without a live DB row — working
without code changes to ``agents/backtest.py``.
"""
from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy import select

from tradefarm.storage.db import SessionLocal
from tradefarm.storage.models import Agent, AgentNote

log = structlog.get_logger()


def _encode_meta(metadata: dict | None) -> str:
    if not metadata:
        return ""
    try:
        return json.dumps(metadata, default=str)
    except Exception:
        return ""


def _decode_meta(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _row_to_dict(n: AgentNote) -> dict:
    return {
        "id": n.id,
        "agent_id": n.agent_id,
        "kind": n.kind,
        "symbol": n.symbol,
        "content": n.content,
        "metadata": _decode_meta(n.note_metadata),
        "created_at": n.created_at.isoformat() if n.created_at else None,
        "outcome_trade_id": n.outcome_trade_id,
        "outcome_realized_pnl": n.outcome_realized_pnl,
        "outcome_closed_at": n.outcome_closed_at.isoformat() if n.outcome_closed_at else None,
    }


async def write_note(
    agent_id: int,
    kind: str,
    symbol: str,
    content: str,
    metadata: dict | None = None,
) -> int | None:
    """Append a journal note for ``agent_id``. Returns the new note id, or
    ``None`` if the write was skipped (e.g. unknown agent row — tolerated for
    backtest / no-session contexts).
    """
    if kind not in ("entry", "exit", "observation"):
        log.warning("journal_bad_kind", kind=kind, agent_id=agent_id)
        return None
    try:
        async with SessionLocal() as session:
            # Silently skip if the agent doesn't exist in the DB yet (backtest path).
            exists = (await session.execute(
                select(Agent.id).where(Agent.id == agent_id)
            )).scalar_one_or_none()
            if exists is None:
                return None
            note = AgentNote(
                agent_id=agent_id,
                kind=kind,
                symbol=symbol,
                content=content or "",
                note_metadata=_encode_meta(metadata),
            )
            session.add(note)
            await session.commit()
            await session.refresh(note)
            return note.id
    except Exception as e:
        log.warning("journal_write_failed", agent_id=agent_id, symbol=symbol, error=str(e))
        return None


async def close_outcome(
    agent_id: int,
    symbol: str,
    realized_pnl: float,
    trade_id: int | None = None,
) -> int | None:
    """Stamp the oldest unstamped ``entry`` note for ``(agent_id, symbol)``
    with the realized PnL and close timestamp. Returns the stamped note id,
    or ``None`` if no unstamped entry exists (idempotent).
    """
    try:
        async with SessionLocal() as session:
            stmt = (
                select(AgentNote)
                .where(
                    AgentNote.agent_id == agent_id,
                    AgentNote.symbol == symbol,
                    AgentNote.kind == "entry",
                    AgentNote.outcome_closed_at.is_(None),
                )
                .order_by(AgentNote.created_at.asc(), AgentNote.id.asc())
                .limit(1)
            )
            note = (await session.execute(stmt)).scalar_one_or_none()
            if note is None:
                return None
            from datetime import datetime, timezone
            note.outcome_realized_pnl = float(realized_pnl)
            note.outcome_trade_id = trade_id
            note.outcome_closed_at = datetime.now(timezone.utc)
            await session.commit()
            return note.id
    except Exception as e:
        log.warning("journal_close_failed", agent_id=agent_id, symbol=symbol, error=str(e))
        return None


async def recent_outcomes(agent_id: int, n: int = 20) -> list[dict]:
    """Return the newest ``n`` notes for ``agent_id`` (newest first), with
    outcome fields populated where present.
    """
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(AgentNote)
                .where(AgentNote.agent_id == agent_id)
                .order_by(AgentNote.created_at.desc(), AgentNote.id.desc())
                .limit(n)
            )).scalars().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.warning("journal_recent_failed", agent_id=agent_id, error=str(e))
        return []


async def find_similar(
    agent_id: int,
    symbol: str,
    *,
    limit: int = 3,
) -> list[dict]:
    """v1: match on same symbol, stamped outcome only, ordered by recency.

    Phase 3 may extend this with embeddings; the contract is: return a list of
    note dicts (same shape as :func:`recent_outcomes`). No embeddings here.
    """
    try:
        async with SessionLocal() as session:
            rows = (await session.execute(
                select(AgentNote)
                .where(
                    AgentNote.agent_id == agent_id,
                    AgentNote.symbol == symbol,
                    AgentNote.outcome_closed_at.is_not(None),
                )
                .order_by(AgentNote.outcome_closed_at.desc(), AgentNote.id.desc())
                .limit(limit)
            )).scalars().all()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        log.warning("journal_similar_failed", agent_id=agent_id, symbol=symbol, error=str(e))
        return []
