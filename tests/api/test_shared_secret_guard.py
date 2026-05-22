"""Audit fix (H28): X-TradeFarm-Token middleware behavior.

Verifies the shared-secret guard registered in ``tradefarm.api.main``:
  (a) no secret set       → POST allowed (unchanged behavior, backwards-compat).
  (b) secret set + missing header → 401.
  (c) secret set + wrong header   → 401.
  (d) secret set + GET            → allowed (read-only surface stays open).
  (e) ``/health`` exempt even with secret set (so health probes never break).

The middleware function is imported from main and re-registered on a
fresh FastAPI app, so the test exercises the REAL middleware code
(not a reimplementation) without booting the real app's lifespan.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradefarm.api.main import _shared_secret_guard
from tradefarm.config import settings


def _build_app() -> FastAPI:
    """Fresh FastAPI app with the real middleware + minimal routes."""
    app = FastAPI()
    # Re-register the real middleware function on this fresh app.
    app.middleware("http")(_shared_secret_guard)

    @app.get("/health")
    async def _health():
        return {"status": "ok"}

    @app.get("/agents")
    async def _agents():
        return []

    @app.post("/tick")
    async def _tick():
        return {"fills": 0}

    return app


def test_no_secret_set_post_allowed(monkeypatch):
    """(a) When ``api_shared_secret`` is empty, POSTs go through unchanged."""
    monkeypatch.setattr(settings, "api_shared_secret", "")
    with TestClient(_build_app()) as c:
        r = c.post("/tick")
    assert r.status_code == 200
    assert r.json() == {"fills": 0}


def test_secret_set_missing_header_returns_401(monkeypatch):
    """(b) Secret configured + no token header → 401 from the middleware."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    with TestClient(_build_app()) as c:
        r = c.post("/tick")
    assert r.status_code == 401
    assert "X-TradeFarm-Token" in r.json()["detail"]


def test_secret_set_wrong_header_returns_401(monkeypatch):
    """(c) Secret configured + WRONG token → 401."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    with TestClient(_build_app()) as c:
        r = c.post("/tick", headers={"X-TradeFarm-Token": "not-the-secret"})
    assert r.status_code == 401


def test_secret_set_get_allowed_without_header(monkeypatch):
    """(d) GETs stay open even when the secret is set — the dashboard's
    polling doesn't have to thread the token through every fetch."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    with TestClient(_build_app()) as c:
        r = c.get("/agents")
    assert r.status_code == 200
    assert r.json() == []


def test_health_exempt_even_with_secret(monkeypatch):
    """(e) ``/health`` is in _AUTH_EXEMPT_PREFIXES so probes never 401."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    with TestClient(_build_app()) as c:
        r = c.get("/health")  # GET would pass anyway; confirm explicitly
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_secret_set_correct_header_allows_post(monkeypatch):
    """Sanity check companion to (b)/(c): correct token → POST succeeds."""
    monkeypatch.setattr(settings, "api_shared_secret", "swordfish")
    with TestClient(_build_app()) as c:
        r = c.post("/tick", headers={"X-TradeFarm-Token": "swordfish"})
    assert r.status_code == 200
