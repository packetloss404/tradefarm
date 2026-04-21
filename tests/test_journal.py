"""Phase 1 (Agent Academy) journal tests.

Uses a per-test in-memory SQLite DB so writes don't leak into the dev DB.
The settings' ``database_url`` is patched to an in-process SQLite; each test
recreates tables from scratch.
"""
from __future__ import annotations

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def journal_db(monkeypatch):
    """Point SessionLocal/engine at a fresh in-memory SQLite DB for this test."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch both the db module *and* the journal module's already-imported reference.
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed one agent row so journal writes are not skipped.
    async with SessionLocal() as s:
        s.add(Agent(id=1, name="agent-001", strategy="lstm_llm_v1",
                    starting_capital=1000.0, cash=1000.0, status="waiting"))
        await s.commit()

    yield SessionLocal
    await engine.dispose()


async def test_agent_note_table_registered_after_init_db(journal_db):
    """Risk #1 smoke test: AgentNote must be registered in the metadata."""
    from tradefarm.storage.models import AgentNote, Base
    assert "agent_notes" in Base.metadata.tables
    assert AgentNote.__table__ is not None


async def test_journal_write_and_read(journal_db):
    from tradefarm.storage import journal

    nid = await journal.write_note(
        agent_id=1, kind="entry", symbol="SPY",
        content="bought on golden cross",
        metadata={"lstm_confidence": 0.72, "size_pct": 0.2},
    )
    assert nid is not None and nid > 0

    rows = await journal.recent_outcomes(agent_id=1, n=5)
    assert len(rows) == 1
    r = rows[0]
    assert r["kind"] == "entry"
    assert r["symbol"] == "SPY"
    assert r["content"] == "bought on golden cross"
    assert r["metadata"]["lstm_confidence"] == 0.72
    assert r["outcome_realized_pnl"] is None
    assert r["outcome_closed_at"] is None


async def test_journal_write_unknown_agent_returns_none(journal_db):
    """Backtest / no-session path: writes for unknown agent are a silent no-op."""
    from tradefarm.storage import journal
    nid = await journal.write_note(
        agent_id=999, kind="entry", symbol="SPY", content="ghost", metadata=None,
    )
    assert nid is None


async def test_close_outcome_stamps_pnl(journal_db):
    from tradefarm.storage import journal

    nid = await journal.write_note(
        agent_id=1, kind="entry", symbol="AAPL", content="bought dip",
    )
    assert nid is not None

    stamped = await journal.close_outcome(
        agent_id=1, symbol="AAPL", realized_pnl=1.23, trade_id=42,
    )
    assert stamped == nid

    rows = await journal.recent_outcomes(agent_id=1, n=5)
    assert len(rows) == 1
    r = rows[0]
    assert r["outcome_realized_pnl"] == pytest.approx(1.23)
    assert r["outcome_trade_id"] == 42
    assert r["outcome_closed_at"] is not None


async def test_close_outcome_idempotent_when_no_open_entry(journal_db):
    from tradefarm.storage import journal
    result = await journal.close_outcome(agent_id=1, symbol="MSFT", realized_pnl=5.0)
    assert result is None


async def test_partial_exit_does_not_double_stamp(journal_db):
    """One note gets stamped per full flat-out, not per partial exit.

    Rule documented in ``journal.py``: ``close_outcome`` stamps the oldest
    unstamped ``entry``. A second ``close_outcome`` call with no other open
    entries returns ``None`` — the original note is *not* restamped.
    """
    from tradefarm.storage import journal

    entry_id = await journal.write_note(
        agent_id=1, kind="entry", symbol="TSLA", content="bought breakout",
    )
    assert entry_id is not None

    # Partial exit: stamps the entry.
    first = await journal.close_outcome(agent_id=1, symbol="TSLA", realized_pnl=2.0)
    assert first == entry_id

    # Full exit: no other open entry → returns None (idempotent).
    second = await journal.close_outcome(agent_id=1, symbol="TSLA", realized_pnl=3.0)
    assert second is None

    rows = await journal.recent_outcomes(agent_id=1, n=5)
    assert len(rows) == 1
    # The note keeps its original stamp (2.0), not the second call's 3.0.
    assert rows[0]["outcome_realized_pnl"] == pytest.approx(2.0)


async def test_find_similar_matches_symbol_and_stamped(journal_db):
    from tradefarm.storage import journal

    # Two entries on SPY — stamp one.
    nid_a = await journal.write_note(agent_id=1, kind="entry", symbol="SPY", content="a")
    await journal.write_note(agent_id=1, kind="entry", symbol="SPY", content="b")
    await journal.close_outcome(agent_id=1, symbol="SPY", realized_pnl=1.0)
    # One entry on AAPL — stamp it.
    nid_c = await journal.write_note(agent_id=1, kind="entry", symbol="AAPL", content="c")
    await journal.close_outcome(agent_id=1, symbol="AAPL", realized_pnl=-0.5)

    similar = await journal.find_similar(agent_id=1, symbol="SPY", limit=5)
    assert len(similar) == 1
    assert similar[0]["id"] == nid_a
    assert similar[0]["symbol"] == "SPY"
    assert similar[0]["outcome_realized_pnl"] == pytest.approx(1.0)

    similar_aapl = await journal.find_similar(agent_id=1, symbol="AAPL", limit=5)
    assert len(similar_aapl) == 1
    assert similar_aapl[0]["id"] == nid_c


async def test_end_to_end_roundtrip(journal_db):
    """Construct an in-memory VirtualBook + stub agent, write an entry note,
    simulate a closing sell via ``close_outcome``, assert the note has the
    expected outcome fields populated.
    """
    from tradefarm.execution.virtual_book import VirtualBook
    from tradefarm.storage import journal

    book = VirtualBook(agent_id=1, cash=1000.0)
    # Open a position — the entry note is written as part of the "decision".
    book.record_fill("NVDA", "buy", 5, 100.0)
    entry_id = await journal.write_note(
        agent_id=1, kind="entry", symbol="NVDA",
        content="bought NVDA on LSTM up signal",
        metadata={"lstm_probs": [0.1, 0.2, 0.7], "lstm_confidence": 0.7},
    )
    assert entry_id is not None

    # Close the position — VirtualBook returns the realized PnL.
    realized = book.record_fill("NVDA", "sell", 5, 100.246)
    assert realized == pytest.approx(1.23)

    stamped_id = await journal.close_outcome(
        agent_id=1, symbol="NVDA", realized_pnl=realized,
    )
    assert stamped_id == entry_id

    rows = await journal.recent_outcomes(agent_id=1, n=5)
    assert len(rows) == 1
    assert rows[0]["outcome_realized_pnl"] == pytest.approx(1.23)
    assert rows[0]["outcome_closed_at"] is not None


async def test_record_fill_returns_realized_pnl():
    """Phase 1 changed ``VirtualBook.record_fill`` to return the realized PnL
    from the fill alone (was -> None before).
    """
    from tradefarm.execution.virtual_book import VirtualBook

    book = VirtualBook(agent_id=7, cash=1000.0)
    r_open = book.record_fill("SPY", "buy", 2, 100.0)
    assert r_open == 0.0  # opening — no realized

    r_close = book.record_fill("SPY", "sell", 2, 110.0)
    assert r_close == pytest.approx(20.0)
    # Book's running total matches.
    assert book.realized_pnl == pytest.approx(20.0)
