"""Manifest-driven historical state queries for replay mode.

Pure functions that take a parsed manifest dict + a target timestamp
and return what the endpoints stream/ consumes need. No DB, no clock,
no orchestrator state — the only inputs are what session/run.py wrote
to disk, so the same queries work on a fresh dev box, on the broadcast
VM, or in the headless renderer's Playwright capture loop.

What the manifest carries today (per session/run.py):
  fill events    — {symbol, side, qty, price, notional, reason}
  decision events — {kind: "entry"|"exit", symbol, content, metadata}

That's enough to reconstruct positions, cash, realized PnL, and the
last decision per agent. Two things the manifest does NOT carry that
endpoints normally surface:

  - Per-agent rank / strategy (static metadata; the renderer reads these
    from the DB at replay time and merges with our snapshot).
  - Per-tick marks of *other* symbols an agent isn't trading. For v0 we
    mark each position at the last fill price we saw — close enough for
    a beat-clip snapshot, wrong for any precise PnL reconstruction.

When the next session of the roadmap lands (point-in-time marks +
status/journal-counter snapshots), this module gets enriched. For now
it's the smallest substrate the headless renderer needs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


# ----- IO -------------------------------------------------------------------

DEFAULT_SESSIONS_DIR = Path("out/sessions")

# Session ids are file-system identifiers; reject anything that could
# escape `out/sessions/` or carry a leading dot. Real session ids come
# from session.run as `s_<YYYY-MM-DD>_<6-hex>`; the regex is wider so
# operators can hand-craft ids during dev (e.g. `s_smoke_test`).
import re as _re  # noqa: E402  (co-located with the regex it defines)

_SAFE_SESSION_ID = _re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _require_safe_session_id(session_id: str) -> str:
    """Raise ValueError if session_id contains path-traversal characters,
    URL-encoded equivalents, or NUL bytes. Returns the id on success.
    Called at every public entrypoint that uses session_id as a path
    component — REST endpoints, WS handshake, CLI."""
    if not isinstance(session_id, str) or not _SAFE_SESSION_ID.match(session_id):
        raise ValueError(
            f"invalid session_id {session_id!r}: must match [A-Za-z0-9][A-Za-z0-9_.-]{{0,127}}"
        )
    if ".." in session_id or session_id.startswith("."):
        raise ValueError(f"invalid session_id {session_id!r}: traversal-like")
    return session_id


def manifest_path(session_id: str, sessions_dir: Path | None = None) -> Path:
    base = sessions_dir or DEFAULT_SESSIONS_DIR
    return base / _require_safe_session_id(session_id) / "manifest.json"


def load_manifest(session_id: str, sessions_dir: Path | None = None) -> dict[str, Any]:
    p = manifest_path(session_id, sessions_dir)
    return json.loads(p.read_text(encoding="utf-8"))


def parse_iso(ts: str) -> datetime:
    """Parse the manifest's ISO timestamps. Cope with trailing Z."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    return datetime.fromisoformat(ts)


# ----- per-agent fold -------------------------------------------------------


@dataclass
class Position:
    qty: float
    avg_price: float


@dataclass
class AgentSnapshot:
    agent_id: int
    name: str
    cash: float
    realized_pnl: float
    positions: dict[str, Position] = field(default_factory=dict)
    last_decision: dict[str, Any] | None = None
    last_lstm: dict[str, Any] | None = None
    last_event_t: datetime | None = None
    n_fills: int = 0


def _apply_fill(
    snap: AgentSnapshot,
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float,
) -> None:
    """Average-cost accounting against snap.positions, updating cash +
    realized_pnl. Mirrors src/tradefarm/session/beats.py's logic so
    the two stay coherent — same trades, same numbers."""

    pos = snap.positions.get(symbol)
    cur_qty = pos.qty if pos is not None else 0.0
    cur_avg = pos.avg_price if pos is not None else 0.0
    signed_fill = qty if side == "buy" else -qty

    # Cash side: buys debit, sells credit (regardless of long/short).
    snap.cash -= signed_fill * price
    snap.n_fills += 1

    if cur_qty == 0 or (cur_qty > 0 and signed_fill > 0) or (cur_qty < 0 and signed_fill < 0):
        # Opening / adding.
        new_qty = cur_qty + signed_fill
        new_avg = (
            ((abs(cur_qty) * cur_avg) + (abs(signed_fill) * price)) / abs(new_qty)
            if new_qty != 0
            else 0.0
        )
        snap.positions[symbol] = Position(qty=new_qty, avg_price=new_avg)
        return

    # Reducing / flipping.
    closing_qty = min(abs(signed_fill), abs(cur_qty))
    if cur_qty > 0:
        snap.realized_pnl += (price - cur_avg) * closing_qty
    else:
        snap.realized_pnl += (cur_avg - price) * closing_qty

    remaining = abs(signed_fill) - closing_qty
    if remaining == 0:
        new_qty = cur_qty + signed_fill
        if new_qty == 0:
            snap.positions.pop(symbol, None)
        else:
            snap.positions[symbol] = Position(qty=new_qty, avg_price=cur_avg)
    else:
        flip_qty = -1.0 * (cur_qty / abs(cur_qty)) * remaining
        snap.positions[symbol] = Position(qty=flip_qty, avg_price=price)


def fold_to(
    manifest: dict[str, Any],
    at: datetime,
    *,
    starting_capital: float = 1000.0,
) -> tuple[dict[int, AgentSnapshot], dict[str, float]]:
    """Apply every event up to and including `at` into per-agent
    snapshots. Returns (snapshots, last_marks) — last_marks is the most
    recent fill price per symbol, used as the mark-to-market price when
    /account and /agents compute equity."""

    snaps: dict[int, AgentSnapshot] = {}
    last_marks: dict[str, float] = {}
    events: list[dict[str, Any]] = manifest.get("events") or []

    for ev in events:
        try:
            t = parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if t > at:
            break  # events are written in chronological order by the runner
        agent_id = ev.get("agent_id")
        if agent_id is None:
            continue
        aid = int(agent_id)
        snap = snaps.get(aid)
        if snap is None:
            snap = AgentSnapshot(
                agent_id=aid,
                name=str(ev.get("agent_name") or f"agent_{aid}"),
                cash=float(starting_capital),
                realized_pnl=0.0,
            )
            snaps[aid] = snap
        snap.last_event_t = t

        kind = ev.get("kind")
        payload = ev.get("payload") or {}
        if kind == "fill":
            symbol = str(payload.get("symbol") or "")
            side = str(payload.get("side") or "").lower()
            qty = float(payload.get("qty") or 0.0)
            price = float(payload.get("price") or 0.0)
            if symbol and side in ("buy", "sell") and qty > 0 and price > 0:
                _apply_fill(snap, symbol=symbol, side=side, qty=qty, price=price)
                last_marks[symbol] = price
        elif kind == "decision":
            snap.last_decision = {
                "kind": payload.get("kind"),
                "symbol": payload.get("symbol"),
                "content": payload.get("content"),
                "metadata": payload.get("metadata"),
            }

    return snaps, last_marks


# ----- equity / account aggregates -----------------------------------------


def position_value(positions: dict[str, Position], marks: dict[str, float]) -> tuple[float, float]:
    """Returns (notional_value, unrealized_pnl). Unmarked symbols fall
    back to the position's average price (so they read as zero
    unrealized PnL until a fresh mark arrives)."""

    notional = 0.0
    unrealized = 0.0
    for sym, p in positions.items():
        if p.qty == 0:
            continue
        mark = marks.get(sym, p.avg_price)
        notional += p.qty * mark
        unrealized += (mark - p.avg_price) * p.qty
    return notional, unrealized


def equity_for(snap: AgentSnapshot, marks: dict[str, float]) -> float:
    notional, _ = position_value(snap.positions, marks)
    return snap.cash + notional


def agent_status(snap: AgentSnapshot, marks: dict[str, float], starting_capital: float) -> str:
    """The status field /api/account counts. Mirrors the orchestrator's
    own classification: agent is in profit / loss if there's an open
    position with material unrealized P&L, otherwise waiting."""

    has_position = any(p.qty != 0 for p in snap.positions.values())
    if not has_position:
        return "waiting"
    _, unrealized = position_value(snap.positions, marks)
    if unrealized > 1:
        return "profit"
    if unrealized < -1:
        return "loss"
    return "waiting"


# ----- endpoint-shaped builders --------------------------------------------


def agent_payload(
    snap: AgentSnapshot,
    marks: dict[str, float],
    *,
    static_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Shape one agent the way /api/agents emits it live. Caller passes
    `static_meta` for fields the manifest doesn't carry (strategy,
    rank, symbol pin) — typically pulled from the DB."""

    meta = static_meta or {}
    notional, unrealized = position_value(snap.positions, marks)
    equity = snap.cash + notional
    return {
        "id": snap.agent_id,
        "name": snap.name,
        "strategy": meta.get("strategy", "unknown"),
        "status": agent_status(snap, marks, starting_capital=1000.0),
        "rank": meta.get("rank", "intern"),
        "symbol": meta.get("symbol"),
        "cash": snap.cash,
        "equity": equity,
        "realized_pnl": snap.realized_pnl,
        "unrealized_pnl": unrealized,
        "positions": {
            sym: {
                "qty": p.qty,
                "avg_price": p.avg_price,
                "mark": marks.get(sym, p.avg_price),
            }
            for sym, p in snap.positions.items()
            if p.qty
        },
        "last_lstm": snap.last_lstm,
        "last_decision": snap.last_decision,
    }


def agents_payload(
    snaps: dict[int, AgentSnapshot],
    marks: dict[str, float],
    *,
    static_meta_by_id: dict[int, dict[str, Any]] | None = None,
    include_silent: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Build the /api/agents list. `include_silent` lets the caller pad
    in agents that never traded in this session (so the diorama still
    shows a full 100-dot roster) — each entry is a static-meta dict
    plus id and name; they'll come out with cash = starting_capital
    and no positions."""

    static = static_meta_by_id or {}
    out: list[dict[str, Any]] = []
    seen: set[int] = set()
    for aid, snap in snaps.items():
        out.append(agent_payload(snap, marks, static_meta=static.get(aid)))
        seen.add(aid)
    if include_silent:
        for meta in include_silent:
            aid = int(meta["id"])
            if aid in seen:
                continue
            blank = AgentSnapshot(
                agent_id=aid,
                name=str(meta.get("name") or f"agent_{aid}"),
                cash=float(meta.get("starting_capital", 1000.0)),
                realized_pnl=0.0,
            )
            out.append(agent_payload(blank, marks, static_meta=meta))
    return sorted(out, key=lambda a: a["id"])


def account_payload(
    snaps: dict[int, AgentSnapshot],
    marks: dict[str, float],
    *,
    silent_agent_count: int = 0,
    last_tick_at: str | None = None,
    starting_capital: float = 1000.0,
) -> dict[str, Any]:
    """Build the /api/account aggregate. `silent_agent_count` is how
    many roster agents didn't trade this session — they're counted as
    `waiting` so the header's profit/loss/wait totals reach 100."""

    profit = 0
    loss = 0
    waiting = silent_agent_count
    total_equity = silent_agent_count * starting_capital
    realized = 0.0
    unrealized = 0.0
    for snap in snaps.values():
        notional, ag_unrealized = position_value(snap.positions, marks)
        equity = snap.cash + notional
        total_equity += equity
        realized += snap.realized_pnl
        unrealized += ag_unrealized
        status = agent_status(snap, marks, starting_capital=starting_capital)
        if status == "profit":
            profit += 1
        elif status == "loss":
            loss += 1
        else:
            waiting += 1
    return {
        "profit_ai": profit,
        "loss_ai": loss,
        "waiting_ai": waiting,
        "total_equity": total_equity,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "last_tick_at": last_tick_at,
        "notes_this_tick": 0,
        "outcomes_this_tick": 0,
    }


def trades_for_agent(
    manifest: dict[str, Any],
    agent_id: int,
    at: datetime,
    *,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fills for one agent, newest first, capped at `limit`. Shape
    matches /api/agents/{id}/trades (id is synthesized from event index
    since the manifest doesn't preserve Trade.id)."""

    out: list[dict[str, Any]] = []
    events = manifest.get("events") or []
    for idx, ev in enumerate(events):
        if ev.get("kind") != "fill":
            continue
        ev_aid = ev.get("agent_id")
        # Cannot use `or -1` here — agent_id=0 is a legitimate id and
        # Python's truthiness would coerce it to the sentinel, dropping
        # every event for the first agent.
        if ev_aid is None or int(ev_aid) != agent_id:
            continue
        try:
            t = parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if t > at:
            break
        payload = ev.get("payload") or {}
        out.append(
            {
                "id": idx,
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "qty": float(payload.get("qty") or 0.0),
                "price": float(payload.get("price") or 0.0),
                "executed_at": ev["t"],
                "reason": payload.get("reason"),
            }
        )
    out.reverse()
    return out[:limit]


# ----- WS replay event stream ----------------------------------------------


def events_in_window(
    manifest: dict[str, Any],
    *,
    at: datetime,
    until: datetime | None = None,
) -> list[dict[str, Any]]:
    """Slice the manifest's event list to the time window the WS replay
    handshake asked for. Events are returned in their original order
    (chronological); each retains its `t` string for the WS pump to
    sleep between."""

    events = manifest.get("events") or []
    out: list[dict[str, Any]] = []
    for ev in events:
        try:
            t = parse_iso(ev["t"])
        except (KeyError, ValueError):
            continue
        if t < at:
            continue
        if until is not None and t > until:
            break
        out.append(ev)
    return out


# ----- helpers to convert manifest events into WS envelopes ----------------


def manifest_event_to_ws_envelope(ev: dict[str, Any]) -> dict[str, Any] | None:
    """Translate a manifest event into the {type, ts, payload} shape
    the frontend's useLiveEvents validator expects.

    Manifest events use `kind` as the discriminator; the live WS uses
    `type`. Fills carry the same payload shape (symbol/side/qty/price
    + agent_id) so they pass through unchanged. Decisions don't map
    cleanly to a single live event today — emit them as a generic
    `agent_decisions_batch`-style envelope so the existing handler can
    pick them up.
    """

    kind = ev.get("kind")
    ts = ev.get("t")
    if not ts:
        return None
    payload = ev.get("payload") or {}
    agent_id = ev.get("agent_id")
    if kind == "fill":
        return {
            "type": "fill",
            "ts": ts,
            "payload": {
                "agent_id": agent_id,
                "symbol": payload.get("symbol"),
                "side": payload.get("side"),
                "qty": payload.get("qty"),
                "price": payload.get("price"),
            },
        }
    if kind == "decision":
        return {
            "type": "agent_decisions_batch",
            "ts": ts,
            "payload": {
                "decisions": [
                    {
                        "agent_id": agent_id,
                        "agent_name": ev.get("agent_name"),
                        "kind": payload.get("kind"),
                        "symbol": payload.get("symbol"),
                        "content": payload.get("content"),
                        "metadata": payload.get("metadata"),
                        "at": ts,
                    }
                ],
            },
        }
    return None
