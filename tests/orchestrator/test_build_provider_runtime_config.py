"""Tests for the LLM provider build path under the runtime config.

0.18.0 — ``build_provider`` is called from ``llm_overlay._provider_from_settings``,
which now reads the runtime ``LlmModelConfig`` first and falls
back to the env-var settings when the operator has never touched
the picker. These tests pin the precedence + the per-provider
dispatch.
"""

from __future__ import annotations

import pytest

from tradefarm.agents.llm_overlay import _provider_from_settings
from tradefarm.agents.llm_providers import (
    AnthropicProvider,
    MinimaxProvider,
    OpenAiProvider,
    build_provider,
)
from tradefarm.runtime.llm_model_config import (
    LlmModelConfig,
    reset_llm_model_config,
    set_llm_model_config,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with the env-var defaults + clean keys so
    the credential-gating assertions are deterministic."""
    from tradefarm.config import settings

    reset_llm_model_config()
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MINIMAX_API_KEY", raising=False)
    # pydantic-settings reads env at import time; set the Settings
    # fields directly so the runtime config + the credential
    # gating see a deterministic value.
    settings.anthropic_api_key = ""
    settings.openai_api_key = ""
    settings.minimax_api_key = ""
    yield
    reset_llm_model_config()


def test_build_provider_dispatches_anthropic() -> None:
    provider = build_provider(
        "anthropic",
        anthropic_key="test-key",
        minimax_key="",
        minimax_base_url="https://api.minimax.io/v1",
        model_override="claude-haiku-4-5-20251001",
    )
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-haiku-4-5-20251001"


def test_build_provider_dispatches_openai() -> None:
    provider = build_provider(
        "openai",
        anthropic_key="",
        openai_key="test-openai-key",
        minimax_key="",
        minimax_base_url="https://api.minimax.io/v1",
        model_override="gpt-5.6-sol",
    )
    assert isinstance(provider, OpenAiProvider)
    assert provider.model == "gpt-5.6-sol"


def test_build_provider_dispatches_minimax() -> None:
    provider = build_provider(
        "minimax",
        anthropic_key="",
        minimax_key="test-minimax-key",
        minimax_base_url="https://api.minimax.io/v1",
        model_override="M2.7-highspeed",
    )
    assert isinstance(provider, MinimaxProvider)
    assert provider.model == "M2.7-highspeed"


def test_overlay_uses_runtime_config_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the runtime config is set (operator picked via the
    admin picker), the overlay builds the corresponding provider
    — even if the env-var ``settings.llm_provider`` disagrees."""
    from tradefarm.config import settings

    # pydantic-settings reads env at import time; set the
    # Settings fields directly so the overlay sees the keys.
    settings.anthropic_api_key = "test-anthropic-key"
    settings.openai_api_key = "test-openai-key"
    set_llm_model_config(LlmModelConfig(provider="openai", model="gpt-5.6-sol"))

    provider = _provider_from_settings()
    assert isinstance(provider, OpenAiProvider)
    assert provider.model == "gpt-5.6-sol"


def test_overlay_falls_back_to_settings_when_runtime_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the runtime config still has the env-var default
    (operator has never touched the picker), the overlay builds
    whichever provider ``settings.llm_provider`` names."""
    from tradefarm.config import settings

    settings.anthropic_api_key = "test-anthropic-key"
    # Force settings.llm_provider to anthropic (the default),
    # then build the overlay. The runtime config was reset by
    # the autouse fixture, so it equals the env-var seed.
    settings.llm_provider = "anthropic"
    settings.llm_model = "claude-opus-4-8"
    # Reset so the runtime config rebuilds from the new settings.
    reset_llm_model_config()

    provider = _provider_from_settings()
    assert isinstance(provider, AnthropicProvider)
    assert provider.model == "claude-opus-4-8"


def test_overlay_raises_when_runtime_provider_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A misconfigured runtime provider name (e.g. via a manual
    ``set_llm_model_config`` from external code with a typo)
    falls through to AnthropicProvider rather than crashing the
    boot path. The admin endpoint already validates provider
    names; this is the runtime safety net."""
    # Bypass the runtime config validator (the public
    # set_llm_model_config would reject "acme-llm"). Use the
    # underlying module to inject a bad value.
    import tradefarm.runtime.llm_model_config as cfg_mod

    cfg_mod._current = LlmModelConfig(provider="acme-llm", model="bad")

    # The dispatch falls through to the Anthropic branch.
    # It then fails on the missing key — that's expected, the
    # test asserts the build_provider function took the default
    # Anthropic branch.
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY not configured"):
        _provider_from_settings()


def test_runtime_config_takes_precedence_over_env_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the env says anthropic and the runtime config says
    openai, the runtime wins (the operator explicitly picked
    OpenAI)."""
    from tradefarm.config import settings

    settings.anthropic_api_key = "test-anthropic-key"
    settings.openai_api_key = "test-openai-key"
    # settings.llm_provider still says anthropic (the env-var
    # default) — but the runtime config overrides.
    settings.llm_provider = "anthropic"
    settings.llm_model = "claude-haiku-4-5-20251001"
    set_llm_model_config(LlmModelConfig(provider="openai", model="gpt-5.6-sol"))

    provider = _provider_from_settings()
    assert isinstance(provider, OpenAiProvider)
    assert provider.model == "gpt-5.6-sol"
