"""LLM provider abstraction.

`LlmProvider` is the common contract. We ship two implementations:

- AnthropicProvider  — Claude Haiku 4.5 with ephemeral prompt caching on the
                       shared system prompt.
- MinimaxProvider    — MiniMax M2.7-highspeed via their OpenAI-compatible
                       chat/completions endpoint. No prompt caching.

A third can be added by implementing the `decide(ctx) -> LlmDecision` coroutine.
"""
from __future__ import annotations

import json
from typing import Protocol

import httpx
from anthropic import AsyncAnthropic

from tradefarm.agents.llm_overlay_types import LlmContext, LlmDecision, SYSTEM_PROMPT, user_message

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MINIMAX_MODEL = "M2.7-highspeed"


class LlmProvider(Protocol):
    name: str
    model: str

    async def decide(self, ctx: LlmContext) -> LlmDecision: ...


def _parse_decision_json(raw: str) -> LlmDecision:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    return LlmDecision(
        bias=data["bias"],
        predictive=data["predictive"],
        stance=data["stance"],
        size_pct=float(data.get("size_pct", 0.0)),
        reason=str(data.get("reason", ""))[:120],
    )


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
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(url, json=body, headers=headers)
            r.raise_for_status()
            data = r.json()
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
