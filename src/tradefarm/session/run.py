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
"""

from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select

from tradefarm.market.hours import NYSE
from tradefarm.orchestrator.scheduler import Orchestrator
from tradefarm.runtime.session_context import reset_session_id, set_session_id
from tradefarm.session import closing_snapshot, replay
from tradefarm.session.manifest import SessionEvent, SessionManifest, write_manifest
from tradefarm.storage.db import SessionLocal, init_db
from tradefarm.storage.models import Agent, AgentNote, Trade


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
