"""Smoke test for the /market/clock router.

Avoids the full app startup (which would spin up the orchestrator + DB) by
mounting just the router on a fresh FastAPI app.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradefarm.api.market_clock import router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_market_clock_returns_one_of_four_phases() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] in {"premarket", "rth", "afterhours", "closed"}


def test_market_clock_server_now_is_iso_utc() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    data = r.json()
    parsed = datetime.fromisoformat(data["server_now"])
    assert parsed.tzinfo is not None


def test_market_clock_open_close_iso_or_null() -> None:
    with _client() as c:
        r = c.get("/market/clock")
    data = r.json()
    for key in ("opens_at", "closes_at"):
        v = data[key]
        if v is None:
            continue
        parsed = datetime.fromisoformat(v)
        assert parsed.tzinfo is not None
