"""LLM provider abstraction.

`LlmProvider` is the common contract. We ship two implementations:

- AnthropicProvider  — Claude Haiku 4.5 with ephemeral prompt caching on the
                       shared system prompt.
- MinimaxProvider    — MiniMax M2.7-highspeed via their OpenAI-compatible
                       chat/completions endpoint. No prompt caching. Uses
                       the shared httpx client (round-5 AA) with retry on
                       transient 5xx/429/network (round-6 MED-minimax) and
                       an https+host allowlist on the base URL.

A third can be added by implementing the `decide(ctx) -> LlmDecision` coroutine.
"""

from __future__ import annotations

from typing import Protocol

from anthropic import AsyncAnthropic

from tradefarm.agents.llm_overlay_types import (
    LlmContext,
    LlmDecision,
    LlmParseError,
    SYSTEM_PROMPT,
    parse_decision,
    user_message,
)
from tradefarm.runtime.http import get_shared_client, validate_minimax_base_url, with_retries

__all__ = [
    "AnthropicProvider",
    "LlmParseError",
    "LlmProvider",
    "MinimaxProvider",
    "build_provider",
]

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MINIMAX_MODEL = "M2.7-highspeed"


class LlmProvider(Protocol):
    name: str
    model: str

    async def decide(self, ctx: LlmContext) -> LlmDecision: ...


def _parse_decision_json(raw: str) -> LlmDecision:
    """Validate a raw model reply into an :class:`LlmDecision`.

    Thin wrapper over :func:`parse_decision`; malformed replies raise
    :class:`LlmParseError` so callers distinguish them from call failures.
    """
    return parse_decision(raw)


async def _post_chat_completions(
    client: object,
    url: str,
    body: dict,
    headers: dict,
) -> dict:
    """POST a chat-completions request and return the parsed JSON body.

    Pulled out of :meth:`MinimaxProvider.decide` so the retry helper can
    re-invoke the same call. Raises :class:`httpx.HTTPStatusError` on
    4xx/5xx (the retry helper decides whether to retry based on status).
    """
    response = await client.post(url, json=body, headers=headers, timeout=30.0)  # type: ignore[attr-defined]
    response.raise_for_status()
    return response.json()


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str = DEFAULT_ANTHROPIC_MODEL) -> None:
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not configured")
        self.model = model or DEFAULT_ANTHROPIC_MODEL
        self.client = AsyncAnthropic(api_key=api_key)

    async def decide(self, ctx: LlmContext) -> LlmDecision:
        msg = await self.client.messages.create(
            model=self.model,
            max_tokens=200,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user_message(ctx)}],
        )
        raw = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return _parse_decision_json(raw)


class MinimaxProvider:
    """MiniMax via their OpenAI-compatible chat completions endpoint.

    Request shape matches OpenAI's /v1/chat/completions; MiniMax's gateway
    accepts `model`, `messages`, `max_tokens`, `temperature` unchanged.
    """

    name = "minimax"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MINIMAX_MODEL,
        base_url: str = "https://api.minimax.io/v1",
    ) -> None:
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY not configured")
        # Round-6 audit fix (MED-minimax): https+host allowlist. Raises
        # ValueError when the operator points minimax_base_url at a
        # non-https scheme or an unknown host. The Authorization bearer
        # token would otherwise leak to whatever URL was provided.
        validate_minimax_base_url(base_url)
        self.model = model or DEFAULT_MINIMAX_MODEL
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    async def decide(self, ctx: LlmContext) -> LlmDecision:
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": 200,
            "temperature": 0.3,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message(ctx)},
            ],
        }
        # Reuse the shared client (round-5 AA) and wrap in the retry helper
        # (round-6 MED-minimax) so transient 5xx/429/network errors don't
        # waste a full decision cycle.
        client = await get_shared_client()
        data = await with_retries(
            lambda: _post_chat_completions(client, url, body, headers),
            label="minimax",
        )
        raw = data["choices"][0]["message"]["content"]
        return _parse_decision_json(raw)


def build_provider(
    provider_name: str,
    *,
    anthropic_key: str,
    minimax_key: str,
    minimax_base_url: str,
    model_override: str,
) -> LlmProvider:
    if provider_name == "minimax":
        return MinimaxProvider(
            api_key=minimax_key,
            model=model_override,
            base_url=minimax_base_url,
        )
    return AnthropicProvider(api_key=anthropic_key, model=model_override)
