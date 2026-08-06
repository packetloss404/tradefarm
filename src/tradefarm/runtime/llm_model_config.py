"""Process-wide runtime LLM model configuration.

0.18.0 - the dashboard's LLM model picker flips the active provider
and model at runtime (no env-var restart). This module owns the
singleton; the ``LlmModelConfig`` shape is read by ``build_provider``
via ``llm_overlay._provider_from_settings`` and the admin panel's
select/reset endpoints mirror the 0.17.0 TTS pattern at
``src/tradefarm/runtime/tts_config.py``.

The runtime config overrides ``settings.llm_provider`` and
``settings.llm_model``. If the operator has never touched the picker,
``get_llm_model_config()`` returns a config built from settings
defaults (so the existing env-var-driven behavior is preserved). The
switch takes effect on the *next* ``build_provider`` call - the
in-flight LLM call completes with the old config (a provider object
is per-call, and ``reload_llm_overlay`` rebuilds the shared overlay
when the admin panel writes new credentials).

Single-process only. A multi-worker deployment would need to push
the config into a shared store (DB or Redis); not a current concern
(the sandbox runs one orchestrator + one web process on the same
host).
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from tradefarm.config import settings

# Allowed LLM provider names. The canonical set is the three the
# picker surfaces (Anthropic, OpenAI, the 0.18.0-newly-added provider,
# and MiniMax). Mirrors the type the Settings field already uses
# (``Literal["anthropic", "minimax"]``) extended with "openai" -
# keeping this as a separate frozenset lets the runtime accept
# "openai" before the Settings type is broadened.
VALID_LLM_PROVIDERS: frozenset[str] = frozenset({"anthropic", "openai", "minimax"})


def _default_for(provider: str) -> str:
    """Pick the canonical default model id for a provider.

    The dashboard's "Reset" button should land on the same model id
    the operator would see if they deleted the override and rebooted.
    Mirrors the ``DEFAULT_*_MODEL`` constants in
    ``tradefarm.agents.llm_providers`` so the runtime defaults and
    the picker defaults stay in sync.
    """
    # Local import avoids a circular dependency: llm_providers imports
    # from runtime.http; runtime.llm_model_config is read by
    # llm_overlay which also imports llm_providers.
    from tradefarm.agents.llm_providers import (
        DEFAULT_ANTHROPIC_MODEL,
        DEFAULT_MINIMAX_MODEL,
        DEFAULT_OPENAI_MODEL,
    )

    if provider == "anthropic":
        return DEFAULT_ANTHROPIC_MODEL
    if provider == "openai":
        return DEFAULT_OPENAI_MODEL
    if provider == "minimax":
        return DEFAULT_MINIMAX_MODEL
    # Unknown provider - return a safe placeholder; the admin
    # endpoint will reject unknown names before we get here, so this
    # is purely a fallback for the reset path on a misconfigured
    # settings.llm_provider.
    return ""


@dataclass(frozen=True)
class LlmModelConfig:
    """Effective LLM model settings used by the per-tick provider build.

    ``provider`` is the canonical provider name (``"anthropic"`` /
    ``"openai"`` / ``"minimax"``); ``model`` is the canonical model
    id (e.g. ``"claude-haiku-4-5-20251001"``) - the value the runtime
    passes in the chat completions / messages call. The picker
    should submit canonical ids (not aliases) so future alias renames
    don't break existing operator choices.
    """

    provider: str
    model: str

    def to_payload(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
        }


def _build_default_config() -> LlmModelConfig:
    """Build the boot-time config from settings.

    ``settings.llm_model`` may be empty (the "use provider default"
    pattern from the existing config); we substitute the canonical
    default in that case so the runtime config always carries a
    concrete model id. The Settings field's Literal type is
    ``"anthropic" | "minimax"`` today; treat anything else as a
    fallback to anthropic so a misconfigured settings.llm_provider
    doesn't crash boot.
    """
    provider = settings.llm_provider if settings.llm_provider in VALID_LLM_PROVIDERS else "anthropic"
    model = settings.llm_model or _default_for(provider)
    return LlmModelConfig(provider=provider, model=model)


_DEFAULT_CONFIG = _build_default_config()

_lock = threading.Lock()
_current: LlmModelConfig = _DEFAULT_CONFIG


def get_llm_model_config() -> LlmModelConfig:
    """Return the active LLM model config (snapshot - read-only).

    The dataclass is frozen, so callers cannot mutate the returned
    object. To change the active config, use ``set_llm_model_config``.
    """
    with _lock:
        return _current


def set_llm_model_config(config: LlmModelConfig) -> LlmModelConfig:
    """Replace the active config. Returns the previous config so the
    caller (admin endpoint) can include it in the response.

    Validation: provider must be in ``VALID_LLM_PROVIDERS``; model
    must be a non-empty string. The caller (admin endpoint) is
    expected to have validated the provider's env key is set first
    so a missing-key switch doesn't leak into the synthesis path
    (the same gating pattern ``tts_switch`` uses).
    """
    if config.provider not in VALID_LLM_PROVIDERS:
        raise ValueError(f"unknown provider: {config.provider!r}")
    if not config.model or not config.model.strip():
        raise ValueError("model must be a non-empty string")

    global _current
    with _lock:
        previous = _current
        _current = config
    return previous


def reset_llm_model_config() -> LlmModelConfig:
    """Reset to the env-var defaults.

    Re-reads ``settings.llm_provider`` / ``settings.llm_model`` (the
    Settings object is mutable, so a write to settings.llm_model at
    runtime is picked up here on the next reset). Returns the
    previous config so the admin endpoint can include it in the
    response - mirrors ``reset_tts_config``.
    """
    global _current
    with _lock:
        previous = _current
        _current = _build_default_config()
    return previous
