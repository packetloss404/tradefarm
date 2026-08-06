# LLM model picker — operator guide

0.18.0 replaces the dashboard's free-form `llm_model` text input
with a live-discovered dropdown. The picker fans out to each
provider's `/v1/models` endpoint, caches the result, and ships a
per-row cost hint. The runtime config is the source of truth; the
env-var settings remain the boot-time seed.

## What the dropdown does

The picker is split into two parts:

1. **Provider radio cards** (`Anthropic Claude` / `OpenAI GPT` /
   `MiniMax`). Each card is gated on the env key for that provider
   being set — operators can't switch to a provider whose key
   isn't there. The "Active" badge marks the currently-running
   provider.
2. **Model dropdown** — populated from the live `/v1/models` fetch
   for the selected provider. Selecting a row and hitting "Save"
   POSTs to `/admin/llm/select`, which updates the runtime
   `LlmModelConfig` singleton AND writes `LLM_PROVIDER` /
   `LLM_MODEL` to `.env`. The next `build_provider` call picks it
   up; the in-flight LLM call completes with the old config.

The "Revert to env defaults" button calls `/admin/llm/reset`, which
rebuilds the runtime config from `settings.llm_provider` /
`settings.llm_model`.

## What the price column means

Each row carries a `cost_hint_usd` field the picker renders as
"~$X.XX in / $Y.YY out per 1M tokens". The numbers come from a
static table in `src/tradefarm/agents/llm_providers.py:281` (the
`MODEL_COST_HINTS` dict). The values are cross-referenced against
the providers' public pricing pages at release time; the
research-doc sources are in
`docs/research/llm-model-discovery.md` section 4.2.

A missing row renders as "cost: unknown" rather than a wrong
number. The picker does NOT auto-rewrite the spend counter
(`settings.llm_input_per_million` / `llm_output_per_million` /
`llm_cache_read_per_million`); operators who want to update the
spend estimate do it via the existing "Tuning" range sliders.

## Why is the model I picked yesterday gone after a refresh?

The catalog has a 60-min in-memory cache. The dropdown shows
"list cached at HH:MM:SS" so the operator can see how stale the
list is. Hitting the "Refresh list" button forces a refetch by
calling `/admin/llm/models?refresh=true`.

If the operator picks a model that's later removed from the
provider's listing (a deprecation, for example), the picker shows
the model as missing on the next refresh. The runtime config
still points at the old id; the next LLM call to that id will
fail with a 4xx. Operators who want to revert hit "Revert to env
defaults".

## Why do I see a yellow "fetch failed" on a provider?

The picker fan-out is partial-failure: one provider being slow
or missing a key does not fail the whole modal. The per-provider
section shows:

- `ok: true` with a list of `ModelInfo` rows — the catalog succeeded.
- `ok: false` with an `error` string — the catalog fetch failed
  (timeout, 4xx/5xx, missing key, malformed JSON). The dropdown
  for that section is disabled; the operator can retry by hitting
  "Refresh list".

Common error strings:

| error | what it means |
|---|---|
| `ANTHROPIC_API_KEY not set` | operator needs to add `ANTHROPIC_API_KEY=...` to `.env` and restart. |
| `OPENAI_API_KEY not set` | same, for OpenAI. |
| `MINIMAX_API_KEY not set` | same, for MiniMax. |
| `anthropic fetch failed: HTTPStatusError: 401 ...` | key is set but the provider rejected it (key revoked, wrong project). |
| `fetch timed out after 5s` | the provider's `/v1/models` endpoint didn't respond in 5s. Hit "Refresh list" to retry. |
| `minimax base URL invalid: ...` | `MINIMAX_BASE_URL` is not on the allowlist (round-6 MED-minimax). The catalog refuses to leak the bearer token to a non-allowlisted host. |

## What's the difference between the picker's "Save" and the admin modal's footer "save"?

Two different saves for two different concerns:

- The **admin modal's footer "save"** persists draft fields
  (including the API keys, base URL, strategy toggles, etc.) to
  `.env` via `/admin/config`. It writes the whole `ConfigPatch` in
  one shot.
- The **picker's "Save"** writes the chosen provider + model to
  the runtime `LlmModelConfig` singleton AND to `.env` via
  `/admin/llm/select`. The runtime singleton takes effect
  immediately; the `.env` write is for durability.

In practice, operators set the API keys via the modal's "Brain
Provider" section, save those, then use the picker to swap
providers + models at runtime without re-saving the whole admin
form.

## Thread-safety

The runtime `LlmModelConfig` singleton uses a `threading.Lock`
(not `asyncio.Lock`) because the config is read from both sync
code paths (the LLM overlay rebuild runs in the asyncio loop) and
async paths (the admin endpoint's POST handler). The lock is
held only long enough to swap the reference; readers see either
the old or the new config, never a half-built one. This is the
same pattern as the 0.17.0 TTS config.

## Future work

Not in 0.18.0 scope, but worth noting:

- **Per-model max-tokens / temperature controls.** The picker is
  a model id, not a per-call params editor. Those stay in the
  existing `LlmContext` + provider shape.
- **Auto-pricing the spend counter based on the chosen model.**
  The existing `COST_PER_CALL_USD = 0.0006` in
  `web/src/components/ApiSpendWidget.tsx:10` is calibrated for
  Haiku 4.5 and breaks for everything else; rewriting it is a
  follow-up.
- **A "test connection" button on each row.** That would be N
  LLM round-trips per modal open (one per model). Bad UX. The
  existing "save" button validates the choice on the next actual
  call.
- **Per-provider credential editing inside the picker row.** The
  existing "Anthropic API key" / "OpenAI API key" / "MiniMax API
  key" rows in the admin modal's "Brain Provider" section stay.
  The picker reads the runtime config; the credential rows write
  the `.env` keys.
