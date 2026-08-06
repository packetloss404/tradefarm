# LLM live model discovery — endpoint research + picker design

research date: 2026-08-10 (post-0.17.0, pre-0.18.0)
scope: replace the free-form `llm_model` text input in `web/src/components/AdminModal.tsx:142-150` with a live-discovered dropdown that calls each provider's `/v1/models` endpoint, caches the result, and round-trips the selected value through a new `LlmModelConfig` runtime singleton (mirroring the 0.17.0 `TtsConfig` pattern in `src/tradefarm/runtime/tts_config.py:1`). covers three providers — Anthropic, OpenAI (a new provider, the picker is ready for it), and MiniMax. the OpenAI provider itself is out of scope; only the model-picker UI is.

## tl;dr

- **anthropic: `GET https://api.anthropic.com/v1/models`**, `x-api-key` + `anthropic-version: 2023-06-01`. response is `{data: [{id, display_name, created_at, type, capabilities}], first_id, last_id, has_more}` with `?before_id`/`?after_id` pagination. as of 2026-08 the top-line models are **`claude-haiku-4-5-20251001`** (existing default), **`claude-sonnet-5`** (released 2026-06-30, new general-purpose default), and **`claude-opus-4-8`** (released 2026-07, highest-capability widely-released). `claude-fable-5` is also live; `claude-mythos-5` is Project-Glasswing-invite-only.
- **openai: `GET https://api.openai.com/v1/models`**, `Authorization: Bearer <key>`. response is `{object: "list", data: [{id, object, created, owned_by}]}` — no pagination. the "GPT 5.6 all 3 variants" **does exist** — released 2026-07-09, model IDs are **`gpt-5.6-sol`** (flagship, $5/$30 per MTok), **`gpt-5.6-terra`** ($2.50/$15), **`gpt-5.6-luna`** ($1/$6). `gpt-5.6` is the alias for `gpt-5.6-sol`. the GPT-5.x family and the o-series are still in the listing, with the GPT-5 dated snapshots retiring 2026-12-11.
- **MiniMax: `GET https://api.minimax.io/v1/models`** (OpenAI-compatible) and **`GET https://api.minimax.io/anthropic/v1/models`** (Anthropic-compatible). bearer auth on both, OpenAI-style envelope on the former. as of 2026-08 the lineup is **`MiniMax-M3`** (released 2026-06-01, 1M context, new frontier coding/agentic model), `MiniMax-M2.7` (200K, $0.30/$1.20 per MTok), `MiniMax-M2.7-highspeed` (the existing TradeFarm default — same quality, ~100 tps vs ~60 tps), and the older M2.5 / M2.1 / M2 lines.
- **picker design:** `/admin/llm/models` fans out to all three providers **in parallel** with a 5s per-provider timeout, caches for 60 minutes, returns a partial-failure envelope (`{anthropic: {ok, models, fetched_at, error}, openai: {...}, minimax: {...}, cached_at}`). a runtime `LlmModelConfig` singleton (`get/set/reset`, thread-locked like `TtsConfig`) is the new source of truth; `settings.llm_model` becomes the seed default. the existing `model_override` parameter on `build_provider` (`src/tradefarm/agents/llm_providers.py:156`) is unchanged.

## Section 1: Anthropic

### endpoint

```
GET https://api.anthropic.com/v1/models
Headers:
  x-api-key: $ANTHROPIC_API_KEY
  anthropic-version: 2023-06-01
```

(verified against the [Anthropic list-models API ref](https://platform.claude.com/docs/en/api/python/beta/models/list).) pagination uses `?before_id=...` and `?after_id=...` query params. with ~9 active models, a single page is the practical default.

### response shape

```json
{
  "data": [
    {
      "id": "claude-opus-4-8",
      "display_name": "Claude Opus 4.8",
      "created_at": "2026-07-01T00:00:00Z",
      "type": "model",
      "max_input_tokens": 1000000,
      "max_tokens": 128000,
      "capabilities": {"batch": {"supported": true}, "thinking": {"supported": true, "types": {"adaptive": {"supported": true}}}, ...}
    }
  ],
  "first_id": "claude-opus-4-8",
  "last_id": "claude-3-haiku-20240307",
  "has_more": false
}
```

the `capabilities` object was added mid-2026 per the [release notes](https://platform.claude.com/docs/en/release-notes/overview); older code can ignore it. the list comes back "more recently released first."

### current model lineup (2026-08)

sourced from the [models overview page](https://platform.claude.com/docs/en/about-claude/models/overview) and the [skills repo mirror](https://github.com/anthropics/skills/blob/main/skills/claude-api/shared/models.md):

| friendly name | model id | context | input $/M | output $/M | notes |
|---|---|---|---|---|---|
| Claude Haiku 4.5 | `claude-haiku-4-5-20251001` | 200K | $1.00 | $5.00 | **existing TradeFarm default**. alias `claude-haiku-4-5` resolves to this snapshot. |
| Claude Sonnet 5 | `claude-sonnet-5` | 1M | $2.00 (intro) / $3.00 (after 2026-08-31) | $10.00 / $15.00 | new general-purpose default. released 2026-06-30. |
| Claude Opus 4.8 | `claude-opus-4-8` | 1M | $5.00 | $25.00 | highest-capability widely-released Opus. released 2026-07-01. |
| Claude Opus 4.7 | `claude-opus-4-7` | 1M | (see pricing page) | (see pricing page) | recent-gen Opus. |
| Claude Opus 4.6 | `claude-opus-4-6` | 1M | — | — | recent-gen Opus. |
| Claude Sonnet 4.6 | `claude-sonnet-4-6` | 1M | — | — | recent-gen Sonnet. |
| Claude Sonnet 4.5 | `claude-sonnet-4-5-20250929` | 1M | $3.00 | $15.00 | still active. |
| Claude Opus 4.1 | `claude-opus-4-1-20250805` | 200K | — | — | last 200K-context Opus. |
| Claude Fable 5 | `claude-fable-5` | 1M | $10.00 | $50.00 | "most capable widely released" per Anthropic. |
| Claude Mythos 5 | `claude-mythos-5` | — | — | — | Project-Glasswing-only; operators won't have access. |

see the [official pricing page](https://platform.claude.com/docs/en/about-claude/pricing) for the full grid + 5m/1h cache-write columns.

### model ids vs. aliases — the picker gotcha

`4.6`+ uses **dateless ids** (`claude-sonnet-4-6`, `claude-opus-4-8`) that are pinned snapshots, not evergreens. `4.5`- and earlier use **dated ids** (`claude-haiku-4-5-20251001`) and have **shorter aliases** (`claude-haiku-4-5`) that resolve server-side to the most recent dated snapshot for that minor version. **for the picker:** the canonical id goes in the dropdown row's "value" field (what the backend sends in `model=`); the friendly name goes in the label. the existing `settings.llm_model = "claude-haiku-4-5-20251001"` constant at `src/tradefarm/agents/llm_providers.py:40` is already in the dated form and stays correct.

## Section 2: OpenAI

### endpoint

```
GET https://api.openai.com/v1/models
Headers:
  Authorization: Bearer $OPENAI_API_KEY
```

(verified against the [OpenAI list-models API ref](https://developers.openai.com/api/reference/resources/models/methods/list/).) no pagination on the root — full list in one call. `object: "model"` in every row, `object: "list"` at the top level (a [known doc inconsistency](https://community.openai.com/t/incorrect-example-response-for-list-models-api/1368421); both work, the wire is consistent).

### response shape

```json
{
  "object": "list",
  "data": [
    {"id": "gpt-5.6-sol", "object": "model", "created": 1780000000, "owned_by": "openai"},
    {"id": "gpt-5.6-terra", "object": "model", "created": 1780000000, "owned_by": "openai"},
    {"id": "gpt-5.6-luna", "object": "model", "created": 1780000000, "owned_by": "openai"}
  ]
}
```

`created` is unix seconds. `owned_by` is typically `"openai"` for first-party, `"system"` for snapshot variants. no `display_name` — the `id` is the human-readable name too.

### current model lineup (2026-08) — the GPT 5.6 trio

**yes, GPT-5.6 exists** — released 2026-07-09 (sourced from the [GPT-5.6 release post](https://openai.com/index/gpt-5-6/) and the [apidog pricing breakdown](https://apidog.com/blog/gpt-5-6-pricing/)). the new "durable capability tier" naming replaces the older `gpt-5-mini` / `gpt-5-nano` style — Sol/Terra/Luna are stable brand names that survive across generations:

| model id | alias | role | input $/M | output $/M | context |
|---|---|---|---|---|---|
| `gpt-5.6-sol` | `gpt-5.6` | flagship | $5.00 | $30.00 | 1M |
| `gpt-5.6-terra` | — | balanced / everyday | $2.50 (→$2.00 after 2026-07-30) | $15.00 (→$12.00) | 1M |
| `gpt-5.6-luna` | — | cheap + fast | $1.00 (→$0.20 after 2026-07-30) | $6.00 (→$1.20) | 1M |

**the previous-generation family is still in the listing** (per the [OpenAI deprecations page](https://developers.openai.com/api/docs/deprecations)) and the picker should show them with a "retiring 2026-12-11" badge:

| model id | notes |
|---|---|
| `gpt-5` / `gpt-5-2025-08-07` / `gpt-5-mini` / `gpt-5-nano` / `gpt-5-pro` | retiring 2026-12-11; replacements `gpt-5.5` / `gpt-5.4-mini` / `gpt-5.4-nano` / `gpt-5.5-pro`. |
| `gpt-5.5` / `gpt-5.4` / `gpt-5.4-mini` / `gpt-5.4-nano` | active mid-gen. |
| `o3` / `o3-pro` / `o4-mini` | reasoning line, active. $2/$8, $20/$80, $1.10/$4.40 per MTok. |
| `gpt-5.3-codex` | agentic coding. $1.75/$14 per MTok. |
| `gpt-realtime-2.1` / `gpt-realtime-2.1-mini` / `gpt-audio-1.5` | out of scope for decision-prompt use. |

**alias gotcha:** `gpt-5.6` is an alias for `gpt-5.6-sol`. the picker should submit the canonical id and display the alias as a hint, so future alias renames don't break existing operator choices.

**`openai api gotcha — :deployment-id` suffixes:** operators using Azure OpenAI can suffix the model id with `:deployment-id` (e.g. `gpt-5.6-sol:my-eastus2-deploy`). TradeFarm runs against `api.openai.com` directly so this isn't a default use case, but the form validator should be permissive about strings containing `:` — an operator copy-pasting from a colleague's URL shouldn't get a 400.

## Section 3: MiniMax

### endpoint(s)

MiniMax is dual-protocol — OpenAI-compatible chat/completions AND Anthropic-compatible messages — and exposes two parallel `/v1/models` endpoints ([docs](https://minimax-ai.chat/docs/minimax-api-key-base-url/)):

```
GET https://api.minimax.io/v1/models                       (OpenAI-compatible)
Headers: Authorization: Bearer $MINIMAX_API_KEY

GET https://api.minimax.io/anthropic/v1/models             (Anthropic-compatible)
Headers: X-Api-Key: $MINIMAX_API_KEY
```

`api.minimax.io` is the global/international endpoint; mainland China uses `api.minimaxi.com`. the existing allowlist at `src/tradefarm/runtime/http.py:108-110` covers `api.minimax.io` and `api.minimax.chat`; a 0.18.0 operator on the Chinese endpoint would need `MINIMAX_EXTRA_HOSTS=api.minimaxi.com` (the same hook the existing code uses for staging mirrors).

**recommendation:** the picker hits the **OpenAI-compatible** endpoint, because TradeFarm's existing `MinimaxProvider.decide` (`src/tradefarm/agents/llm_providers.py:129-153`) uses the OpenAI-compatible chat completions format — the returned model ids match what we pass in `model=`, so no id-translation step.

### response shape (OpenAI-compatible)

```json
{
  "object": "list",
  "data": [
    {"id": "MiniMax-M3", "object": "model", "created": 1780272000, "owned_by": "minimax"},
    {"id": "MiniMax-M2.7", "object": "model", "created": 1773799200, "owned_by": "minimax"},
    {"id": "MiniMax-M2.7-highspeed", "object": "model", "created": 1773799200, "owned_by": "minimax"}
  ]
}
```

byte-identical to OpenAI's envelope: `object: "list"`, `data: [...]` with `{id, object, created, owned_by}`. no pagination. (verified against the [MiniMax OpenAI list-models schema](https://platform.minimax.io/docs/api-reference/models/openai/list-models).)

### current model lineup (2026-08) — M3 is the new top-line

sourced from the [API overview](https://platform.minimax.io/docs/api-reference/api-overview) and the [models guide](https://platform.minimax.io/docs/guides/models-intro):

| model id | context | output speed | input $/M | output $/M | notes |
|---|---|---|---|---|---|
| `MiniMax-M3` | 1,000,000 | (frontier coding) | (TBD) | (TBD) | **released 2026-06-01, new top-line**. multimodal, agentic, long-context. |
| `MiniMax-M2.7` | 204,800 | ~60 tps | $0.30 | $1.20 | per the [ofox pricing writeup](https://ofox.ai/blog/minimax-m2-api-pricing-comparison-2026/). |
| `MiniMax-M2.7-highspeed` | 204,800 | ~100 tps | $0.60 | $2.40 | **the existing TradeFarm default** (`DEFAULT_MINIMAX_MODEL = "M2.7-highspeed"` at `src/tradefarm/agents/llm_providers.py:41`). |
| `MiniMax-M2.5` / `M2.5-highspeed` | 204,800 | 60/100 tps | — | — | still active. |
| `MiniMax-M2.1` / `M2.1-highspeed` | 204,800 | 60/100 tps | — | — | still active. |
| `MiniMax-M2` | 204,800 | (default) | — | — | oldest still-active. |

**the M3 tradeoff:** 1M context is 5x the M2.7's 200K, which is great for the `lstm_llm_v1` prompt's overlay context block. but M3 hasn't been battle-tested by the TradeFarm tick loop, and the existing per-call tuning (`max_tokens=200`, `temperature=0.3` at `src/tradefarm/agents/llm_providers.py:135-138`) was calibrated against M2.7. the picker shows M3 in the dropdown but the existing `DEFAULT_MINIMAX_MODEL` stays at `M2.7-highspeed` — operators opt into M3 by selecting it.

## Section 4: Design recommendations

### 4.1 — live list vs. cached list

**cache for 60 minutes with an explicit "Refresh" button.** three HTTPS round-trips to three providers per cache miss (1-3s each with a fresh TLS handshake) would lag the modal open 5-10s. the operator's mental model of "I open the modal" should not include three SPINDIALs.

```python
# src/tradefarm/runtime/llm_model_catalog.py
@dataclass(frozen=True)
class ModelEntry:
    id: str
    display_name: str
    created_at: str | None           # ISO 8601 (anthropic/minimax) or None (openai)
    context_tokens: int | None
    cost_hint_usd: dict[str, float]  # {input_per_million, output_per_million, cached_input_per_million}

@dataclass(frozen=True)
class ProviderListing:
    ok: bool
    models: tuple[ModelEntry, ...] = ()
    fetched_at: str | None = None
    error: str | None = None
    ttl_sec: int = 3600

@dataclass(frozen=True)
class ModelCatalog:
    anthropic: ProviderListing
    openai: ProviderListing
    minimax: ProviderListing
    cached_at: str                    # when THIS catalog was assembled
```

### 4.2 — cost estimate per model

the picker needs a per-row cost hint. source of truth is the providers' public pricing pages ([anthropic](https://platform.claude.com/docs/en/about-claude/pricing), [openai](https://developers.openai.com/api/docs/models), [MiniMax](https://platform.minimax.io/docs/guides/models-intro)). **ship a static table** keyed by `(provider, model_id) → {input_per_million, output_per_million, cached_input_per_million}`. the providers' own `/v1/models` responses do **not** include pricing — a scraper would be fragile. the values are checked at release time; an outdated row shows a slightly wrong cost hint, the model itself still works.

the existing `settings.llm_input_per_million` / `llm_output_per_million` / `llm_cache_read_per_million` fields at `src/tradefarm/config.py:42-44` are the spend-counter inputs the `ApiSpendWidget` uses (via `COST_PER_CALL_USD = 0.0006` at `web/src/components/ApiSpendWidget.tsx:10`). the picker should **not** auto-rewrite those settings when the operator picks a new model — that's a separate (larger) feature.

### 4.3 — concurrency: fan out in parallel

**parallel (`asyncio.gather`) with a per-provider 5s timeout.** sequential would be 3-9s of accumulated latency; parallel is bounded by the slowest single provider, ~2-3s in practice. `with_retries` at `src/tradefarm/runtime/http.py:142` already retries 3x on 5xx/429/network, so the 5s timeout is the wall-clock budget including retries.

```python
async def get_model_catalog(*, force: bool = False) -> ModelCatalog:
    async with _cache_lock:
        if not force and _cache and (now - _cache.cached_at) < _cache.ttl_sec:
            return _cache
    client = await get_shared_client()
    a, o, m = await asyncio.gather(
        asyncio.wait_for(_fetch_anthropic(client), timeout=5.0),
        asyncio.wait_for(_fetch_openai(client),    timeout=5.0),
        asyncio.wait_for(_fetch_minimax(client),   timeout=5.0),
        return_exceptions=True,   # one provider's failure mustn't cancel the others
    )
    def _coerce(x):
        return x if isinstance(x, ProviderListing) else ProviderListing(
            ok=False, error=f"{type(x).__name__}: {str(x)[:200]}"
        )
    catalog = ModelCatalog(anthropic=_coerce(a), openai=_coerce(o), minimax=_coerce(m), cached_at=now_iso())
    async with _cache_lock:
        _cache = catalog
    return catalog
```

**missing-key shortcut:** when `OPENAI_API_KEY` is unset (the default for a 0.17.0 → 0.18.0 upgrade), `_fetch_openai` returns `ProviderListing(ok=False, error="OPENAI_API_KEY not set")` *without* making a network call. same for the other two keys. the dashboard renders a yellow "no API key" hint instead of a 401 — same pattern the existing `tts_status` endpoint uses at `src/tradefarm/api/admin.py:512-545` with its `has_creds` map.

### 4.4 — failure mode: partial success

the response shape the dashboard consumes:

```json
{
  "anthropic": {"ok": true, "models": [{"id": "claude-haiku-4-5-20251001", "display_name": "Claude Haiku 4.5", "context_tokens": 200000, "cost_hint_usd": {"input_per_million": 1.00, "output_per_million": 5.00}}], "fetched_at": "2026-08-10T14:23:01Z", "ttl_sec": 3600},
  "openai":    {"ok": false, "error": "OPENAI_API_KEY not set", "fetched_at": null},
  "minimax":   {"ok": true, "models": [...], "fetched_at": "2026-08-10T14:23:01Z", "ttl_sec": 3600},
  "cached_at": "2026-08-10T14:23:01Z"
}
```

the dashboard renders whichever providers returned `ok: true`; failed ones show an inline hint with a per-section "retry" button that calls `GET /admin/llm/models?refresh=true`. the picker does **not** hard-fail the modal open just because one provider is unhappy — partial success is the norm.

### 4.5 — runtime model selection: the `LlmModelConfig` singleton

mirror the 0.17.0 `TtsConfig` pattern at `src/tradefarm/runtime/tts_config.py:64-137` exactly. new module `src/tradefarm/runtime/llm_model_config.py`:

```python
@dataclass(frozen=True)
class LlmModelConfig:
    provider: str   # "anthropic" | "openai" | "minimax"
    model: str      # the canonical model id (e.g. "claude-haiku-4-5-20251001")
    def to_payload(self) -> dict[str, str]: ...

_DEFAULT_CONFIG = LlmModelConfig(
    provider=settings.llm_provider,
    model=settings.llm_model or _default_for(settings.llm_provider),
)
_lock = threading.Lock()
_current: LlmModelConfig = _DEFAULT_CONFIG

def get_llm_model_config() -> LlmModelConfig: ...   # read-only snapshot
def set_llm_model_config(config: LlmModelConfig) -> LlmModelConfig:  # validate + swap, returns previous
def reset_llm_model_config() -> LlmModelConfig: ...  # back to env defaults
```

**thread-safety story:** `threading.Lock` (not `asyncio.Lock`) because the config is read from both sync code paths and the admin endpoint's async POST handler. the lock is held only long enough to swap the reference; readers see either old or new, never a half-built one. the 60-min catalog cache uses a separate `asyncio.Lock` because the catalog object is only ever touched from async paths. two locks for two lifecycles — same as the existing TTS design.

**wiring into `build_provider`:** the call site at `src/tradefarm/agents/llm_overlay.py:38-45` reads the **runtime config first** and falls back to the env-var settings:

```python
def _provider_from_settings() -> LlmProvider:
    cfg = get_llm_model_config()         # read runtime override first
    return build_provider(
        cfg.provider,
        anthropic_key=settings.anthropic_api_key,
        minimax_key=settings.minimax_api_key,
        minimax_base_url=settings.minimax_base_url,
        model_override=cfg.model,        # existing parameter, unchanged
    )
```

the existing `model_override` parameter on `build_provider` (`src/tradefarm/agents/llm_providers.py:156`) is unchanged — the runtime config is just a new layer between `settings.llm_model` and the provider constructor. the orchestrator's `reload_llm_overlay()` at `src/tradefarm/orchestrator/scheduler.py:1366` already goes through `_provider_from_settings()`, so no changes to the reload path are needed.

**does the runtime config survive `.env` writes?** no — same behavior as the TTS config. the admin panel's existing "save" button writes to `.env` AND triggers `orch.reload_llm_overlay()`. the 0.18.0 picker should also write the chosen model to `LLM_MODEL` in `.env` (durability) AND set the runtime config (live without restart). two writes, both fire.

### 4.6 — what the picker should NOT do

explicit non-goals for 0.18.0:

- **per-model max-tokens / temperature controls.** those stay in `LlmContext` + provider shape. the picker is a model id, not a per-call params editor.
- **auto-pricing the spend counter based on the chosen model.** the existing `COST_PER_CALL_USD = 0.0006` is calibrated for Haiku 4.5 and breaks for everything else; rewriting it is a follow-up.
- **a "test connection" button on each row.** N LLM round-trips per modal open. bad UX. the existing "save" button validates on the next actual call.
- **per-provider credential editing inside the picker row.** the existing "Anthropic API key" / "MiniMax API key" rows at `web/src/components/AdminModal.tsx:152-184` stay. the picker reads the runtime config; the credential rows write the `.env` keys.

## Section 5: Files to touch (impl checklist for the dev subagents)

| file | change | lines (est.) |
|---|---|---|
| `src/tradefarm/runtime/llm_model_config.py` | **new**: `LlmModelConfig` dataclass + `get/set/reset` + `VALID_LLM_PROVIDERS`. mirrors `tts_config.py:64-137` exactly. | 100 |
| `src/tradefarm/runtime/llm_model_catalog.py` | **new**: `ModelEntry`, `ProviderListing`, `ModelCatalog` + `get_model_catalog(force=False)` async fan-out with 5s timeout + 60-min cache + `_fetch_anthropic/_openai/_minimax` helpers. | 250 |
| `src/tradefarm/agents/llm_providers.py` | add `MODEL_COST_HINTS: dict[tuple[str, str], dict[str, float]]` as the static pricing table the picker reads. (the OpenAI provider itself is out of scope.) | 40 |
| `src/tradefarm/agents/llm_overlay.py` | swap `_provider_from_settings` body to read `get_llm_model_config()` first, fall back to `settings.llm_model`. | 15 |
| `src/tradefarm/api/admin.py` | add `GET /admin/llm/models`, `POST /admin/llm/select`, `POST /admin/llm/reset`. mirror the TTS endpoints at `admin.py:512-597`. extend `VALID_PROVIDERS` to include `"openai"`. | 185 |
| `src/tradefarm/config.py` | add `openai_api_key: str = ""`. | 1 |
| `web/src/api.ts` | add `adminLlmModels(refresh?)` + `adminLlmSelect(provider, model)` + `adminLlmReset()`. extend `AdminConfig` with `openai_api_key: {set, masked}`. | 60 |
| `web/src/components/AdminModal.tsx` | **replace** the `llm_model` text input at `AdminModal.tsx:142-150` with `<LlmModelPicker />`. extend the provider radio cards at `AdminModal.tsx:124-140` to include `"openai"`. add "OpenAI API key" Row. | 200 |
| `web/src/components/LlmModelPicker.tsx` | **new**: takes `provider` prop, fetches `/admin/llm/models` via SWR, renders the provider's model list as a select with `(id, display_name, cost_hint)` per row. "Refresh" calls `?refresh=true`. handles `ok: false` with an inline hint. | 250 |
| `tests/runtime/test_llm_model_config.py` | new: `get/set/reset` round-trip, validation errors, lock semantics, defaults-from-settings seeding. | 150 |
| `tests/runtime/test_llm_model_catalog.py` | new: all three providers mocked; partial-failure (one provider 500 → ok:false, others ok:true); cache TTL; per-provider timeout; missing-key shortcut. | 200 |
| `tests/api/test_admin_llm_endpoints.py` | new: `GET /admin/llm/models` envelope; `POST /admin/llm/select` validates + persists; `POST /admin/llm/reset` reverts. | 120 |
| `docs/admin/llm-picker.md` | new operator-facing notes: "what does this dropdown do, where does the price come from, why is my model gone after refresh". | 150 |

**total: ~1720 lines.** `L` effort (1-2 days), driven mostly by the picker component (250) + the catalog module (250) + the admin endpoints (185). budget realistically 2 days for the first cut + ½ day for test fixes — the catalog's partial-failure logic + 3-provider mocking surface is the part most likely to need iteration during code review.

## Recommendation

**ship it.** the existing free-form `llm_model` text input at `web/src/components/AdminModal.tsx:142-150` is a footgun: the operator can typo a model id, pick a model that doesn't exist, and only find out at the next tick when `with_retries` logs an httpx 404. the picker is the right size for a 0.18.0 milestone (~1720 lines, 2 days of work), reuses the proven `TtsConfig` runtime pattern, the three `/v1/models` endpoints are stable and well-documented, and the static cost-hint table keeps the implementation honest without a separate pricing scraper.

the three biggest design choices and why:

1. **60-min cache + manual "Refresh" button.** avoids the 5-10s modal-open lag without forcing a stale model list. the operator hits "Refresh" once when they know a new model dropped.
2. **partial-failure envelope (`{ok: true|false, models, error}`).** one provider being slow or missing a key doesn't fail the whole modal. the dashboard renders the providers that succeeded; the failed ones get an inline retry button.
3. **`LlmModelConfig` runtime singleton + `settings.llm_model` as the seed.** the runtime config is the source of truth for the picker; the env-var settings remain the default at boot.

the alternative — a simpler "hardcode a few known model ids" approach — saves maybe ½ a day but loses the "fresh model on day 1 of release" story. the live `/v1/models` integration is the whole point; ship the real thing.
