"""Phase 4 (Agent Academy) — curriculum auto-promote/demote tests.

Mirrors ``test_ranks.py``'s in-memory-SQLite fixture so writes don't leak into
the dev DB. Covers:
- promotion threshold (winning notes → senior),
- demotion trigger (losing notes with drawdown → junior),
- demotion floor (intern with 0 trades is never demoted),
- per-pass demotion cap (50 agents, 10% cap → exactly 5 demoted),
- risk manager rebuild on rank change,
- end-to-end via FastAPI's TestClient.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import pytest_asyncio


@dataclass
class FakeState:
    id: int
    name: str


class FakeAgent:
    """Minimal agent shim for curriculum.evaluate_all — only needs
    ``state.id``, ``state.name``, and a real ``risk`` we can swap.
    """

    def __init__(self, agent_id: int, name: str, risk):
        self.state = FakeState(id=agent_id, name=name)
        self.risk = risk


class FakeOrchestrator:
    def __init__(self, agents):
        self.agents = agents
        self._tick_in_progress = False


@pytest_asyncio.fixture
async def curriculum_db(monkeypatch):
    """In-memory DB + one seed agent created 3 weeks ago."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    import tradefarm.academy.promotions_repo as pr_mod
    import tradefarm.academy.ranks as ranks_mod
    import tradefarm.academy.repo as academy_repo_mod
    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod
    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ranks_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(academy_repo_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(pr_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    three_weeks_ago = datetime.now(timezone.utc) - timedelta(days=21)
    async with SessionLocal() as s:
        s.add(Agent(
            id=1, name="agent-001", strategy="lstm_llm_v1",
            starting_capital=1000.0, cash=1000.0, status="waiting",
            rank="intern", created_at=three_weeks_ago,
        ))
        await s.commit()

    yield SessionLocal
    await engine.dispose()


async def _seed_wins(agent_id: int, symbol: str, n: int) -> None:
    from tradefarm.storage import journal
    for i in range(n):
        await journal.write_note(
            agent_id=agent_id, kind="entry", symbol=symbol, content=f"win #{i}",
        )
        await journal.close_outcome(
            agent_id=agent_id, symbol=symbol, realized_pnl=5.0 + i * 0.01,
        )


async def _seed_losses(agent_id: int, symbol: str, n: int) -> None:
    from tradefarm.storage import journal
    for i in range(n):
        await journal.write_note(
            agent_id=agent_id, kind="entry", symbol=symbol, content=f"loss #{i}",
        )
        await journal.close_outcome(
            agent_id=agent_id, symbol=symbol, realized_pnl=-4.0 - i * 0.01,
        )


def _make_agent(agent_id: int, name: str, rank: str):
    from tradefarm.risk.manager import RiskManager
    return FakeAgent(agent_id, name, RiskManager(starting_capital=1000.0, rank=rank))


# ---------------------------------------------------------------------------
# 1. Promotion threshold — 20 winners → senior.
# ---------------------------------------------------------------------------


async def test_promotion_threshold_reached(curriculum_db):
    from tradefarm.academy import curriculum
    from tradefarm.academy import repo as academy_repo
    from tradefarm.storage.db import SessionLocal
    from tradefarm.storage.models import AcademyPromotion
    from sqlalchemy import select

    await _seed_wins(agent_id=1, symbol="AAPL", n=20)
    agent = _make_agent(1, "agent-001", "intern")
    orch = FakeOrchestrator([agent])

    # eligible_rank → "senior"; one-step-per-pass, so first pass → "junior".
    result = await curriculum.evaluate_all(orch)
    assert len(result.promoted) == 1
    assert result.promoted[0].to_rank == "junior"

    # Second pass bumps to senior.
    result2 = await curriculum.evaluate_all(orch)
    assert len(result2.promoted) == 1
    assert result2.promoted[0].to_rank == "senior"
    assert await academy_repo.get_rank(1) == "senior"

    async with SessionLocal() as s:
        rows = (await s.execute(select(AcademyPromotion))).scalars().all()
    assert len(rows) == 2
    assert rows[-1].to_rank == "senior"


# ---------------------------------------------------------------------------
# 2. Demotion trigger — losing streak on a senior → junior.
# ---------------------------------------------------------------------------


async def test_demote_on_drawdown_streak(curriculum_db, monkeypatch):
    from tradefarm.academy import curriculum
    from tradefarm.academy import repo as academy_repo
    from tradefarm.config import settings

    # Ensure the loss count itself triggers demotion (5 losses in a row).
    monkeypatch.setattr(settings, "academy_demote_consecutive_losses", 5)
    monkeypatch.setattr(settings, "academy_demote_cap_pct", 1.0)

    # Seed 5 losing trades; current rank = senior (forcing a demotion direction).
    await _seed_losses(agent_id=1, symbol="AAPL", n=5)
    await academy_repo.set_rank(1, "senior", reason="test setup")

    agent = _make_agent(1, "agent-001", "senior")
    orch = FakeOrchestrator([agent])

    result = await curriculum.evaluate_all(orch)
    assert len(result.demoted) == 1
    assert result.demoted[0].from_rank == "senior"
    assert result.demoted[0].to_rank == "junior"
    assert await academy_repo.get_rank(1) == "junior"


# ---------------------------------------------------------------------------
# 3. Demotion floor — a fresh intern with 0 trades never demotes.
# ---------------------------------------------------------------------------


async def test_demote_below_min_trades_is_blocked(curriculum_db):
    from tradefarm.academy import curriculum
    from tradefarm.academy import repo as academy_repo

    agent = _make_agent(1, "agent-001", "intern")
    orch = FakeOrchestrator([agent])
    result = await curriculum.evaluate_all(orch)

    assert result.promoted == []
    assert result.demoted == []
    assert await academy_repo.get_rank(1) == "intern"


# ---------------------------------------------------------------------------
# 4. Per-pass demotion cap — 50 agents, cap 0.10 → exactly 5 demoted.
# ---------------------------------------------------------------------------


async def test_per_pass_demotion_cap(curriculum_db, monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
    from tradefarm.academy import curriculum
    from tradefarm.academy import repo as academy_repo
    from tradefarm.config import settings
    from tradefarm.storage import journal
    from tradefarm.storage.models import Agent, Base
    import tradefarm.academy.promotions_repo as pr_mod
    import tradefarm.academy.ranks as ranks_mod
    import tradefarm.academy.repo as academy_repo_mod
    import tradefarm.storage.db as db_mod
    import tradefarm.storage.journal as journal_mod

    # Fresh engine for this test — the shared fixture only seeds agent 1.
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(journal_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(ranks_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(academy_repo_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(pr_mod, "SessionLocal", SessionLocal)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(settings, "academy_demote_cap_pct", 0.10)
    monkeypatch.setattr(settings, "academy_demote_consecutive_losses", 5)

    # Seed 50 agents at senior + 5 losses each — all candidates.
    agents = []
    async with SessionLocal() as s:
        for i in range(1, 51):
            s.add(Agent(
                id=i, name=f"agent-{i:03d}", strategy="momentum_sma20",
                starting_capital=1000.0, cash=1000.0, status="waiting", rank="senior",
            ))
        await s.commit()
    for i in range(1, 51):
        for k in range(5):
            await journal.write_note(
                agent_id=i, kind="entry", symbol="AAPL", content=f"loss #{k}",
            )
            await journal.close_outcome(
                agent_id=i, symbol="AAPL", realized_pnl=-5.0,
            )
        agents.append(_make_agent(i, f"agent-{i:03d}", "senior"))

    orch = FakeOrchestrator(agents)
    result = await curriculum.evaluate_all(orch)

    assert len(result.demoted) == 5
    # The remaining 45 stayed at senior.
    demoted_ids = {e.agent_id for e in result.demoted}
    remaining_seniors = 0
    for i in range(1, 51):
        if i in demoted_ids:
            continue
        assert await academy_repo.get_rank(i) == "senior"
        remaining_seniors += 1
    assert remaining_seniors == 45
    await engine.dispose()


# ---------------------------------------------------------------------------
# 5. RiskManager rebuilt on rank change.
# ---------------------------------------------------------------------------


async def test_risk_manager_rebuilt_on_rank_change(curriculum_db, monkeypatch):
    from tradefarm.academy import curriculum
    from tradefarm.config import settings
    from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT

    monkeypatch.setattr(
        settings, "academy_rank_multipliers",
        "intern=0.5,junior=1.0,senior=1.5,principal=2.0",
    )

    # 20 winning notes → eligible senior. Start at "junior" so the one-step
    # promotion in this pass lands on "senior".
    await _seed_wins(agent_id=1, symbol="AAPL", n=20)
    from tradefarm.academy import repo as academy_repo
    await academy_repo.set_rank(1, "junior", reason="test setup")
    agent = _make_agent(1, "agent-001", "junior")

    # Prove the starting cap is the junior one (1.0 multiplier).
    assert agent.risk.limits.max_position_notional_pct == pytest.approx(
        BASE_MAX_POSITION_NOTIONAL_PCT * 1.0,
    )

    orch = FakeOrchestrator([agent])
    await curriculum.evaluate_all(orch)

    # After promotion, agent.risk was swapped — cap now reflects senior's 1.5x.
    assert agent.risk.rank == "senior"
    assert agent.risk.limits.max_position_notional_pct == pytest.approx(
        BASE_MAX_POSITION_NOTIONAL_PCT * 1.5,
    )


# ---------------------------------------------------------------------------
# 6. End-to-end: POST /academy/evaluate via FastAPI TestClient.
# ---------------------------------------------------------------------------


async def test_end_to_end_evaluate_endpoint(curriculum_db, monkeypatch):
    """Seed an intern with enough winners to promote, call POST /academy/evaluate,
    and assert a promotion row is reachable via GET /agents/{id}/promotions.
    """
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from tradefarm.academy import curriculum
    from tradefarm.api.main import (
        academy_evaluate, agent_promotions, academy_promotions as academy_promos_ep,
    )

    # Seed 10 winning trades — clears junior (min=5) but not senior (min=15).
    await _seed_wins(agent_id=1, symbol="AAPL", n=10)

    # Build a minimal app that exposes just the Phase 4 endpoints.
    app = FastAPI()
    agent = _make_agent(1, "agent-001", "intern")
    orch = FakeOrchestrator([agent])
    app.state.orchestrator = orch

    # Re-implement the two handlers inline; they read app.state.orchestrator.
    @app.post("/academy/evaluate")
    async def _evaluate() -> dict[str, Any]:
        result = await curriculum.evaluate_all(app.state.orchestrator)
        return result.to_dict()

    app.add_api_route("/agents/{agent_id}/promotions", agent_promotions, methods=["GET"])
    app.add_api_route("/academy/promotions", academy_promos_ep, methods=["GET"])

    client = TestClient(app)
    r = client.post("/academy/evaluate")
    assert r.status_code == 200
    body = r.json()
    assert len(body["promoted"]) >= 1
    assert body["promoted"][0]["to_rank"] == "junior"

    r2 = client.get("/agents/1/promotions")
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) >= 1
    assert rows[0]["to_rank"] == "junior"
    assert rows[0]["agent_name"] == "agent-001"
