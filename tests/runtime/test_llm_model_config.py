"""Unit tests for the runtime LLM model config singleton.

0.18.0 - the dashboard's LLM model picker flips the active provider
+ model at runtime. These tests cover the round-trip + validation
without spinning up FastAPI.
"""

from __future__ import annotations

import pytest

from tradefarm.runtime.llm_model_config import (
    LlmModelConfig,
    VALID_LLM_PROVIDERS,
    get_llm_model_config,
    reset_llm_model_config,
    set_llm_model_config,
)


@pytest.fixture(autouse=True)
def _reset_config() -> None:
    """Each test starts from the env-var defaults so a previous test's
    mutation doesn't bleed into the next one."""
    reset_llm_model_config()
    yield
    reset_llm_model_config()


def test_default_config_is_built_from_settings() -> None:

    config = get_llm_model_config()
    # settings.llm_provider is one of the three valid providers
    # (the broadened Literal includes "openai" now); if it was
    # empty the bootstrap falls back to "anthropic".
    assert config.provider in VALID_LLM_PROVIDERS
    assert config.model  # non-empty (the default constant for the provider)


def test_set_llm_model_config_round_trips() -> None:
    new_config = LlmModelConfig(provider="openai", model="gpt-5.6-sol")
    previous = set_llm_model_config(new_config)
    assert get_llm_model_config() == new_config
    assert isinstance(previous, LlmModelConfig)


def test_set_llm_model_config_returns_previous() -> None:
    first = LlmModelConfig(provider="anthropic", model="claude-haiku-4-5-20251001")
    set_llm_model_config(first)
    second = LlmModelConfig(provider="openai", model="gpt-5.6-sol")
    previous = set_llm_model_config(second)
    assert previous == first
    assert get_llm_model_config() == second


def test_set_llm_model_config_rejects_unknown_provider() -> None:
    bad = LlmModelConfig(provider="acme-llm", model="whatever")
    with pytest.raises(ValueError, match="unknown provider"):
        set_llm_model_config(bad)


def test_set_llm_model_config_rejects_empty_model() -> None:
    bad = LlmModelConfig(provider="openai", model="")
    with pytest.raises(ValueError, match="model must be a non-empty string"):
        set_llm_model_config(bad)


def test_set_llm_model_config_rejects_whitespace_model() -> None:
    bad = LlmModelConfig(provider="openai", model="   ")
    with pytest.raises(ValueError, match="model must be a non-empty string"):
        set_llm_model_config(bad)


def test_reset_llm_model_config_reverts_to_settings() -> None:
    set_llm_model_config(LlmModelConfig(provider="openai", model="gpt-5.6-sol"))
    assert get_llm_model_config().provider == "openai"
    reset_llm_model_config()
    # After reset, the active config should match what the
    # settings-derived default would build. We don't pin the
    # exact value (settings.llm_provider is environment-driven)
    # but the provider must be one of the three valid.
    assert get_llm_model_config().provider in VALID_LLM_PROVIDERS


def test_valid_llm_providers_includes_all_three() -> None:
    assert "anthropic" in VALID_LLM_PROVIDERS
    assert "openai" in VALID_LLM_PROVIDERS
    assert "minimax" in VALID_LLM_PROVIDERS


def test_llm_model_config_is_frozen() -> None:
    """Frozen dataclass - operators mutate via set_llm_model_config,
    not by mutating the returned object."""
    config = LlmModelConfig(provider="openai", model="gpt-5.6-sol")
    with pytest.raises(Exception):  # FrozenInstanceError
        config.provider = "anthropic"  # type: ignore[misc]


def test_llm_model_config_to_payload_shape() -> None:
    config = LlmModelConfig(provider="openai", model="gpt-5.6-sol")
    payload = config.to_payload()
    assert payload == {
        "provider": "openai",
        "model": "gpt-5.6-sol",
    }


def test_set_llm_model_config_accepts_minimax() -> None:
    """The MiniMax provider must remain valid through the 0.18.0
    broaden - the picker should still let operators switch to it
    if their account is set up for MiniMax instead of OpenAI."""
    cfg = LlmModelConfig(provider="minimax", model="M2.7-highspeed")
    set_llm_model_config(cfg)
    assert get_llm_model_config() == cfg


def test_set_llm_model_config_accepts_anthropic() -> None:
    cfg = LlmModelConfig(
        provider="anthropic", model="claude-opus-4-8"
    )
    set_llm_model_config(cfg)
    assert get_llm_model_config() == cfg


def test_default_for_anthropic_is_haiku_4_5() -> None:
    """The canonical default for Anthropic matches the historical
    TradeFarm default (Haiku 4.5) so a 0.17.0 -> 0.18.0 upgrade
    sees zero behavior change on first boot."""
    from tradefarm.agents.llm_providers import DEFAULT_ANTHROPIC_MODEL
    from tradefarm.runtime.llm_model_config import _default_for

    assert _default_for("anthropic") == DEFAULT_ANTHROPIC_MODEL


def test_default_for_openai_is_gpt_5_6_sol() -> None:
    """The canonical default for OpenAI is the new top-line GPT-5.6
    model (canonical id, not the 'gpt-5.6' alias)."""
    from tradefarm.agents.llm_providers import DEFAULT_OPENAI_MODEL
    from tradefarm.runtime.llm_model_config import _default_for

    assert _default_for("openai") == DEFAULT_OPENAI_MODEL


def test_default_for_minimax_is_m2_7_highspeed() -> None:
    """The canonical default for MiniMax matches the historical
    TradeFarm default (M2.7-highspeed)."""
    from tradefarm.agents.llm_providers import DEFAULT_MINIMAX_MODEL
    from tradefarm.runtime.llm_model_config import _default_for

    assert _default_for("minimax") == DEFAULT_MINIMAX_MODEL
