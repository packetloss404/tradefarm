"""Session runner — manifest extras writer.

The runner now writes three new top-level keys onto manifest.json:
    rivalries
    interns_under_watch
    strategy_rollup

We don't spin up a real orchestrator + DB for these tests — that
path is covered by the existing tests/session/test_run.py. Instead
we test the helpers directly with synthetic data:

    - `_merge_manifest_extras()` writes the three new keys in-place
      onto an existing manifest.json (round-trip contract).
    - `_compute_rivalries()` returns the right shape.
    - `_compute_strategy_rollup()` returns the right shape.
    - `_snapshot_intern_cast()` queries the agent table.

The intern-cast query needs a real DB so we reuse the same SQLite
fixture pattern as tests/session/test_run.py.

Per the project's testing policy: 4+ tests, all pure except the
intern-cast one which needs the DB.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradefarm.session.manifest import SessionEvent, SessionManifest, write_manifest
from tradefarm.session.run import (
    StrategyRollup,
    _compute_rivalries,
    _compute_strategy_rollup,
    _merge_manifest_extras,
)


# ----- _merge_manifest_extras ----------------------------------------------


def _write_minimal_manifest(path: Path) -> None:
    """Write a SessionManifest-shaped JSON file the helper can read."""
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = SessionManifest(
        session_id="s_test",
        date_range=["2026-05-19", "2026-05-19"],
        started_at=datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc).isoformat(),
        ended_at=datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc).isoformat(),
        trading_days=["2026-05-19"],
        tick_count=1,
        fill_count=2,
        agents_active=2,
        events=[],
    )
    write_manifest(manifest, path)


def test_merge_manifest_extras_writes_three_top_level_keys(tmp_path: Path):
    """The new keys land in the JSON file under their canonical names."""
    manifest_path = tmp_path / "s_x" / "manifest.json"
    _write_minimal_manifest(manifest_path)
    _merge_manifest_extras(
        manifest_path,
        rivalries=[{"a": 1, "b": 2, "symbol": "NVDA", "count": 3, "a_pnl": 12.0, "b_pnl": -5.0}],
        lowest_ranks=[
            {"agent_id": 3, "name": "marcus_smith", "rank": "intern", "rank_index": 0,
             "strategy": "momentum_12_1", "starting_capital": 1000.0},
            {"agent_id": 7, "name": "lisa_garcia", "rank": "intern", "rank_index": 0,
             "strategy": "rsi2", "starting_capital": 1000.0},
        ],
        strategy_rollup={
            "momentum": StrategyRollup(agents=44, equity=44_000.0, pnl=120.0, pnlPct=0.27, fills=2),
            "lstm": StrategyRollup(agents=14, equity=14_000.0, pnl=-30.0, pnlPct=-0.21, fills=1),
        },
    )
    data = json.loads(manifest_path.read_text())
    # Original fields preserved
    assert data["session_id"] == "s_test"
    assert data["fill_count"] == 2
    # New fields land
    assert data["rivalries"] == [
        {"a": 1, "b": 2, "symbol": "NVDA", "count": 3, "a_pnl": 12.0, "b_pnl": -5.0}
    ]
    assert data["interns_under_watch"] == [3, 7]
    assert data["lowest_ranks"] == [
        {"agent_id": 3, "name": "marcus_smith", "rank": "intern", "rank_index": 0,
         "strategy": "momentum_12_1", "starting_capital": 1000.0},
        {"agent_id": 7, "name": "lisa_garcia", "rank": "intern", "rank_index": 0,
         "strategy": "rsi2", "starting_capital": 1000.0},
    ]
    assert data["strategy_rollup"] == {
        "momentum": {
            "agents": 44,
            "equity": 44_000.0,
            "pnl": 120.0,
            "pnlPct": 0.27,
            "fills": 2,
        },
        "lstm": {
            "agents": 14,
            "equity": 14_000.0,
            "pnl": -30.0,
            "pnlPct": -0.21,
            "fills": 1,
        },
    }


def test_merge_manifest_extras_round_trips_through_json(tmp_path: Path):
    """The merged JSON parses back to the same dict — no field drops,
    no float-precision loss beyond the explicit `round(..., 4)` we
    apply in `_compute_*`."""
    manifest_path = tmp_path / "s_x" / "manifest.json"
    _write_minimal_manifest(manifest_path)
    rivalries = [
        {"a": 1, "b": 2, "symbol": "AAPL", "count": 4, "a_pnl": 0.0, "b_pnl": 0.0},
    ]
    _merge_manifest_extras(
        manifest_path,
        rivalries=rivalries,
        lowest_ranks=[
            {"agent_id": 1, "name": "a_b", "rank": "intern", "rank_index": 0,
             "strategy": "momentum", "starting_capital": 1000.0},
            {"agent_id": 2, "name": "c_d", "rank": "intern", "rank_index": 0,
             "strategy": "momentum", "starting_capital": 1000.0},
            {"agent_id": 3, "name": "e_f", "rank": "intern", "rank_index": 0,
             "strategy": "momentum", "starting_capital": 1000.0},
        ],
        strategy_rollup={
            "momentum": StrategyRollup(agents=1, equity=1000.0, pnl=0.0, pnlPct=0.0, fills=0),
        },
    )
    data = json.loads(manifest_path.read_text())
    assert data["rivalries"] == rivalries
    # round-trip preserves ints (intern ids), floats (pnl), and the
    # string 'AAPL' in the symbol field.
    assert data["rivalries"][0]["symbol"] == "AAPL"
    assert data["lowest_ranks"][0]["agent_id"] == 1
    # back-compat: the round-8 `interns_under_watch` field stays as
    # the derived list of agent_ids from `lowest_ranks`.
    assert data["interns_under_watch"] == [1, 2, 3]


def test_merge_manifest_extras_handles_empty_inputs(tmp_path: Path):
    """Empty lists / dicts must still write the keys (with empty
    payloads) — the studio can't tell from a missing key whether
    the runner skipped the field or the data was empty."""
    manifest_path = tmp_path / "s_x" / "manifest.json"
    _write_minimal_manifest(manifest_path)
    _merge_manifest_extras(
        manifest_path,
        rivalries=[],
        lowest_ranks=[],
        strategy_rollup={},
    )
    data = json.loads(manifest_path.read_text())
    assert data["rivalries"] == []
    assert data["lowest_ranks"] == []
    # back-compat field also empty.
    assert data["interns_under_watch"] == []
    assert data["strategy_rollup"] == {}


# ----- _compute_rivalries --------------------------------------------------


def _ev(agent_id: int, name: str, symbol: str, side: str, t: str) -> SessionEvent:
    return SessionEvent(
        t=t,
        kind="fill",
        agent_id=agent_id,
        agent_name=name,
        payload={
            "symbol": symbol,
            "side": side,
            "qty": 10.0,
            "price": 100.0,
            "notional": 1000.0,
            "reason": "test",
        },
    )


def test_compute_rivalries_returns_top_two_by_count():
    """3 rivalries in the data → top 2 by occurrence count."""
    from datetime import timedelta

    base = datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc)
    events = [
        # Rivalry 1: alice vs bob, 4 crossings on NVDA (within 90 min)
        _ev(1, "alice", "NVDA", "buy", (base).isoformat()),
        _ev(2, "bob", "NVDA", "sell", (base + timedelta(minutes=5)).isoformat()),
        _ev(1, "alice", "NVDA", "buy", (base + timedelta(minutes=20)).isoformat()),
        _ev(2, "bob", "NVDA", "sell", (base + timedelta(minutes=25)).isoformat()),
        _ev(1, "alice", "NVDA", "buy", (base + timedelta(minutes=40)).isoformat()),
        _ev(2, "bob", "NVDA", "sell", (base + timedelta(minutes=45)).isoformat()),
        _ev(1, "alice", "NVDA", "buy", (base + timedelta(minutes=60)).isoformat()),
        _ev(2, "bob", "NVDA", "sell", (base + timedelta(minutes=65)).isoformat()),
        # Rivalry 2: carol vs dave, 3 crossings on AAPL
        _ev(3, "carol", "AAPL", "sell", (base + timedelta(minutes=10)).isoformat()),
        _ev(4, "dave", "AAPL", "buy", (base + timedelta(minutes=15)).isoformat()),
        _ev(3, "carol", "AAPL", "sell", (base + timedelta(minutes=20)).isoformat()),
        _ev(4, "dave", "AAPL", "buy", (base + timedelta(minutes=25)).isoformat()),
        _ev(3, "carol", "AAPL", "sell", (base + timedelta(minutes=30)).isoformat()),
        _ev(4, "dave", "AAPL", "buy", (base + timedelta(minutes=35)).isoformat()),
    ]
    rivalries = _compute_rivalries(events)
    assert len(rivalries) == 2
    # Higher count first.
    assert rivalries[0]["count"] == 4
    assert rivalries[0]["symbol"] == "NVDA"
    assert {rivalries[0]["a"], rivalries[0]["b"]} == {1, 2}
    assert rivalries[1]["count"] == 3
    assert rivalries[1]["symbol"] == "AAPL"
    # PnL keys are present even if 0.0.
    for r in rivalries:
        assert "a_pnl" in r
        assert "b_pnl" in r


def test_compute_rivalries_empty_events_returns_empty():
    assert _compute_rivalries([]) == []


# ----- _compute_strategy_rollup -------------------------------------------


def test_compute_strategy_rollup_groups_agents_by_strategy():
    """Per-strategy rollup aggregates agents + equity + realised pnl.
    Uses a fake orchestrator with two strategies."""

    class _Book:
        def __init__(self, cash: float, realized: float, positions: dict | None = None):
            self.cash = cash
            self.realized_pnl = realized
            self.positions = positions or {}

    class _Agent:
        def __init__(self, id: int, name: str, strategy: str, book: _Book):
            self.state = type("S", (), {"id": id, "name": name, "strategy": strategy, "book": book})()

    class _Orchestrator:
        def __init__(self, agents):
            self.agents = agents

    agents = [
        _Agent(1, "alice", "momentum_12_1", _Book(cash=1000.0, realized=10.0)),
        _Agent(2, "bob", "momentum_12_1", _Book(cash=1100.0, realized=20.0)),
        _Agent(3, "carol", "lstm", _Book(cash=900.0, realized=-15.0)),
    ]
    rollup = _compute_strategy_rollup(_Orchestrator(agents), marks={})
    assert "momentum_12_1" in rollup
    assert "lstm" in rollup
    # momentum_12_1: 2 agents, equity 1000+1100=2100, pnl 30, pnlPct = 30/2000*100 = 1.5
    assert rollup["momentum_12_1"].agents == 2
    assert rollup["momentum_12_1"].equity == 2100.0
    assert rollup["momentum_12_1"].pnl == 30.0
    assert rollup["momentum_12_1"].pnlPct == 1.5
    # lstm: 1 agent, equity 900, pnl -15, pnlPct = -15/1000*100 = -1.5
    assert rollup["lstm"].agents == 1
    assert rollup["lstm"].equity == 900.0
    assert rollup["lstm"].pnl == -15.0
    assert rollup["lstm"].pnlPct == -1.5


def test_compute_strategy_rollup_empty_orchestrator_returns_empty():
    class _Orchestrator:
        agents: list = []

    rollup = _compute_strategy_rollup(_Orchestrator(), marks={})
    assert rollup == {}


# ----- _snapshot_intern_cast (DB-backed) -----------------------------------


@pytest.fixture
async def session_smoke(monkeypatch, tmp_path):
    """Same fixture as tests/session/test_run.py — file-based SQLite
    so multiple async sessions share the same tables."""
    from sqlalchemy.ext.asyncio import (
        AsyncSession,
        async_sessionmaker,
        create_async_engine,
    )

    import tradefarm.storage.db as db_mod
    from tradefarm.storage.models import Base, Agent

    db_path = tmp_path / "session_smoke.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)

    # The intern cast helper reads the same SessionLocal imported in
    # tradefarm.session.run.
    import tradefarm.session.run as run_mod

    monkeypatch.setattr(run_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Insert 7 agents: 4 interns (varied cash) + 3 other ranks.
    # We set rank explicitly because the Agent model's server_default
    # fills the column with "intern" if the field is omitted — which
    # would defeat the cohort filter the production query uses.
    from decimal import Decimal

    async with SessionLocal() as session:
        session.add_all(
            [
                Agent(id=1, name="intern_a", strategy="momentum_12_1", starting_capital=Decimal("1000"), cash=Decimal("900"), status="waiting", rank="intern"),
                Agent(id=2, name="intern_b", strategy="momentum_12_1", starting_capital=Decimal("1000"), cash=Decimal("800"), status="waiting", rank="intern"),
                Agent(id=3, name="intern_c", strategy="lstm", starting_capital=Decimal("1000"), cash=Decimal("700"), status="waiting", rank="intern"),
                Agent(id=4, name="intern_d", strategy="momentum_12_1", starting_capital=Decimal("1000"), cash=Decimal("950"), status="waiting", rank="intern"),
                Agent(id=5, name="junior_a", strategy="momentum_12_1", starting_capital=Decimal("1000"), cash=Decimal("1100"), status="waiting", rank="junior"),
                Agent(id=6, name="senior_a", strategy="lstm", starting_capital=Decimal("1000"), cash=Decimal("1200"), status="waiting", rank="senior"),
                Agent(id=7, name="principal_a", strategy="lstm", starting_capital=Decimal("1000"), cash=Decimal("1300"), status="waiting", rank="principal"),
            ]
        )
        await session.commit()

    yield engine
    await engine.dispose()


async def test_snapshot_intern_cast_returns_five_lowest_equity_interns(session_smoke):
    from tradefarm.session.run import _snapshot_intern_cast

    cast = await _snapshot_intern_cast(limit=5)
    # 4 interns + 1 tiebreaker (4 < 5, so all 4 interns + nothing else)
    # Sorted by cash asc, then id asc. New shape: list of dicts.
    assert len(cast) == 4
    assert [r["agent_id"] for r in cast] == [3, 2, 1, 4]
    # Every row carries the full cast card shape.
    for row in cast:
        assert set(row.keys()) == {
            "agent_id",
            "name",
            "rank",
            "rank_index",
            "strategy",
            "starting_capital",
        }
        assert row["rank"] == "intern"
        assert row["rank_index"] == 0  # RANK_ORDER index for "intern"


async def test_snapshot_intern_cast_includes_name_and_strategy(session_smoke):
    """The cast card is what the studio + recap endpoint surface; the
    name + strategy fields must come back populated (not just ids)."""
    from tradefarm.session.run import _snapshot_intern_cast

    cast = await _snapshot_intern_cast(limit=5)
    assert all(r["name"] for r in cast), "name must be populated"
    assert all(r["strategy"] for r in cast), "strategy must be populated"


async def test_snapshot_intern_cast_limit_respected(session_smoke):
    from tradefarm.session.run import _snapshot_intern_cast

    cast = await _snapshot_intern_cast(limit=2)
    assert [r["agent_id"] for r in cast] == [3, 2]


async def test_snapshot_intern_cast_excludes_non_intern_ranks(session_smoke):
    """Only `rank == intern` agents are returned; seniors are filtered
    out even when they're the lowest-cash in the agent table."""
    from tradefarm.session.run import _snapshot_intern_cast

    cast = await _snapshot_intern_cast(limit=10)
    for row in cast:
        assert row["rank"] == "intern"
