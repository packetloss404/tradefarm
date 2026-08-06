"""Tests for the 0.19.0 ``GET /decisions/recent`` endpoint.

The endpoint reads from the process-wide ``recent_decisions_ledger``
singleton in ``tradefarm.api.main``. To keep tests hermetic we
monkeypatch that singleton with a fresh ledger per test (via the
``client`` fixture's teardown) so the endpoint's responses are
deterministic.

We do NOT exercise the lifespan-spawned subscriber here — that's
covered indirectly by the unit tests in
``tests/orchestrator/test_recent_decisions.py``. The endpoint
contract is what this file verifies.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradefarm.orchestrator.recent_decisions import RecentDecisionsLedger


@pytest.fixture
def client(monkeypatch):
    """FastAPI TestClient with a fresh per-test ``RecentDecisionsLedger``.

    We monkeypatch the module-level ``recent_decisions_ledger``
    singleton on ``tradefarm.api.main`` so the endpoint reads from a
    clean ring buffer. The previous value is restored at teardown
    via the ``monkeypatch`` finalizer chain.
    """
    import tradefarm.api.main as main_mod

    fresh_ledger = RecentDecisionsLedger(max_entries=50)
    monkeypatch.setattr(main_mod, "recent_decisions_ledger", fresh_ledger)
    # TestClient without `with` — the endpoint doesn't need the
    # orchestrator, and skipping lifespan keeps the test fast.
    yield TestClient(main_mod.app), fresh_ledger


def _entry(
    agent_id: int,
    *,
    strategy: str = "lstm_llm_v1",
    llm_bias: str | None = "long",
    llm_stance: str | None = "trade",
    tick_id: str = "t-1",
) -> dict:
    return {
        "agent_id": agent_id,
        "agent_name": f"agent-{agent_id:03d}",
        "strategy": strategy,
        "symbol": "NVDA",
        "verdict": "trade",
        "reason": "llm says go",
        "llm_bias": llm_bias,
        "llm_stance": llm_stance,
        "at": "2026-08-05T20:00:00+00:00",
        "tick_id": tick_id,
    }


def test_endpoint_returns_empty_when_ledger_empty(client) -> None:
    c, _led = client
    r = c.get("/decisions/recent")
    assert r.status_code == 200
    body = r.json()
    assert body["entries"] == []
    assert body["total_in_ledger"] == 0
    assert body["limit"] == 50  # default
    assert body["agent_id"] is None
    assert body["only_llm"] is False


def test_endpoint_returns_recorded_entries_newest_first(client) -> None:
    c, led = client
    led.record_batch(
        {
            "tick_id": "t-1",
            "at": "2026-08-05T20:00:00+00:00",
            "decisions": [_entry(1), _entry(2), _entry(3)],
        }
    )
    r = c.get("/decisions/recent")
    body = r.json()
    assert [e["agent_id"] for e in body["entries"]] == [3, 2, 1]
    assert body["total_in_ledger"] == 3


def test_endpoint_respects_limit_query_param(client) -> None:
    c, led = client
    led.record_batch(
        {
            "tick_id": "t-1",
            "at": "2026-08-05T20:00:00+00:00",
            "decisions": [_entry(i) for i in range(10)],
        }
    )
    r = c.get("/decisions/recent?limit=3")
    body = r.json()
    assert len(body["entries"]) == 3
    assert [e["agent_id"] for e in body["entries"]] == [9, 8, 7]
    # total_in_ledger reflects the ledger, not the response.
    assert body["total_in_ledger"] == 10


def test_endpoint_rejects_limit_above_max(client) -> None:
    c, _ = client
    r = c.get("/decisions/recent?limit=500")
    assert r.status_code == 422  # FastAPI validation error


def test_endpoint_rejects_zero_limit(client) -> None:
    c, _ = client
    r = c.get("/decisions/recent?limit=0")
    assert r.status_code == 422


def test_endpoint_filters_by_agent_id(client) -> None:
    c, led = client
    led.record_batch(
        {
            "tick_id": "t-mix",
            "at": "2026-08-05T20:00:00+00:00",
            "decisions": [
                _entry(1, tick_id="t-mix"),
                _entry(2, tick_id="t-mix"),
                _entry(1, tick_id="t-mix"),
                _entry(3, tick_id="t-mix"),
            ],
        }
    )
    r = c.get("/decisions/recent?agent_id=1")
    body = r.json()
    assert len(body["entries"]) == 2
    assert all(e["agent_id"] == 1 for e in body["entries"])
    assert body["agent_id"] == 1


def test_endpoint_only_llm_filter_excludes_rule_based(client) -> None:
    c, led = client
    led.record_batch(
        {
            "tick_id": "t-mix",
            "at": "2026-08-05T20:00:00+00:00",
            "decisions": [
                _entry(1, strategy="lstm_llm_v1", llm_bias="long", llm_stance="trade"),
                _entry(2, strategy="lstm_v1", llm_bias=None, llm_stance=None),
                _entry(
                    3,
                    strategy="momentum_sma20",
                    llm_bias=None,
                    llm_stance=None,
                ),
            ],
        }
    )
    r = c.get("/decisions/recent?only_llm=true")
    body = r.json()
    assert len(body["entries"]) == 1
    assert body["entries"][0]["agent_id"] == 1
    assert body["only_llm"] is True


def test_endpoint_round_trip_via_subscriber_pattern(client) -> None:
    """End-to-end check that an ``agent_decisions_batch`` envelope
    published on the event bus is observed by a future subscriber
    AND ends up in the ledger. Simulates the lifespan subscriber
    without booting the full app lifespan.
    """
    import asyncio

    import tradefarm.api.events as events_mod
    import tradefarm.api.main as main_mod

    c, led = client

    async def _publish_and_record() -> None:
        async with events_mod.bus.subscribe() as q:
            # Publish from a side task so the subscriber-side queue
            # actually receives the envelope.
            async def _pub() -> None:
                await events_mod.publish_event(
                    "agent_decisions_batch",
                    {
                        "tick_id": "t-live",
                        "at": "2026-08-05T20:00:00+00:00",
                        "decisions": [_entry(7), _entry(8)],
                    },
                )

            pub_task = asyncio.create_task(_pub())
            event = await asyncio.wait_for(q.get(), timeout=2.0)
            if event.get("type") == "agent_decisions_batch":
                main_mod.recent_decisions_ledger.record_batch(event["payload"])
            await pub_task

    asyncio.run(_publish_and_record())

    r = c.get("/decisions/recent")
    body = r.json()
    assert body["total_in_ledger"] == 2
    assert sorted(e["agent_id"] for e in body["entries"]) == [7, 8]
