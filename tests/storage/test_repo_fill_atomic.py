"""Tests for ``repo.record_fill_atomic`` — single-transaction fill persistence.

ISSUE #8c: the in-tick fill path used to call ``record_trade`` then
``sync_positions`` in two SEPARATE async sessions, so a crash between them
left the DB with a trade row but stale positions (or vice versa).
``record_fill_atomic`` writes both in ONE transaction. These tests assert the
trade row and the position rows are persisted together, and that a duplicate
``broker_order_id`` doesn't create a second trade row.

Uses a per-test in-memory SQLite DB (no network, no real broker).
"""

from __future__ import annotations

import pytest_asyncio
from sqlalchemy import func, select


@pytest_asyncio.fixture
async def repo_db(monkeypatch):
    """Point SessionLocal/engine at a fresh in-memory SQLite DB for this test."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.storage.db as db_mod
    import tradefarm.storage.repo as repo_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as s:
        s.add(
            Agent(
                id=1,
                name="agent-001",
                strategy="momentum_sma20",
                starting_capital=1000.0,
                cash=1000.0,
                status="waiting",
            )
        )
        await s.commit()

    yield SessionLocal
    await engine.dispose()


def _book_with_position(agent_id: int, symbol: str, qty: float, avg: float):
    """Build a VirtualBook holding one open position."""
    from tradefarm.execution.virtual_book import VirtualBook

    book = VirtualBook(agent_id=agent_id, cash=1000.0)
    book.record_fill(symbol, "buy", qty, avg)
    return book


async def test_record_fill_atomic_writes_trade_and_positions(repo_db):
    """The Trade row and the synced Position rows are both persisted."""
    from tradefarm.storage import repo
    from tradefarm.storage.models import Position, Trade

    book = _book_with_position(1, "SPY", 10, 400.0)
    await repo.record_fill_atomic(
        agent_id=1,
        book=book,
        symbol="SPY",
        side="buy",
        qty=10,
        price=400.0,
        reason="entry",
        broker_order_id="broker-fill-1",
    )

    async with repo_db() as s:
        trades = (await s.execute(select(Trade))).scalars().all()
        positions = (await s.execute(select(Position))).scalars().all()

    assert len(trades) == 1
    assert trades[0].symbol == "SPY"
    assert trades[0].broker_order_id == "broker-fill-1"
    assert len(positions) == 1
    assert positions[0].symbol == "SPY"
    assert positions[0].qty == 10
    assert positions[0].avg_price == 400.0


async def test_record_fill_atomic_replaces_stale_positions(repo_db):
    """sync semantics: a flat book wipes the agent's prior position rows."""
    from tradefarm.storage import repo
    from tradefarm.storage.models import Position

    # Open then fully close: the book is now flat for SPY.
    open_book = _book_with_position(1, "SPY", 10, 400.0)
    await repo.record_fill_atomic(
        1, open_book, "SPY", "buy", 10, 400.0, "entry", broker_order_id="b-open"
    )

    open_book.record_fill("SPY", "sell", 10, 420.0)
    await repo.record_fill_atomic(
        1, open_book, "SPY", "sell", 10, 420.0, "exit", broker_order_id="b-close"
    )

    async with repo_db() as s:
        positions = (await s.execute(select(Position))).scalars().all()
    assert positions == []  # flat book → no position rows persisted


async def test_duplicate_broker_order_id_is_deduped(repo_db):
    """A second atomic write with the same broker_order_id is a silent no-op.

    Both the duplicate trade row AND the duplicate position-sync roll back, so
    the count stays at one trade.
    """
    from tradefarm.storage import repo
    from tradefarm.storage.models import Trade

    oid = "broker-dup-8c"
    book = _book_with_position(1, "SPY", 10, 400.0)
    await repo.record_fill_atomic(
        1, book, "SPY", "buy", 10, 400.0, "optimistic", broker_order_id=oid
    )
    # Reconcile path / restart replay writes the same fill again.
    await repo.record_fill_atomic(
        1, book, "SPY", "buy", 10, 401.5, "reconciled_fill", broker_order_id=oid
    )

    async with repo_db() as s:
        count = int(
            (
                await s.execute(select(func.count(Trade.id)).where(Trade.broker_order_id == oid))
            ).scalar_one()
        )
    assert count == 1


async def test_null_broker_order_id_allows_multiple_rows(repo_db):
    """NULL broker_order_id skips dedupe — the partial UNIQUE index ignores NULLs."""
    from tradefarm.storage import repo
    from tradefarm.storage.models import Trade

    book = _book_with_position(1, "SPY", 10, 400.0)
    await repo.record_fill_atomic(1, book, "SPY", "buy", 10, 400.0, "sim")
    await repo.record_fill_atomic(1, book, "SPY", "buy", 10, 400.0, "sim")

    async with repo_db() as s:
        count = int((await s.execute(select(func.count(Trade.id)))).scalar_one())
    assert count == 2
