"""Tests for the 0.20.0 ``StrategyDailyAttribution`` snapshot module.

The module is a thin wrapper over ``pnl_snapshots``: it aggregates
one day, then upserts into the snapshot table. Tests run against a
per-test temp-file SQLite so the upsert + read path is exercised
end-to-end (no mocks for the DB).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import tradefarm.storage.db as db_mod
import tradefarm.storage.repo as repo_mod
from tradefarm.storage.models import Agent, Base, PnlSnapshot, Trade
from tradefarm.storage.strategy_attribution import (
    compute_and_store_for_date,
    live_strategy_attribution,
    read_attribution_rows,
    upsert_attribution_rows,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def attribution_db(monkeypatch, tmp_path):
    """Per-test temp-file SQLite so the snapshot table is observable.

    The fixture mirrors the ``recap_db`` / ``daily_recap_db`` shape:
    point ``db.engine`` + ``db.SessionLocal`` + ``repo.SessionLocal``
    at a fresh file-backed DB, ``create_all`` registers the
    ``StrategyDailyAttribution`` model, and dispose the engine on
    teardown so the next test gets a clean slate.
    """
    url = f"sqlite+aiosqlite:///{tmp_path / 'attribution.db'}"
    engine = create_async_engine(url, echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine
    await engine.dispose()


async def _seed_agent(
    session: AsyncSession, name: str, strategy: str
) -> Agent:
    a = Agent(
        name=name,
        strategy=strategy,
        starting_capital=1000,
        cash=1000,
    )
    session.add(a)
    await session.flush()
    return a


async def _seed_snapshot(
    session: AsyncSession,
    agent_id: int,
    *,
    equity: float,
    realized: float,
    unrealized: float,
    taken_at: datetime,
) -> None:
    s = PnlSnapshot(
        agent_id=agent_id,
        equity=equity,
        realized_pnl=realized,
        unrealized_pnl=unrealized,
        taken_at=taken_at,
    )
    session.add(s)


async def _seed_trade(
    session: AsyncSession,
    agent_id: int,
    *,
    executed_at: datetime,
) -> None:
    t = Trade(
        agent_id=agent_id,
        symbol="NVDA",
        side="buy",
        qty=1,
        price=100.0,
        executed_at=executed_at,
        reason="test",
    )
    session.add(t)


# ---------------------------------------------------------------------------
# live_strategy_attribution
# ---------------------------------------------------------------------------


async def test_live_aggregation_with_no_snapshots(attribution_db) -> None:
    rows = await live_strategy_attribution(__import__("datetime").date(2026, 8, 4))
    assert rows == []


async def test_live_aggregation_groups_by_strategy(attribution_db) -> None:
    day = __import__("datetime").date(2026, 8, 4)
    async with db_mod.SessionLocal() as session:
        a1 = await _seed_agent(session, "mom-001", "momentum_sma20")
        a2 = await _seed_agent(session, "mom-002", "momentum_sma20")
        a3 = await _seed_agent(session, "lstm-001", "lstm_v1")
        await _seed_snapshot(
            session, a1.id, equity=1100, realized=50, unrealized=50, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await _seed_snapshot(
            session, a2.id, equity=900, realized=-100, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await _seed_snapshot(
            session, a3.id, equity=1200, realized=200, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await session.commit()

    rows = await live_strategy_attribution(day)
    by_strat = {r["strategy"]: r for r in rows}
    assert set(by_strat) == {"momentum_sma20", "lstm_v1"}
    mom = by_strat["momentum_sma20"]
    assert mom["agent_count"] == 2
    assert mom["equity_total"] == 2000.0
    assert mom["realized_pnl_total"] == -50.0
    assert mom["unrealized_pnl_total"] == 50.0
    # 1 winner (a1: realized+unrealized=100>0), 1 loser (a2: -100)
    assert mom["win_rate"] == 0.5
    lstm = by_strat["lstm_v1"]
    assert lstm["agent_count"] == 1
    assert lstm["win_rate"] == 1.0


async def test_live_aggregation_takes_latest_snapshot_per_agent(attribution_db) -> None:
    day = __import__("datetime").date(2026, 8, 4)
    async with db_mod.SessionLocal() as session:
        a = await _seed_agent(session, "mom-001", "momentum_sma20")
        # Two snapshots for the same agent on the same day: only the
        # latest (20:00) should count.
        await _seed_snapshot(
            session, a.id, equity=1000, realized=0, unrealized=0, taken_at=datetime(2026, 8, 4, 16, 0, tzinfo=timezone.utc)
        )
        await _seed_snapshot(
            session, a.id, equity=1100, realized=100, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await session.commit()

    rows = await live_strategy_attribution(day)
    assert len(rows) == 1
    assert rows[0]["equity_total"] == 1100.0
    assert rows[0]["realized_pnl_total"] == 100.0


async def test_live_aggregation_excludes_replay_snapshots(attribution_db) -> None:
    day = __import__("datetime").date(2026, 8, 4)
    async with db_mod.SessionLocal() as session:
        a = await _seed_agent(session, "mom-001", "momentum_sma20")
        live = PnlSnapshot(
            agent_id=a.id, equity=1100, realized_pnl=100, unrealized_pnl=0,
            taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc), session_id=None,
        )
        replay = PnlSnapshot(
            agent_id=a.id, equity=9999, realized_pnl=999, unrealized_pnl=0,
            taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc), session_id="sess-1",
        )
        session.add_all([live, replay])
        await session.commit()

    rows = await live_strategy_attribution(day)
    assert rows[0]["equity_total"] == 1100.0
    assert rows[0]["realized_pnl_total"] == 100.0


# ---------------------------------------------------------------------------
# upsert + read
# ---------------------------------------------------------------------------


async def test_upsert_then_read_round_trip(attribution_db) -> None:
    day = __import__("datetime").date(2026, 8, 4)
    rows = [
        {
            "strategy": "momentum_sma20",
            "agent_count": 2,
            "realized_pnl_total": -50.0,
            "unrealized_pnl_total": 50.0,
            "equity_total": 2000.0,
            "trades_today": 5,
            "win_rate": 0.5,
            "best_agent_name": "mom-001",
            "worst_agent_name": "mom-002",
        },
        {
            "strategy": "lstm_v1",
            "agent_count": 1,
            "realized_pnl_total": 200.0,
            "unrealized_pnl_total": 0.0,
            "equity_total": 1200.0,
            "trades_today": 1,
            "win_rate": 1.0,
            "best_agent_name": "lstm-001",
            "worst_agent_name": "lstm-001",
        },
    ]
    n = await upsert_attribution_rows(day, rows)
    assert n == 2
    out = await read_attribution_rows(day, day)
    assert len(out) == 2
    by_strat = {r["strategy"]: r for r in out}
    assert by_strat["momentum_sma20"]["agent_count"] == 2
    assert by_strat["lstm_v1"]["win_rate"] == 1.0
    assert all(r["date"] == "2026-08-04" for r in out)
    assert all(r["computed_at"] for r in out)


async def test_upsert_replaces_same_day_row(attribution_db) -> None:
    """The composite PK is (date, strategy). A second write for the
    same day+strategy replaces the row rather than appending a
    duplicate (the SQLite ON CONFLICT DO UPDATE path).
    """
    day = __import__("datetime").date(2026, 8, 4)
    await upsert_attribution_rows(
        day,
        [
            {
                "strategy": "momentum_sma20",
                "agent_count": 1, "realized_pnl_total": 0.0, "unrealized_pnl_total": 0.0,
                "equity_total": 1000.0, "trades_today": 0, "win_rate": 0.0,
                "best_agent_name": None, "worst_agent_name": None,
            }
        ],
    )
    # Same day, different numbers. Should overwrite.
    await upsert_attribution_rows(
        day,
        [
            {
                "strategy": "momentum_sma20",
                "agent_count": 3, "realized_pnl_total": 333.0, "unrealized_pnl_total": 0.0,
                "equity_total": 3333.0, "trades_today": 7, "win_rate": 0.66,
                "best_agent_name": "x", "worst_agent_name": "y",
            }
        ],
    )
    out = await read_attribution_rows(day, day)
    assert len(out) == 1
    assert out[0]["equity_total"] == 3333.0
    assert out[0]["trades_today"] == 7


async def test_read_filters_by_date_window(attribution_db) -> None:
    """Multi-day read: a [start, end] window only returns rows
    within the inclusive bounds.
    """
    for d in ("2026-08-01", "2026-08-02", "2026-08-03", "2026-08-05"):
        day = __import__("datetime").date.fromisoformat(d)
        await upsert_attribution_rows(
            day,
            [
                {
                    "strategy": "momentum_sma20",
                    "agent_count": 1, "realized_pnl_total": 0.0, "unrealized_pnl_total": 0.0,
                    "equity_total": float(d[-1]), "trades_today": 0, "win_rate": 0.0,
                    "best_agent_name": None, "worst_agent_name": None,
                }
            ],
        )
    start = __import__("datetime").date(2026, 8, 2)
    end = __import__("datetime").date(2026, 8, 3)
    out = await read_attribution_rows(start, end)
    assert {r["date"] for r in out} == {"2026-08-02", "2026-08-03"}


async def test_upsert_empty_clears_existing_rows(attribution_db) -> None:
    """Defensive: a day with no strategies (e.g. fresh DB before
    any agents ran) should clear any stale rows from a prior
    run, not leave them in place.
    """
    day = __import__("datetime").date(2026, 8, 4)
    await upsert_attribution_rows(
        day,
        [
            {
                "strategy": "momentum_sma20",
                "agent_count": 1, "realized_pnl_total": 0.0, "unrealized_pnl_total": 0.0,
                "equity_total": 1000.0, "trades_today": 0, "win_rate": 0.0,
                "best_agent_name": None, "worst_agent_name": None,
            }
        ],
    )
    n = await upsert_attribution_rows(day, [])
    assert n == 0
    out = await read_attribution_rows(day, day)
    assert out == []


# ---------------------------------------------------------------------------
# compute_and_store_for_date
# ---------------------------------------------------------------------------


async def test_compute_and_store_end_to_end(attribution_db) -> None:
    """The end-to-end helper: seed pnl_snapshots, call
    compute_and_store_for_date, verify the snapshot table has the
    expected rows.
    """
    day = __import__("datetime").date(2026, 8, 4)
    async with db_mod.SessionLocal() as session:
        a1 = await _seed_agent(session, "mom-001", "momentum_sma20")
        a2 = await _seed_agent(session, "lstm-001", "lstm_v1")
        await _seed_snapshot(
            session, a1.id, equity=1100, realized=100, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await _seed_snapshot(
            session, a2.id, equity=900, realized=-100, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await session.commit()

    n = await compute_and_store_for_date(day)
    assert n == 2
    out = await read_attribution_rows(day, day)
    by_strat = {r["strategy"]: r for r in out}
    assert by_strat["momentum_sma20"]["equity_total"] == 1100.0
    assert by_strat["lstm_v1"]["equity_total"] == 900.0


async def test_compute_and_store_is_idempotent_within_a_day(attribution_db) -> None:
    """Calling compute_and_store_for_date twice on the same day
    should produce a stable snapshot (not append duplicates).
    """
    day = __import__("datetime").date(2026, 8, 4)
    async with db_mod.SessionLocal() as session:
        a = await _seed_agent(session, "mom-001", "momentum_sma20")
        await _seed_snapshot(
            session, a.id, equity=1100, realized=100, unrealized=0, taken_at=datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
        )
        await session.commit()

    n1 = await compute_and_store_for_date(day)
    n2 = await compute_and_store_for_date(day)
    assert n1 == 1
    assert n2 == 1
    out = await read_attribution_rows(day, day)
    assert len(out) == 1
