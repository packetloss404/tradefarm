"""Ambient session_id for replay-mode storage writes.

Mirrors the pattern in :mod:`tradefarm.runtime.clock`: a single
``contextvars.ContextVar`` that storage helpers consult when writing
rows. Live mode leaves the var empty, so ``Trade.session_id``,
``PnlSnapshot.session_id``, and ``AgentNote.session_id`` stay NULL.
The session runner sets the var before invoking ``orchestrator.tick_once``
so every row produced by that tick gets stamped.

Why context-var instead of an explicit parameter: the alternative is
threading ``session_id`` through ``repo.record_trade``,
``repo.snapshot_pnl``, ``journal.write_note``, every test that calls
them, and every downstream caller in the orchestrator. The context-var
keeps the writeable signatures stable and gives correct asyncio task
isolation — exactly the same reasoning as the clock.
"""
from __future__ import annotations

import contextvars

_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tradefarm_session_id", default=None,
)


def current_session_id() -> str | None:
    return _session_id.get()


def set_session_id(sid: str) -> contextvars.Token:
    if not sid:
        raise ValueError("session_id must be a non-empty string")
    return _session_id.set(sid)


def reset_session_id(token: contextvars.Token) -> None:
    _session_id.reset(token)
