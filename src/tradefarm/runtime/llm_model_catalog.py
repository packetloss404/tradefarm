"""Live LLM model catalog - fan out to /v1/models, cache the result.

0.18.0 - replaces the dashboard's free-form ``llm_model`` text input
with a live-discovered dropdown. The admin endpoint
``GET /admin/llm/models`` calls :func:`get_model_catalog` to fetch
each provider's current model list, normalizes the responses into a
common :class:`ModelEntry` shape, and serves a 60-min in-memory
cache. A single provider being slow or missing a key does not fail
the whole request - the response carries one
:class:`ProviderListing` per provider, each marked ``ok`` or
``ok=False`` with an error string.

Per the research doc (``docs/research/llm-model-discovery.md``):

- **Anthropic**: ``GET https://api.anthropic.com/v1/models`` with
  ``x-api-key`` + ``anthropic-version: 2023-06-01``. Anthropic
  envelope: ``{data: [{id, display_name, created_at, ...}],
  has_more}``.
- **OpenAI**: ``GET https://api.openai.com/v1/models`` with
  ``Authorization: Bearer <key>``. OpenAI envelope: ``{object: "list",
  data: [{id, object, created, owned_by}]}``. No pagination on
  ``/v1/models``.
- **MiniMax**: hits the OpenAI-compatible ``/v1/models`` endpoint
  (so the returned ids match the ids TradeFarm's ``MinimaxProvider``
  already passes in ``model=``).

Cache: 60 min (``CATALOG_TTL_SEC``). The dashboard's SWR 60s
refresh keeps the UI from feeling laggy without spamming the
providers. A ``?refresh=true`` query param forces a refetch.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from tradefarm.agents.llm_providers import MODEL_COST_HINTS
from tradefarm.runtime.http import get_shared_client, with_retries

__all__ = [
    "CATALOG_TTL_SEC",
    "ModelEntry",
    "ProviderListing",
    "ModelCatalog",
    "get_model_catalog",
    "reset_model_catalog_cache",
]

# 60 min - the operator hits the "Refresh" button in the modal when
# they know a new model dropped. The 60s SWR refresh on the web side
# keeps the cached list from feeling stale on a long-lived modal.
CATALOG_TTL_SEC = 3600

# Per-provider network timeout (seconds). 5s is generous given
# ``with_retries`` already retries 3x on 5xx/429/network, but a single
# slow provider should not block the whole modal.
PROVIDER_TIMEOUT_SEC = 5.0


def _now_iso() -> str:
    """ISO-8601 timestamp in UTC, e.g. ``2026-08-10T14:23:01Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ModelEntry:
    """A single model row in a provider's listing.

    ``cost_hint_usd`` is a small dict the picker reads to render the
    per-row cost hint (``{"input_per_million": 1.00,
    "output_per_million": 5.00}``). The values come from the static
    ``MODEL_COST_HINTS`` table in ``agents/llm_providers.py``;
    missing entries render as "cost: unknown" rather than a wrong
    number. The values are per-million, not per-1k, to match the
    providers' public pricing pages (a 0.18.0 follow-up can use
    these to drive the spend widget's per-model estimate).
    """

    id: str
    display_name: str
    created_at: str | None
    context_tokens: int | None
    capabilities: dict[str, Any] = field(default_factory=dict)
    cost_hint_usd: dict[str, float] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        # asdict gives us a fresh copy; the frozen dataclass prevents
        # the caller from mutating the live object.
        return asdict(self)


@dataclass(frozen=True)
class ProviderListing:
    """One provider's result from a catalog fetch.

    ``ok=True`` rows carry ``models`` + ``fetched_at``; ``ok=False``
    rows carry ``error`` (e.g. ``"ANTHROPIC_API_KEY not set"``) and
    the modal renders a red "fetch failed" line per the spec.
    ``ttl_sec`` is per-provider so a future iteration can refresh
    faster-changing providers more often without breaking the wire
    format.
    """

    ok: bool
    models: tuple[ModelEntry, ...] = ()
    fetched_at: str | None = None
    error: str | None = None
    ttl_sec: int = CATALOG_TTL_SEC

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "models": [m.to_payload() for m in self.models],
            "fetched_at": self.fetched_at,
            "error": self.error,
            "ttl_sec": self.ttl_sec,
        }


@dataclass(frozen=True)
class ModelCatalog:
    """All three providers' listings, assembled at one wall-clock time.

    ``cached_at`` is the moment the backend assembled this catalog
    (used by the dashboard's "(cached at HH:MM:SS)" line); the
    per-provider ``fetched_at`` is when each individual provider was
    last hit (a cache miss on one provider doesn't force a cache
    miss on the others).
    """

    anthropic: ProviderListing
    openai: ProviderListing
    minimax: ProviderListing
    cached_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "anthropic": self.anthropic.to_payload(),
            "openai": self.openai.to_payload(),
            "minimax": self.minimax.to_payload(),
            "cached_at": self.cached_at,
        }


# In-process cache. The whole catalog object is immutable, so we
# swap the reference under the lock (readers see either the old or
# the new catalog, never a half-built one - same pattern as
# TtsConfig). A future iteration can move this into Redis if the
# deployment goes multi-worker; for 0.18.0 the single-process
# assumption matches the rest of the runtime config.
_cache_lock = asyncio.Lock()
_cache: ModelCatalog | None = None
_cache_fetched_monotonic: float = 0.0


# ---------------------------------------------------------------------------
# /v1/models fetchers - one per provider. Each is a small async
# function that returns a :class:`ProviderListing`. They swallow
# exceptions (timeouts, 4xx, 5xx, malformed JSON) and return
# ``ok=False`` with a short error string - the catalog endpoint
# converts the error into the dashboard's red row.
# ---------------------------------------------------------------------------


async def _fetch_anthropic(client: httpx.AsyncClient) -> ProviderListing:
    """Fetch Anthropic's model list. Requires ``ANTHROPIC_API_KEY``."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return ProviderListing(
            ok=False,
            error="ANTHROPIC_API_KEY not set",
        )

    async def _do_fetch() -> dict[str, Any]:
        response = await client.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            timeout=PROVIDER_TIMEOUT_SEC,
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = await with_retries(_do_fetch, label="anthropic-models")
    except Exception as e:  # noqa: BLE001
        return ProviderListing(ok=False, error=f"anthropic fetch failed: {type(e).__name__}: {str(e)[:160]}")

    return _parse_anthropic(payload)


async def _fetch_openai(client: httpx.AsyncClient) -> ProviderListing:
    """Fetch OpenAI's model list. Requires ``OPENAI_API_KEY``."""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return ProviderListing(
            ok=False,
            error="OPENAI_API_KEY not set",
        )

    async def _do_fetch() -> dict[str, Any]:
        response = await client.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROVIDER_TIMEOUT_SEC,
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = await with_retries(_do_fetch, label="openai-models")
    except Exception as e:  # noqa: BLE001
        return ProviderListing(ok=False, error=f"openai fetch failed: {type(e).__name__}: {str(e)[:160]}")

    return _parse_openai(payload)


async def _fetch_minimax(client: httpx.AsyncClient) -> ProviderListing:
    """Fetch MiniMax's model list via the OpenAI-compatible endpoint.

    TradeFarm's existing ``MinimaxProvider.decide`` uses the
    OpenAI-compatible chat completions path; we hit the
    OpenAI-compatible ``/v1/models`` so the returned ids are
    byte-identical to what the provider passes in ``model=``.
    MiniMax mirrors an Anthropic-style ``/anthropic/v1/models`` too;
    that path is not in scope for 0.18.0.
    """
    from tradefarm.config import settings
    from tradefarm.runtime.http import validate_minimax_base_url

    api_key = os.environ.get("MINIMAX_API_KEY", "")
    if not api_key:
        return ProviderListing(
            ok=False,
            error="MINIMAX_API_KEY not set",
        )

    # The base URL ends in /v1; the /v1/models endpoint is one
    # level deeper. Strip the trailing /v1 if present, then
    # re-append /v1/models so the URL is correct regardless of
    # whether the operator's settings.minimax_base_url has a
    # trailing slash.
    base = settings.minimax_base_url.rstrip("/")
    if base.endswith("/v1"):
        url = f"{base}/models"
    else:
        url = f"{base}/v1/models"

    # Host allowlist guard (round-6 MED-minimax audit fix). A
    # misconfigured MINIMAX_BASE_URL pointing at a non-allowlisted
    # host would otherwise leak the bearer token.
    try:
        # Reconstruct the base URL with /v1 for the allowlist check
        # (validate_minimax_base_url expects the base URL form, not
        # the per-endpoint form).
        validate_minimax_base_url(f"{base}/v1" if not base.endswith("/v1") else base)
    except ValueError as e:
        return ProviderListing(ok=False, error=f"minimax base URL invalid: {e}")

    async def _do_fetch() -> dict[str, Any]:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=PROVIDER_TIMEOUT_SEC,
        )
        response.raise_for_status()
        return response.json()

    try:
        payload = await with_retries(_do_fetch, label="minimax-models")
    except Exception as e:  # noqa: BLE001
        return ProviderListing(ok=False, error=f"minimax fetch failed: {type(e).__name__}: {str(e)[:160]}")

    return _parse_minimax(payload)


# ---------------------------------------------------------------------------
# Response parsers - one per provider. Each is a pure function that
# converts the wire JSON into a :class:`ProviderListing`. They are
# kept as module-level functions (not nested in the fetcher) so the
# unit tests can call them directly with synthetic payloads.
# ---------------------------------------------------------------------------


def _cost_hint(provider: str, model_id: str) -> dict[str, float]:
    """Look up the per-million cost hint for ``(provider, model_id)``.

    Returns an empty dict when the table has no entry (the picker
    then renders "cost: unknown" instead of a wrong number).
    """
    row = MODEL_COST_HINTS.get((provider, model_id))
    if not row:
        return {}
    # Strip the cached_input_per_million key if it's None - the
    # dashboard treats absent fields as "no cache discount" rather
    # than "zero cache discount".
    return {k: v for k, v in row.items() if v is not None}


def _parse_anthropic(payload: dict[str, Any]) -> ProviderListing:
    """Parse Anthropic's list-models response.

    Wire shape: ``{data: [{id, display_name, created_at, type, ...},
    ...], has_more, first_id, last_id}``. ``capabilities`` is a
    passthrough dict the dashboard ignores in 0.18.0 (the spec
    explicitly notes we don't surface per-model capability flags
    yet).
    """
    data = payload.get("data")
    if not isinstance(data, list):
        return ProviderListing(
            ok=False,
            error="anthropic response missing 'data' array",
        )

    models: list[ModelEntry] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        # The Anthropic envelope gives display_name, created_at,
        # type; we pass capabilities through as-is (the picker
        # ignores it in 0.18.0 but a future iteration can show
        # "thinking supported" badges).
        display = row.get("display_name") or mid
        created = row.get("created_at")
        if not isinstance(created, str):
            created = None
        context_tokens = row.get("max_input_tokens")
        if not isinstance(context_tokens, int):
            context_tokens = None
        capabilities = row.get("capabilities")
        if not isinstance(capabilities, dict):
            capabilities = {}
        models.append(
            ModelEntry(
                id=mid,
                display_name=str(display),
                created_at=created,
                context_tokens=context_tokens,
                capabilities=capabilities,
                cost_hint_usd=_cost_hint("anthropic", mid),
            )
        )

    return ProviderListing(ok=True, models=tuple(models), fetched_at=_now_iso())


def _parse_openai(payload: dict[str, Any]) -> ProviderListing:
    """Parse OpenAI's list-models response.

    Wire shape: ``{object: "list", data: [{id, object: "model",
    created, owned_by, ...}, ...]}``. OpenAI's envelope has no
    ``display_name`` (the id IS the human-readable name) and no
    ``created_at`` ISO timestamp (only a unix-seconds ``created``
    int). We map the unix timestamp to ISO-8601 UTC so the
    dashboard's "released 2026-07-09" line renders without a
    second conversion.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        return ProviderListing(
            ok=False,
            error="openai response missing 'data' array",
        )

    models: list[ModelEntry] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        mid = row.get("id")
        if not isinstance(mid, str) or not mid:
            continue
        # OpenAI uses unix seconds; convert to ISO-8601 for the
        # dashboard's date column. Negative / zero values fall back
        # to None so the picker renders a dash instead of a fake
        # date.
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
        models.append(
            ModelEntry(
                id=mid,
                display_name=mid,
                created_at=created_iso,
                context_tokens=None,
                capabilities={"owned_by": row.get("owned_by")} if isinstance(row.get("owned_by"), str) else {},
                cost_hint_usd=_cost_hint("openai", mid),
            )
        )

    return ProviderListing(ok=True, models=tuple(models), fetched_at=_now_iso())


def _parse_minimax(payload: dict[str, Any]) -> ProviderListing:
    """Parse MiniMax's OpenAI-compatible list-models response.

    Wire shape is byte-identical to OpenAI's; we duplicate the
    loop here (rather than delegating to :func:`_parse_openai`)
    so the cost-hint lookup uses ``"minimax"`` as the provider
    key — the static ``MODEL_COST_HINTS`` table is keyed by
    ``(provider, model_id)`` and the MiniMax rows are not
    retrievable through the OpenAI key.
    """
    data = payload.get("data")
    if not isinstance(data, list):
        return ProviderListing(
            ok=False,
            error="minimax response missing 'data' array",
        )

    models: list[ModelEntry] = []
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
        models.append(
            ModelEntry(
                id=mid,
                display_name=mid,
                created_at=created_iso,
                context_tokens=None,
                capabilities={"owned_by": row.get("owned_by")} if isinstance(row.get("owned_by"), str) else {},
                cost_hint_usd=_cost_hint("minimax", mid),
            )
        )

    return ProviderListing(ok=True, models=tuple(models), fetched_at=_now_iso())


# ---------------------------------------------------------------------------
# Top-level: get_model_catalog + cache management.
# ---------------------------------------------------------------------------


async def get_model_catalog(*, force: bool = False) -> ModelCatalog:
    """Return the current catalog, fetching from /v1/models if stale.

    A request is "stale" if the cache is empty or older than
    ``CATALOG_TTL_SEC``. A ``force=True`` call always refetches -
    the dashboard's "Refresh" button passes that so the operator
    doesn't have to wait up to 60 min for a newly-released model
    to show up.

    Fan-out: the three providers are queried in parallel via
    :func:`asyncio.gather` with a per-provider 5s timeout and
    ``return_exceptions=True``. One provider's failure doesn't
    cancel the others; the failed one becomes a
    ``ProviderListing(ok=False)`` in the response.

    The catalog object is immutable, so we swap the reference
    under the lock - readers see either the old or the new
    catalog, never a half-built one.
    """
    global _cache, _cache_fetched_monotonic

    if not force:
        async with _cache_lock:
            if _cache is not None and (time.monotonic() - _cache_fetched_monotonic) < CATALOG_TTL_SEC:
                return _cache

    client = await get_shared_client()

    # Per-provider 5s timeout - generous given with_retries already
    # retries 3x, but a single slow provider should not block the
    # whole modal. asyncio.wait_for cancels the slow task; the
    # gather(return_exceptions=True) coerces the TimeoutError into
    # a ProviderListing(ok=False).
    async def _guarded(coro) -> ProviderListing:
        try:
            return await asyncio.wait_for(coro, timeout=PROVIDER_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            return ProviderListing(ok=False, error=f"fetch timed out after {PROVIDER_TIMEOUT_SEC:.0f}s")
        except Exception as e:  # noqa: BLE001
            return ProviderListing(
                ok=False,
                error=f"{type(e).__name__}: {str(e)[:160]}",
            )

    a, o, m = await asyncio.gather(
        _guarded(_fetch_anthropic(client)),
        _guarded(_fetch_openai(client)),
        _guarded(_fetch_minimax(client)),
        return_exceptions=False,  # _guarded already converts to ProviderListing
    )

    catalog = ModelCatalog(
        anthropic=a,
        openai=o,
        minimax=m,
        cached_at=_now_iso(),
    )

    async with _cache_lock:
        _cache = catalog
        _cache_fetched_monotonic = time.monotonic()

    return catalog


def reset_model_catalog_cache() -> None:
    """Drop the in-memory cache. Test helper.

    Production code never needs to call this; the cache TTL is the
    only legitimate reason to drop the cache. Tests use it to
    assert fresh-fetch behavior without waiting 60 min.
    """
    global _cache, _cache_fetched_monotonic
    _cache = None
    _cache_fetched_monotonic = 0.0
