"""Thin facade over the active LLM provider.

Agents construct an `LlmOverlay` once; the overlay delegates to whichever
provider `settings.llm_provider` currently names. Admin-panel changes swap
the provider in place via `LlmOverlay.rebuild()` so agents don't need to
be re-wired.
"""
from __future__ import annotations

from tradefarm.agents.llm_overlay_types import LlmContext, LlmDecision  # re-exported
from tradefarm.agents.llm_providers import LlmProvider, build_provider
from tradefarm.config import settings

__all__ = ["LlmContext", "LlmDecision", "LlmOverlay"]


class LlmOverlay:
    def __init__(self, provider: LlmProvider | None = None) -> None:
        self.provider: LlmProvider = provider or _provider_from_settings()

    @staticmethod
    def from_settings() -> "LlmOverlay":
        return LlmOverlay(_provider_from_settings())

    def rebuild(self) -> None:
        """Pick up changes to `settings.llm_provider` / keys / model."""
        self.provider = _provider_from_settings()

    @property
    def info(self) -> dict[str, str]:
        return {"provider": self.provider.name, "model": self.provider.model}

    async def decide(self, ctx: LlmContext) -> LlmDecision:
        return await self.provider.decide(ctx)


def _provider_from_settings() -> LlmProvider:
    return build_provider(
        settings.llm_provider,
        anthropic_key=settings.anthropic_api_key,
        minimax_key=settings.minimax_api_key,
        minimax_base_url=settings.minimax_base_url,
        model_override=settings.llm_model,
    )
