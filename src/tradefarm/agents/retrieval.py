"""Phase 3 — Retrieval-augmented prompt.

Wraps :func:`journal.find_similar` and formats the results into a list of
:class:`RetrievedExample` values that :mod:`llm_overlay_types` can splice
into the user message.

v1 retrieval is metadata-only (same-symbol + recency). Embeddings are
deferred per the canonical plan's Phase 3 Risk #4 (prompt bloat) — the
cap on ``academy_retrieval_k`` (3) plus the 80-char content truncation
in :func:`format_for_prompt` keep the non-cached user message tight.

Contract (hard):
- ``academy_retrieval_enabled=False`` → :func:`fetch` returns ``[]``.
- Any journal error → :func:`fetch` returns ``[]`` (never blocks a decision).
- :func:`format_for_prompt([])` → empty string, so callers can concat blindly.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from tradefarm.config import settings
from tradefarm.storage import journal

log = structlog.get_logger()


@dataclass
class RetrievedExample:
    """One past stamped setup retrieved from the agent's own journal."""

    symbol: str
    direction_hint: str
    content: str
    realized_pnl: float
    closed_at_iso: str
    note_id: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "direction_hint": self.direction_hint,
            "content": self.content,
            "realized_pnl": self.realized_pnl,
            "closed_at_iso": self.closed_at_iso,
            "note_id": self.note_id,
        }


def _row_to_example(row: dict[str, Any]) -> RetrievedExample:
    meta = row.get("metadata") or {}
    direction_hint = ""
    if isinstance(meta, dict):
        raw = meta.get("lstm_direction", "")
        if isinstance(raw, str):
            direction_hint = raw
    return RetrievedExample(
        symbol=str(row.get("symbol") or ""),
        direction_hint=direction_hint,
        content=str(row.get("content") or ""),
        realized_pnl=float(row.get("outcome_realized_pnl") or 0.0),
        closed_at_iso=str(row.get("outcome_closed_at") or ""),
        note_id=int(row.get("id") or 0),
    )


async def fetch(agent_id: int, symbol: str, k: int | None = None) -> list[RetrievedExample]:
    """Retrieve the agent's ``k`` most-similar past stamped setups for ``symbol``.

    Short-circuits to ``[]`` when retrieval is disabled or ``k <= 0``. Any
    journal error is swallowed and logged — retrieval must never block a
    decision.
    """
    if not settings.academy_retrieval_enabled:
        return []
    limit = settings.academy_retrieval_k if k is None else int(k)
    if limit <= 0:
        return []
    try:
        rows = await journal.find_similar(agent_id, symbol, limit=limit)
    except Exception as e:
        log.warning(
            "retrieval_fetch_failed",
            agent_id=agent_id,
            symbol=symbol,
            error=str(e),
        )
        return []
    return [_row_to_example(r) for r in rows]


def format_for_prompt(examples: list[RetrievedExample]) -> str:
    """Render the "Past similar setups" block.

    Returns an empty string when ``examples`` is empty so that the user
    message is byte-identical to pre-Phase-3 output. The leading blank line
    is intentional — it visually separates the block from the prior lines.
    Content is truncated to 80 chars to contain prompt bloat.
    """
    if not examples:
        return ""
    lines = ["", "Past similar setups (your own history):"]
    for ex in examples:
        pnl_str = f"{'+' if ex.realized_pnl >= 0 else '-'}${abs(ex.realized_pnl):.2f}"
        date_part = ex.closed_at_iso[:10] if ex.closed_at_iso else "unknown date"
        content_trunc = ex.content[:80]
        dir_part = f" {ex.direction_hint}" if ex.direction_hint else ""
        lines.append(
            f"- {ex.symbol}{dir_part} \u00b7 {content_trunc} \u2192 realized {pnl_str} on {date_part}"
        )
    return "\n".join(lines)
