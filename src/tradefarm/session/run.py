"""Session runner — replay N historical days through the full 100-agent
orchestrator with everything written to disk tagged by session_id.

CLI:
    uv run python -m tradefarm.session.run \\
        --date-range 2026-05-12:2026-05-16 \\
        [--date 2026-05-15] \\
        [--speed asap] \\
        [--session-id auto] \\
        [--out out/sessions/]

Output:
    out/sessions/<session_id>/manifest.json
    DB rows in trades/pnl_snapshots/agent_notes tagged with the session_id

Manifest extras (v1 — written after the standard `SessionManifest`):
    rivalries           - top 2 same-symbol opposite-side agent pairs
    lowest_ranks        - 5 lowest-cash intern cast rows at session start
                          (id, name, rank, rank_index, strategy, starting_capital)
    interns_under_watch - back-compat: derived list of agent_ids from lowest_ranks
    strategy_rollup     - per-strategy aggregate (agents, equity, pnl, pnlPct, fills)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from tradefarm.academy import RANK_ORDER
from tradefarm.market.hours import NYSE
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.runtime.session_context import reset_session_id, set_session_id
from tradefarm.session import closing_snapshot, replay
from tradefarm.session.beats import _agent_pnl_from_fills, _fills
from tradefarm.session.manifest import SessionEvent, SessionManifest, write_manifest
from tradefarm.storage.db import SessionLocal, init_db
from tradefarm.storage.models import Agent, AgentNote, Trade


# Number of "interns under watch" for the Friday Intern Watch episode.
# Five keeps the cast list short enough to read on a phone and matches
# what the channel art can fit in a 5-row card.
_INTERN_WATCH_COUNT = 5
# Rivals surfaced into the manifest. Top 2 = enough for a single 60s
# short and a chapter in the weekly reel without crowding the
# divergence slot.
_RIVALRY_TOP_N = 2
# Rolling window for the rivalry detector (minutes). Matches the beat
# detector's default so the two views agree on which overlaps "count".
_RIVALRY_WINDOW_MIN = 90.0
# Minimum overlap count for a rivalry to surface.
_RIVALRY_MIN_OCCURRENCES = 3


@dataclass(frozen=True)
class StrategyRollup:
    """One bucket's aggregate for the manifest's `strategy_rollup` field.
    Mirrors `web/src/vod/types.ts:StrategyRollup` so the studio can
    consume the field without a shape translation. Money in dollars,
    fills in count of Trade rows.
    """

    agents: int
    equity: float
    pnl: float
    pnlPct: float
    fills: int


async def run_session(
    *,
    start_date: date,
    end_date: date,
    session_id: str,
    out_dir: Path,
) -> Path:
    """Run a session covering [start_date, end_date] inclusive.

    Returns the path to the written manifest.json.

    Implementation outline for the agent:
    1. Ensure DB schema exists: `await storage.db.init_db()`
    2. Build orchestrator: `orch = Orchestrator.build_default()`
    3. await orch.persist_initial_state() to upsert agent rows
    4. Set the session_id ContextVar for the whole session:
       `token = set_session_id(session_id)`
       Use try/finally to always reset.
    5. Compute trading days in range: skip weekends. Use
       tradefarm.market.hours.NYSE.schedule(start_date=..., end_date=...)
       to filter to actual NYSE trading days. The result has rows for
       each open session.
    6. For each trading day:
        result = await replay.run_day(orch, day)
        Track fill_count += result.get("fills", 0)
    7. After the last day: capture `marks = dict(orch.last_marks)`
       and call closing_snapshot.write_closing_snapshot(orch, marks)
    8. Build the event list by querying the DB for rows tagged with
       this session_id (see _build_events_from_db below).
    9. Build SessionManifest with the collected stats and events,
       write to out_dir / session_id / manifest.json.

    Notes:
    - started_at / ended_at should be REAL wall-clock UTC timestamps
      (datetime.now(timezone.utc).isoformat()), not the replay clock —
      they describe when the runner actually ran.
    - Pass through any orchestrator exceptions; don't swallow.
    """
    started_at = datetime.now(timezone.utc).isoformat()

    await init_db()
    orch = Orchestrator.build_default()
    await orch.persist_initial_state()

    token = set_session_id(session_id)
    try:
        # Audit fix (round 4): refuse to replay a future date or a
        # weekend/holiday-only range. The previous code happily wrote
        # a manifest with zero events because NYSE.schedule returns
        # empty for those windows and the loop simply iterated zero
        # times — operator saw "session_id=…" + no fills with no clue
        # why. Fail loud at the boundary instead.
        wall_today = datetime.now(timezone.utc).date()
        if start_date > wall_today:
            raise SystemExit(
                f"refusing to replay future date {start_date.isoformat()} "
                f"(wall-clock today is {wall_today.isoformat()})"
            )
        schedule = NYSE.schedule(start_date=start_date, end_date=end_date)
        trading_days: list[date] = [ts.date() for ts in schedule.index.to_pydatetime()]
        if not trading_days:
            raise SystemExit(
                f"refusing to replay {start_date.isoformat()}..{end_date.isoformat()} — "
                "no NYSE trading days in that range (weekend/holiday)"
            )

        # Snapshot the intern cast BEFORE the replay runs. The Friday
        # "Intern Watch" episode opens with the cohort at session start;
        # the curriculum can promote them mid-session but the cast card
        # shouldn't change retroactively. Returns the full cast list
        # (id, name, rank, rank_index, strategy, starting_capital) so
        # the VOD studio + recap endpoint don't have to re-query.
        lowest_ranks = await _snapshot_intern_cast(limit=_INTERN_WATCH_COUNT)

        fill_count = 0
        for day in trading_days:
            result = await replay.run_day(orch, day)
            fill_count += int(result.get("fills", 0) or 0)

        marks = dict(orch.last_marks)
        await closing_snapshot.write_closing_snapshot(orch, marks)

        events, agents_active = await _build_events_from_db(session_id)
    finally:
        reset_session_id(token)

    ended_at = datetime.now(timezone.utc).isoformat()

    manifest = SessionManifest(
        session_id=session_id,
        date_range=[start_date.isoformat(), end_date.isoformat()],
        started_at=started_at,
        ended_at=ended_at,
        trading_days=[d.isoformat() for d in trading_days],
        tick_count=len(trading_days),
        fill_count=fill_count,
        agents_active=agents_active,
        events=events,
    )

    manifest_path = out_dir / session_id / "manifest.json"
    write_manifest(manifest, manifest_path)

    # The three new fields (rivalries, lowest_ranks, strategy_rollup)
    # live alongside the SessionManifest dataclass but aren't part of
    # its schema — `manifest.py` is owned by the platform team. We
    # post-process the JSON file in-place so the round-trip contract for
    # `manifest.json` stays the canonical source of truth.
    rivalries = _compute_rivalries(events, top_n=_RIVALRY_TOP_N)
    strategy_rollup = _compute_strategy_rollup(orch, marks)
    _merge_manifest_extras(
        manifest_path,
        rivalries=rivalries,
        lowest_ranks=lowest_ranks,
        strategy_rollup=strategy_rollup,
    )

    return manifest_path


async def _build_events_from_db(session_id: str) -> tuple[list[SessionEvent], int]:
    """Query trades + agent_notes for the session_id, build the flat
    event list sorted by timestamp. Returns (events, agents_active_count).

    Implementation outline for the agent:
    - Use tradefarm.storage.db.SessionLocal and tradefarm.storage.models.
    - Query Trade rows WHERE session_id = ?, JOIN Agent for name.
      Build "fill" events with payload = {symbol, side, qty, price,
      notional, reason}.
    - Query AgentNote rows WHERE session_id = ?, JOIN Agent for name.
      Build "decision" events with payload = {kind, symbol, content,
      metadata}. Skip notes with kind="observation" if they bloat the
      manifest — they're internal.
    - Sort all events by t ascending.
    - agents_active = count of DISTINCT agent_ids that appear in any
      Trade or non-observation AgentNote row for this session.
    """
    events: list[SessionEvent] = []
    active_agent_ids: set[int] = set()

    async with SessionLocal() as session:
        trade_rows = (
            await session.execute(
                select(Trade, Agent.name)
                .join(Agent, Trade.agent_id == Agent.id)
                .where(Trade.session_id == session_id)
            )
        ).all()

        for trade, agent_name in trade_rows:
            active_agent_ids.add(trade.agent_id)
            notional = abs(float(trade.qty) * float(trade.price))
            events.append(
                SessionEvent(
                    t=trade.executed_at.isoformat(),
                    kind="fill",
                    agent_id=trade.agent_id,
                    agent_name=agent_name,
                    payload={
                        "symbol": trade.symbol,
                        "side": trade.side,
                        # DB Numeric columns are Decimal; the manifest is a
                        # JSON-number contract (replay_query / frontend), so
                        # convert at this serialization boundary.
                        "qty": float(trade.qty),
                        "price": float(trade.price),
                        "notional": notional,
                        "reason": trade.reason,
                    },
                )
            )

        note_rows = (
            await session.execute(
                select(AgentNote, Agent.name)
                .join(Agent, AgentNote.agent_id == Agent.id)
                .where(
                    AgentNote.session_id == session_id,
                    AgentNote.kind != "observation",
                )
            )
        ).all()

        for note, agent_name in note_rows:
            active_agent_ids.add(note.agent_id)
            events.append(
                SessionEvent(
                    t=note.created_at.isoformat(),
                    kind="decision",
                    agent_id=note.agent_id,
                    agent_name=agent_name,
                    payload={
                        "kind": note.kind,
                        "symbol": note.symbol,
                        "content": note.content,
                        "metadata": note.note_metadata,
                    },
                )
            )

    events.sort(key=lambda e: e.t)
    return events, len(active_agent_ids)


async def _snapshot_intern_cast(*, limit: int) -> list[dict[str, Any]]:
    """Return up to `limit` intern cast rows for the "Intern Watch"
    episode, sorted by current cash ascending (lowest first) and
    agent_id as tiebreaker for deterministic output.

    Each row: {agent_id, name, rank, rank_index, strategy,
    starting_capital}. The `rank_index` is the position in
    `academy.RANK_ORDER` (0=intern, 1=junior, 2=senior, 3=principal)
    so downstream consumers can group/sort by rank without re-parsing
    the string.

    Returns an empty list if the DB is unreachable (e.g. a fresh
    fixture) — the manifest still round-trips, the field is just empty.
    """
    rank_idx: dict[str, int] = {r: i for i, r in enumerate(RANK_ORDER)}
    try:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(
                        Agent.id,
                        Agent.name,
                        Agent.rank,
                        Agent.strategy,
                        Agent.starting_capital,
                        Agent.cash,
                    )
                    .where(Agent.rank == "intern")
                    .order_by(Agent.cash.asc(), Agent.id.asc())
                    .limit(max(0, limit))
                )
            ).all()
    except Exception:
        return []
    out: list[dict[str, Any]] = []
    for agent_id, name, rank, strategy, starting_capital, _cash in rows:
        out.append(
            {
                "agent_id": int(agent_id),
                "name": str(name),
                "rank": str(rank),
                "rank_index": rank_idx.get(str(rank), 0),
                "strategy": str(strategy),
                "starting_capital": float(starting_capital or 0.0),
            }
        )
    return out


def _compute_rivalries(
    events: list[SessionEvent],
    *,
    top_n: int = _RIVALRY_TOP_N,
    min_occurrences: int = _RIVALRY_MIN_OCCURRENCES,
    window_min: float = _RIVALRY_WINDOW_MIN,
) -> list[dict[str, Any]]:
    """Top-N rivalry triples for the manifest. Mirrors the beat
    detector's logic but emits plain dicts (no Beat wrapper) so the
    manifest schema stays simple.

    Each entry: {a, b, symbol, count, a_pnl, b_pnl}. PnL is the
    average-cost realised PnL per agent on the day's fills.

    The "count" field is the number of distinct (buy, sell) crossings
    — min(buys_by_a, sells_by_b, ...) — the same definition the beat
    detector uses. With 4 buys by alice and 4 sells by bob on the
    same symbol, count=4 (not 16). The studio headline reads
    "X and Y, fourth time today" which the audience reads as
    "4 distinct moments".
    """
    # Reuse the beat detector's internal _Fill projection by wrapping
    # events in the same shape. The detector does the same walk.
    manifest_for_scoring: dict[str, Any] = {"events": [e.__dict__ for e in events]}
    fills = _fills(manifest_for_scoring)
    pnls = _agent_pnl_from_fills(fills) if fills else {}

    by_symbol: dict[str, list[Any]] = {}
    for f in fills:
        if not f.symbol or f.side not in ("buy", "sell"):
            continue
        by_symbol.setdefault(f.symbol, []).append(f)

    window = timedelta(minutes=window_min)
    # Per (lo_agent, hi_agent, symbol) bucket: per-agent timestamp list.
    buckets: dict[tuple[int, int, str], dict[int, list[Any]]] = {}

    for sym, group in by_symbol.items():
        group_sorted = sorted(group, key=lambda f: f.t)
        for f in group_sorted:
            for g in group_sorted:
                if f.idx == g.idx:
                    continue
                if f.agent_id == g.agent_id:
                    continue
                if f.side == g.side:
                    continue
                if abs((f.t - g.t).total_seconds()) > window.total_seconds():
                    continue
                lo, hi = sorted((f.agent_id, g.agent_id))
                key = (lo, hi, sym)
                side_bucket = buckets.setdefault(key, {lo: [], hi: []})
                side_bucket[f.agent_id].append(f.t)

    # count = min(lo_count, hi_count) for each bucket. Sort desc by
    # count, ties broken by latest activity so the freshest rivalry
    # wins.
    EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
    ranked: list[tuple[tuple[int, int, str], int, Any]] = []
    for key, per_agent in buckets.items():
        per_agent_dedup = {a: sorted(set(ts)) for a, ts in per_agent.items()}
        lo, hi, _ = key
        lo_n = len(per_agent_dedup.get(lo, []))
        hi_n = len(per_agent_dedup.get(hi, []))
        count = min(lo_n, hi_n)
        all_ts = per_agent_dedup.get(lo, []) + per_agent_dedup.get(hi, [])
        latest = max(all_ts) if all_ts else EPOCH
        ranked.append((key, count, latest))
    ranked.sort(key=lambda x: (x[1], x[2]), reverse=True)

    out: list[dict[str, Any]] = []
    for (lo, hi, sym), count, _ in ranked:
        if count < min_occurrences:
            continue
        a_pnl = float(pnls[lo].realized) if lo in pnls else 0.0
        b_pnl = float(pnls[hi].realized) if hi in pnls else 0.0
        out.append(
            {
                "a": int(lo),
                "b": int(hi),
                "symbol": sym,
                "count": int(count),
                "a_pnl": round(a_pnl, 4),
                "b_pnl": round(b_pnl, 4),
            }
        )
        if len(out) >= top_n:
            break
    return out


def _compute_strategy_rollup(
    orch: Orchestrator,
    marks: dict[str, float],
) -> dict[str, StrategyRollup]:
    """Per-strategy aggregate at session end. Mirrors
    `web/src/vod/types.ts:StrategyRollup`. Equity is `cash + Σqty*mark`
    for each position; PnL is the realised-only delta (so the field
    matches the headless renderer's "P&L at end" card). Fills is the
    count of open positions per strategy at end-of-session; the
    per-strategy fill count would require a DB hit which we skip to
    keep the manifest write offline (the field stays useful as a
    "how many positions did the strategy leave open" signal).

    Empty cohort (no agents, or orchestrator was built with zero
    rows) returns an empty dict.
    """
    out: dict[str, StrategyRollup] = {}
    by_strat: dict[str, list[Any]] = {}
    for agent in orch.agents:
        strat = getattr(agent.state, "strategy", "unknown") or "unknown"
        by_strat.setdefault(strat, []).append(agent)

    for strat, group in by_strat.items():
        agents_count = len(group)
        equity_total = 0.0
        realised_total = 0.0
        positions_count = 0
        for agent in group:
            book = agent.state.book
            cash = float(book.cash)
            realised = float(book.realized_pnl)
            unrealized = 0.0
            for sym, pos in book.positions.items():
                qty = float(pos.qty)
                mark = marks.get(sym, float(pos.avg_price))
                unrealized += qty * mark
                positions_count += 1
            equity_total += cash + unrealized
            realised_total += realised
        allocated = agents_count * 1000.0
        pnl_pct = (realised_total / allocated * 100.0) if allocated > 0 else 0.0
        out[strat] = StrategyRollup(
            agents=agents_count,
            equity=round(equity_total, 4),
            pnl=round(realised_total, 4),
            pnlPct=round(pnl_pct, 4),
            fills=positions_count,
        )
    return out


def _merge_manifest_extras(
    manifest_path: Path,
    *,
    rivalries: list[dict[str, Any]],
    lowest_ranks: list[dict[str, Any]],
    strategy_rollup: dict[str, StrategyRollup],
) -> None:
    """Add the three new top-level fields to a manifest.json file
    in-place. The function reads, mutates, writes — single-writer
    guarantees hold because the runner is a single async process.

    `lowest_ranks` is the full Intern Watch cast list
    ({agent_id, name, rank, rank_index, strategy, starting_capital});
    the legacy `interns_under_watch: list[int]` field is kept as a
    derived list of agent_ids for back-compat with the round-8 studio
    surface and any other consumer that read the older field name.
    """
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["rivalries"] = rivalries
    data["lowest_ranks"] = lowest_ranks
    data["interns_under_watch"] = [r["agent_id"] for r in lowest_ranks]
    data["strategy_rollup"] = {
        k: {
            "agents": v.agents,
            "equity": v.equity,
            "pnl": v.pnl,
            "pnlPct": v.pnlPct,
            "fills": v.fills,
        }
        for k, v in strategy_rollup.items()
    }
    manifest_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _parse_date_arg(s: str) -> date:
    return date.fromisoformat(s)


def _parse_date_range(s: str) -> tuple[date, date]:
    if ":" not in s:
        raise argparse.ArgumentTypeError("date-range must be START:END (ISO 8601)")
    a, b = s.split(":", 1)
    return _parse_date_arg(a), _parse_date_arg(b)


def main() -> None:
    """argparse entry point.

    Implementation outline for the agent:
    - Mutually exclusive: --date OR --date-range
    - --speed accepts only "asap" in v0; raise on anything else (with a
      helpful message naming Phase 1.5 as the planned home for 10x/realtime)
    - --session-id: default "auto" → generate "s_<YYYY-MM-DD>_<6-hex>"
      where the date is the start of the range
    - --out: default Path("out/sessions")
    - Print the session_id and manifest path on success
    - Use asyncio.run(run_session(...))
    """
    parser = argparse.ArgumentParser(
        prog="tradefarm.session.run",
        description="Replay historical trading days through the orchestrator.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--date",
        type=_parse_date_arg,
        help="Single ISO date to replay (e.g. 2026-05-15).",
    )
    group.add_argument(
        "--date-range",
        type=_parse_date_range,
        help="ISO date range START:END inclusive (e.g. 2026-05-12:2026-05-16).",
    )
    parser.add_argument(
        "--speed",
        default="asap",
        choices=["asap"],
        help="Replay speed. Only 'asap' is supported in v0; 10x / realtime "
        "are planned for Phase 1.5.",
    )
    parser.add_argument(
        "--session-id",
        default="auto",
        help="Session id. 'auto' generates s_<YYYY-MM-DD>_<6-hex>.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Output directory for the manifest tree.",
    )
    args = parser.parse_args()

    if args.date is not None:
        start_date = args.date
        end_date = args.date
    else:
        start_date, end_date = args.date_range

    session_id = args.session_id
    if session_id == "auto":
        session_id = f"s_{start_date.isoformat()}_{uuid.uuid4().hex[:6]}"

    manifest_path = asyncio.run(
        run_session(
            start_date=start_date,
            end_date=end_date,
            session_id=session_id,
            out_dir=args.out,
        )
    )

    print(f"session_id={session_id}\nmanifest={manifest_path}")


if __name__ == "__main__":
    main()
