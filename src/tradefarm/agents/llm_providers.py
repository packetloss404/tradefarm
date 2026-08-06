"""LLM provider abstraction.

`LlmProvider` is the common contract. We ship three implementations:

- AnthropicProvider  — Claude Haiku 4.5 with ephemeral prompt caching on the
                       shared system prompt.
- OpenAiProvider     — OpenAI GPT-5.6 (the 2026-07 release; "gpt-5.6-sol"
                       alias = "gpt-5.6") via their chat/completions
                       endpoint. Reuses the shared httpx client with retry
                       on transient 5xx/429/network.
- MinimaxProvider    — MiniMax M2.7-highspeed via their OpenAI-compatible
                       chat/completions endpoint. No prompt caching. Uses
                       the shared httpx client (round-5 AA) with retry on
                       transient 5xx/429/network (round-6 MED-minimax) and
                       an https+host allowlist on the base URL.

A fourth can be added by implementing the `decide(ctx) -> LlmDecision` coroutine.

Also owns the ``MODEL_COST_HINTS`` static pricing table the dashboard's
LLM model picker reads to render per-row cost hints (per-million USD).
Values cross-referenced against the providers' public pricing pages at
release time; a stale row just shows a slightly wrong hint, the model
itself still works.
"""

from __future__ import annotations

import os
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
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_MINIMAX_MODEL",
    "DEFAULT_OPENAI_MODEL",
    "LlmParseError",
    "LlmProvider",
    "MODEL_COST_HINTS",
    "MinimaxProvider",
    "OpenAiProvider",
    "build_provider",
    "list_anthropic_models",
    "list_minimax_models",
    "list_openai_models",
]

DEFAULT_ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MINIMAX_MODEL = "M2.7-highspeed"
# 0.18.0 — OpenAI provider ships with GPT-5.6 (2026-07 release). The
# spec doc picked "gpt-5.6-sol" as the canonical id (the new top-line
# of the GPT-5.6 trio); "gpt-5.6" is the server-side alias. We always
# submit the canonical id, so the boot-time default matches what
# /v1/models returns.
DEFAULT_OPENAI_MODEL = "gpt-5.6-sol"


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


class OpenAiProvider:
    """OpenAI via their chat/completions endpoint.

    Reuses the shared httpx client (round-5 AA) and wraps the call
    in ``with_retries`` (round-6 MED-minimax pattern) so transient
    5xx/429/network errors don't waste a full decision cycle. No
    prompt caching — OpenAI's chat completions endpoint does not
    expose Anthropic-style cache_control, so the per-call cost is
    higher than the cached Anthropic path on the same prompt.
    """

    name = "openai"

    BASE_URL = "https://api.openai.com/v1"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_MODEL,
        base_url: str = BASE_URL,
    ) -> None:
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not configured")
        self.model = model or DEFAULT_OPENAI_MODEL
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
        client = await get_shared_client()
        data = await with_retries(
            lambda: _post_chat_completions(client, url, body, headers),
            label="openai",
        )
        raw = data["choices"][0]["message"]["content"]
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
    openai_key: str = "",
    minimax_key: str,
    minimax_base_url: str,
    model_override: str,
) -> LlmProvider:
    if provider_name == "openai":
        return OpenAiProvider(api_key=openai_key, model=model_override)
    if provider_name == "minimax":
        return MinimaxProvider(
            api_key=minimax_key,
            model=model_override,
            base_url=minimax_base_url,
        )
    return AnthropicProvider(api_key=anthropic_key, model=model_override)


# ---------------------------------------------------------------------------
# 0.18.0 — model cost hints (per-million USD).
#
# Static table the dashboard's LLM model picker reads to render the
# per-row cost hint. The providers' /v1/models responses do NOT include
# pricing — pricing is on a separate docs page. Values cross-referenced
# against the providers' public pricing pages at release time
# (see docs/research/llm-model-discovery.md for the source links).
# A stale row just shows a slightly wrong hint; the model itself still
# works because the call goes to the API, not the table.
#
# Keys are (provider, model_id). `None` for cached_input means the
# provider does not advertise a cache discount for that model.
# ---------------------------------------------------------------------------

MODEL_COST_HINTS: dict[tuple[str, str], dict[str, float | None]] = {
    # --- Anthropic (per claude pricing page) ---
    ("anthropic", "claude-haiku-4-5-20251001"): {
        "input_per_million": 1.00,
        "output_per_million": 5.00,
        "cached_input_per_million": 0.10,
    },
    ("anthropic", "claude-haiku-4-5"): {
        "input_per_million": 1.00,
        "output_per_million": 5.00,
        "cached_input_per_million": 0.10,
    },
    ("anthropic", "claude-sonnet-5"): {
        # Intro pricing through 2026-08-31; standard pricing is $3/$15.
        "input_per_million": 2.00,
        "output_per_million": 10.00,
        "cached_input_per_million": 0.20,
    },
    ("anthropic", "claude-opus-4-8"): {
        "input_per_million": 5.00,
        "output_per_million": 25.00,
        "cached_input_per_million": 0.50,
    },
    ("anthropic", "claude-fable-5"): {
        "input_per_million": 10.00,
        "output_per_million": 50.00,
        "cached_input_per_million": 1.00,
    },
    # --- OpenAI (per openai pricing page; GPT-5.6 trio) ---
    ("openai", "gpt-5.6-sol"): {
        "input_per_million": 5.00,
        "output_per_million": 30.00,
        "cached_input_per_million": 0.50,
    },
    ("openai", "gpt-5.6"): {
        # alias for gpt-5.6-sol
        "input_per_million": 5.00,
        "output_per_million": 30.00,
        "cached_input_per_million": 0.50,
    },
    ("openai", "gpt-5.6-terra"): {
        # Pre-2026-07-30 launch pricing; the doc notes a step-down on
        # 2026-07-30 to $2.00/$12.00. The picker shows the current
        # rate; the doc keeps the launch values for the changelog.
        "input_per_million": 2.50,
        "output_per_million": 15.00,
        "cached_input_per_million": 0.25,
    },
    ("openai", "gpt-5.6-luna"): {
        "input_per_million": 1.00,
        "output_per_million": 6.00,
        "cached_input_per_million": 0.10,
    },
    # --- MiniMax (per ofox + Requesty secondary sources; M2.7 official
    #     rate is the source of truth for the M2.7 line) ---
    ("minimax", "M2.7"): {
        "input_per_million": 0.30,
        "output_per_million": 1.20,
        "cached_input_per_million": None,
    },
    ("minimax", "M2.7-highspeed"): {
        "input_per_million": 0.60,
        "output_per_million": 2.40,
        "cached_input_per_million": None,
    },
}


# ---------------------------------------------------------------------------
# 0.18.0 — module-level list_*_models helpers.
#
# Each helper calls the provider's /v1/models endpoint with the right
# auth, parses the response into a list of {"id", "display_name",
# "created_at"} dicts, and returns. The async catalog module
# (tradefarm.runtime.llm_model_catalog) wraps these in cache + fan-out
# + per-provider timeout; the helpers themselves are kept thin and
# pure so tests can drive them with httpx.MockTransport.
#
# Returns a list of dicts (not the richer ModelEntry dataclass) so
# the helpers don't import the runtime module — keeps the dependency
# graph one-way (runtime imports agents, not the other way).
# ---------------------------------------------------------------------------


async def list_anthropic_models(
    api_key: str | None = None,
) -> list[dict[str, object]]:
    """Hit Anthropic's /v1/models and return a normalized list.

    Each row is ``{"id", "display_name", "created_at",
    "context_tokens", "capabilities"}`` with the same shape the
    runtime catalog module's :class:`ModelEntry` exposes (minus the
    cost hint, which is added by the catalog module after the
    fetch). Missing env key returns ``[]``.
    """
    key = api_key if api_key is not None else os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return []
    client = await get_shared_client()
    response = await client.get(
        "https://api.anthropic.com/v1/models",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    out: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        out.append(
            {
                "id": mid,
                "display_name": row.get("display_name") or mid,
                "created_at": row.get("created_at"),
                "context_tokens": row.get("max_input_tokens"),
                "capabilities": row.get("capabilities") or {},
            }
        )
    return out


async def list_openai_models(
    api_key: str | None = None,
) -> list[dict[str, object]]:
    """Hit OpenAI's /v1/models and return a normalized list.

    The OpenAI envelope uses unix-seconds ``created`` (not an ISO
    timestamp). We convert to ISO-8601 UTC here so the catalog
    module doesn't need to re-do the conversion. Missing env key
    returns ``[]``.
    """
    from datetime import datetime, timezone

    key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
    if not key:
        return []
    client = await get_shared_client()
    response = await client.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    out: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        created_unix = row.get("created")
        created_iso: str | None = None
        if isinstance(created_unix, (int, float)) and created_unix > 0:
            try:
                created_iso = (
                    datetime.fromtimestamp(float(created_unix), tz=timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")
                )
            except (OverflowError, OSError, ValueError):
                created_iso = None
        out.append(
            {
                "id": mid,
                "display_name": mid,
                "created_at": created_iso,
                "context_tokens": None,
                "capabilities": (
                    {"owned_by": row.get("owned_by")}
                    if isinstance(row.get("owned_by"), str)
                    else {}
                ),
            }
        )
    return out


async def list_minimax_models(
    api_key: str | None = None,
    base_url: str | None = None,
) -> list[dict[str, object]]:
    """Hit MiniMax's OpenAI-compatible /v1/models and return a normalized list.

    Wire shape is byte-identical to OpenAI's; we re-use the same
    conversion (unix-seconds ``created`` -> ISO-8601). Missing env
    key returns ``[]``; the host allowlist guard is the catalog
    module's job (this helper trusts the caller to pass a valid
    base_url).
    """
    from datetime import datetime, timezone

    key = api_key if api_key is not None else os.environ.get("MINIMAX_API_KEY", "")
    if not key:
        return []
    resolved_base = (base_url or "https://api.minimax.io/v1").rstrip("/")
    if resolved_base.endswith("/v1"):
        url = f"{resolved_base}/models"
    else:
        url = f"{resolved_base}/v1/models"
    client = await get_shared_client()
    response = await client.get(
        url,
        headers={"Authorization": f"Bearer {key}"},
        timeout=5.0,
    )
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", [])
    out: list[dict[str, object]] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        created_unix = row.get("created")
        created_iso: str | None = None
        if isinstance(created_unix, (int, float)) and created_unix > 0:
            try:
                created_iso = (
                    datetime.fromtimestamp(float(created_unix), tz=timezone.utc)
                    .strftime("%Y-%m-%dT%H:%M:%SZ")
                )
            except (OverflowError, OSError, ValueError):
                created_iso = None
        out.append(
            {
                "id": mid,
                "display_name": mid,
                "created_at": created_iso,
                "context_tokens": None,
                "capabilities": (
                    {"owned_by": row.get("owned_by")}
                    if isinstance(row.get("owned_by"), str)
                    else {}
                ),
            }
        )
    return out
