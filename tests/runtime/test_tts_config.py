"""Unit tests for the runtime TTS config singleton.

0.17.0 — the dashboard's TTS settings panel flips the active config at
runtime. These tests cover the round-trip + validation without
spinning up FastAPI.
"""

from __future__ import annotations

import pytest

from tradefarm.runtime.tts_config import (
    COST_PER_1K_CHARS_USD,
    ELEVENLABS_VOICES,
    OPENAI_VOICES,
    SILENCE_VOICES,
    VALID_TTS_PROVIDERS,
    VOICES_BY_PROVIDER,
    TtsConfig,
    estimate_cost_usd,
    get_tts_config,
    reset_tts_config,
    set_tts_config,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    """Each test starts from the env-var defaults so a previous test's
    mutation doesn't bleed into the next one."""
    reset_tts_config()
    yield
    reset_tts_config()


def test_default_config_is_built_from_settings() -> None:
    from tradefarm.config import settings

    config = get_tts_config()
    assert config.provider == settings.podcast_tts_provider
    assert config.voice == settings.podcast_voice
    assert config.speaking_rate == 1.0


def test_set_tts_config_round_trips() -> None:
    new_config = TtsConfig(provider="openai", voice="alloy", speaking_rate=1.25)
    previous = set_tts_config(new_config)
    assert get_tts_config() == new_config
    # The previous config was the env-var default; we don't assert its
    # exact shape (settings may differ between test runs) but it must
    # be a TtsConfig instance.
    assert isinstance(previous, TtsConfig)


def test_set_tts_config_returns_previous() -> None:
    first = TtsConfig(provider="openai", voice="alloy")
    set_tts_config(first)
    second = TtsConfig(provider="elevenlabs", voice="rachel", speaking_rate=0.9)
    previous = set_tts_config(second)
    assert previous == first
    assert get_tts_config() == second


def test_set_tts_config_rejects_unknown_provider() -> None:
    bad = TtsConfig(provider="acme-tts", voice="x")
    with pytest.raises(ValueError, match="unknown provider"):
        set_tts_config(bad)


def test_set_tts_config_rejects_empty_voice() -> None:
    bad = TtsConfig(provider="openai", voice="")
    with pytest.raises(ValueError, match="voice must be a non-empty string"):
        set_tts_config(bad)


def test_set_tts_config_rejects_whitespace_voice() -> None:
    bad = TtsConfig(provider="openai", voice="   ")
    with pytest.raises(ValueError, match="voice must be a non-empty string"):
        set_tts_config(bad)


def test_set_tts_config_rejects_speaking_rate_too_low() -> None:
    bad = TtsConfig(provider="openai", voice="alloy", speaking_rate=0.1)
    with pytest.raises(ValueError, match="speaking_rate"):
        set_tts_config(bad)


def test_set_tts_config_rejects_speaking_rate_too_high() -> None:
    bad = TtsConfig(provider="openai", voice="alloy", speaking_rate=5.0)
    with pytest.raises(ValueError, match="speaking_rate"):
        set_tts_config(bad)


def test_reset_tts_config_reverts_to_settings() -> None:
    set_tts_config(TtsConfig(provider="elevenlabs", voice="rachel"))
    assert get_tts_config().provider == "elevenlabs"
    reset_tts_config()
    from tradefarm.config import settings

    assert get_tts_config().provider == settings.podcast_tts_provider


def test_valid_tts_providers_includes_silence() -> None:
    """The silence provider is the no-cred fallback for CI / dev boxes;
    it must be in the valid set so the dashboard can switch to it."""
    assert "silence" in VALID_TTS_PROVIDERS
    assert "openai" in VALID_TTS_PROVIDERS
    assert "elevenlabs" in VALID_TTS_PROVIDERS


def test_voices_by_provider_covers_all_providers() -> None:
    for provider in VALID_TTS_PROVIDERS:
        assert provider in VOICES_BY_PROVIDER
        assert len(VOICES_BY_PROVIDER[provider]) > 0


def test_openai_voices_match_sdk_stock_set() -> None:
    """Sanity: the OpenAI stock voices are exactly the SDK's 6 — change
    this set deliberately if you add or remove a voice."""
    assert OPENAI_VOICES == (
        "alloy", "echo", "fable", "onyx", "nova", "shimmer",
    )


def test_elevenlabs_voices_contains_known_stock_names() -> None:
    """The ElevenLabs list is a curated subset; this test pins the
    minimum surface so a future cleanup can't quietly drop a name
    operators are relying on."""
    required = {"rachel", "domi", "bella", "antoni"}
    assert required.issubset(set(ELEVENLABS_VOICES))


def test_silence_provider_has_a_voice_label() -> None:
    """The silence provider has no real voice, but the UI wants a label
    so the dropdown isn't empty."""
    assert SILENCE_VOICES == ("silent",)


def test_estimate_cost_usd_for_openai() -> None:
    # 1000 chars at openai rate $0.015/1k = $0.015
    assert estimate_cost_usd("openai", "x" * 1000) == pytest.approx(0.015)
    # 200 chars = $0.003
    assert estimate_cost_usd("openai", "x" * 200) == pytest.approx(0.003)


def test_estimate_cost_usd_for_elevenlabs() -> None:
    # 1000 chars at elevenlabs rate $0.30/1k = $0.30
    assert estimate_cost_usd("elevenlabs", "x" * 1000) == pytest.approx(0.30)


def test_estimate_cost_usd_for_silence_is_zero() -> None:
    assert estimate_cost_usd("silence", "x" * 1000) == 0.0


def test_estimate_cost_usd_for_unknown_provider_is_zero() -> None:
    """Defensive: an unknown provider name yields 0 rather than raising.
    The switch endpoint rejects unknown names before we get here, so
    this is the cost-layer safety net."""
    assert estimate_cost_usd("acme-tts", "x" * 1000) == 0.0


def test_cost_table_covers_all_valid_providers() -> None:
    """The cost map is the source of truth for the dashboard's "this
    will cost ~$X" preview. Every valid provider needs a row (the
    unknown-provider fallback to 0 is a defensive net, not a
    contract)."""
    for provider in VALID_TTS_PROVIDERS:
        assert provider in COST_PER_1K_CHARS_USD


def test_tts_config_is_frozen() -> None:
    """Frozen dataclass — operators mutate via set_tts_config, not
    by mutating the returned object."""
    config = TtsConfig(provider="openai", voice="alloy")
    with pytest.raises(Exception):  # FrozenInstanceError
        config.provider = "elevenlabs"  # type: ignore[misc]


def test_tts_config_to_payload_shape() -> None:
    config = TtsConfig(provider="openai", voice="alloy", speaking_rate=1.5)
    payload = config.to_payload()
    assert payload == {
        "provider": "openai",
        "voice": "alloy",
        "speaking_rate": 1.5,
    }
