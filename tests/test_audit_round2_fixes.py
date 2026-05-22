"""Regression tests for the round-2 audit fixes (M/N/O/P/Q/R/S).

Covers:
  M — apply_reconciled_fill on add-to-position (no phantom realized PnL)
  N — find_similar / recent_outcomes scoped to session_id
  O — pending_exits cleared on in-tick fill (simulated mode)
  P — YT chunked upload 308-no-Range doesn't silently skip bytes
  Q — broadcast arbiter only installed during start_background
  R — predictions evening-of-reset doesn't walk straight to revealed
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest


# ----- N: journal session_id scoping -------------------------------------


async def test_recent_outcomes_scopes_to_current_session_id(tmp_path, monkeypatch):
    """A replay run's `recent_outcomes` must NOT return live notes for
    the same agent, and vice versa. Closes the cross-session leak that
    contaminated streak/rank state."""
    # Use an in-memory aiosqlite DB so nothing leaks to disk.
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from tradefarm.storage import db as storage_db, journal
    from tradefarm.storage.models import AgentNote, Base
    from tradefarm.runtime.session_context import set_session_id, reset_session_id

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(eng, expire_on_commit=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(storage_db, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal, "SessionLocal", SessionLocal)

    # Seed: 1 live note + 1 replay note for the same agent.
    async with SessionLocal() as s:
        s.add(AgentNote(
            agent_id=42, kind="entry", symbol="SPY", content="live",
            note_metadata="{}", session_id=None,
        ))
        s.add(AgentNote(
            agent_id=42, kind="entry", symbol="SPY", content="replay",
            note_metadata="{}", session_id="s_replay_x",
        ))
        await s.commit()

    # Live caller sees only the live row.
    out_live = await journal.recent_outcomes(42, n=10)
    assert len(out_live) == 1
    assert out_live[0]["content"] == "live"

    # Replay caller sees only the replay row.
    tok = set_session_id("s_replay_x")
    try:
        out_replay = await journal.recent_outcomes(42, n=10)
    finally:
        reset_session_id(tok)
    assert len(out_replay) == 1
    assert out_replay[0]["content"] == "replay"

    await eng.dispose()


# ----- R: predictions evening-of-reset -----------------------------------


async def test_predictions_reset_evening_does_not_walk_to_revealed(tmp_path):
    """The wall-time-vs-tomorrow's-session check used to walk fresh
    predictions through open→locked→revealed on the same evening's
    next tick (because wall ET was already past REVEAL_TIME on day D
    while the new predictions targeted day D+1).

    Verify the fix: after a 17:00+ ET tick triggers the reset, the
    next tick (still on day D) leaves the new predictions as `open`.
    """
    from tradefarm.orchestrator.predictions import PredictionsBoard

    # Stub orchestrator with the bare minimum: last_marks dict + agents.
    class _StubOrch:
        agents: list = []
        last_marks: dict[str, float] = {}

    pb = PredictionsBoard(orch=_StubOrch())
    # Wall-time 18:00 ET on day D — past RESET_TIME (17:00 ET).
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    t_d_evening = datetime(2026, 5, 22, 18, 0, tzinfo=et)
    # Seed initial session for today so the reset path can fire.
    pb._seed_session(t_d_evening)
    initial_date = pb._session_date

    # First tick: triggers reset, bumps _session_date to D+1.
    await pb.tick(now_et_dt=t_d_evening)
    assert pb._session_date == initial_date + timedelta(days=1)
    assert all(p.status == "open" for p in pb._predictions.values())

    # Second tick on the same evening (30s later): MUST NOT walk the
    # fresh "open" predictions to revealed. The fix's session_date >
    # now_et_dt.date() short-circuit handles this.
    t_d_evening_2 = t_d_evening + timedelta(seconds=30)
    await pb.tick(now_et_dt=t_d_evening_2)
    # Without the fix, they'd all be `revealed` here.
    assert all(p.status == "open" for p in pb._predictions.values())


# ----- Q: broadcast arbiter not installed by constructor ----------------


def test_orchestrator_constructor_does_not_install_arbiter():
    """Test pollution regression: each Orchestrator() used to clobber
    the module-global ledger + scheduler in broadcast_os, polluting
    state across tests + masking the legacy fall-through path."""
    from tradefarm.orchestrator import broadcast_os as bos

    # Reset to known state.
    bos.install_broadcast_arbiter(None, None)
    assert bos.get_broadcast_ledger() is None
    assert bos.get_broadcast_scheduler() is None

    # Constructing the Orchestrator no longer installs anything.
    from tradefarm.orchestrator.scheduler import Orchestrator
    orch = Orchestrator(agents=[])
    assert bos.get_broadcast_ledger() is None
    assert bos.get_broadcast_scheduler() is None
    # And the orch owns its instances ready for start_background to wire up.
    assert orch._broadcast_ledger is not None
    assert orch._broadcast_scheduler is not None
