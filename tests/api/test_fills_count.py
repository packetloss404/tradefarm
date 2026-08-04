"""MED-new (round-6 audit): /fills/count endpoint.

The VOD "fills today" stat (in web/src/vod/useVodSessionLive.ts:218) was
reading ``liveFills.length`` which is the in-memory WS buffer (capped to
20). After more than 20 fills roll through the buffer, the count was
wrong. This endpoint hits the DB directly so the number stays accurate
regardless of WS buffer size.

Contract:
  - GET /fills/count
  - Optional query: ``since=YYYY-MM-DD`` (defaults to today, UTC).
  - Returns ``{"count": int, "since": "YYYY-MM-DD", "as_of": ISO-8601}``.
  - Live-only: excludes replay-tagged trades (session_id IS NOT NULL).
  - 400 on a malformed ``since`` date.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import tradefarm.api.main as main_mod
from tradefarm.storage.models import Trade


# ---------------------------------------------------------------------------
# Async DB fixture scoped to this file (mirrors test_recap.py's recap_db
# pattern but seeds only the rows we care about).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def fills_db(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr(main_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as s:
        s.add(
            Agent(
                id=1,
                name="agent-001",
                strategy="momentum_12_1",
                starting_capital=1000.0,
                cash=1000.0,
                status="waiting",
            )
        )
        s.add(
            Agent(
                id=2,
                name="agent-002",
                strategy="lstm_v1",
                starting_capital=1000.0,
                cash=1000.0,
                status="waiting",
            )
        )
        await s.commit()

    yield SessionLocal
    await engine.dispose()


def _today() -> date:
    return date.today()


async def test_fills_count_default_since_today(fills_db):
    """No `since` query param → defaults to today, returns today's live fills only."""
    today = _today()
    today_mid = datetime.combine(today, datetime.min.time())
    yesterday = today_mid - timedelta(days=1)

    async with fills_db() as s:
        # 3 fills today (live, session_id NULL).
        s.add(
            Trade(
                agent_id=1,
                symbol="AAPL",
                side="buy",
                qty=1.0,
                price=100.0,
                executed_at=today_mid + timedelta(hours=10),
                reason="x",
            )
        )
        s.add(
            Trade(
                agent_id=1,
                symbol="NVDA",
                side="buy",
                qty=2.0,
                price=200.0,
                executed_at=today_mid + timedelta(hours=11),
                reason="x",
            )
        )
        s.add(
            Trade(
                agent_id=2,
                symbol="MSFT",
                side="sell",
                qty=1.0,
                price=300.0,
                executed_at=today_mid + timedelta(hours=12),
                reason="x",
            )
        )
        # 1 fill yesterday — should NOT count toward today's total.
        s.add(
            Trade(
                agent_id=1,
                symbol="GOOG",
                side="buy",
                qty=1.0,
                price=150.0,
                executed_at=yesterday,
                reason="x",
            )
        )
        await s.commit()

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/fills/count")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 3
    assert body["since"] == today.isoformat()
    # as_of is a tz-aware ISO string.
    parsed = datetime.fromisoformat(body["as_of"])
    assert parsed.tzinfo is not None


async def test_fills_count_explicit_since(fills_db):
    """`since=YYYY-MM-DD` filters Trade.executed_at >= since 00:00 UTC."""
    today = _today()
    three_days_ago = today - timedelta(days=3)
    three_days_ago_mid = datetime.combine(three_days_ago, datetime.min.time())

    async with fills_db() as s:
        s.add(
            Trade(
                agent_id=1,
                symbol="AAPL",
                side="buy",
                qty=1.0,
                price=100.0,
                executed_at=three_days_ago_mid + timedelta(hours=10),
                reason="x",
            )
        )
        s.add(
            Trade(
                agent_id=1,
                symbol="NVDA",
                side="buy",
                qty=2.0,
                price=200.0,
                executed_at=three_days_ago_mid + timedelta(hours=11),
                reason="x",
            )
        )
        await s.commit()

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get(f"/fills/count?since={three_days_ago.isoformat()}")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    assert body["since"] == three_days_ago.isoformat()


async def test_fills_count_excludes_replay_tagged_trades(fills_db):
    """A trade tagged with a session_id (replay) does NOT count toward live fills."""
    today = _today()
    today_mid = datetime.combine(today, datetime.min.time())

    async with fills_db() as s:
        s.add(
            Trade(
                agent_id=1,
                symbol="AAPL",
                side="buy",
                qty=1.0,
                price=100.0,
                executed_at=today_mid,
                reason="live",
            )
        )
        s.add(
            Trade(
                agent_id=1,
                symbol="NVDA",
                side="buy",
                qty=2.0,
                price=200.0,
                executed_at=today_mid + timedelta(hours=1),
                reason="replay",
                session_id="session-abc-123",
            )
        )
        await s.commit()

    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/fills/count")
    assert r.status_code == 200
    assert r.json()["count"] == 1  # replay row excluded


async def test_fills_count_zero_when_empty(fills_db):
    """No trades in the window → count=0, response still well-formed."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/fills/count")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 0
    assert "since" in body
    assert "as_of" in body


async def test_fills_count_rejects_malformed_since(fills_db):
    """A `since` value that isn't YYYY-MM-DD returns 422 (FastAPI date validation)."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/fills/count?since=not-a-date")
    assert r.status_code == 422
