"""Phase 2 (Agent Academy) — rank scoring + risk-cap multiplier + repo.

Uses an in-memory SQLite DB (same pattern as ``tests/test_journal.py``) so
writes don't leak into the dev DB. Each test recreates tables from scratch.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def academy_db(monkeypatch):
    """Fresh in-memory DB + a single seed agent row for rank writes."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed one agent — created 3 weeks ago so `weeks_active` > principal gate.
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


# ---------------------------------------------------------------------------
# 1. eligible_rank thresholds — pure function, table-driven.
# ---------------------------------------------------------------------------


def test_rank_scoring_thresholds():
    from tradefarm.academy.ranks import RankStats, eligible_rank

    # intern: no trades
    assert eligible_rank(RankStats(0, 0.0, 0.0, 0.0)) == "intern"

    # junior: 5 trades, weak win rate still OK
    assert eligible_rank(RankStats(5, 0.4, 0.0, 0.0)) == "junior"

    # senior: 20 trades, win_rate >= 0.52
    assert eligible_rank(RankStats(20, 0.6, 0.1, 1.0)) == "senior"

    # principal: 50 trades, strong sharpe, 4 weeks active
    assert eligible_rank(RankStats(50, 0.6, 0.8, 4.0)) == "principal"


def test_insufficient_trades_stays_intern():
    """n_closed < min_junior → intern regardless of win_rate."""
    from tradefarm.academy.ranks import RankStats, eligible_rank

    assert eligible_rank(RankStats(4, 0.99, 2.0, 10.0)) == "intern"
    assert eligible_rank(RankStats(0, 1.0, 5.0, 5.0)) == "intern"


def test_principal_requires_weeks_active():
    """Trade count + sharpe alone aren't enough — need 2+ weeks tenure."""
    from tradefarm.academy.ranks import RankStats, eligible_rank

    # 50 trades, strong sharpe, but only 1 week active → senior (not principal)
    assert eligible_rank(RankStats(50, 0.6, 1.0, 1.0)) == "senior"


# ---------------------------------------------------------------------------
# 2. Multiplier CSV parsing.
# ---------------------------------------------------------------------------


def test_multiplier_csv_parsing(monkeypatch):
    from tradefarm.config import settings

    # Empty CSV → 1.0 for every rank (backwards-compat contract).
    monkeypatch.setattr(settings, "academy_rank_multipliers", "")
    assert settings.rank_multiplier("intern") == 1.0
    assert settings.rank_multiplier("junior") == 1.0
    assert settings.rank_multiplier("senior") == 1.0
    assert settings.rank_multiplier("principal") == 1.0

    # Populated CSV → parsed.
    monkeypatch.setattr(
        settings, "academy_rank_multipliers",
        "intern=0.5,junior=1.0,senior=1.5,principal=2.0",
    )
    assert settings.rank_multiplier("intern") == 0.5
    assert settings.rank_multiplier("junior") == 1.0
    assert settings.rank_multiplier("senior") == 1.5
    assert settings.rank_multiplier("principal") == 2.0

    # Malformed entries silently fall back to 1.0.
    monkeypatch.setattr(
        settings, "academy_rank_multipliers",
        "intern=xx,junior=,=0.5,senior=1.5,garbage",
    )
    assert settings.rank_multiplier("intern") == 1.0  # malformed value
    assert settings.rank_multiplier("junior") == 1.0  # empty value
    assert settings.rank_multiplier("senior") == 1.5  # valid
    assert settings.rank_multiplier("principal") == 1.0  # missing entirely

    # Unknown rank → 1.0.
    assert settings.rank_multiplier("godlike") == 1.0


# ---------------------------------------------------------------------------
# 3. RiskManager uses the rank multiplier.
# ---------------------------------------------------------------------------


def test_risk_manager_uses_rank_multiplier(monkeypatch):
    """Same signal, two ranks → different `check_entry` cap."""
    from tradefarm.config import settings
    from tradefarm.execution.virtual_book import VirtualBook
    from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT, RiskManager

    monkeypatch.setattr(
        settings, "academy_rank_multipliers",
        "intern=0.5,junior=1.0,senior=1.5,principal=2.0",
    )

    starting = 1000.0
    intern = RiskManager(starting_capital=starting, rank="intern")
    senior = RiskManager(starting_capital=starting, rank="senior")

    # Intern effective cap = 0.25 * 0.5 = 0.125 → $125.
    # Senior effective cap = 0.25 * 1.5 = 0.375 → $375.
    assert intern.limits.max_position_notional_pct == pytest.approx(
        BASE_MAX_POSITION_NOTIONAL_PCT * 0.5,
    )
    assert senior.limits.max_position_notional_pct == pytest.approx(
        BASE_MAX_POSITION_NOTIONAL_PCT * 1.5,
    )

    book = VirtualBook(agent_id=1, cash=starting)
    # A $200 notional trade: intern blocks (exceeds $125), senior allows (<$375).
    intern_decision = intern.check_entry(book, "SPY", qty=2, price=100.0)
    senior_decision = senior.check_entry(book, "SPY", qty=2, price=100.0)
    assert intern_decision.allow is False
    assert senior_decision.allow is True


def test_risk_manager_default_rank_is_intern_and_backcompat(monkeypatch):
    """With multipliers unset, rank defaults yield 1.0× — Phase 1 behavior preserved."""
    from tradefarm.config import settings
    from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT, RiskManager

    monkeypatch.setattr(settings, "academy_rank_multipliers", "")
    rm = RiskManager(starting_capital=1000.0)  # no rank arg → "intern"
    # Multiplier is 1.0 (CSV empty) → effective cap == base cap.
    assert rm.limits.max_position_notional_pct == pytest.approx(BASE_MAX_POSITION_NOTIONAL_PCT)


# ---------------------------------------------------------------------------
# 4. Stats from journal.
# ---------------------------------------------------------------------------


async def test_stats_from_journal(academy_db):
    """Seed 10 AgentNotes with outcomes → compute_stats reports them correctly."""
    from tradefarm.academy.ranks import compute_stats
    from tradefarm.storage import journal

    # 7 winners + 3 losers on the same symbol.
    for pnl in [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, -1.0, -2.0, -3.0]:
        await journal.write_note(
            agent_id=1, kind="entry", symbol="SPY", content=f"trade pnl={pnl}",
        )
        await journal.close_outcome(
            agent_id=1, symbol="SPY", realized_pnl=pnl,
        )

    stats = await compute_stats(agent_id=1, starting_capital=1000.0)
    assert stats.n_closed_trades == 10
    assert stats.win_rate == pytest.approx(0.7)
    # Sharpe defined (n>=2, std>0).
    assert stats.sharpe != 0.0
    # Agent was seeded 3 weeks ago (fixture) → weeks_active > 2.
    assert stats.weeks_active >= 2.0


async def test_stats_empty_when_no_trades(academy_db):
    from tradefarm.academy.ranks import compute_stats

    stats = await compute_stats(agent_id=1, starting_capital=1000.0)
    assert stats.n_closed_trades == 0
    assert stats.win_rate == 0.0
    assert stats.sharpe == 0.0


# ---------------------------------------------------------------------------
# 5. End-to-end: seed agent + winning outcomes → rank becomes senior → cap
#    reflects multiplier.
# ---------------------------------------------------------------------------


async def test_end_to_end_winning_outcomes_promote_to_senior(academy_db, monkeypatch):
    from tradefarm.academy import repo as academy_repo
    from tradefarm.academy.ranks import compute_stats, eligible_rank
    from tradefarm.config import settings
    from tradefarm.risk.manager import BASE_MAX_POSITION_NOTIONAL_PCT, RiskManager
    from tradefarm.storage import journal

    monkeypatch.setattr(
        settings, "academy_rank_multipliers",
        "intern=0.5,junior=1.0,senior=1.5,principal=2.0",
    )

    # 20 winning stamped notes — clears junior (n>=5) AND senior (n>=15, wr>=0.52).
    # Kept below 40 to stay *below* principal's min_trades_principal threshold.
    for i in range(20):
        await journal.write_note(
            agent_id=1, kind="entry", symbol="AAPL", content=f"win #{i}",
        )
        await journal.close_outcome(
            agent_id=1, symbol="AAPL", realized_pnl=5.0 + i * 0.01,
        )

    stats = await compute_stats(agent_id=1, starting_capital=1000.0)
    assert stats.n_closed_trades == 20
    assert stats.win_rate == pytest.approx(1.0)

    target = eligible_rank(stats)
    assert target == "senior"

    await academy_repo.set_rank(agent_id=1, rank=target, reason="test")
    assert await academy_repo.get_rank(1) == "senior"

    # RiskManager built for that rank → cap reflects 1.5× multiplier.
    rm = RiskManager(starting_capital=1000.0, rank="senior")
    assert rm.limits.max_position_notional_pct == pytest.approx(
        BASE_MAX_POSITION_NOTIONAL_PCT * 1.5,
    )


async def test_rank_distribution_counts(academy_db):
    """Adding agents at various ranks yields a correct distribution map."""
    from tradefarm.academy import repo as academy_repo
    from tradefarm.storage.db import SessionLocal
    from tradefarm.storage.models import Agent

    async with SessionLocal() as s:
        s.add_all([
            Agent(id=2, name="agent-002", strategy="momentum_sma20",
                  starting_capital=1000.0, cash=1000.0, status="waiting", rank="junior"),
            Agent(id=3, name="agent-003", strategy="momentum_sma20",
                  starting_capital=1000.0, cash=1000.0, status="waiting", rank="senior"),
            Agent(id=4, name="agent-004", strategy="momentum_sma20",
                  starting_capital=1000.0, cash=1000.0, status="waiting", rank="principal"),
        ])
        await s.commit()

    dist = await academy_repo.rank_distribution()
    # Agent 1 is the seed (intern); add one each junior/senior/principal.
    assert dist == {"intern": 1, "junior": 1, "senior": 1, "principal": 1}


async def test_set_rank_noop_on_unknown_rank(academy_db):
    """Invalid rank string → no write; agent stays at intern."""
    from tradefarm.academy import repo as academy_repo

    await academy_repo.set_rank(agent_id=1, rank="godlike", reason="test")  # type: ignore[arg-type]
    assert await academy_repo.get_rank(1) == "intern"
