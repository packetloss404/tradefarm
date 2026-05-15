"""Recap v2 — aggregator unit tests.

Drives ``tradefarm.api.recap.build_recap`` directly against an in-memory
SQLite + a stub orchestrator. No FastAPI app boot. Mirrors the journal /
curriculum test pattern.

Cases:
1. Empty day: all sections null/empty, shape is valid.
2. Single big fill: ``biggest_fill`` populated; ``total_fills == 1``.
3. Multiple closed outcomes: ``top_winners`` sorted desc; ``biggest_loss``
   is the most-negative.
4. All profitable closes → ``biggest_loss`` is None.
5. Promotions ordered + demotions filtered.
6. Predictions snapshot is mapped cleanly (mock board).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio

from tradefarm.market.hours import ET


# ---------------------------------------------------------------------------
# Stubs.
# ---------------------------------------------------------------------------


@dataclass
class _StubBook:
    cash: float = 1000.0
    realized: float = 0.0
    _equity: float = 1000.0

    @property
    def realized_pnl(self) -> float:
        return self.realized

    def equity(self, marks: dict[str, float]) -> float:
        return self._equity

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        return 0.0


@dataclass
class _StubState:
    id: int
    name: str
    book: _StubBook = field(default_factory=_StubBook)


@dataclass
class _StubAgent:
    state: _StubState


class _StubBoard:
    def __init__(self, payloads: list[dict[str, Any]]):
        self._payloads = payloads

    def snapshot(self) -> list[dict[str, Any]]:
        return list(self._payloads)


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)
    last_marks: dict[str, float] = field(default_factory=dict)
    _predictions: _StubBoard | None = None


def _make_orch(
    agents: list[tuple[int, str, float]] | None = None,
    board: _StubBoard | None = None,
    marks: dict[str, float] | None = None,
) -> _StubOrch:
    """Build a stub orchestrator. ``agents`` items are (id, name, equity)."""
    agents = agents or [(1, "agent-001", 1000.0), (2, "agent-002", 1000.0)]
    out = []
    for i, n, eq in agents:
        book = _StubBook(_equity=eq)
        out.append(_StubAgent(state=_StubState(id=i, name=n, book=book)))
    return _StubOrch(agents=out, last_marks=marks or {}, _predictions=board)


# ---------------------------------------------------------------------------
# DB fixture: in-memory SQLite, seeded with two agents.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def recap_db(monkeypatch):
    """Per-test in-memory DB. Returns the session factory."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.academy.promotions_repo as pr_mod
    import tradefarm.api.recap as recap_mod
    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(pr_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(recap_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed two agents.
    async with SessionLocal() as s:
        s.add(Agent(id=1, name="agent-001", strategy="momentum_sma20",
                    starting_capital=1000.0, cash=1000.0, status="waiting"))
        s.add(Agent(id=2, name="agent-002", strategy="lstm_v1",
                    starting_capital=1000.0, cash=1000.0, status="waiting"))
        await s.commit()

    yield SessionLocal
    await engine.dispose()


def _today_et_window() -> tuple[datetime, datetime, datetime]:
    """Return (start_utc, end_utc, midday_utc) for a known ET day to use as
    test bounds + insertion timestamps. ``midday_utc`` is comfortably inside
    the window with ~5 minutes of headroom on both sides so individual
    rows can be offset by a few seconds without spilling past the end.
    """
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc.astimezone(ET)
    midnight_et = now_et.replace(hour=0, minute=0, second=0, microsecond=0)
    start_utc = midnight_et.astimezone(timezone.utc)
    end_utc = now_utc
    # Choose a midday that's at least 5 min before end_utc to leave room for
    # +N-second offsets in the test rows. If the window is too tight (just
    # after ET midnight), fall back to (start + half-window).
    span = end_utc - start_utc
    midday_utc = end_utc - timedelta(minutes=5)
    if midday_utc <= start_utc:
        midday_utc = start_utc + span / 2
    return start_utc, end_utc, midday_utc


# ---------------------------------------------------------------------------
# 1. Empty day.
# ---------------------------------------------------------------------------


async def test_empty_day_shape(recap_db):
    from tradefarm.api.recap import build_recap

    orch = _make_orch(board=_StubBoard([]))
    payload = await build_recap(orch, session_factory=recap_db)

    assert payload["total_fills"] == 0
    assert payload["biggest_fill"] is None
    assert payload["top_winners"] == []
    assert payload["biggest_loss"] is None
    assert payload["promotions"] == []
    assert payload["predictions"] == []
    # Shape sanity — every contract key present.
    assert set(payload.keys()) == {
        "date", "session_pnl_pct", "session_total_equity", "total_fills",
        "biggest_fill", "top_winners", "biggest_loss", "promotions",
        "predictions",
    }
    # ISO YYYY-MM-DD.
    assert len(payload["date"]) == 10 and payload["date"][4] == "-"


# ---------------------------------------------------------------------------
# 2. Single biggest fill + count.
# ---------------------------------------------------------------------------


async def test_biggest_fill_picks_largest_notional(recap_db):
    from tradefarm.api.recap import build_recap
    from tradefarm.storage.models import Trade

    start_utc, end_utc, mid = _today_et_window()
    mid_naive = mid.replace(tzinfo=None)
    async with recap_db() as s:
        # Three fills of different notionals on the same day.
        s.add(Trade(agent_id=1, symbol="AAPL", side="buy", qty=2.0,
                    price=100.0, executed_at=mid_naive, reason="x"))
        s.add(Trade(agent_id=2, symbol="NVDA", side="buy", qty=5.0,
                    price=180.5, executed_at=mid_naive + timedelta(seconds=1), reason="x"))
        s.add(Trade(agent_id=1, symbol="MSFT", side="sell", qty=1.0,
                    price=300.0, executed_at=mid_naive + timedelta(seconds=2), reason="x"))
        await s.commit()

    orch = _make_orch(board=_StubBoard([]))
    payload = await build_recap(
        orch, session_factory=recap_db, bounds=(start_utc, end_utc),
    )

    assert payload["total_fills"] == 3
    big = payload["biggest_fill"]
    assert big is not None
    assert big["symbol"] == "NVDA"
    assert big["agent_id"] == 2
    assert big["agent_name"] == "agent-002"
    assert big["side"] == "buy"
    assert big["qty"] == pytest.approx(5.0)
    assert big["price"] == pytest.approx(180.5)
    assert big["notional"] == pytest.approx(5.0 * 180.5)
    assert big["at"].endswith("Z")


async def test_biggest_fill_uses_orchestrator_for_name(recap_db):
    """If the agent name isn't in the orchestrator map, ``agent_name`` is None.

    This mirrors the contract: agent_name is best-effort from the live
    orchestrator (not the DB), so a fill from a deleted agent surfaces with
    name = None rather than raising.
    """
    from tradefarm.api.recap import build_recap
    from tradefarm.storage.models import Trade

    start_utc, end_utc, mid = _today_et_window()
    async with recap_db() as s:
        s.add(Trade(agent_id=99, symbol="GHOST", side="buy", qty=1.0,
                    price=1.0, executed_at=mid.replace(tzinfo=None), reason="x"))
        await s.commit()

    orch = _make_orch(board=_StubBoard([]))  # agent 99 not in orch
    payload = await build_recap(
        orch, session_factory=recap_db, bounds=(start_utc, end_utc),
    )
    assert payload["biggest_fill"]["agent_id"] == 99
    assert payload["biggest_fill"]["agent_name"] is None


# ---------------------------------------------------------------------------
# 3. Multiple closed outcomes — top_winners sorted, biggest_loss is min.
# ---------------------------------------------------------------------------


async def test_top_winners_sorted_and_biggest_loss(recap_db):
    from tradefarm.api.recap import build_recap
    from tradefarm.storage.models import AgentNote

    start_utc, end_utc, mid = _today_et_window()
    mid_naive = mid.replace(tzinfo=None)
    async with recap_db() as s:
        # 4 closed outcomes today: pnls 50, 200, 10, -75.
        s.add(AgentNote(
            agent_id=1, kind="entry", symbol="AAPL", content="a",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=50.0, outcome_closed_at=mid_naive,
        ))
        s.add(AgentNote(
            agent_id=2, kind="entry", symbol="NVDA", content="b",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=200.0, outcome_closed_at=mid_naive,
        ))
        s.add(AgentNote(
            agent_id=1, kind="entry", symbol="MSFT", content="c",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=10.0, outcome_closed_at=mid_naive,
        ))
        s.add(AgentNote(
            agent_id=2, kind="entry", symbol="TSLA", content="d",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=-75.0, outcome_closed_at=mid_naive,
        ))
        # An outcome from yesterday — should be excluded.
        s.add(AgentNote(
            agent_id=1, kind="entry", symbol="OLD", content="old",
            note_metadata="", created_at=mid_naive - timedelta(days=2),
            outcome_realized_pnl=9999.0,
            outcome_closed_at=mid_naive - timedelta(days=2),
        ))
        await s.commit()

    orch = _make_orch(board=_StubBoard([]))
    payload = await build_recap(
        orch, session_factory=recap_db, bounds=(start_utc, end_utc),
    )

    winners = payload["top_winners"]
    assert len(winners) == 3  # top-3 cap
    assert [w["realized_pnl"] for w in winners] == [200.0, 50.0, 10.0]
    assert winners[0]["symbol"] == "NVDA"
    assert winners[0]["agent_name"] == "agent-002"
    # Yesterday's monster outcome did NOT leak in.
    assert all(w["realized_pnl"] != 9999.0 for w in winners)

    loss = payload["biggest_loss"]
    assert loss is not None
    assert loss["realized_pnl"] == pytest.approx(-75.0)
    assert loss["symbol"] == "TSLA"
    assert loss["agent_name"] == "agent-002"


# ---------------------------------------------------------------------------
# 4. All profitable → biggest_loss is None.
# ---------------------------------------------------------------------------


async def test_biggest_loss_null_when_all_profitable(recap_db):
    from tradefarm.api.recap import build_recap
    from tradefarm.storage.models import AgentNote

    start_utc, end_utc, mid = _today_et_window()
    mid_naive = mid.replace(tzinfo=None)
    async with recap_db() as s:
        s.add(AgentNote(
            agent_id=1, kind="entry", symbol="AAPL", content="a",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=5.0, outcome_closed_at=mid_naive,
        ))
        s.add(AgentNote(
            agent_id=2, kind="entry", symbol="NVDA", content="b",
            note_metadata="", created_at=mid_naive,
            outcome_realized_pnl=1.0, outcome_closed_at=mid_naive,
        ))
        await s.commit()

    orch = _make_orch(board=_StubBoard([]))
    payload = await build_recap(
        orch, session_factory=recap_db, bounds=(start_utc, end_utc),
    )
    assert payload["biggest_loss"] is None
    assert len(payload["top_winners"]) == 2


# ---------------------------------------------------------------------------
# 5. Promotions — present, newest-first, demotions filtered.
# ---------------------------------------------------------------------------


async def test_promotions_today_filters_demotions_and_orders_newest(recap_db):
    from tradefarm.api.recap import build_recap
    from tradefarm.storage.models import AcademyPromotion

    start_utc, end_utc, mid = _today_et_window()
    mid_naive = mid.replace(tzinfo=None)
    earlier_naive = mid_naive - timedelta(minutes=30)
    async with recap_db() as s:
        # Promotion (intern → junior), earlier today.
        s.add(AcademyPromotion(
            agent_id=1, from_rank="intern", to_rank="junior",
            reason="t1", stats_snapshot="{}", at=earlier_naive,
        ))
        # Promotion (junior → senior), later today.
        s.add(AcademyPromotion(
            agent_id=2, from_rank="junior", to_rank="senior",
            reason="t2", stats_snapshot="{}", at=mid_naive,
        ))
        # Demotion (should be filtered).
        s.add(AcademyPromotion(
            agent_id=1, from_rank="senior", to_rank="junior",
            reason="d", stats_snapshot="{}", at=mid_naive - timedelta(minutes=10),
        ))
        await s.commit()

    orch = _make_orch(board=_StubBoard([]))
    payload = await build_recap(
        orch, session_factory=recap_db, bounds=(start_utc, end_utc),
    )
    promos = payload["promotions"]
    assert len(promos) == 2
    # Newest first.
    assert promos[0]["to"] == "senior"
    assert promos[0]["from"] == "junior"
    assert promos[0]["agent_id"] == 2
    assert promos[0]["agent_name"] == "agent-002"
    assert promos[1]["to"] == "junior"
    assert promos[1]["from"] == "intern"
    # All ISO-UTC.
    for p in promos:
        assert p["at"].endswith("Z")


# ---------------------------------------------------------------------------
# 6. Predictions snapshot integration.
# ---------------------------------------------------------------------------


async def test_predictions_mapped_from_board_snapshot(recap_db):
    from tradefarm.api.recap import build_recap

    board = _StubBoard([
        {
            "id": "pick-winner",
            "question": "Pick today's winner agent",
            "options": ["agent-001", "agent-002"],
            "status": "revealed",
            "tally": {"agent-001": 12, "agent-002": 8},
            "locks_at": "2026-05-14T13:30:00+00:00",
            "reveals_at": "2026-05-14T20:00:00+00:00",
            "winning_option": "agent-001",
        },
        {
            "id": "spy-direction",
            "question": "Will SPY close green?",
            "options": ["up", "down"],
            "status": "locked",
            "tally": {"up": 5, "down": 3},
            "locks_at": "",
            "reveals_at": "",
            "winning_option": None,
        },
    ])
    orch = _make_orch(board=board)
    payload = await build_recap(orch, session_factory=recap_db)

    preds = payload["predictions"]
    assert len(preds) == 2

    pw = next(p for p in preds if p["id"] == "pick-winner")
    assert pw["question"] == "Pick today's winner agent"
    assert pw["winning_option"] == "agent-001"
    assert pw["tally"] == {"agent-001": 12, "agent-002": 8}
    assert pw["total_votes"] == 20
    assert pw["status"] == "revealed"
    # Irrelevant fields stripped.
    assert "locks_at" not in pw
    assert "reveals_at" not in pw
    assert "options" not in pw

    spy = next(p for p in preds if p["id"] == "spy-direction")
    assert spy["status"] == "locked"
    assert spy["winning_option"] is None
    assert spy["total_votes"] == 8


# ---------------------------------------------------------------------------
# Session totals — uses orchestrator agents + settings.agent_starting_capital.
# ---------------------------------------------------------------------------


async def test_session_totals_reflect_roster_equity(recap_db, monkeypatch):
    from tradefarm.api.recap import build_recap
    from tradefarm.config import settings

    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)

    # Two agents: equity 1100 + 900 = 2000 vs starting 2000 → pnl 0%.
    orch = _make_orch(
        agents=[(1, "agent-001", 1100.0), (2, "agent-002", 900.0)],
        board=_StubBoard([]),
    )
    payload = await build_recap(orch, session_factory=recap_db)
    assert payload["session_total_equity"] == pytest.approx(2000.0)
    assert payload["session_pnl_pct"] == pytest.approx(0.0)

    # Now: equity 1200 + 1100 = 2300 → +15%.
    orch2 = _make_orch(
        agents=[(1, "agent-001", 1200.0), (2, "agent-002", 1100.0)],
        board=_StubBoard([]),
    )
    payload2 = await build_recap(orch2, session_factory=recap_db)
    assert payload2["session_total_equity"] == pytest.approx(2300.0)
    assert payload2["session_pnl_pct"] == pytest.approx(15.0)
