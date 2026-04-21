"""Phase 3 — retrieval-augmented LLM prompt tests.

Byte-identical guarantee: when ``retrieved_examples`` is empty,
``user_message(ctx)`` matches the pre-Phase-3 golden string verbatim.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
import pytest_asyncio

PRE_PHASE3_PROMPT = (
    "Ticker: SPY\n"
    "Feature digest: 5d close: [100.0, 101.0, 102.0, 103.0, 104.0] "
    "(+4.00% over window); vol last=1,000,000, range last=1.50\n"
    "LSTM: bias=up probs(down/flat/up)=(0.10/0.20/0.70) confidence=0.65\n"
    "Position: flat\n"
    "Day P&L vs starting capital: +0.00%\n"
    "\nReturn the decision JSON now."
)


def _baseline_ctx():
    from tradefarm.agents.llm_overlay_types import LlmContext
    return LlmContext(
        symbol="SPY",
        feature_digest=(
            "5d close: [100.0, 101.0, 102.0, 103.0, 104.0] "
            "(+4.00% over window); vol last=1,000,000, range last=1.50"
        ),
        lstm_direction="up", lstm_probs=(0.10, 0.20, 0.70), lstm_confidence=0.65,
        has_long=False, held_qty=0.0, day_pnl_pct=0.0,
    )


@pytest_asyncio.fixture
async def retrieval_db(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SL = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    for mod in (db_mod, journal_mod):
        monkeypatch.setattr(mod, "SessionLocal", SL)
    monkeypatch.setattr(db_mod, "engine", engine)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with SL() as s:
        s.add(Agent(id=1, name="agent-001", strategy="lstm_llm_v1",
                    starting_capital=1000.0, cash=1000.0, status="waiting"))
        await s.commit()
    yield SL
    await engine.dispose()


@pytest.fixture
def retrieval_on(monkeypatch):
    from tradefarm.config import settings
    monkeypatch.setattr(settings, "academy_retrieval_enabled", True)


async def test_retrieval_ranks_by_symbol_match(retrieval_db, retrieval_on):
    from tradefarm.agents import retrieval
    from tradefarm.storage import journal

    nid_a = await journal.write_note(
        agent_id=1, kind="entry", symbol="SPY", content="spy-a",
        metadata={"lstm_direction": "up"},
    )
    await journal.close_outcome(agent_id=1, symbol="SPY", realized_pnl=1.0)
    nid_b = await journal.write_note(agent_id=1, kind="entry", symbol="SPY", content="spy-b")
    await journal.close_outcome(agent_id=1, symbol="SPY", realized_pnl=-0.5)
    await journal.write_note(agent_id=1, kind="entry", symbol="AAPL", content="aapl-x")
    await journal.close_outcome(agent_id=1, symbol="AAPL", realized_pnl=2.0)

    examples = await retrieval.fetch(1, "SPY")
    assert all(ex.symbol == "SPY" for ex in examples)
    assert [ex.note_id for ex in examples[:2]] == [nid_b, nid_a]  # newest-first
    assert next(ex for ex in examples if ex.note_id == nid_a).direction_hint == "up"


def test_user_message_unchanged_when_empty():
    from tradefarm.agents.llm_overlay_types import user_message
    ctx = _baseline_ctx()
    assert ctx.retrieved_examples == []
    assert user_message(ctx) == PRE_PHASE3_PROMPT


def test_user_message_includes_retrieval_block():
    from tradefarm.agents.llm_overlay_types import user_message
    ctx = _baseline_ctx()
    ctx.retrieved_examples = [
        {"symbol": "SPY", "direction_hint": "up", "content": "bought on strong LSTM signal",
         "realized_pnl": 4.21, "closed_at_iso": "2026-04-18T14:30:00+00:00", "note_id": 11},
        {"symbol": "SPY", "direction_hint": "", "content": "loser",
         "realized_pnl": -1.80, "closed_at_iso": "2026-04-10T18:00:00+00:00", "note_id": 9},
    ]
    msg = user_message(ctx)
    assert "Past similar setups (your own history):" in msg
    assert "+$4.21" in msg and "-$1.80" in msg and "2026-04-18" in msg
    assert msg.rstrip().endswith("Return the decision JSON now.")


async def test_retrieval_disabled_setting(retrieval_db, monkeypatch):
    from tradefarm.agents import retrieval
    from tradefarm.config import settings
    from tradefarm.storage import journal

    await journal.write_note(agent_id=1, kind="entry", symbol="SPY", content="x")
    await journal.close_outcome(agent_id=1, symbol="SPY", realized_pnl=1.0)
    monkeypatch.setattr(settings, "academy_retrieval_enabled", False)
    assert await retrieval.fetch(1, "SPY") == []


async def test_retrieval_error_degrades_gracefully(monkeypatch, retrieval_on):
    from tradefarm.agents import retrieval
    from tradefarm.storage import journal

    async def boom(*_a, **_kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(journal, "find_similar", boom)
    assert await retrieval.fetch(1, "SPY") == []


# --- Hermetic E2E ------------------------------------------------------------


class _StubFitted:
    class model:  # noqa: N801 — mimics FittedModel.model.cfg access path.
        class cfg:
            seq_len = 2

    def predict(self, _window):
        from tradefarm.agents.lstm_model import Prediction
        return Prediction(direction=2, direction_probs=(0.05, 0.10, 0.85), confidence=0.80)


class _StubOverlay:
    def __init__(self):
        self.seen_ctx = None

    async def decide(self, ctx):
        from tradefarm.agents.llm_overlay_types import LlmDecision
        self.seen_ctx = ctx
        return LlmDecision(bias="flat", predictive="flat", stance="wait",
                           size_pct=0.0, reason="stubbed")


def _build_agent(overlay, monkeypatch):
    from tradefarm.agents import lstm_llm_agent as agent_mod
    from tradefarm.agents.base import AgentState
    from tradefarm.agents.lstm_llm_agent import LstmLlmAgent
    from tradefarm.execution.virtual_book import VirtualBook
    from tradefarm.risk.manager import RiskManager

    monkeypatch.setattr(agent_mod, "featurize", lambda df: (np.zeros((3, 4)), np.zeros(3)))
    monkeypatch.setattr(agent_mod, "latest_window", lambda X, seq_len=2: np.zeros((seq_len, 4)))

    state = AgentState(id=1, name="agent-001", strategy="lstm_llm_v1",
                       book=VirtualBook(agent_id=1, cash=1000.0))
    agent = LstmLlmAgent(state=state, risk=RiskManager(starting_capital=1000.0),
                         symbol="SPY", overlay=overlay)
    agent._fitted = _StubFitted()
    return agent


_BARS = {"SPY": pd.DataFrame({
    "date": pd.to_datetime(["2026-04-17", "2026-04-18", "2026-04-19"]),
    "adjusted_close": [100.0, 101.0, 102.0], "volume": [1_000_000, 1_100_000, 1_200_000],
    "high": [101.0, 102.0, 103.0], "low": [99.5, 100.5, 101.5],
})}


async def test_e2e_lstm_llm_agent_sees_retrieval(retrieval_db, retrieval_on, monkeypatch):
    from tradefarm.agents.llm_overlay_types import user_message
    from tradefarm.storage import journal

    nid = await journal.write_note(
        agent_id=1, kind="entry", symbol="SPY", content="bought on up bias",
        metadata={"lstm_direction": "up"},
    )
    await journal.close_outcome(agent_id=1, symbol="SPY", realized_pnl=3.14)

    overlay = _StubOverlay()
    agent = _build_agent(overlay, monkeypatch)
    signals = await agent.decide(_BARS, {"SPY": 102.0})

    assert signals == []
    assert overlay.seen_ctx is not None
    assert len(overlay.seen_ctx.retrieved_examples) == 1
    ex = overlay.seen_ctx.retrieved_examples[0]
    assert ex["symbol"] == "SPY" and ex["note_id"] == nid
    assert ex["realized_pnl"] == pytest.approx(3.14)
    assert "+$3.14" in user_message(overlay.seen_ctx)


async def test_e2e_retrieval_failure_still_decides(retrieval_db, retrieval_on, monkeypatch):
    """Journal error → agent still reaches overlay with retrieved_examples=[]."""
    from tradefarm.storage import journal

    async def boom(*_a, **_kw):
        raise RuntimeError("db exploded")

    monkeypatch.setattr(journal, "find_similar", boom)
    overlay = _StubOverlay()
    agent = _build_agent(overlay, monkeypatch)
    await agent.decide(_BARS, {"SPY": 102.0})
    assert overlay.seen_ctx is not None
    assert overlay.seen_ctx.retrieved_examples == []
