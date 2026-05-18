"""Injectable clock for replay-mode sessions.

Live trading reads ``datetime.now(timezone.utc)`` everywhere it needs
the current time. For session replay we need every call site in the
trading path to return a historical timestamp instead, without
threading a ``now`` parameter through dozens of function signatures.

Strategy: a single ``contextvars.ContextVar`` holding an optional
override. ``now_utc()`` returns the override when set, otherwise falls
through to wall-clock. The override is set per-session by the session
runner via ``set_replay_now`` / ``reset_replay_now``.

ContextVars (rather than thread-locals) give us correct isolation
across concurrent ``asyncio`` tasks: each task sees its own override
without leaking into sibling tasks. Live mode never touches the var,
so the live trading path is a strict no-op against today's behavior.
"""
from __future__ import annotations

import contextvars
from datetime import date, datetime, timezone

_replay_now: contextvars.ContextVar[datetime | None] = contextvars.ContextVar(
    "tradefarm_replay_now", default=None,
)


def now_utc() -> datetime:
    override = _replay_now.get()
    return override if override is not None else datetime.now(timezone.utc)


def today_utc() -> date:
    return now_utc().date()


def set_replay_now(t: datetime) -> contextvars.Token:
    if t.tzinfo is None:
        raise ValueError("replay clock requires a tz-aware datetime")
    return _replay_now.set(t)


def reset_replay_now(token: contextvars.Token) -> None:
    _replay_now.reset(token)


def is_replaying() -> bool:
    return _replay_now.get() is not None
