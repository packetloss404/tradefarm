"""Session runner integration smoke test.

Wires up the four session/ modules end-to-end:
  manifest + replay + closing_snapshot + run

Stubs EodhdClient so no network is hit and no real bars exist, so every
agent waits and no fills materialize. The point is to prove the
pipeline integrates — the manifest writes, the DB columns get the
session_id contextvar, no exceptions leak.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest_asyncio


@pytest_asyncio.fixture
async def session_smoke(monkeypatch, tmp_path):
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod
    import tradefarm.storage.repo as repo_mod
    from tradefarm.storage.models import Base

    # File-based SQLite avoids the per-connection-DB quirk of :memory:
    # — multiple async sessions all see the same tables.
    db_path = tmp_path / "session_smoke.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    # Tiny roster + no LLM credentials so the overlay falls back to None
    # and lstm_llm slots degrade to momentum cleanly.
    from tradefarm.config import settings

    monkeypatch.setattr(settings, "agent_count", 3)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "minimax_api_key", "")

    # Force every agent slot to momentum by making model_path always miss.
    import tradefarm.orchestrator.scheduler as scheduler_mod

    monkeypatch.setattr(scheduler_mod, "model_path", lambda symbol: Path("/nonexistent-models"))

    # Stub EODHD so no network and the orchestrator gets empty bars
    # (which means no marks, no fills, but everything else still runs).
    from tradefarm.data import eodhd

    async def empty_bars(self, symbol, *, start, end, exchange="US"):
        return pd.DataFrame()

    monkeypatch.setattr(eodhd.EodhdClient, "get_eod", empty_bars)

    # Pre-create schema. run_session calls init_db itself, but doing it
    # here too means table-creation errors surface in the fixture, not in
    # the asserted code.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


async def test_runner_single_day_produces_manifest(session_smoke, tmp_path):
    from tradefarm.session.run import run_session

    out_dir = tmp_path / "sessions"
    day = date(2026, 5, 15)  # Friday — real NYSE trading day

    manifest_path = await run_session(
        start_date=day,
        end_date=day,
        session_id="s_smoke_test",
        out_dir=out_dir,
    )

    assert manifest_path == out_dir / "s_smoke_test" / "manifest.json"
    assert manifest_path.exists()

    data = json.loads(manifest_path.read_text())
    assert data["session_id"] == "s_smoke_test"
    assert data["date_range"] == ["2026-05-15", "2026-05-15"]
    assert data["trading_days"] == ["2026-05-15"]
    assert data["tick_count"] == 1
    assert data["fill_count"] == 0
    assert isinstance(data["events"], list)
    # No bars => no fills => no fill events; decision events may still
    # exist if any momentum agent emitted an "observation" — but the
    # builder skips observation kind, so events should be empty.
    fill_events = [e for e in data["events"] if e["kind"] == "fill"]
    assert fill_events == []
    # started_at / ended_at are real wall-clock ISO timestamps
    assert "T" in data["started_at"]
    assert "T" in data["ended_at"]


async def test_runner_refuses_weekend(session_smoke, tmp_path):
    """Audit fix (round 4 X1): a weekend-only date range used to
    silently write an empty manifest. Operator saw `session_id=…` +
    zero fills with no clue why. Runner now refuses with SystemExit
    so the operator gets a loud "no trading days" message instead."""
    import pytest

    from tradefarm.session.run import run_session

    out_dir = tmp_path / "sessions"
    saturday = date(2026, 5, 16)
    sunday = date(2026, 5, 17)

    with pytest.raises(SystemExit, match="no NYSE trading days"):
        await run_session(
            start_date=saturday,
            end_date=sunday,
            session_id="s_weekend_test",
            out_dir=out_dir,
        )


async def test_runner_refuses_future_date(session_smoke, tmp_path):
    """Future dates also fail-loud (round 4 X1)."""
    import pytest

    from tradefarm.session.run import run_session

    far_future = date(2099, 12, 25)
    with pytest.raises(SystemExit, match="future date"):
        await run_session(
            start_date=far_future,
            end_date=far_future,
            session_id="s_future_test",
            out_dir=tmp_path / "sessions",
        )
