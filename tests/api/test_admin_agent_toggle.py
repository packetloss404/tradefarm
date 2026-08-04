"""Per-agent enable/disable admin endpoints.

Covers the new `/admin/agents` family:
  - GET  /admin/agents                     → all 100 agents with their disable state
  - POST /admin/agents/{id}/disabled       → flip one agent
  - POST /admin/agents/bulk-disabled       → flip a batch of agents in one request

The per-agent `disabled` flag is a *runtime* signal — it's deliberately
NOT in `admin.SECRET_KEYS` (the suffix-based secret-mask set is keyed on
`_api_key` / `_secret` / `_token` / `_refresh_token`). This test pins that
contract so a future refactor can't accidentally start masking the
`disabled` field on the `/admin/config` payload.
"""

from __future__ import annotations

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import tradefarm.api.main as main_mod
from tradefarm.api import admin as admin_mod


# ---------------------------------------------------------------------------
# Async DB fixture scoped to this file (mirrors test_fills_count.py's
# fills_db pattern: in-memory SQLite, full schema via Base.metadata.create_all).
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def agents_db(monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from tradefarm.storage.models import Agent, Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Patch the SessionLocal reference on EVERY module that imported it
    # at module-load time — repo.py has its own `from tradefarm.storage.db
    # import SessionLocal` so a patch on main_mod (or db_mod) alone
    # wouldn't redirect its DB calls to our in-memory engine.
    monkeypatch.setattr(main_mod, "SessionLocal", SessionLocal)
    from tradefarm.storage import db as db_mod
    from tradefarm.storage import repo as repo_mod

    monkeypatch.setattr(db_mod, "SessionLocal", SessionLocal)
    monkeypatch.setattr(repo_mod, "SessionLocal", SessionLocal)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 100 agents (the production count), one per slot of the universe
    # so the GET response covers the full range and the bulk endpoint
    # has a real population to slice.
    async with SessionLocal() as s:
        for i in range(100):
            s.add(
                Agent(
                    id=i,
                    name=f"agent-{i:03d}",
                    strategy=("momentum_12_1" if i % 3 == 0 else "lstm_v1" if i % 3 == 1 else "lstm_llm_v1"),
                    starting_capital=1000.0,
                    cash=1000.0,
                    status="waiting",
                )
            )
        await s.commit()

    # Pin settings.agent_count to 100 so the range-guard in
    # admin._validate_agent_id mirrors the seeded population.
    from tradefarm.config import settings

    monkeypatch.setattr(settings, "agent_count", 100)

    yield SessionLocal
    await engine.dispose()


async def test_list_agents_returns_all_100_with_disabled_state(agents_db):
    """GET /admin/agents returns the full population with the per-agent flag."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/admin/agents")
    assert r.status_code == 200, r.text
    rows = r.json()
    assert len(rows) == 100, f"expected 100 agents, got {len(rows)}"
    # Default value is False (server_default="0"); an unflagged row must
    # surface as `disabled: false` so the UI can render the toggle ON.
    assert all(row["disabled"] is False for row in rows)
    # Each row has the 5 fields the UI needs (no extras leaking).
    sample = rows[0]
    assert set(sample.keys()) == {"id", "name", "strategy", "disabled", "cash"}
    assert sample["cash"] == 1000.0
    # Stable ordering by id (so the UI list doesn't reshuffle between polls).
    assert [r["id"] for r in rows] == list(range(100))


async def test_set_agent_disabled_true(agents_db):
    """POST /admin/agents/{id}/disabled with disabled=true flips the DB row."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/admin/agents/7/disabled", json={"disabled": True})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"agent_id": 7, "disabled": True}

    # Persisted: a fresh GET must report the row as disabled.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r2 = await ac.get("/admin/agents")
    rows = r2.json()
    assert rows[7]["disabled"] is True
    # No collateral damage on neighbors.
    assert rows[6]["disabled"] is False
    assert rows[8]["disabled"] is False


async def test_set_agent_disabled_false(agents_db):
    """POST /admin/agents/{id}/disabled with disabled=false is reversible."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # First, flip ON.
        r = await ac.post("/admin/agents/42/disabled", json={"disabled": True})
        assert r.status_code == 200
        # Then, flip OFF.
        r = await ac.post("/admin/agents/42/disabled", json={"disabled": False})
    assert r.status_code == 200, r.text
    assert r.json() == {"agent_id": 42, "disabled": False}

    # Persisted flip-off.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        rows = (await ac.get("/admin/agents")).json()
    assert rows[42]["disabled"] is False


async def test_set_agent_disabled_rejects_out_of_range_id(agents_db):
    """A negative id or id >= settings.agent_count returns 400."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post("/admin/agents/-1/disabled", json={"disabled": True})
        assert r.status_code == 400
        assert "out of range" in r.json()["detail"]
        # >= settings.agent_count (100) is also out of range.
        r = await ac.post("/admin/agents/100/disabled", json={"disabled": True})
        assert r.status_code == 400
        r = await ac.post("/admin/agents/9999/disabled", json={"disabled": True})
        assert r.status_code == 400


async def test_bulk_set_disabled_makes_all_agents_disabled(agents_db):
    """POST /admin/agents/bulk-disabled flips a list in one request."""
    transport = ASGITransport(app=main_mod.app)
    target_ids = [1, 2, 3]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/admin/agents/bulk-disabled",
            json={"agent_ids": target_ids, "disabled": True},
        )
    assert r.status_code == 200, r.text
    assert r.json() == {"updated": target_ids}

    # All three rows are now disabled in the DB.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        rows = (await ac.get("/admin/agents")).json()
    for i in target_ids:
        assert rows[i]["disabled"] is True
    # And bulk-flips are reversible too.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/admin/agents/bulk-disabled",
            json={"agent_ids": target_ids, "disabled": False},
        )
        assert r.status_code == 200
        rows = (await ac.get("/admin/agents")).json()
    for i in target_ids:
        assert rows[i]["disabled"] is False


async def test_bulk_set_disabled_rejects_any_out_of_range_id(agents_db):
    """If any id in the batch is out of range, the whole batch is rejected (no partial updates)."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/admin/agents/bulk-disabled",
            json={"agent_ids": [1, 2, 999], "disabled": True},
        )
    assert r.status_code == 400
    # Confirm none of the batch was applied.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        rows = (await ac.get("/admin/agents")).json()
    assert rows[1]["disabled"] is False
    assert rows[2]["disabled"] is False


async def test_bulk_set_disabled_with_empty_list(agents_db):
    """An empty agent_ids list is a no-op (200, updated=[])."""
    transport = ASGITransport(app=main_mod.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/admin/agents/bulk-disabled",
            json={"agent_ids": [], "disabled": True},
        )
    assert r.status_code == 200
    assert r.json() == {"updated": []}


def test_disabled_field_is_not_in_secret_keys():
    """The per-agent `disabled` field is NOT a secret — it must never be masked.

    `SECRET_KEYS` is the suffix-based allowlist used by `/admin/config`
    GET to mask credential fields (api keys, secrets, tokens, refresh
    tokens). The `disabled` field is an operator-facing bool and the
    admin UI must be able to read its actual value to render toggles.
    A regression here would silently replace the field with `***` in
    the admin response and break the toggle UI.
    """
    for k in admin_mod.SECRET_KEYS:
        assert k != "disabled", "disabled must not be in SECRET_KEYS"
        assert not k.endswith("_disabled"), (
            f"{k!r} looks like a derivative of `disabled` — should not be masked"
        )
