"""Thin facade over the active LLM provider.

Agents construct an `LlmOverlay` once; the overlay delegates to whichever
provider the runtime ``LlmModelConfig`` currently names. Admin-panel
changes swap the provider in place via `LlmOverlay.rebuild()` so agents
don't need to be re-wired.
"""

from __future__ import annotations

from tradefarm.agents.llm_overlay_types import LlmContext, LlmDecision  # re-exported
from tradefarm.agents.llm_providers import LlmProvider, build_provider
from tradefarm.config import settings
from tradefarm.runtime.llm_model_config import get_llm_model_config

__all__ = ["LlmContext", "LlmDecision", "LlmOverlay"]


class LlmOverlay:
    def __init__(self, provider: LlmProvider | None = None) -> None:
        self.provider: LlmProvider = provider or _provider_from_settings()

    @staticmethod
    def from_settings() -> "LlmOverlay":
        return LlmOverlay(_provider_from_settings())

    def rebuild(self) -> None:
        """Pick up changes to the runtime config / env-var settings."""
        self.provider = _provider_from_settings()

    @property
    def info(self) -> dict[str, str]:
        return {"provider": self.provider.name, "model": self.provider.model}

    async def decide(self, ctx: LlmContext) -> LlmDecision:
        return await self.provider.decide(ctx)


def _provider_from_settings() -> LlmProvider:
    """Build a provider from the runtime config, falling back to env settings.

    0.18.0 — the runtime ``LlmModelConfig`` singleton is the source of
    truth. ``settings.llm_provider`` / ``settings.llm_model`` are the
    boot-time seed; the operator's runtime picker updates the
    singleton and the next ``build_provider`` call picks it up. The
    env-var fallback is only here for the rare path where
    ``LlmModelConfig`` hasn't been initialized yet (e.g. test code
    that imports this module without booting the orchestrator).
    """
    cfg = get_llm_model_config()
    return build_provider(
        cfg.provider,
        anthropic_key=settings.anthropic_api_key,
        openai_key=settings.openai_api_key,
        minimax_key=settings.minimax_api_key,
        minimax_base_url=settings.minimax_base_url,
        model_override=cfg.model,
    )
