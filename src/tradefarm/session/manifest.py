"""Session manifest — the flat event list a downstream beat detector consumes.

The session runner builds one of these per run by querying DB rows tagged
with the session_id. The manifest is the *only* output the next pipeline
stages need; they don't talk to the DB directly.

Skeleton — implementation lives in this file; see TODOs.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SessionEvent:
    """One event materialized from a session's DB writes.

    `t` is an ISO-8601 datetime string at the moment the row was written
    (which under replay equals the injected clock time, i.e. the trading
    day's market close). `kind` is one of "fill" | "decision" |
    "tick_summary". `payload` is event-specific structured data (symbol,
    side, qty, price, etc. for fills; signal + rationale for decisions).
    """

    t: str
    kind: str
    agent_id: int | None
    agent_name: str | None
    payload: dict[str, Any]


@dataclass
class SessionManifest:
    session_id: str
    date_range: list[str]
    started_at: str
    ended_at: str
    trading_days: list[str]
    tick_count: int
    fill_count: int
    agents_active: int
    events: list[SessionEvent] = field(default_factory=list)


def write_manifest(manifest: SessionManifest, path: Path) -> None:
    """Serialize the manifest to JSON at `path`.

    Schema is stable — the beat detector and downstream subsystems
    parse it. Use json.dumps with indent=2 for human-debuggability;
    the file is small enough that disk cost is negligible.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = asdict(manifest)
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
