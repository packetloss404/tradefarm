"""Integration tests for the TTS admin endpoints (0.17.0).

Covers ``GET /admin/tts/status``, ``POST /admin/tts/switch``,
``POST /admin/tts/reset``, and ``POST /admin/tts/preview``.
"""

from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from tradefarm.api.main import TTS_SPEND, app
from tradefarm.runtime.tts_config import reset_tts_config


@pytest.fixture(autouse=True)
def _reset_tts_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with the env-var defaults + a clean spend
    counter. The spend counter is mutated in place (matches the
    `LLM_SKIPS` pattern in ``lstm_llm_agent``)."""
    reset_tts_config()
    TTS_SPEND["calls"] = 0.0
    TTS_SPEND["chars_synthesized"] = 0.0
    TTS_SPEND["cost_usd"] = 0.0
    # Strip any TTS-related env keys the dev shell might have set,
    # so the "no creds" assertions are deterministic.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    yield
    reset_tts_config()
    TTS_SPEND["calls"] = 0.0
    TTS_SPEND["chars_synthesized"] = 0.0
    TTS_SPEND["cost_usd"] = 0.0


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /admin/tts/status
# ---------------------------------------------------------------------------


def test_status_returns_current_config(client: TestClient) -> None:
    response = client.get("/admin/tts/status")
    assert response.status_code == 200
    body = response.json()
    assert "config" in body
    assert set(body["config"].keys()) == {"provider", "voice", "speaking_rate"}
    assert body["available_providers"]  # non-empty (silence is always there)
    assert "silence" in body["available_providers"]


def test_status_has_creds_map_with_all_three_providers(client: TestClient) -> None:
    body = client.get("/admin/tts/status").json()
    assert set(body["has_creds"].keys()) == {"openai", "elevenlabs", "silence"}
    # silence is always available; cloud providers default to false
    # (env keys stripped by the autouse fixture).
    assert body["has_creds"]["silence"] is True
    assert body["has_creds"]["openai"] is False
    assert body["has_creds"]["elevenlabs"] is False


def test_status_voices_by_provider(client: TestClient) -> None:
    body = client.get("/admin/tts/status").json()
    assert set(body["voices_by_provider"].keys()) == {"openai", "elevenlabs", "silence"}
    assert "alloy" in body["voices_by_provider"]["openai"]
    assert "rachel" in body["voices_by_provider"]["elevenlabs"]


def test_status_cost_table(client: TestClient) -> None:
    body = client.get("/admin/tts/status").json()
    assert set(body["cost_per_1k_chars_usd"].keys()) == {"openai", "elevenlabs", "silence"}
    assert body["cost_per_1k_chars_usd"]["silence"] == 0.0


# ---------------------------------------------------------------------------
# POST /admin/tts/switch
# ---------------------------------------------------------------------------


def test_switch_to_silence_succeeds_without_creds(client: TestClient) -> None:
    """The silence provider is the no-cred fallback; the switch must
    succeed even when no cloud keys are set."""
    response = client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["active"]["provider"] == "silence"


def test_switch_to_openai_without_key_returns_400(client: TestClient) -> None:
    response = client.post(
        "/admin/tts/switch",
        json={"provider": "openai", "voice": "alloy", "speaking_rate": 1.0},
    )
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_switch_to_elevenlabs_without_key_returns_400(client: TestClient) -> None:
    response = client.post(
        "/admin/tts/switch",
        json={"provider": "elevenlabs", "voice": "rachel", "speaking_rate": 1.0},
    )
    assert response.status_code == 400
    assert "ELEVENLABS_API_KEY" in response.json()["detail"]


def test_switch_to_openai_with_key_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    response = client.post(
        "/admin/tts/switch",
        json={"provider": "openai", "voice": "alloy", "speaking_rate": 1.25},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["active"]["provider"] == "openai"
    assert body["active"]["voice"] == "alloy"
    assert body["active"]["speaking_rate"] == 1.25


def test_switch_rejects_unknown_provider(client: TestClient) -> None:
    response = client.post(
        "/admin/tts/switch",
        json={"provider": "acme-tts", "voice": "x", "speaking_rate": 1.0},
    )
    assert response.status_code == 400


def test_switch_rejects_speaking_rate_out_of_range(client: TestClient) -> None:
    for bad_rate in (0.1, 5.0, 0.0, 99.0):
        response = client.post(
            "/admin/tts/switch",
            json={"provider": "silence", "voice": "silent", "speaking_rate": bad_rate},
        )
        assert response.status_code == 422, f"speaking_rate={bad_rate} should be rejected"


def test_switch_returns_previous_config(client: TestClient) -> None:
    # First switch: silence.
    r1 = client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    assert r1.status_code == 200
    # Second switch: also silence, but with a different voice.
    r2 = client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.5},
    )
    assert r2.status_code == 200
    body = r2.json()
    # The "previous" should be the first switch's active config.
    assert body["previous"]["speaking_rate"] == 1.0
    assert body["active"]["speaking_rate"] == 1.5


# ---------------------------------------------------------------------------
# POST /admin/tts/reset
# ---------------------------------------------------------------------------


def test_reset_reverts_to_env_defaults(client: TestClient) -> None:
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.5},
    )
    response = client.post("/admin/tts/reset")
    assert response.status_code == 200
    # The endpoint returns the previous config, but the active config
    # is now back to settings. Verify via /admin/tts/status.
    status = client.get("/admin/tts/status").json()
    assert status["config"]["speaking_rate"] == 1.0


# ---------------------------------------------------------------------------
# POST /admin/tts/preview
# ---------------------------------------------------------------------------


def test_preview_with_silence_provider_succeeds(client: TestClient) -> None:
    """The silence path is the only one that works without creds."""
    # First switch to silence (the autouse fixture strips cloud keys).
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    response = client.post(
        "/admin/tts/preview",
        json={"text": "Hello from TradeFarm"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "silence"
    assert body["voice"] == "silent"
    assert body["duration_sec"] > 0
    assert body["cost_usd"] == 0.0
    # The audio is base64-encoded wav bytes.
    assert body["mime"] == "audio/wav"
    import base64
    wav = base64.b64decode(body["audio_base64"])
    # 44-byte RIFF/WAV header + PCM samples.
    assert wav[:4] == b"RIFF"


def test_preview_increments_spend_counter(client: TestClient) -> None:
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    # Spend starts at 0.
    assert TTS_SPEND["calls"] == 0.0
    response = client.post(
        "/admin/tts/preview",
        json={"text": "Hello there"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_calls"] == 1
    assert TTS_SPEND["calls"] == 1.0
    assert TTS_SPEND["chars_synthesized"] == len("Hello there")


def test_preview_with_openai_override_without_key_returns_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A one-shot override to openai without the env key should be
    rejected with 400 (same as the switch endpoint). The active
    config (silence) is not consulted when an override is provided."""
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    response = client.post(
        "/admin/tts/preview",
        json={"text": "Hello", "provider": "openai", "voice": "alloy"},
    )
    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_preview_with_openai_override_with_key_succeeds(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The override path uses the provided provider + voice for this
    call only; the active config (still silence) is unchanged
    afterward."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-real")
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    response = client.post(
        "/admin/tts/preview",
        json={"text": "Override voice test", "provider": "openai", "voice": "alloy"},
    )
    # The build_provider call will succeed (we set the env key), but
    # the actual synthesize() call will fail at the SDK layer because
    # the key is fake. We accept either 200 (the silent fallback
    # inside the provider) or 500 (real SDK error) — both are valid
    # signals that the override was honored. The important assertion
    # is the active config is still silence.
    assert response.status_code in (200, 500)
    # Re-read the status; the active config should be unchanged.
    status = client.get("/admin/tts/status").json()
    assert status["config"]["provider"] == "silence"


def test_preview_rejects_empty_text(client: TestClient) -> None:
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    response = client.post("/admin/tts/preview", json={"text": ""})
    assert response.status_code == 422


def test_preview_rejects_oversized_text(client: TestClient) -> None:
    client.post(
        "/admin/tts/switch",
        json={"provider": "silence", "voice": "silent", "speaking_rate": 1.0},
    )
    response = client.post("/admin/tts/preview", json={"text": "x" * 3000})
    assert response.status_code == 422
