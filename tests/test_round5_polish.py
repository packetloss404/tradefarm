"""Round-5 production-polish tests:

- BB: daily LLM budget ceiling
- CC: /metrics exposes the right counters
- AA: shared httpx client lifecycle
- DD: Postgres dispatch in _table_columns (smoke)
"""

from __future__ import annotations


# ----- BB: daily LLM budget ----------------------------------------------


def test_llm_budget_disabled_when_zero(monkeypatch):
    from tradefarm.runtime import llm_budget as lb

    monkeypatch.setattr(lb.settings, "llm_daily_budget_usd", 0.0)
    lb.reset_for_test()
    assert lb.is_over_budget() is False

    lb.register_call(input_tokens=1_000_000, output_tokens=1_000_000)
    # Spent significant USD but the gate is off → still not over.
    assert lb.today_usd() > 0
    assert lb.is_over_budget() is False


def test_llm_budget_trips_when_spend_crosses_cap(monkeypatch):
    from tradefarm.runtime import llm_budget as lb

    monkeypatch.setattr(lb.settings, "llm_daily_budget_usd", 0.001)
    lb.reset_for_test()
    assert lb.is_over_budget() is False

    # 1000 input tokens × $0.80/1M = $0.0008 — under the cap.
    lb.register_call(input_tokens=1000, output_tokens=0)
    assert lb.is_over_budget() is False

    # Bump output to push past $0.001.
    lb.register_call(input_tokens=0, output_tokens=200)
    assert lb.is_over_budget() is True


def test_llm_budget_snapshot_shape(monkeypatch):
    from tradefarm.runtime import llm_budget as lb

    monkeypatch.setattr(lb.settings, "llm_daily_budget_usd", 5.0)
    lb.reset_for_test()
    lb.register_call(input_tokens=100, output_tokens=50, cache_read_tokens=200)
    lb.register_blocked()
    snap = lb.snapshot()
    assert snap["input_tokens"] == 100
    assert snap["output_tokens"] == 50
    assert snap["cache_read_tokens"] == 200
    assert snap["calls"] == 1
    assert snap["blocked"] == 1
    assert snap["budget_usd"] == 5.0
    assert snap["usd"] > 0


# ----- AA: shared httpx client lifecycle ---------------------------------


async def test_shared_client_is_singleton(monkeypatch):
    from tradefarm.runtime import http as runtime_http

    monkeypatch.setattr(runtime_http, "_client", None)
    c1 = await runtime_http.get_shared_client()
    c2 = await runtime_http.get_shared_client()
    assert c1 is c2
    await runtime_http.aclose_shared_client()
    # After close, the next get rebuilds.
    c3 = await runtime_http.get_shared_client()
    assert c3 is not c1
    await runtime_http.aclose_shared_client()


# ----- DD: Postgres dispatch (smoke) -------------------------------------


async def test_table_columns_sqlite_dialect(tmp_path):
    """Sanity-check the SQLite branch still works after the dialect
    dispatch refactor."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from tradefarm.storage.db import _table_columns
    from tradefarm.storage.models import Base

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        cols = await _table_columns(conn, "agents")
    assert "id" in cols
    assert "rank" in cols
    await eng.dispose()


async def test_table_columns_empty_for_missing_table(tmp_path):
    from sqlalchemy.ext.asyncio import create_async_engine
    from tradefarm.storage.db import _table_columns

    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/t.db", echo=False)
    async with eng.begin() as conn:
        cols = await _table_columns(conn, "does_not_exist")
    assert cols == set()
    await eng.dispose()


# ----- CC: /metrics endpoint shape ---------------------------------------


async def test_metrics_lines_are_prometheus_shaped():
    """Each non-HELP/TYPE line must be `name value\\n`.

    Calls the `metrics` route function directly (with a stub Request)
    instead of going through TestClient — TestClient would boot the
    full lifespan (DB + orchestrator + sidecars) which is expensive
    and unrelated to what we're testing here."""
    from types import SimpleNamespace

    from tradefarm.api.main import metrics

    # Stub Request with the orchestrator field the route reads.
    stub_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(orchestrator=None)))
    body = await metrics(stub_request)
    assert "tradefarm_llm_calls_total" in body
    assert "tradefarm_llm_budget_spent_usd" in body
    assert "tradefarm_last_tick_timestamp_seconds" in body
    # Spot-check exposition format: every "tradefarm_*" line that
    # isn't a # HELP/TYPE has exactly one space + a value.
    for line in body.splitlines():
        if line.startswith("tradefarm_"):
            parts = line.split(" ")
            assert len(parts) == 2, f"malformed metric line: {line!r}"
            # Value parses as float.
            float(parts[1])
