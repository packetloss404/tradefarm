"""Integration tests for the 0.18.0 LLM model picker admin endpoints.

Covers ``GET /admin/llm/models``, ``POST /admin/llm/select``,
``POST /admin/llm/reset``. The catalog module is mocked so the
endpoint tests don't depend on real network calls.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from tradefarm.api.main import app
from tradefarm.runtime import llm_model_catalog as _catalog
from tradefarm.runtime.llm_model_config import reset_llm_model_config, set_llm_model_config


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with the env-var defaults + a clean
    catalog cache. The catalog fixture bypasses the real network
    via monkey-patching."""
    from tradefarm.config import settings

    reset_llm_model_config()
    _catalog.reset_model_catalog_cache()
    # Strip any LLM-related env keys the dev shell might have set,
    # so the "no creds" assertions are deterministic.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    # Also blank the Settings fields directly. pydantic-settings
    # reads env vars at import time; subsequent monkeypatch
    # mutations don't refresh the field.
    settings.anthropic_api_key = ""
    settings.openai_api_key = ""
    settings.minimax_api_key = ""
    monkeypatch.setattr(_catalog, "PROVIDER_TIMEOUT_SEC", 0.5)
    yield
    reset_llm_model_config()
    _catalog.reset_model_catalog_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _stub_catalog(monkeypatch: pytest.MonkeyPatch, **states: dict) -> None:
    """Stub the catalog's per-provider fetchers to return canned
    ProviderListing objects. ``states`` keys are 'anthropic',
    'openai', 'minimax'; values are dicts of kwargs for the
    ProviderListing constructor."""

    async def _anthropic_stub(_client) -> _catalog.ProviderListing:
        return _catalog.ProviderListing(**(states.get("anthropic") or {"ok": False, "error": "ANTHROPIC_API_KEY not set"}))

    async def _openai_stub(_client) -> _catalog.ProviderListing:
        return _catalog.ProviderListing(**(states.get("openai") or {"ok": False, "error": "OPENAI_API_KEY not set"}))

    async def _minimax_stub(_client) -> _catalog.ProviderListing:
        return _catalog.ProviderListing(**(states.get("minimax") or {"ok": False, "error": "MINIMAX_API_KEY not set"}))

    monkeypatch.setattr(_catalog, "_fetch_anthropic", _anthropic_stub)
    monkeypatch.setattr(_catalog, "_fetch_openai", _openai_stub)
    monkeypatch.setattr(_catalog, "_fetch_minimax", _minimax_stub)


# ---------------------------------------------------------------------------
# GET /admin/llm/models
# ---------------------------------------------------------------------------


def test_list_models_returns_per_provider_envelope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_catalog(
        monkeypatch,
        anthropic={"ok": True, "fetched_at": "2026-08-10T14:23:01Z"},
        openai={"ok": False, "error": "OPENAI_API_KEY not set"},
        minimax={"ok": True, "fetched_at": "2026-08-10T14:23:01Z"},
    )
    response = client.get("/admin/llm/models")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"anthropic", "openai", "minimax", "cached_at"}
    # Each provider carries the documented shape.
    for provider in ("anthropic", "openai", "minimax"):
        assert set(body[provider].keys()) == {
            "ok",
            "models",
            "fetched_at",
            "error",
            "ttl_sec",
        }
    assert body["anthropic"]["ok"] is True
    assert body["openai"]["ok"] is False
    assert "OPENAI_API_KEY" in body["openai"]["error"]
    assert body["minimax"]["ok"] is True


def test_list_models_with_models_in_payload(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The per-provider ``models`` array carries the ModelEntry
    shape: id, display_name, created_at, context_tokens,
    capabilities, cost_hint_usd."""
    models = (
        _catalog.ModelEntry(
            id="claude-haiku-4-5-20251001",
            display_name="Claude Haiku 4.5",
            created_at="2025-10-15T00:00:00Z",
            context_tokens=200000,
            capabilities={"thinking": {"supported": True}},
            cost_hint_usd={
                "input_per_million": 1.00,
                "output_per_million": 5.00,
            },
        ),
    )
    _stub_catalog(
        monkeypatch,
        anthropic={"ok": True, "models": models, "fetched_at": "2026-08-10T14:23:01Z"},
    )
    response = client.get("/admin/llm/models")
    body = response.json()
    assert len(body["anthropic"]["models"]) == 1
    row = body["anthropic"]["models"][0]
    assert row["id"] == "claude-haiku-4-5-20251001"
    assert row["display_name"] == "Claude Haiku 4.5"
    assert row["created_at"] == "2025-10-15T00:00:00Z"
    assert row["context_tokens"] == 200000
    assert row["cost_hint_usd"]["input_per_million"] == 1.00


def test_list_models_force_refetch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``?refresh=true`` calls ``get_model_catalog(force=True)``."""
    call_count = 0

    async def _counting(_client) -> _catalog.ProviderListing:
        nonlocal call_count
        call_count += 1
        return _catalog.ProviderListing(ok=True, fetched_at="2026-08-10T14:23:01Z")

    monkeypatch.setattr(_catalog, "_fetch_anthropic", _counting)

    client.get("/admin/llm/models")
    assert call_count == 1
    # Without refresh, the cache serves the previous result.
    client.get("/admin/llm/models")
    assert call_count == 1
    # With refresh, we re-fetch.
    client.get("/admin/llm/models?refresh=true")
    assert call_count == 2


def test_list_models_includes_ttl_sec(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_catalog(monkeypatch, anthropic={"ok": True})
    body = client.get("/admin/llm/models").json()
    # The default TTL is 60 min (3600s) per the spec.
    assert body["anthropic"]["ttl_sec"] == 3600


# ---------------------------------------------------------------------------
# POST /admin/llm/select
# ---------------------------------------------------------------------------


def test_select_rejects_unknown_provider(client: TestClient) -> None:
    response = client.post(
        "/admin/llm/select",
        json={"provider": "acme-llm", "model": "whatever"},
    )
    assert response.status_code == 400
    assert "unknown provider" in response.json()["detail"]


def test_select_rejects_empty_model(client: TestClient) -> None:
    response = client.post(
        "/admin/llm/select",
        json={"provider": "anthropic", "model": ""},
    )
    assert response.status_code == 422  # pydantic min_length=1


def test_select_anthropic_without_key_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ANTHROPIC_API_KEY is stripped by the autouse fixture.
    response = client.post(
        "/admin/llm/select",
        json={"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    )
    assert response.status_code == 400
    assert "ANTHROPIC_API_KEY" in response.json()["detail"]


def test_select_openai_without_key_returns_400(client: TestClient) -> None:
    response = client.post(
        "/admin/llm/select",
        json={"provider": "openai", "model": "gpt-5.6-sol"},
    )
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_select_minimax_without_key_returns_400(client: TestClient) -> None:
    response = client.post(
        "/admin/llm/select",
        json={"provider": "minimax", "model": "M2.7-highspeed"},
    )
    assert response.status_code == 400
    assert "MINIMAX_API_KEY" in response.json()["detail"]


def test_select_with_key_updates_runtime_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tradefarm.config import settings
    from tradefarm.runtime.llm_model_config import get_llm_model_config

    # pydantic-settings reads env at import time; set the
    # Settings field directly so the runtime config can find
    # the key. The select endpoint gates on the settings value.
    settings.openai_api_key = "test-openai-key-not-real"
    response = client.post(
        "/admin/llm/select",
        json={"provider": "openai", "model": "gpt-5.6-sol"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["active"] == {"provider": "openai", "model": "gpt-5.6-sol"}
    assert "previous" in body
    # The runtime singleton was updated.
    cfg = get_llm_model_config()
    assert cfg.provider == "openai"
    assert cfg.model == "gpt-5.6-sol"


def test_select_returns_previous_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two sequential selects; the second response's ``previous``
    is the first select's ``active``."""
    from tradefarm.config import settings

    settings.anthropic_api_key = "test-anthropic-key"
    settings.openai_api_key = "test-openai-key"

    r1 = client.post(
        "/admin/llm/select",
        json={"provider": "openai", "model": "gpt-5.6-sol"},
    )
    assert r1.status_code == 200
    r2 = client.post(
        "/admin/llm/select",
        json={"provider": "anthropic", "model": "claude-opus-4-8"},
    )
    assert r2.status_code == 200
    body = r2.json()
    assert body["previous"] == {"provider": "openai", "model": "gpt-5.6-sol"}
    assert body["active"] == {"provider": "anthropic", "model": "claude-opus-4-8"}


# ---------------------------------------------------------------------------
# POST /admin/llm/reset
# ---------------------------------------------------------------------------


def test_reset_reverts_runtime_config(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tradefarm.runtime.llm_model_config import get_llm_model_config

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    set_llm_model_config(
        __import__(
            "tradefarm.runtime.llm_model_config", fromlist=["LlmModelConfig"]
        ).LlmModelConfig(provider="openai", model="gpt-5.6-sol")
    )
    assert get_llm_model_config().provider == "openai"

    response = client.post("/admin/llm/reset")
    assert response.status_code == 200
    body = response.json()
    # The endpoint returns the previous config.
    assert body["previous"]["provider"] == "openai"
    # The active config is back to the env-var defaults - the
    # provider may not be "openai" anymore (depending on the
    # env). We just assert the singleton is back in sync with
    # the settings-derived default.
    assert get_llm_model_config().provider != "openai"


def test_reset_when_already_at_defaults(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Resetting an already-defaulted config is a no-op; the
    endpoint still returns the previous config (which equals the
    new one) so the dashboard's UI can show "previous: X"."""
    response = client.post("/admin/llm/reset")
    assert response.status_code == 200
    assert "previous" in response.json()
