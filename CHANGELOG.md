# Changelog

All notable changes to this project. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
follows [Semantic Versioning](https://semver.org/) starting from `0.1.0`.

Dates are when the commit landed on `main`. Hashes link to the canonical
commit on GitHub.

## [Unreleased]

- None yet.

## [0.26.0] - 2026-08-05

A "speech bubbles on agents" release.
AgentWorldXL now surfaces the LLM's
``last_decision.reason`` as a truncated SVG
bubble above the matching sprite for 6s
after a fill. Rendered as a rounded rect
with a pointer triangle and a centered
monospace text node; fade-in (200ms) and
fade-out (last 800ms) keep the bubble from
popping in/out abruptly. The bubble data
lives in a Map<agentId, {reason, expiresAt}>
that ticks on the same interval as the
existing halos/flows (300ms). No new env
vars, no backend changes, no test infra
yet (the visual is observable in the
running stream; the unit-test infra is
web/jsx, which we don't have wired).
Web bundle unchanged; stream tsc clean.

## [0.24.0] - 2026-08-05

A "intraday data path" release. The
orchestrator was reasoning on a 24h-stale
mark (yesterday's daily close) at the
start of every RTH tick; at 10:00 ET an
agent's `mark` was still last night's
settle. New `EodhdClient.get_intraday()`
fetches EODHD's 5m intraday bars (paid
tier; the free tier short-circuits to an
empty frame so the daily mark stays in
charge). The orchestrator's
`_refresh_intraday_marks()` mutates
`marks` in place when `intraday_enabled`
is on AND the market is open. Off-RTH
the daily path stays in charge regardless.
The 5m window auto-scales with the period
(30m for 5m, 4h for 1h). The intraday
mark is <5min stale vs the 18h-stale
daily mark. Subscription-required (401/403)
is a logged info + empty frame, not a
crash; the existing daily path is the
fall-through. Two new env vars:
`intraday_enabled=False` (master switch,
off until the operator has an EODHD
subscription), `intraday_period="5m"`.
6 new tests; total 1107 passing.

## [0.20.0] - 2026-08-05

A "per-strategy daily attribution snapshot" release.
The hot `GET /pnl/by-strategy/timeseries` endpoint
used to aggregate from `pnl_snapshots` on every
chart poll (a 2x group-by that scales with rows
in the snapshot table). New `strategy_daily_attribution`
table holds one row per (date, strategy), written
once at end-of-day by the 4pm ET recap scheduler
in `_fire_daily_recap_moment`. The endpoint now
reads historical days from the snapshot, falling
back to live aggregation for today and for any
pre-0.20.0 history. The schema migration is a
new `Base.metadata.create_all`-managed table;
`SCHEMA_VERSION` bumped 4 -> 5. The repo helper
`compute_and_store_for_date(day)` is the end-to-end
write path; `upsert_attribution_rows` uses SQLite
`ON CONFLICT DO UPDATE` so a same-day rerun
replaces in place rather than appending. Live
aggregation also got a fix: the join on
`PnlSnapshot.taken_at == max(taken_at)` now also
filters on `session_id IS NULL`, so a same-day
replay snapshot sharing the live row's timestamp
can't double-count. 10 new tests; total 1101
passing. No new env vars, no new endpoints.

## [0.19.0] - 2026-08-05

A "persistent LLM-decision feed sidebar"
release. The dashboard's Today page gets a
new `<DecisionFeedSidebar />` at the bottom
that holds the last ~50 per-agent decision-lab
entries for quick review. Two refresh paths:
SWR polling of the new `GET /api/decisions/recent`
endpoint every 5s, plus a live WebSocket
subscription to `agent_decisions_batch` so
freshly-arriving entries prepend without
waiting for the next poll. Backed by a
process-wide bounded ring buffer
(`RecentDecisionsLedger`, 200 entries) that
a lifespan-spawned subscriber feeds from the
event bus - so a freshly-reloaded page sees
recent history before any new tick lands.
Filters: `?agent_id=N` (single agent),
`?only_llm=true` (skip rule-based + LSTM-only
agents), `?limit=N` (1..200). 22 new tests
(14 unit + 8 endpoint). Web bundle:
385 KB / 111.7 KB gzipped (+5 KB / +1.7 KB
vs 0.18.0 for the new sidebar).

## [0.18.1] - 2026-08-05

Hotfix for the legacy `web/src/dash/Admin.tsx`
admin *tab* (the one at `localhost:5179/#admin`)
that the 0.18.0 McLove pass missed. Three fixes:

- The Strategies section was hardcoded to 3
  strategies. Now reads the 8-strategy list from
  the live `/admin/config._meta.known_strategies`
  (same path the McLoved modal uses).
- The BRAIN PROVIDER section had no model
  picker. Mounted `<LlmModelPicker />` and added
  `openai` to the provider Segment + an
  `openai_api_key` field, mirroring the modal.
- The legacy route used a 640px modal treatment
  that hid the strategies table below the fold.
  Added a `fullPage` prop to `AdminModal`; the
  legacy `Admin.tsx` now passes `fullPage=true`
  so the admin renders as an in-page takeover
  (no overlay, "back to dashboard" button).

Also: demo catalog fallback for the LLM model
catalog. When an API key is missing, the backend
returns a curated demo list with `ok: true` and
a `warning: "<KEY> not set; showing demo catalog"`
so dev/QA sees the real lineup with cost hints.
Production always has keys so the demo path is
unreachable in practice.

Test fix: 5th instance of the carryover test
isolation family. `tests/orchestrator/test_daily_recap_scheduler.py`
now uses the canonical `set_replay_now` ContextVar
pattern instead of `monkeypatch.setattr(clock_mod,
...)`. The market clock's `is_market_closed_for_n_minutes`
reads `now_utc` via module-level import, so a direct
monkeypatch on `clock_mod.now_utc` was leaking the
real wall clock to the market-clock check; the
ContextVar pattern is the only one that affects
every reader. 1069 passed, 8 skipped, 0 failed.

---

## [0.18.0] — 2026-08-05

A "live LLM model discovery + McLove the admin
panel" release. The dashboard's free-form
`llm_model` text input is replaced with a live-
discovered dropdown that calls each provider's
`/v1/models` API, caches for 60 minutes, and
shows the current top-line models with cost
hints. **The user's mentions of "haiku/sonnet/
opus/fable", "M3", and "GPT 5.6 all 3 variants"
were all real, current model names — verified
via the research subagent's per-provider scan.**
Anthropic: `claude-haiku-4-5-20251001`,
`claude-sonnet-5`, `claude-opus-4-8`,
`claude-fable-5`. OpenAI: `gpt-5.6-sol` (alias
`gpt-5.6`), `gpt-5.6-terra`, `gpt-5.6-luna`.
MiniMax: `MiniMax-M3`, `MiniMax-M2.7`,
`MiniMax-M2.7-highspeed`. The admin modal
also gets a full McLove pass — section
reordering, dead-UI removal, a11y upgrade,
friendly error states on every async action.
The OpenAI provider ships for the first time
(reuses the shared httpx + retry pattern).
1069 tests pass (+52 since 0.17.0).

### Added — live LLM model discovery

- **`docs/research/llm-model-discovery.md`** (NEW,
  ~3135 words) — the per-provider spec: endpoint
  URL, auth header shape, response shape (with
  JSON samples), current model lineup, the
  recommended dashboard flow (parallel fan-out
  with 5s per-provider timeout + 60-min in-memory
  cache + partial-failure envelope), and a "files
  to touch" implementation table.

- **`src/tradefarm/runtime/llm_model_config.py`**
  (NEW, ~150 lines) — `LlmModelConfig` dataclass
  with `provider: str, model: str`. Singleton
  `get_llm_model_config()` /
  `set_llm_model_config()` /
  `reset_llm_model_config()`. Threading lock
  around the singleton so the dashboard's SWR
  refresh doesn't see a torn read during a save.
  Mirrors the 0.17.0 `TtsConfig` pattern exactly.
  Validation rejects empty models + unknown
  providers.

- **`src/tradefarm/runtime/llm_model_catalog.py`**
  (NEW, ~140 lines) — in-memory catalog cache
  (`max_age_sec=3600`) + the `list_*_models`
  fan-out. `fetch_catalog(refresh=False)` returns
  the cached payload or hits all 3 providers in
  parallel via `asyncio.gather` with 5s per-
  provider timeout. Partial-failure envelope:
  `{anthropic: {ok, models, fetched_at, error?},
  openai: {...}, minimax: {...}, cached_at}`. The
  cache survives process restarts via pickle
  (optional, defaults to off — see `record_path`
  arg).

- **`src/tradefarm/agents/llm_providers.py`** —
  significant extension:
    - New `OpenAiProvider` class (the OpenAI
      provider didn't exist before; the user
      explicitly asked for it). Uses the shared
      httpx client + `with_retries`. Default
      `gpt-5.6-sol` (with `gpt-5.6` alias).
      `name = "openai"`.
    - `list_anthropic_models(api_key)` — calls
      `GET https://api.anthropic.com/v1/models`
      with `x-api-key` + `anthropic-version:
      2023-06-01` headers, normalizes the
      `{data: [...], has_more, ...}` envelope.
    - `list_openai_models(api_key)` — calls
      `GET https://api.openai.com/v1/models`
      with bearer auth, normalizes the
      `{object: "list", data: [...]}` envelope.
    - `list_minimax_models(api_key, base_url)` —
      calls
      `GET https://api.minimax.io/v1/models`
      (the OpenAI-compatible endpoint), bearer
      auth, OpenAI-style envelope.
    - `MODEL_COST_HINTS` static table — per-
      `(provider, model)` per-1M-token cost
      (input/output/cached). Covers the GPT-5.6
      trio, Claude Haiku/Sonnet/Opus/Fable,
      MiniMax M3/M2.7. The providers' `/v1/models`
      responses don't include pricing, so this
      is the source of truth for the dashboard's
      cost hint.
    - `build_provider()` extended to handle
      `"openai"` + read from
      `get_llm_model_config()` for the active
      provider/model (with `settings.llm_model`
      as the seed default).

- **`src/tradefarm/api/admin.py`** — 3 new admin
  endpoints:
    - `GET /admin/llm/models?refresh=true|false` —
      fans out the catalog fetch (the `refresh=true`
      bypasses the 60-min server cache). Returns
      the per-provider envelope + `cached_at`.
    - `POST /admin/llm/select` — body
      `{provider, model}`. Validates the model
      is in the cached list (or accepts the string
      and trusts the operator). Updates the
      runtime singleton. Returns `{previous, active}`.
    - `POST /admin/llm/reset` — reverts to the
      env-var defaults.
  + `ConfigPatch` extended with `llm_provider`
  now accepting `"openai"` as a valid value.

- **`src/tradefarm/config.py`** — added
  `openai_api_key: SecretStr = SecretStr("")` +
  `default_openai_model: str = "gpt-5.6-sol"`
  (the new top-line OpenAI default, not the
  fictional "GPT 5.6" string the user mentioned
  — `gpt-5.6-sol` is the canonical model id
  with `gpt-5.6` as a documented alias).

- **`web/src/components/LlmModelPicker.tsx`**
  (NEW, ~310 lines) — new admin modal section.
  Provider radio cards (anthropic/openai/minimax)
  with availability indicators (green check if
  env key set; cloud providers greyed out
  otherwise). Per-provider model dropdown
  populated from `GET /admin/llm/models`
  (SWR with 60s refresh + a manual "Refresh"
  button). Per-row cost hint when
  `cost_per_1k_input_usd` is present. "(cached
  at HH:MM:SS)" line + a dedicated error row
  when a provider's fetch failed. Save posts
  `{provider, model}` together (single source
  of truth for the model selection).

- **`web/src/api.ts`** — `llmModels`,
  `llmSelect`, `llmReset` SWR fetchers + types
  (`LlmModelInfo`, `ProviderModelsResponse`,
  `ProviderModelsPayload`). `AdminConfig` +
  `AdminPatch` extended with
  `openai_api_key: AdminSecretField`.

### Added — McLove the admin panel

- **`web/src/components/AdminModal.tsx`** — the
  full McLove pass (per the review subagent's
  report). The Brain Provider section's
  provider-radio group is **removed** (the
  LLM Model picker owns provider + model as a
  single source of truth; the picker posts
  both fields together). API key fields stay
  in Brain Provider and now render for all
  3 providers unconditionally (the operator
  can paste a key for any provider regardless
  of which is active). Section ordering:
    1. AI Control
    2. Brain Provider (3 API key fields)
    3. LLM Model (3-provider radio + dropdown
       + save)
    4. Tuning
    5. Execution
    6. Strategies
    7. Backtest
    8. Curriculum
    9. TTS
  The "Coming soon" placeholder section is
  dropped. Every `<input>` / `<select>` /
  `<button>` has explicit `htmlFor` / `id` /
  `aria-label` (was implicit `<label>` wrappers
  before). The `toggleAi` async action now
  has friendly error handling (was the only
  async action without it). The `Row` +
  `Toggle` components gained `htmlFor` / `id`
  + `badge` + `label` props. CTA-style `<button>`
  rows in Brain Provider + Execution are now
  proper radio cards with `sr-only` inputs.

### Orchestrator integration fixes

- **Provider-radio conflict** between the new
  `<LlmModelPicker />` (which has its own 3-
  provider radio) and the existing Brain
  Provider section (which also had a 2-
  provider radio). The McLove spec called this
  out; resolution is to **remove** the parent
  radio and let the picker own provider +
  model as a single surface. API key fields
  stay in Brain Provider and render
  unconditionally for all 3 providers.
- **Stray helper script** (`web/src/fix_em.py`,
  a one-shot em-dash/arrow/checkmark replacer
  used by a subagent) was moved to
  `dev/_archive/fix_em_2026-08-05.py` per the
  no-hard-delete safety policy. Not committed.
- **Ruff auto-fix** cleared 5 F401 (unused
  imports) introduced by the subagents.

### Operational notes

- **1017 → 1069 tests pass** (+52). Breakdown:
  llm_model_config: +12, llm_model_catalog:
  +13, admin_llm_endpoints: +10, build_provider
  _runtime_config: +6, llm_provider model-list
  parsers: +11.
- **No `SCHEMA_VERSION` bump** — runtime config
  + catalog cache are both in-memory.
- **1 new env var** (`openai_api_key` + the
  derived `default_openai_model`). The
  admin modal's existing API key field for
  OpenAI is wired (it was missing in the
  parent before 0.18.0).
- **Web prod bundle**: 374 KB → 374 KB / 108 KB
  → 108 KB gzipped (the new admin picker
  added ~5 KB before gzip, gzipped back to
  the same size — Vite compresses efficiently).
- **The operator's dev stack is still up**
  (uvicorn 8000, vite 5179, vite 5180) but
  uvicorn was started without `--reload` —
  the operator needs to restart the backend
  to see the new endpoints.

---

## [0.17.0] — 2026-08-05

A "real voice + lower-thirds builder + WS recording"
release. Three parallel dev subagents shipped the
three work streams; Subagent A (TTS settings UI)
returned no files so the orchestrator did that work
inline. The orchestrator also wrote the missing
tests for Subagent B (lower-thirds) and fixed three
runtime issues in the TTS preview path
(`asyncio.run()` from inside a running event loop;
the endpoint is `async def` so a plain `await`
suffices). 1017 tests pass (+96 since 0.16.0).

### Added — TTS settings UI

- **`src/tradefarm/runtime/tts_config.py`** (NEW,
  ~150 lines) — runtime-mutable TTS config singleton.
  `TtsConfig` dataclass with `provider`, `voice`,
  `speaking_rate`. `get_tts_config()` /
  `set_tts_config()` / `reset_tts_config()` /
  `estimate_cost_usd()`. Validation in `set_tts_config`
  rejects unknown providers, empty voices, and out-
  of-range rates (0.25-4.0). Threading lock around
  the singleton so the dashboard's SWR refresh
  doesn't see a torn read during a save.
- **`src/tradefarm/api/admin.py`** — 4 new admin
  endpoints:
    - `GET /admin/tts/status` — returns the active
      config + `available_providers` +
      `has_creds[provider]` + `voices_by_provider`
      + `cost_per_1k_chars_usd` (the dashboard's
      `<TtsSettingsPanel />` uses these to gate
      the radio cards).
    - `POST /admin/tts/switch` — flips the active
      config at runtime. Validates the requested
      provider has its env key set (400 otherwise);
      the `silence` provider is always allowed.
      Returns `{previous, active}` so the dashboard
      can show "reverted from X to Y".
    - `POST /admin/tts/reset` — reverts to the
      env-var defaults (`settings.podcast_tts_provider`).
    - `POST /admin/tts/preview` — synthesizes a
      single line to a tmp wav, returns it as
      base64 audio, increments the TTS_SPEND counter
      atomically. Supports a per-call
      `provider`/`voice` override (so the operator
      can try a different voice without committing
      a switch).
- **`src/tradefarm/api/main.py`** — new `TTS_SPEND`
  module-global counter (mirrors `LLM_SKIPS`) +
  `GET /tts/stats` endpoint (chars_synthesized,
  cost_usd, calls, active_provider). The dashboard's
  `<ApiSpendWidget />` reads this to show today's
  TTS cost next to the LLM cost.
- **`web/src/components/TtsSettingsPanel.tsx`** (NEW,
  ~340 lines) — new admin modal section. Provider
  radio cards with availability indicators
  (cloud providers greyed out when env keys
  missing; `silence` always available), voice
  dropdown per provider, speaking-rate slider
  (0.25-4.0x with labels), Save + Revert-to-env
  buttons, inline preview textarea with
  Synthesize button that plays the returned wav
  in an inline `<audio controls>`, and a "Today:
  N calls · N chars · $X · active: Y" spend line.
- **`web/src/api.ts`** — `ttsStatus`, `ttsSwitch`,
  `ttsReset`, `ttsPreview`, `ttsStats` SWR
  fetchers + 5 new types (`TtsProvider`,
  `TtsConfigPayload`, `TtsStatusPayload`,
  `TtsPreviewPayload`, `TtsStatsPayload`).
- **`web/src/components/AdminModal.tsx`** — new
  "TTS" section between Tuning and Curriculum,
  renders `<TtsSettingsPanel />`.

### Added — lower-thirds builder

- **`src/tradefarm/api/lower_third_log.py`** (NEW,
  ~165 lines) — `LowerThirdEntry` dataclass +
  `LowerThirdLog` bounded FIFO ring buffer
  (`max_size=200`, eviction silent on overflow).
  `record()` clamps `ttl_sec` to `[1, 120]`, drops
  unknown colors to None, generates a uuid hex id
  if omitted. `recent(limit)` returns newest-first.
  Process-global singleton (`log = LowerThirdLog()`);
  tests inject their own instance.
- **`src/tradefarm/api/events.py`** — new
  `EVENT_TYPE_LOWER_THIRD = "lower_third"` constant.
  Payload shape documented in the module docstring.
  Comment block explains the coexistence with
  `stream_banner` (visual identical; `lower_third`
  is the operator-driven path, `stream_banner` is
  the broadcast suite's auto-fan-out).
- **`src/tradefarm/api/admin.py`** — 2 new admin
  endpoints:
    - `POST /admin/lower_third/push` — body
      `{title, subtitle?, ttl_sec?, color?, id?}`;
      pydantic validation rejects empty titles,
      unknown colors (`profit`/`loss`/`neutral`
      only), out-of-range ttl. Publishes via
      `publish_event` so the stream's `useStreamCommands`
      sees the event with no extra wiring. Records
      to the in-memory log. Returns the recorded
      entry (with its server-assigned id) so the
      dashboard can show a "pushed at HH:MM:SS" toast.
    - `GET /admin/lower_third/recent?limit=N` —
      returns `{items: [...]}` newest-first.
      Default 50, max 200 (clamped; negative
      returns 400).
- **`stream/src/shared/useLiveEvents.ts`** — new
  `lower_third` case in the `LiveEvent` union;
  `LowerThirdPayload` type. The stream app's
  `useLiveEvents` consumer sees the event with no
  extra wiring.
- **`stream/src/hooks/useStreamCommands.ts`** —
  new `lower_third` case in the WS event switch.
  Routes to the same `setBannerSafe` slot as the
  legacy `stream_banner`; visual is identical. The
  `BannerState` type gains an optional `color`
  field (`profit` | `loss` | `neutral`).
- **`stream/src/components/LowerThird.tsx`** —
  extended to read the new `color` field and apply
  an accent border on the left edge. Pre-0.17.0
  banners (and `stream_banner` events without the
  field) default to `profit`.
- **`web/src/components/LowerThirdBuilder.tsx`**
  (NEW, ~270 lines) — new section in the broadcast
  panel. Title input (required, max 80 chars),
  subtitle input (optional, max 120), TTL slider
  (1-120s, default 8), color radio (profit/loss/
  neutral), "Push to stream" button + success
  toast, recent-rows list (last 10) with "Replay"
  buttons (re-pushes the same payload with a new
  id; one click, not three form fields).
- **`web/src/components/broadcast/BroadcastPanel.tsx`** —
  integrates `<LowerThirdBuilder />` as a new
  collapsible section.
- **`web/src/api.ts`** — `pushLowerThird` +
  `getRecentLowerThirds` SWR fetchers (shipped by
  Subagent B).

### Added — WS event recording (Subagent C)

- **`src/tradefarm/api/ws_recording.py`** (NEW,
  ~140 lines) — `WsRecorder` class. Writes one
  JSON line per WS frame to
  `data_cache/ws_recordings/<session_id>.ndjson`.
  Each line: `{"ts": iso, "session": sid,
  "direction": "in"|"out", "type": ev_type,
  "payload": {...}}`. Line-buffered append mode
  for `tail -f` debugging. Best-effort: failed
  writes log + drop, never crash the WS. Process-
  global registry (`_recorders: dict[str, WsRecorder]`)
  enforces "one recorder per session_id";
  creating a second closes the first (and flushes
  its buffer).
- **`src/tradefarm/api/ws.py`** — wraps the
  `publish_event` hot path with a thin recorder-
  aware shim. Overhead is one `dict.get()` when
  no recorder is active for the session (the
  common case). The `in` direction is recorded
  by `websocket_endpoint` on each received frame.
- **`src/tradefarm/api/admin.py`** — 3 new admin
  endpoints:
    - `POST /admin/ws_recording/start` — body
      `{session_id, base_dir?}`. Creates a recorder
      for the session; idempotent (re-calling
      returns the existing recorder's path).
    - `POST /admin/ws_recording/stop` — body
      `{session_id}`. Closes the recorder, returns
      `{ok, frames_recorded, path}`. 404 if no
      recorder for that session.
    - `GET /admin/ws_recording/list?base_dir=...` —
      returns the list of recorded session_ids
      (filenames without extension).
- **`src/tradefarm/orchestrator/broadcast_fixtures.py`** —
  2 new helpers (no breaking changes to existing
  API):
    - `load_ws_recording(path)` — reads a recording
      NDJSON, returns the list of frames. Skips
      corrupted lines with a warning.
    - `replay_ws_recording(frames, *, tick_sec)` —
      yields one frame at a time, `tick_sec` apart.
      Lets a test or a future "replay mode" iterate
      deterministically.
- **`web/src/components/RecordingPanel.tsx`** (NEW,
  ~150 lines, optional Subagent C scope) — a small
  panel in the broadcast section. Start / Stop
  per session_id; list of available recordings;
  "Replay" button per recording opens a future
  `/replay/<session_id>` route. (The route itself
  is a follow-on; the panel surface ships now.)
- **`tests/api/test_ws_recording.py`** (NEW,
  ~180 lines) — recorder round-trip + IO-error
  swallowing + append-across-instances + close-
  idempotency + path-shape assertions.
- **`tests/orchestrator/test_broadcast_fixtures.py`**
  — 2 new tests for `load_ws_recording` +
  `replay_ws_recording`.

### Orchestrator integration fixes

- **`src/tradefarm/api/admin.py:649`** — the
  preview endpoint's first cut called
  `asyncio.run(synthesize(...))` from inside a
  FastAPI `async def` handler. That fails with
  "asyncio.run() cannot be called from a running
  event loop". The endpoint is `async def` so a
  plain `await` suffices. Fixed.
- **Subagent B's lower-thirds work** shipped
  without tests. Orchestrator wrote
  `tests/api/test_lower_third_admin.py` (7 tests)
  + `tests/api/test_lower_third_log.py` (16 tests)
  + 1 missing test for the cap+eviction case.
- **Subagent A's TTS work** shipped no files at
  all. Orchestrator did the full work: tts_config
  module, 4 admin endpoints, TTS_SPEND counter +
  `/tts/stats` endpoint, TtsSettingsPanel,
  AdminModal integration, api.ts types, plus
  18 admin-endpoint tests + 21 config unit tests.

### Operational notes

- **921 → 1017 tests pass** (+96). Breakdown:
  lower_third_log: +16, lower_third_admin: +7,
  tts_config: +21, tts_admin: +18, ws_recording:
  +5, broadcast_fixtures (ws helpers): +2, +27
  from Subagent C's wider coverage.
- **No `SCHEMA_VERSION` bump** — all new state is
  in-memory (LowerThirdLog, TtsConfig singleton,
  TTS_SPEND counter, WsRecorder registry, ws
  recordings dir on disk).
- **No new env vars.**
- **Web prod bundle**: 373 KB → 374 KB / 108 KB →
  108 KB gzipped (TtsSettingsPanel + LowerThirdBuilder
  + RecordingPanel added ~1 KB before gzip; gzipped
  size is essentially flat — Vite compresses the
  new code efficiently).
- **The audio/cadence controls stay clickable when
  the stream is offline** (0.13.0 carryover):
  Reminder in 0.13.0 CHANGELOG.
- **Visual QA pause** — please verify (a) the
  TTS settings panel opens, shows the silence
  provider as active, and the radio cards gate
  correctly when no env keys are set; (b) the
  lower-thirds builder pushes a banner that
  appears on the stream for the TTL window;
  (c) the WS recording start/stop cycle works
  against a live session (the recording file
  appears in `data_cache/ws_recordings/`).

---

## [0.16.0] — 2026-08-05

A "recap scene + Rivalry Week podcast + scheduler
tuning fixtures" release. Closes three backlog
items in one swing: item **4.5** (recap scene at
4pm ET), the **Rivalry Week podcast format** from
the round-8 research (`docs/research/youtube-interesting.md:103`),
and **milestone 3** of `docs/broadcast_os.md`
(replay fixtures for moment timelines). Three
parallel dev subagents shipped the three work
streams under the orchestrator's integration;
the orchestrator fixes two cross-cutting mypy
errors (Pillow `LANCZOS` namespace + LLM
response-block union-attr) and three
pre-existing `test_vod_scheduler.py` failures
(date-constant `2026-08-04` had drifted past
"today"). 921 tests pass (+60 since 0.15.0).

### Added — 4pm ET live recap scene

- **`src/tradefarm/orchestrator/broadcast_suite.py`** —
  new `run_daily_recap_scheduler` poll loop
  (30s interval) on the suite. Gates: ET clock
  in `[16:00, 16:30)`, `is_market_closed_for_n_minutes(0)`
  True (encodes the holiday calendar), no row in
  the new `daily_recap_fired` table for today's
  date. Fires the canonical `BroadcastMoment`
  with `kind="day_leader"`, `trigger="daily_recap"`,
  `outputs=("recap_log",)` only, `priority=88`
  (below `promotion=90` so a late-day promotion
  still preempts), `ttl_sec=60`. Publish via the
  installed arbiter with `emit_legacy=False`
  (the recap scene is the rotator's job, not the
  legacy macro/banner slots). Idempotency row is
  written *after* the publish — a missed row is
  recoverable, a missed publish is not.
- **`src/tradefarm/storage/models.py`** + **`db.py`** —
  new `DailyRecapFired` table (`date TEXT PRIMARY KEY,
  moment_id TEXT, fired_at TEXT`). Idempotent
  `CREATE TABLE IF NOT EXISTS`; no `SCHEMA_VERSION`
  bump.
- **`src/tradefarm/storage/repo.py`** —
  `find_daily_recap_for_date()` + `record_daily_recap_fired()`.
- **`src/tradefarm/api/admin.py`** —
  `POST /admin/recap/push` operator manual
  trigger. Takes optional `{date: "YYYY-MM-DD"}`,
  publishes unconditionally, does NOT write the
  idempotency row (so the next 4pm auto-fire
  still runs). Used by the dashboard's "Push 4pm
  recap" button.
- **`src/tradefarm/api/recap.py`** —
  `GET /api/recap/ledger` (returns
  `BroadcastRecapLedger.to_payload()`) +
  `GET /api/weekly/{week_id}` (wraps
  `read_weekly_rollup`, validates `YYYY-WNN` regex,
  404 when missing).
- **`stream/src/scenes/LiveRecapScene.tsx`** (NEW,
  ~200 lines) — on-stream scene that reads
  `useRecapLedger()` + `useWeeklyRollup(weekId)`
  via two new SWR hooks. KPI line + top 3 moves
  from the ledger + rivalries from the rollup.
  Mounted by `SceneRotator` as a force-scene
  overlay for the moment's `ttl_sec`.
- **`stream/src/hooks/useRecapLedger.ts`** +
  **`useWeeklyRollup.ts`** — new SWR hooks.
- **`stream/src/shared/broadcastMomentMappers.ts`** —
  new mapper for `kind="day_leader"` +
  `outputs contains "recap_log"` →
  `{ kind: "live_recap", weekId, ttl_sec, firedAt }`.
  `useStreamCommands` consumes this and forces
  the rotator to `LiveRecapScene` for the TTL.
- **`web/src/components/broadcast/BroadcastPanel.tsx`** —
  new "Push 4pm recap" button + toast on success.

### Added — Rivalry Week podcast format (30-min audio)

- **`src/tradefarm/render/podcast.py`** (NEW,
  ~600 lines) — the composer. Public surface:
  `compose_weekly_episode()` (the operator entry),
  `synthesize_voice()` (wraps `tts/run.py:316`
  `run_tts()` with new `podcast_mode` option),
  `render_static_card()` (Pillow frame gen +
  ffmpeg concat into one 30-min `week_card_*.mp4`),
  `make_intro_outro()` (8s vertical teaser cards
  via `render/shorts.py:120` `build_ffmpeg_argv`),
  `write_podcast_metadata()`, `list_episodes()`,
  `upload_episode()`. CLI: `python -m tradefarm.render.podcast
  {compose,upload,list,script} <args>`.
- **`src/tradefarm/render/pipeline.py`** —
  optional new `podcast` stage (compose + upload)
  gated on `enable_podcast()`; doesn't break the
  existing 9-step flow.
- **`src/tradefarm/session/weekly_rollup.py`** —
  `write_weekly_rollup` now populates a
  `podcast: {...}` field from the on-disk
  episode file if it exists (read-on-demand,
  optional, backward-compatible with pre-0.16.0
  rollups that lack the field).
- **`src/tradefarm/tts/run.py`** — `TTSOpts`
  extended with `podcast_mode: bool = False`
  (passes `pause_ms=750` for longer section
  breaks).
- **`src/tradefarm/yt/metadata.py`** —
  `build_episode_meta()` new `kind="podcast"`
  branch (sets `category="podcast"`).
- **`src/tradefarm/orchestrator/scheduler.py`** —
  new `run_podcast_scheduler` poll loop (mirrors
  the VOD scheduler pattern at `run_vod_scheduler`).
  Fires Sat 09:00 ET once per week after the 5
  daily sessions are settled. Gated on
  `settings.podcast_enabled` (default `False` so
  the code ships dark).
- **`src/tradefarm/config.py`** — 4 new settings:
  `podcast_enabled: bool = False`,
  `podcast_tts_provider: str = "openai"`,
  `podcast_voice: str = "alloy"`,
  `podcast_fire_hour_et: int = 9`.
- **`web/src/vod/WeeklyPodcast.tsx`** (NEW,
  ~200 lines) — new VOD studio tab. Lists the
  last 4 weeks' episodes with a `<video controls>`
  player + "view on YouTube" link. Mirrors the
  layout of `RivalryWeek.tsx`.
- **`web/src/vod/VodStudio.tsx`** — new
  `{ id: "podcast", label: "Weekly Podcast",
  sub: "30-min audio" }` entry in the `SURFACES`
  array.
- **`web/src/vod/types.ts`** — new `WeeklyPodcast`
  type.
- **`web/src/api.ts`** — new `getWeeklyRollup(weekId)`
  fetcher.

### Added — replay fixtures for moment timelines

- **`src/tradefarm/orchestrator/broadcast_fixtures.py`**
  (NEW, ~135 lines) — `load_fixture()` +
  `replay_against()` + `FakeClock`. Returns
  `(moments, scheduler)` so tests can inspect
  the timeline + the resulting slot transitions.
  Skips corrupted lines with a warning; missing
  file returns `([], scheduler)` so tests can
  opt into "fixture optional" patterns.
- **`src/tradefarm/orchestrator/broadcast_recap.py`** —
  `BroadcastRecapLedger` extended with
  `record_path: Path | None = None` constructor
  arg; `record()` writes
  `json.dumps(moment.to_payload(), separators=(",", ":")) + "\n"`
  to the open file handle in append mode with
  `buffering=1` (line-buffered for `tail -f`).
  Disk write is best-effort — failed write logs
  + drops, never crashes the orchestrator.
  New `close()` method for handle teardown.
- **`src/tradefarm/orchestrator/broadcast_suite.py`** —
  `BroadcastSuite.__init__` accepts `record_path`
  + plumbs it to the ledger; `close()` calls
  `ledger.close()` after the arbiter uninstall
  (so no in-flight writes from a draining sidecar
  land on a closed file).
- **`src/tradefarm/config.py`** — new
  `broadcast_record_moments: Path | None = None`
  setting (env var for the operator).
- **`tests/fixtures/moments/`** — 3 starter
  fixtures (NDJSON, one `BroadcastMoment.to_payload()`
  per line):
    - `priority_preempt.ndjson` (6 lines) — exercises
      `_preempt_lower_priority`
    - `cooldown_collision.ndjson` (5 lines) —
      exercises ledger dedup, not scheduler
    - `queue_overflow_8.ndjson` (35 lines) — exercises
      `_trim_queue` with `max_queue_size=8`; 2
      priority-80 + 5 priority-60-70 + 28
      priority-40-50
  Plus a `README.md` per-fixture doc.
- **`tests/orchestrator/test_broadcast_fixtures.py`**
  (NEW, ~430 lines, 19 tests) — `load_fixture` +
  `replay_against` against all 3 fixtures;
  FakeClock-based TTL tests.
- **`tests/orchestrator/test_broadcast_recap.py`** —
  +3 `record_to_disk` tests (happy path,
  append-across-instances, swallow-IO-errors).
- **`tests/orchestrator/test_broadcast_suite.py`** —
  +3 tests (record_path plumbed, stop closes
  handle, close idempotent).
- **`tests/conftest.py`** — new `pinned_vod_today`
  fixture (pins runtime clock to 2026-08-04
  17:00 ET, post-close, so the VOD scheduler's
  per-day idempotency check is deterministic).
  Plus the existing `record_path` + `fake_clock`
  fixtures (Dev A).

### Fixed — pre-existing test carryover

- **`tests/orchestrator/test_vod_scheduler.py`** —
  3 tests (`test_scheduler_skips_when_todays_run_already_done`,
  `test_scheduler_skips_when_todays_run_in_flight`,
  `test_scheduler_idempotency_uses_live_today`)
  had a date-constant bug: they hardcoded
  `2026-08-04 17:00 ET` as "today" but the
  scheduler's `_maybe_fire_vod_run` uses
  `runtime.clock.now_utc()`. By 2026-08-05, the
  scheduler thought "today" was the 5th and
  fired despite the pre-existing 4th row, breaking
  the `assert fired is False` invariant. Fixed
  by adding the new `pinned_vod_today` fixture
  to all three tests' arg lists — same pattern
  the 0.11.0 carryover fix used for the sibling
  `is_market_closed_for_n_minutes(5)` test.

### Fixed — cross-cutting mypy errors in `podcast.py`

- **`src/tradefarm/render/podcast.py:232`** — the
  Anthropic SDK's `msg.content` is a union of
  `TextBlock | ThinkingBlock | RedactedThinkingBlock
  | ToolUseBlock | ...`; mypy rejected the
  unconditional `.text` access. Added
  `hasattr(b, "text")` narrowing.
- **`src/tradefarm/render/podcast.py:594`** —
  Pillow moved `LANCZOS` to `Image.Resampling.LANCZOS`
  in 9.1. `getattr(_PILImage, "Resampling", _PILImage).LANCZOS`
  for forward + backward compat.

### Operational notes

- **861 → 921 tests pass** (+60). Breakdown:
  broadcast_fixtures: +19, broadcast_recap: +3,
  broadcast_suite: +3, daily_recap_scheduler: +4,
  recap_extras: +2, admin_recap_push: +1,
  weekly_rollup_podcast_field: +1, podcast_compose: +1,
  podcast_script: +1, vod_scheduler: 0 (carryover
  fix only). 8 skipped (unchanged from 0.15.0).
- **No `SCHEMA_VERSION` bump** — `CREATE TABLE IF NOT EXISTS`
  is idempotent.
- **5 new env vars** (all with safe defaults):
  `daily_recap_enabled=True`, `broadcast_record_moments=None`,
  `podcast_enabled=False`, `podcast_tts_provider="openai"`,
  `podcast_voice="alloy"`, `podcast_fire_hour_et=9`.
- **Web prod bundle**: 360 KB → 373 KB / 108 KB
  → 107.86 KB gzipped (WeeklyPodcast tab + new
  api methods; gzipped size *decreased* slightly
  due to better compression of the new content).
- **`docs/broadcast_os.md`**: milestone 3 marked
  shipped (2026-08-05). All three Broadcast OS
  milestones are now closed.
- **New research docs** (shipped under
  `docs/research/`, committed):
    - `recap-scene.md` (19.5 KB)
    - `podcast-format.md` (21.3 KB)
    - `replay-fixtures.md` (22.9 KB)
- **Visual QA pause** — please verify (a) the
  4pm ET recap scene fires on the next trading
  day close, (b) the dashboard's "Push 4pm recap"
  button works, (c) the Weekly Podcast tab
  renders in the VOD studio. The first two
  require a 4pm ET wall-clock window; the third
  is a static UI check.

---

## [0.15.0] — 2026-08-05

A "stream UI migration to canonical `broadcast_moment`"
release. The backend Broadcast OS scheduler
(`broadcast_scheduler.py`), arbiter
(`broadcast_os.py:install_broadcast_arbiter` +
`publish_broadcast_moment` with `broadcast_slot` fan-out),
and producers (`auto_director.py`, `streak_watcher`) shipped
in round 8 — 0.15.0 is the stream-side counterpart: the
`broadcast_moment` case in `useStreamCommands.ts` now
routes `macro_burst` / `lower_third` outputs to the
existing macro/banner slots via pure mappers, with a
1.5s id-keyed dedup ring so the canonical-then-legacy
fan-out from `publish_broadcast_moment(emit_legacy=True)`
doesn't double-fire the same slot. Closes `docs/broadcast_os.md`
milestone 2.

### Changed — canonical `broadcast_moment` drives stream visuals

- **`stream/src/hooks/broadcastMomentMappers.ts`** (NEW) —
  pure functions `broadcastMomentToMacroFire(payload, firedAt)`
  and `broadcastMomentToBanner(payload, shownAt)` that
  translate a `BroadcastMomentPayload` to `MacroFireState`
  and `BannerState` respectively. Both return `null` when
  the payload's `outputs` array doesn't include the
  matching output name, or when the payload's id/title
  fails validation. The 8s default TTL on the banner slot
  matches the legacy fallback.
- **`stream/src/hooks/useStreamCommands.ts`** — the
  `broadcast_moment` case in the WS event switch now
  records the moment id in a `Map<id, timestamp>` dedup
  ring and routes the macro/banner slots through the
  new mappers. The legacy `stream_macro_fired` branch
  consults the same ring and short-circuits if the
  canonical event fired the same id within 1.5s (the
  typical gap between the canonical and the
  `emit_legacy` fan-out in the same WS burst). The
  legacy `stream_banner` branch is idempotent (no id
  in payload, but `setBannerSafe` resets the same
  TTL timer with the same value) so it stays
  pass-through. Stale map entries are pruned
  on every record so the ring stays bounded under
  long sessions.
- **`docs/broadcast_os.md`** — milestone 2 marked shipped
  (2026-08-05). Milestone 3 (replay fixtures for moment
  timelines) is the next research target.

### Carryover from 0.14.0

The active queue from `dev/feature-backlog.md` (items 1, 5, 6, 7)
was closed by 0.14.0 + earlier rounds. The audit-followup
quick-wins list (both backend and frontend) is now
exhausted. 0.15.0 is the first post-audit release.

### Operational notes

- **861 → 861 tests pass.** No new test files this release
  (the change is React-hooks glue; the existing `tsc --noEmit`
  gate plus the established `uv run pytest` Python suite
  cover the move).
- **No DB schema changes.** `SCHEMA_VERSION` still at 4.
- **No new env vars.** The new code path is gated on the
  same `broadcast_moment` event the backend already emits.
- **Visual QA pause** — please verify the macro burst +
  lower-third still fire as expected on a live `big_win`
  moment (e.g. promote an agent to Senior). The dedup ring
  is keyed on `moment.id` and the window is 1.5s, so a
  single canonical + legacy pair should yield exactly one
  `setMacroFireSafe` call; any pre-existing `stream_banner`
  / `stream_macro_fired`-only backends still work because
  the legacy branches remain live.

---

## [0.14.0] — 2026-08-05

A "dashboard UX quick wins" release. The active queue from
`dev/feature-backlog.md` (tick countdown ring, equity
sparkline, open-positions sparkline strip, API spend
widget, keyboard map) was already shipped in earlier
rounds — 0.14.0 closes the two remaining real gaps: an
operator-controllable daily LLM spend cap dial in the
admin form, and `T` (manual tick) + `A` (open admin) global
shortcuts documented in the keyboard map. Plus a 5-test
carryover fix: pre-existing `render_session` unit tests
were failing when the stream Vite wasn't running because
the round-9 liveness probe runs before the test's
expected error path — the tests now pass `_probe=False`
to bypass the live dependency. 861 tests pass (no new
tests; 5 pre-existing failures fixed).

### Added — daily LLM spend cap dial

- **`web/src/components/AdminModal.tsx`** — new
  "Daily LLM budget ($X/day)" row in the Tuning section.
  Field binds to `llm_daily_budget_usd` on `AdminConfig`
  + `AdminPatch`; operator can dial the cap from 0
  (disables the cap) up to whatever they want. The
  backend's `runtime.llm_budget` module already enforced
  this — the form just wasn't exposing it.
- **`web/src/components/ApiSpendWidget.tsx`** — the
  "Est. Since Boot" + cap progress bar now read the cap
  from the live `/admin/config` SWR feed (refresh 30s) so
  the gauge updates when the operator changes the dial.
  When the cap is 0 the gauge stays at 0% and reads
  "no cap configured — set one in Admin → Tuning" so the
  operator isn't left wondering why the bar is empty.
- **`web/src/api.ts`** — `llm_daily_budget_usd?: number`
  on `AdminConfig` + `AdminPatch` (optional because older
  backends might not return the field).
- **`web/src/dash/data.ts`** + **`web/src/dash/types.ts`**
  — added the field to the `DEFAULT_ADMIN_CONFIG` and
  `DashAdminConfig` types so the form's initial state
  matches the live backend.

### Added — global keyboard shortcuts

- **`web/src/App.tsx`** — `T` (manual tick) and `A`
  (open Admin modal) global shortcuts, wired in a
  small `useEffect` with the same editable-target guard
  as the existing `?` (keyboard map) handler. Shift+T
  and Shift+A are intentionally NOT bound so the
  shortcuts can't fire on accidental caps-lock.
- **`web/src/components/KeyboardMapOverlay.tsx`** —
  expanded `SHORTCUTS` from 2 groups to 3:
  - Global: Ctrl+K, ?, T, A, Esc
  - Command palette: arrows, Enter, Esc
  - Admin modal (when open): Esc, Save button
  The new "Admin modal" group documents that Esc closes
  without saving (matching the existing `useEffect`
  escape handler) and the Save button has no shortcut
  (deliberate — the Admin form uses a debounced PATCH
  with masked-secret guards, not a hotkey).

### Fixed — render_session unit tests bypass stream probe

- **`tests/render/test_headless.py`** + **`tests/test_audit_fixes.py`** —
  5 pre-existing tests that called `render_session()`
  directly were failing when the stream Vite wasn't
  running, because the round-9 liveness probe runs
  synchronously at the top of `render_session` and
  raises `RuntimeError` on connect timeout — before the
  tests' expected error paths (missing beats,
  all-skipped, path traversal). Each of the 5 tests
  now passes `_probe=False` to bypass the live
  dependency. The escape hatch has existed since round
  9; the tests just predated it.

### Carryover — already shipped

- **Stream `TopTicker` tick countdown ring** — shipped
  in round 7. The radial SVG progress + mm:ss label is
  wired to `auto_tick_interval_sec` from `/admin/config`
  and `account.last_tick_at` (see
  `stream/src/components/TopTicker.tsx:171-237`).
- **Stream `TopTicker` equity sparkline** — shipped in
  round 7. 30-tick rolling buffer of `account.total_equity`
  rendered as an inline SVG polyline
  (`TopTicker.tsx:36-48`).
- **Dashboard open-positions sparkline strip** — shipped
  in round 7. One card per symbol with mark, qty, P&L
  + a 20-tick sparkline that builds over time
  (`web/src/components/PositionsSparklineStrip.tsx`).
- **API spend widget** — shipped in round 7
  (`web/src/components/ApiSpendWidget.tsx`). 0.14.0
  adds the operator-controllable cap dial (above).
- **Keyboard map** — shipped in round 7
  (`web/src/components/KeyboardMapOverlay.tsx`). 0.14.0
  adds the T/A shortcuts + Admin modal group (above).
- **861 → 861 tests pass.** No new test files; 5
  pre-existing failures fixed.
- **No DB schema changes.** `SCHEMA_VERSION` still at 4.
- **No new env vars.**

---

## [0.13.0] — 2026-08-05

A "frontend audit followup" release. Closes the remaining
post-0.10.0 frontend audit-followup items. The two
operator-visible changes are: (1) the Broadcast panel's
audio + cadence controls stay clickable when the stream
heartbeat goes stale (the OfflineWarning banner is enough
to flag the situation — greying out the controls was a
double-fault) and (2) the heavy mock-data fixtures in
`web/src/vod/data.ts` and `web/src/dash/data.ts` are
gated behind `import.meta.env.DEV` so they don't ship in
the production bundle. Several other audit items
(RecentFillsRail age label, single WS per tab, a11y pass
on modals, 800ms heartbeat removal) were already shipped in
prior rounds — ROADMAP now reflects that. 861 tests pass
(no new test files this release; the changes are
type-checked + production-build-verified).

### Changed — dev-only mock data

- **`web/src/vod/data.ts`** — heavy exports (VOD_AGENTS,
  BEATS, PIPELINE, DAY_SUMMARY) now return `[]` /
  empty-shell values in production builds. The 3 dev
  presets that the studio reads on the "mock" toggle
  (when the operator is testing without a backend) still
  work — they're just stripped from the prod bundle. Vite
  tree-shakes the dev branch based on the static
  `import.meta.env.DEV === 'false'` literal, so the
  production bundle is the 360 KB / 108 KB gzipped it
  would be without the fixtures.
- **`web/src/dash/data.ts`** — same pattern. EPISODES,
  STORYLINES, POOL_HISTORY, LB_HISTORY, and the
  `anthropic_api_key: "••••GH8X"` placeholder in
  DEFAULT_ADMIN_CONFIG all return empty / redacted in
  production. The form's live `/admin/config` fetch
  populates the real values; the dev preset is a
  development convenience.
- **`web/src/vite-env.d.ts`** — new file with
  `/// <reference types="vite/client" />` so TypeScript
  recognises `import.meta.env.DEV` in the gated exports.

### Fixed — Broadcast controls stay live when stream goes stale

- **`web/src/components/broadcast/BroadcastAudioSection.tsx`**
  and **`BroadcastCadenceSection.tsx`** — both had
  `const disabled = !isOnline` greying out the audio
  toggle + cadence slider whenever the stream heartbeat
  went stale. The BroadcastPanel already renders an
  `OfflineWarning` banner at the top when offline (see
  `web/src/components/broadcast/OfflineWarning.tsx`,
  shipped in round 7), and the backend's command queue
  handles offline gracefully + surfaces failures via the
  per-section `err` display. So greying out the controls
  was a double-fault: operator saw the warning + a slate
  of disabled buttons, and the disable state actively
  prevented them from queuing a cadence change for when
  the stream reconnects. The `isOnline` prop is dropped
  from both sections; the warning banner alone flags the
  situation.

### Carryover

- **861 → 861 tests pass.** No new test files; changes
  are TS-checked + production-build-verified.
- **No DB schema changes.** `SCHEMA_VERSION` still at 4.
- **No new env vars.**
- **ROADMAP cleanup**: most of the "frontend audit
  followup" items in the ROADMAP were already shipped
  across rounds 7-11. The RecentFillsRail age-label fix
  (round 7), the single-WS-per-tab via context provider
  (round 7), the a11y pass on AdminModal + BacktestModal
  (rounds 4-7), and the 800ms heartbeat removal (rounds
  10-11) all landed in prior commits. 0.13.0 closes the
  two remaining real gaps.

---

## [0.12.0] — 2026-08-05

A "backend audit followup" release. Closes the remaining
post-0.10.0 backend audit-followup items that survived
rounds 6-8. The two highest-value changes are the shared
httpx-client migration to the four LLM/YT hot paths (one
TCP/TLS session now spans the entire 4-call YT upload
sequence, including the 100+ chunk PUT) and the
audience-coordinator pin-queue refactor that closes a
double-publish race when an operator hits approve + reject
on the same request id concurrently. 861 tests pass (up
from 848).

### Changed — shared httpx client (round-5 AA followup)

- **`commentary_loop.py:436` MiniMax path now uses the shared
  client + retry helper**. The 45s Bloomberg-style commentary
  tick used to spin a fresh `httpx.AsyncClient` per call (TLS
  handshake + connection-pool init every 45s). Now it shares
  the same keepalive + 5xx/429 retry behaviour as
  `llm_providers.MinimaxProvider.decide` (round 5 AA). Three
  new tests in `test_commentary_loop.py` drive the
  `_commentary_completion` MiniMax path through a recording
  stub of the shared client.
- **`tts/run.py:119` ElevenLabs path migrated**. The provider
  used to instantiate its own client per line — every line of
  every episode paid a fresh handshake. Now it shares the
  same keepalive + retry behaviour. The 4xx path stays
  non-retryable: a 400 from ElevenLabs (bad voice id) records
  the line in `result.failed` and the chain moves on, never
  blocking the run on a permanent error. Three new tests in
  `test_run.py` cover the happy path, 5xx-retry, and 4xx-no-
  retry.
- **`yt/upload.py` 4 callsites migrated**: `refresh_access_token`,
  `_initiate_resumable_upload`, `_put_video_bytes`,
  `_set_thumbnail`. The highest-value target is the chunked
  PUT (300s per-chunk timeout, 100+ chunks per upload) — the
  keepalive now spans the whole chunked PUT instead of being
  re-established every 8 MiB. Three new tests in
  `test_upload.py` cover each callsite's shared-client use.
- **Migration note**: `tests/yt/test_put_video_bytes.py` was
  updated to patch `up.get_shared_client` instead of
  `httpx.AsyncClient` (the real `httpx.AsyncClient` is no
  longer called inside the chunked PUT body).

### Fixed — audience race + deque O(N) rebuild

- **`orchestrator/audience.py:347` — pin-queue dict refactor +
  asyncio lock**. The previous code held a `deque` for
  FIFO ordering + a `dict` for O(1) id-lookup, then rebuilt
  the deque O(N) on every approve/reject. The new code uses
  a single insertion-ordered `dict` (Python 3.7+ guarantees
  order) and pops by id in O(1). The approve + reject methods
  are now guarded by a lazy-initialised `asyncio.Lock` that
  closes a double-publish race: two concurrent operator
  approvals of the same id (or approve+reject of the same id
  from a misbehaving UI) used to both pass the `None`-check
  on a stale view of the dict, double-publishing
  `audience_pin_resolved`. The lock serialises the pop so
  exactly one path wins. Three new tests in `test_audience.py`
  cover the dict order, the approve+reject race, and the
  cap-eviction path.

### Carryover

- **848 → 861 tests pass.** 13 new tests, no removals.
- **No DB schema changes.** `SCHEMA_VERSION` still at 4.
- **No new env vars.**
- **ROADMAP cleanup**: the 16 "audit-followup quick wins" in
  the ROADMAP "Now" section are mostly already shipped
  across rounds 5-8. 0.12.0 closes the two remaining
  backend items (the shared-httpx migration followup + the
  audience race). The remaining unfixed items in the list
  (a11y pass, single-WS-per-tab, etc.) are frontend — see
  0.13.0.

---

## [0.11.0] — 2026-08-05

A "TTS env wiring + Intern Watch / Rivalry Week live-mode" release.
Three small but operator-visible wins: the TTS step is now
auto-included in the default pipeline when the operator has a
provider key in the env (no more forgetting `--include-tts`), the
Intern Watch and Rivalry Week studio surfaces read from real
session data via `/vod/{id}/extras` instead of the synthetic
fallback, and Session Control's live strategy breakdown finally
shows the full 8 buckets instead of the 3-bucket legacy view.

### Added — TTS env wiring

- **`should_auto_include_tts` plumbed into the pipeline HTTP
  wrapper** (`src/tradefarm/api/pipeline.py:_resolve_enabled`).
  When the operator has `ELEVENLABS_API_KEY` or `OPENAI_API_KEY`
  in the env AND `vod_tts_auto_include=true` (the default), the
  chain's default enabled set now includes `tts` automatically.
  The HTTP request body's `include_tts=False` is the explicit
  override and always wins; `include_tts=True` is the loud
  override that always wins. The pattern mirrors the "you have
  creds → stop remembering the flag" UX of provider-backed
  features.
- **`available_providers` / `has_tts_creds` helpers in
  `tradefarm.tts.run`** (added in this release). `available_providers()`
  lists the providers with at least one env key present
  (ordered `elevenlabs` → `openai`, matching `build_provider`'s
  auto selection — `available_providers()[0]` is the same pick
  the auto path takes). `has_tts_creds()` is a thin
  `bool(available_providers())` wrapper used by the auto-include
  decision. The `silence` provider is intentionally NOT in
  `available_providers()` — it has no key to check.
- **`vod_tts_auto_include` setting** (`src/tradefarm/config.py`).
  Default `True`. Operators who explicitly want NO tts can set
  `vod_tts_auto_include=false` in `.env`, OR pass
  `include_tts: false` in the HTTP request body. The request-body
  flag always wins — the env flag is a default, not a forced
  override.

### Added — Intern Watch / Rivalry Week live-mode wire

- **`useVodLiveData` now reads `/vod/{id}/extras`**
  (`web/src/vod/data.live.ts`). The 0.10.0 release shipped the
  endpoint but the live data hook returned `lowest_ranks: []`
  and `rivalries: []`, leaving both studio surfaces on the
  synthetic fallback. The new SWR key `vod-extras-${sid}`
  populates both fields from the session's manifest — when the
  session has a manifest, the surfaces show the real cast list
  and the real weekly rivalries instead of the mock.
- **404 is treated as "no data" rather than "error"**. The
  fetch returns `null` on non-2xx; SWR's `error` stays clean so
  the studio's live indicator doesn't flash red on a fresh
  session. The surfaces still fall back to the synthetic
  head-to-head when no session is loaded.

### Fixed — `useVodSessionLive` 3-bucket carryover

- **Session Control now aggregates all 8 strategy buckets**
  (`web/src/vod/useVodSessionLive.ts:makeSummary`). The
  pre-0.11 hook mapped every non-LSTM/non-LLM live agent into
  the legacy 3-bucket "momentum" slot and padded the other 5
  buckets with zero rollups — the live strategy breakdown
  always showed a giant "momentum" bar with 5 empty bars
  alongside. The new `mapStrategy` mirrors
  `data.live.ts`'s 8-bucket mapping (`momentum_12_1`,
  `mean_reversion_bb`, `rsi2`, `donchian_breakout`,
  `pairs_zscore`, `momentum`, `lstm`, `llm`), and `makeSummary`
  aggregates across all 8. The `StrategyLegacy` type is still
  declared in `web/src/vod/types.ts` for any future back-compat
  caller but no longer shapes the live breakdown.

### Tests

- **`tests/tts/test_run.py`**: 10 new tests for
  `available_providers` / `has_tts_creds` /
  `should_auto_include_tts`. Cover the empty case, single-key
  case, both-keys ordering, the operator-opt-out flag, and
  the matrix of `vod_tts_auto_include` × `has_tts_creds`.
- **`tests/api/test_pipeline_router.py`**: 5 new tests for the
  HTTP wrapper's auto-include behavior. Cover the
  `ELEVENLABS_API_KEY` + default-flag path, the no-creds path
  (tts NOT in enabled), the loud `include_tts=True` override
  that bypasses env, the `OPENAI_API_KEY`-only path, and the
  `vod_tts_auto_include=False` opt-out path.
- **`tests/orchestrator/test_vod_scheduler.py`** carryover fix:
  the `test_scheduler_idempotency_allows_refire_if_live_today_false`
  test pinned the runtime clock to a post-close wall time via
  `set_replay_now` / `reset_replay_now` so the
  `is_market_closed_for_n_minutes(5)` time gate is deterministically
  True. The test was the canary for a 0.9.0 carryover — the
  other 8 scheduler "skip" tests asserted `fired is False` so
  the time-gate failure was silent; this test asserts
  `fired is True` so the same wall-clock drift surfaced here.
  Now passes deterministically regardless of when the developer
  runs the suite.

### Carryover

- **833 → 848 tests pass.** 15 new tests + 1 newly-passing
  scheduler test, no removals.
- **No DB schema changes.** `SCHEMA_VERSION` still at 4.
- **No new env vars.** `vod_tts_auto_include` joins the existing
  `vod_*` env var family.

---

## [0.10.0] — 2026-08-04

A "weekly formats ship + autonomy hardening" release. The
research doc's top 3 weekly episode formats now have at
least one studio surface: **Intern Watch** (12-min
Friday) and **Rivalry Week** (7-min format) are full
studio surfaces, with a new `/vod/{id}/extras` endpoint
that surfaces the 0.9.0 manifest extras. **Asset
archival** lands as a best-effort tar-on-done
(`vod_archive_path`), so a destroyed local box no
longer takes the source artifacts with it. 833 tests
pass (up from 823 at 0.9.0).

### Added — VOD studio weekly formats

- **Intern Watch surface** (`commit 24e5943`,
  `web/src/vod/InternWatch.tsx`). 12-min Friday format
  that profiles the 5 lowest-cash intern agents at
  session start. Reads `manifest.lowest_ranks` (a 0.9.0
  manifest extra — full cast list with id, name, rank,
  rank_index, strategy, starting_capital). Falls back
  to a synthetic cast from the existing agents list
  when the manifest predates 0.9.0. New `InternCastRow`
  type in `web/src/vod/types.ts`.
- **Rivalry Week surface** (`commit 24e5943`,
  `web/src/vod/RivalryWeek.tsx`). 7-min format that
  profiles the two agents with the highest opposite-side
  count over the past 5 sessions, side-by-side with
  their per-side PnL. Reads `manifest.rivalries`
  (a 0.8.0 manifest extra). New `RivalryRow` type in
  `web/src/vod/types.ts`.
- **`GET /vod/{session_id}/extras`** (`commit 24e5943`,
  `src/tradefarm/api/vod.py`). Returns the four 0.9.0-era
  manifest extras (`rivalries`, `lowest_ranks`,
  `strategy_rollup`, `interns_under_watch`) as one JSON
  payload so the Intern Watch + Rivalry Week surfaces
  can pull all three with a single fetch. The
  InternWatch + RivalryWeek studio fall back to mock
  data when this fetch fails (the studio's
  fault-tolerance pattern is "show something rather
  than nothing").
- **VOD studio tab nav extended** (`commit 24e5943`).
  Two new tabs after Episode Review: "Intern Watch"
  (`#vod-studio/interns`) and "Rivalry Week"
  (`#vod-studio/rivalries`). Tab count goes 4 → 6; the
  header still collapses cleanly at 1280px and the URL
  hash routing covers the new ids.

### Added — Autonomy hardening

- **Asset archival on run-done** (`commit 648103b`,
  `src/tradefarm/render/archive.py`). On
  `run.status == "done"` (and optionally on `failed`),
  the session dir is tar-balled (gzip, excluding
  `clips/` and `intermediates/`) to
  `<archive_root>/<YYYY-MM-DD>/<sid>.tar.gz`. Wired
  from the HTTP wrapper and the orchestrator's
  scheduler; both paths share the same fire-and-forget
  pattern. New env vars in `config.py`:
  - `vod_archive_path: str = ""` — empty = no-op (the
    default — operators opt in)
  - `vod_archive_on_failure: bool = False` —
    diagnostic state backup for failed runs
- CLI: `python -m tradefarm.render.archive <session_id>
  --out <dir>` for ad-hoc archival from a dev box.

### Tests + ops

- +10 active tests (823 → 833). 1 new test file:
  - `tests/render/test_archive.py` (7) — happy path,
    skip-on-no-root, skip-on-failed, missing src,
    temp-file cleanup on failure, nested archive
    root, clips/intermediates exclusion
  - 3 new tests on `test_vod_assets.py::get_manifest_extras`
- Full gauntlet: 833 passed, 8 skipped. `ruff`,
  `mypy --strict`, `web tsc --noEmit`, `stream tsc
  --noEmit` all clean.

### Known carryovers (deferred to 0.11)

- TTS still opt-in via `--include-tts`; needs a real
  ElevenLabs or OpenAI key for the `auto` default to
  produce VO. The renderer + chain are wired; the
  missing piece is operator-supplied credentials.
- Shorts `crop=ih*9/16:ih` smart-crop is unit-tested
  for the contract but **not visually verified**
  against a real stream clip with the LLM-reason
  lower-third. 30s manual QA on the next render.
- `web/src/vod/useVodSessionLive.ts` still uses the
  3-bucket legacy `StrategyLegacy` for the Session
  Control view. The 8-bucket `data.live.ts` hook
  carries the wider view; the legacy hook is a
  cosmetic carryover.

---

## [0.9.0] — 2026-08-04

A "tighten the autonomy loop" release. The 0.8.0 known gaps are
addressed one-by-one: the scheduler's power-loss race is closed
(`live_today` flag), the headless renderer captures a 9:16 short
or a recap clip on the same loop, the recap endpoint is
replay-aware, every published video gets a real thumbnail, the
VOD studio's `interns_under_watch` data is now a full cast
list, the pipeline persists per-step timings, and the
weekly Strategy Wars beat + rollup infra ship. 823 tests pass
(up from 690 at 0.8.0). No breaking schema changes.

### Fixed — Carryovers from 0.8.0

- **Scheduler power-loss race** (`live_today` column,
  `commit 98bb18f`). The 0.8.0 scheduler's per-day idempotency
  check could be fooled by a previous process that died mid-run:
  a `status='running'` row from the dead process looked identical
  to a fresh run. The 0.9.0 fix adds a `live_today` boolean column
  on `pipeline_runs` (default `True`); the orchestrator's
  `start_background()` now flips every `live_today=True` row
  whose `date` is not today to `False` BEFORE the scheduler
  loop starts, so a fresh process can only see its own
  in-flight runs.
- **Recap scene replay** (`commit 412186e`). The 0.8.0
  headless renderer skipped the recap scene because
  `/api/recap/today` didn't accept `?session_id=&at=`. The 0.9.0
  endpoint accepts the same query params the other replay
  endpoints accept; the `build_recap_from_manifest` helper
  folds the named manifest's events up to `at` and shapes
  the recap payload from the folded `AgentSnapshot`s. The
  default `skip_kinds` no longer excludes `recap`, and
  `SCENES_WITH_REPLAY_SUPPORT` now includes it. Last beat
  of every VOD is the recap again.
- **Per-step timing roll-up** (`commit 1edfed5`). The 0.8.0
  `pipeline_runs` table only tracked run-level `started_at`
  / `finished_at`. The 0.9.0 `step_timings_json` column stores
  the per-step `{step, started_at, finished_at,
  duration_sec, status}` roll-up. The pipeline runner
  appends incrementally; the HTTP wrapper and the
  orchestrator's scheduler both persist on terminal state.
  A mid-run crash leaves partial timings for the
  post-mortem.
- **Rivalry beat duration** scales with the 90-min window
  (`commit 3fdfd7c`). The 0.8.0 rivalry beat had a fixed
  34-second `duration_sec`, so the headless renderer
  captured only ~0.6s of real-time content at 60x replay
  speed — not enough to show the full back-and-forth. The
  0.9.0 beat's `duration_sec` is `max(34, window_min)` (1s
  of capture per minute of window), so a 90-min rivalry
  gets a 90s clip.

### Added — VOD studio

- **9:16 Shorts capture path** (`commit 8e5f74f`,
  `src/tradefarm/render/shorts.py`). 465 lines, ffmpeg
  smart-crop from the existing 16:9 headless clips. Composes
  the top N beats (default 3) into per-beat shorts. CLI:
  `python -m tradefarm.render.shorts <session_id> --top 3`.
- **Thumbnail pipeline step** (`commit 8e5f74f`,
  `src/tradefarm/render/thumb.py`). A new `render.thumb` step
  between `mix` and `metadata` runs ffmpeg against
  `silent_reel.mp4` to extract a 1280x720 JPEG at the 1-second
  mark (16:9 letterbox for vertical pilot footage). Every
  published video now gets a real thumbnail instead of
  YouTube's auto-pick.
- **Weekly rollup infra** (`commit 9cb7d83`,
  `src/tradefarm/session/weekly_rollup.py`). `compute_weekly_rollup(week_id)` walks
  every session manifest in the trading week and sums the
  per-day `strategy_rollup` into a weekly shape (per-strategy
  pnl + agent count + fill count, deduped rivalries, pool
  pnl + pnlPct). Persists to
  `<sessions_dir>/weekly/<week_id>/rollup.json`. The
  Strategy Wars detector reads the previous week's rollup to
  emit "vs last week" deltas.
- **Strategy Wars beat detector** (`commit 9cb7d83`,
  `session/beats.py:_score_strategy_war`). Reads the
  manifest's `strategy_rollup` (written by
  `session/run.py` at session close in 0.8.0) and emits a
  `kind="strategy_war"` beat at close. When the previous
  week's rollup is provided, the headline includes the
  winner's "vs last week" delta. Maps to the `strategy`
  scene (already in `SCENES_WITH_REPLAY_SUPPORT`). New
  kinds in `SCENE_FOR_KIND`, `DURATION_FOR_KIND`,
  `KIND_PRIORITY`.
- **Intern Watch full cast list** (`commit 07b363c`,
  `session/run.py:_snapshot_intern_cast`). The 0.8.0
  `interns_under_watch: list[int]` is upgraded to
  `lowest_ranks: list[dict]` with `{agent_id, name, rank,
  rank_index, strategy, starting_capital}` per row. The
  legacy `interns_under_watch: list[int]` field is kept as
  a derived list of agent_ids for back-compat.

### Tests + ops

- +133 active tests (690 → 823). 7 new test files:
  - `tests/api/test_ws_replay.py` (11) — headless URL →
    stream URLSearchParams → WS replay handshake → manifest
    envelope chain
  - `tests/render/test_shorts.py` (15)
  - `tests/api/test_recap_replay.py` (6)
  - `tests/orchestrator/test_vod_scheduler.py` (5) +
    `live_today` follow-ups
  - `tests/render/test_thumb.py` (9)
  - `tests/render/test_pipeline_retry.py` (8)
  - `tests/session/test_weekly_rollup.py` (17)
- Migration: `SCHEMA_VERSION` bumps 3 → 4 for the new
  `step_timings_json` column. Idempotent ADD COLUMN
  guards mean re-running `init_db()` is a no-op.
- Full gauntlet: 823 passed, 8 skipped. `ruff`,
  `mypy --strict`, `web tsc --noEmit`, `stream tsc --noEmit`
  all clean.

### Known carryovers (deferred to 0.10)

- TTS still opt-in via `--include-tts`; needs a real
  ElevenLabs or OpenAI key for the `auto` default to produce
  VO.
- Asset archival on terminal state (tar the session dir
  minus clips + intermediates, push to a backup path) — not
  shipped; a destroyed local box still loses the source
  artifacts of every published reel.
- Shorts `crop=ih*9/16:ih` smart-crop is unit-tested for
  the contract but **not visually verified** against a
  real stream clip with the LLM-reason lower-third.
- `web/src/vod/useVodSessionLive.ts` still uses the 3-bucket
  legacy `StrategyLegacy` for the Session Control view
  (works fine; just not as granular as the 8-bucket live
  view). Cosmetic carryover; the new `data.live.ts` hook
  surfaces the wider 8-bucket view.

---

## [0.8.0] — 2026-08-04

A reach release: the operator's "run a day" command now persists, the
VOD studio's prototype fixture matches the live 7-strategy world, and
the headless renderer has a 9:16 capture path for YouTube Shorts. 773
tests pass (up from 690 at 0.7.0). Two research docs under
`docs/research/` capture the design thinking.

### Added — Autonomy plumbing (round 8)

- **DB-backed pipeline run state** (`494279b`). The in-memory `_RUNS`
  deque in `api/pipeline.py` is now a read-through cache over a new
  `pipeline_runs` SQLAlchemy table (12-char hex id, status, ring-buffer
  `last_lines_json`, indexed by `session_id` and `date`). Restart-safe;
  historical run rows survive a process reboot.
- **Daily VOD scheduler loop** in `orchestrator/scheduler.py:run_vod_scheduler()`
  (`494279b`). Fires once per NYSE session, gated on
  `vod_pipeline_enabled=false` (default off), `is_market_closed_for_n_minutes(5)`,
  and a per-day idempotency check in the new `pipeline_runs` table so a
  restart on the same day doesn't re-fire. Auto-uploads as **`private`**
  with `publish_at` = next 16:30 ET; operator clicks "publish" in YouTube
  Studio. `tradefarm/market_clock.py` is the new helper for
  `is_market_closed_for_n_minutes(n)` (handles half-days, holidays,
  weekends via `pandas_market_calendars`).
- **Per-step retry + backoff** in `render/pipeline.py:_run_step()`
  (`494279b`). New `max_attempts=2` and `retry_backoff_sec=30` on
  `PipelineOpts`. Wraps `step.run(argv)` in a retry loop; only retries
  on transient-looking exceptions (`OSError`, `httpx.HTTPError`,
  Playwright errors); never retries `SystemExit` (real failure, not
  transient).
- **Stream liveness probe** in `render/headless.py:render_session()`
  (`494279b`). `httpx.get(stream_base, timeout=2.0)` once at the top of
  the loop; 2xx/3xx = pass, 4xx/5xx/HTTPError = `RuntimeError("stream
  Vite not reachable at <url>")` with a "start `cd stream && npm run
  dev`" hint. Kills the 5-min hang when the operator forgot to start
  the dev server.
- **Webhook notification on terminal state** in
  `api/pipeline.py:_fire_webhook()` (`494279b`). New env var
  `vod_notify_webhook`. Best-effort `httpx.post` on `done` (with
  `video_url`) or `failed` (with `error`). Discord / Slack incoming
  webhook / ntfy / custom — anything that accepts a JSON POST. Wired
  into both the HTTP wrapper and the orchestrator's daily scheduler.

### Added — Content unlock (round 8)

- **YouTube Shorts capture path** (`src/tradefarm/render/shorts.py`,
  465 lines, `d905723`). Mirrors the headless renderer's per-beat
  capture loop but emits `1080x1920` vertical clips. Composes the top
  N beats (default 3) into per-beat shorts via ffmpeg smart-crop from
  the existing 16:9 headless clips. CLI: `python -m tradefarm.render.shorts
  <session_id> --top 3`. Skip-recap (same constraint as `headless.py`).
  ASCII-only banners (Windows cp1252).
- **`agent_rivalry` beat detector** in `session/beats.py:_score_rivalries()`
  (`d905723`). Scans fills for `(agent_a, agent_b, symbol)` triples with
  `a.side != b.side` and `count >= 3` inside a 90-min rolling window;
  emits top 1-2 by occurrence count. Maps to the existing `showdown`
  scene (already in `SCENES_WITH_REPLAY_SUPPORT`).
- **`promotion` beat detector** in `session/beats.py:_score_promotions()`
  (`d905723`). Reads `AcademyPromotion` rows; one beat per (agent,
  from_rank -> to_rank). Demotions map to `top_loser` with the same
  metadata. Maps to `leaderboard`.
- **Manifest extras** in `session/run.py` (`d905723`). Three new keys
  on the per-day manifest JSON:
  - `rivalries: list[{a, b, symbol, count, a_pnl, b_pnl}]` — top 2
  - `interns_under_watch: list[int]` — 5 lowest-ranked `intern` IDs
    at session start
  - `strategy_rollup: dict[str, StrategyRollup]` — per-strategy PnL
    aggregate at close
  All are written post-`write_manifest()` (the dataclass itself is
  unchanged; the JSON file is the source of truth for downstream).
- **8-bucket strategy refresh** in `web/src/vod/data.ts` (`d905723`).
  `VOD_STRATEGIES` now lists all 8 strategy slots
  (`momentum`, `momentum_12_1`, `mean_reversion_bb`, `rsi2`,
  `donchian_breakout`, `pairs_zscore`, `lstm`, `llm`); the prototype
  fixture's 100 agents randomly pick from all 8. `StrategyBucket` and
  `StrategyLegacy` types in `web/src/vod/types.ts` keep the 3-bucket
  back-compat for the existing Session Control view.
- **Live data hook** in `web/src/vod/data.live.ts` (`d905723`).
  `useVodLiveData(sessionId?)` pulls `/api/agents`, `/api/account`,
  `/api/pnl/daily`, and a real session's manifest. Falls back to mock
  on any error. The VOD studio header now has a single "mock/live"
  pill that flips every surface (Beat Picker, Pipeline, Session,
  Episode Review) — previously only Session had the toggle.

### Research docs (round 8)

- `docs/research/youtube-interesting.md` (1,999 words). The 8 scene
  palette + 12 beat kinds vs 8 detector-scored kinds; the 5 new
  strategies as character gold; the sitcom-vs-Bloomberg reframe;
  Intern Watch / Strategy Wars / Rivalry Week as the top 3 weekly
  formats; shorts as the only YT acquisition channel that works for
  new channels.
- `docs/research/autonomy-pipeline.md` (2,439 words). The full 8-step
  chain mapped end-to-end; the trigger gap (orchestrator has zero
  coupling to render/pipeline modules); the dry-run-by-default
  policy decision; the 6 quick wins unblocking later autonomy work.

### Changed

- `useVodSessionLive.ts` switched to `StrategyLegacy` (3-bucket) for
  its local rollup shape; pads the 5 missing buckets with zero rollups
  so the 8-bucket `DaySummary.byStrategy` type stays total. The
  content team's `data.live.ts` is the canonical 8-bucket view going
  forward.

### Known gaps (carryover to 0.9)

- Shorts `crop=ih*9/16:ih` smart-crop is unit-tested for the
  contract but **not visually verified** against a real stream clip
  with the LLM-reason lower-third. If the LLM text gets clipped,
  fallback to a fresh Playwright loop at viewport `1080x1920` (Option
  B in the brief). Needs a 30s manual QA on the next render.
- Scheduler's per-day idempotency is robust to a clean restart but has
  a small race on a power-loss mid-run (no `live_today` flag). The
  v0.8 contract is "operator can manually re-trigger from the
  dashboard if they see the same day re-fired".
- TTS provider is still opt-in via `--include-tts`; needs a real
  ElevenLabs or OpenAI key for the `auto` default to produce VO.
- Thumbnail generation isn't a pipeline step yet (every published
  video still gets YouTube's auto-thumbnail).
- Recap scene is still excluded from replays — the last beat in
  every VOD is `closing_burst`, not the recap.

---

## [0.7.0] — 2026-08-04

A breadth release: the strategy roster grows from 3 to 7, the operator
gets per-agent toggles + a live VOD pipeline runner button, and the
headless replay path is now end-to-end tested. 690 tests pass
(up from 580 at 0.6.0); no breaking schema changes.

### Added — 5 new strategies + per-agent admin

- **Momentum 12-1** (`e062869`). 12-month return minus the most
  recent month, the Jegadeesh-Titman classic. Replaces the
  `momentum_sma20` placeholder.
- **Bollinger Bands mean reversion** (`b9db31a`,
  `mean_reversion_bb`). 20-period SMA ±2σ; enter at the band, exit
  at the SMA.
- **RSI-2 (Connors)** (`3109e84`, `rsi2`). 2-period RSI, oversold=5,
  overbought=95.
- **Donchian breakout** (`4c1c185`, `donchian_breakout`).
  20-period channel breakout; uses the *prior* 20 bars, not the
  current one (subagent flagged the spec ambiguity).
- **Pairs z-score** (`7da7b8d`, `pairs_zscore`). 14 hardcoded US
  equity pairs (`src/tradefarm/data/pairs.py`); long A on
  z < -2, exit at |z| < 0.5. Sandbox constraint: long-only.
- **Per-agent admin toggles** (`ad2ccc9`). `Agent.disabled` Boolean
  column + 3 REST endpoints (`GET /admin/agents` carries the flag,
  `POST /admin/agents/{id}/disabled`, `POST /admin/agents/disabled-bulk`)
  + an Agent Override section in the VOD admin tab.
- **Orchestrator 7-strategy rotation** (`de909a5`, `746e2d9`).
  `i % 7` slot rotation: momentum, lstm_v1, lstm_llm_v1, bb, rsi2,
  donchian, pairs. The two LSTM slots fall back to momentum when
  no model/overlay is loaded — explicit, not silent.
- 100 agents spread: 44 momentum, 14 each of bb/rsi2/donchian/pairs.

### Added — VOD studio live surface

- **Episode review live MP4 preview + working download** (`9cbf43c`).
  `<video controls poster>` against the new `/vod/{id}/reel.mp4`
  endpoint; session picker + `<a download>`. 9 endpoint tests.
- **One-shot VOD pipeline runner** (`11732fb`,
  `python -m tradefarm.render.pipeline`). 8-step chain
  (session → beats → headless → stitch → tts → mix → metadata →
  upload) with skip/force/dry-run controls, structured progress,
  and a `sink` callback so the HTTP wrapper can fan out to the WS
  bus.
- **Live pipeline runner + render button** (`f8d1ec8`). POST
  `/pipeline/run` returns a `run_id`; the VOD studio polls
  `/pipeline/runs/{id}` every 2s and shows a real `RunPanel` with
  status pill + log tail. The 10-subsystem pills merge with the
  active run when one is in flight, falling back to the mock
  subsystem counts otherwise.
- **Stream-side `?scene=` URL pin** (`f8d1ec8`). `stream/src/App.tsx`
  reads `?scene=<id>` and pins the rotator (`rotationSec=0`,
  `forceSceneId`) so the headless renderer's URL builder can lock
  a scene for capture.
- **10-card subsystem state merge** (`f1e31a8`,
  `web/src/vod/derivePipelineNodes.ts`). Pure helper that maps
  each of the 10 prototype cards to a real `tradefarm.render.pipeline`
  step (session/beats/headless/stitch/tts/mix/metadata/upload) and
  derives per-card status from the run's `last_lines` tail. The
  two prototype-only cards (script writer, thumbnail) stay in the
  grid with an honest "no matching step" note.

### Added — Replay chain coverage

- **End-to-end replay chain test** (`1ede68f`,
  `tests/api/test_ws_replay.py`, 11 tests). Pins the contract
  between `headless.build_url()` and the stream app's
  `URLSearchParams` parser; the canonical `{type, ts, payload}`
  envelope shape from `manifest_event_to_ws_envelope`; and a
  real `TestClient` WS round-trip with the in-process `/ws`
  endpoint that drives the full
  URL → handshake → `events_in_window` → envelope chain.
  Also covers path-traversal rejection, missing-manifest error
  envelope, invalid-timestamp error envelope, and
  `speed=0` (as-fast-as-possible) mode.

### Changed

- `KNOWN_STRATEGIES` now lists 7 strategies
  (`momentum_12_1`, `mean_reversion_bb`, `rsi2`,
  `donchian_breakout`, `pairs_zscore`, `lstm_v1`, `lstm_llm_v1`).
  `momentum_sma20` is kept as a back-compat alias for existing
  DB rows.

---

## [0.6.0] — 2026-06-18

A correctness-flavor release: every high-priority finding from the
2026-06 senior staff review and the round-5 audit is now landed. Money
is exact (`Decimal` end-to-end), the orchestrator is no longer a god
object, security is correct by default, and the LLM surface is
schema-validated. CI gates mypy, ruff, and ESLint. Test count: 556
passing across 72 files (up from 31 at 0.5.0).

### Added — Round 5 production polish (`1031652`, 2026-05-26)

- **Alpaca SDK offloaded to threads.** `execution/alpaca_broker.py`
  now wraps every blocking SDK call in `asyncio.to_thread` so a 500ms
  broker round-trip no longer pauses the tick loop.
- **Per-book reconciled-id LRU cap** (10k entries) so a multi-day
  broadcast can't OOM the reconciler.
- **Shared `httpx.AsyncClient` singleton** (`runtime/http.py`) with
  HTTP/2 keepalive — closed in `Orchestrator.stop_background`. Wired
  through EODHD; the two LLM-provider hot paths still need migration.
- **Daily LLM spend ceiling** (`llm_daily_budget_usd`, default 0=off;
  `runtime/llm_budget.py`). Once tripped, agents fall back to LSTM-only
  with `reason="llm budget exhausted"`. Resets at UTC midnight.
- **Prometheus metrics endpoint** `GET /metrics` exposing
  `tradefarm_llm_calls_total`, `llm_skips_total`, `llm_budget_spent_usd`,
  `llm_budget_blocked_total`, `last_tick_timestamp_seconds`,
  `notes_this_tick`, `outcomes_this_tick`.
- **Readiness endpoint** `GET /readiness` returns 503 + `failed_checks`
  when DB, scheduler, or last-tick freshness is degraded.
- **Postgres compatibility** in `storage/db.py` — dialect detection
  via `engine.dialect.name`; `ADD COLUMN` guarded with check-then-add
  and Postgres `IF NOT EXISTS`; a `schema_version` table records
  applied migrations.
- **RUNBOOK.md rewrite** for round-5 surface — fail-fast bind, secrets,
  database recovery, VOD pipeline failures, split-machine topology.
- **Author-scale test suite** — 22 new test files across
  `tests/execution/`, `tests/runtime/`, `tests/storage/`,
  `tests/audit_round*`, `tests/agents/test_llm_parse.py`,
  `tests/orchestrator/test_broadcast_*`, `tests/yt/`, `tests/tts/`,
  `tests/script/`, `tests/data/`.

### Fixed — Audit top-5 (`941150c`, 2026-06-18)

- **C1 — Flat-only invariant on `VirtualBook`.** A sell with
  `qty > held_qty` is clamped to the held position; the long→short
  "flip" path is no longer reachable. Reconciler reverses-and-reapplies
  the optimistic fill math to recover pre-fill state.
- **C2 — `broker_order_id` dedup is now live.** `record_trade(…,
  broker_order_id=)` writes the column; a second write hits the
  `uq_trades_broker_order_id` UNIQUE constraint and is swallowed
  (idempotent). Reconciler, in-tick fill, and `record_fill_atomic` all
  propagate `broker_order_id` end-to-end.
- **C3 — Fail-fast on insecure bind.** `_assert_secure_bind()` aborts
  startup if uvicorn binds a non-loopback host and `api_shared_secret`
  is empty. Refuses to expose `/admin/config`, `/tick`, `/backtest/run`
  to the LAN silently.
- **C4 — Default-safe CORS.** Loopback + Tauri only by default.
  RFC-1918 LAN ranges opt-in via `CORS_ALLOW_LAN=true`; exact
  origins via `CORS_ALLOW_ORIGINS` CSV.
- **C5 — `AgentWorldXL` 60fps loop no longer re-renders React.**
  rAF mutates `camGroupRef.setAttribute("transform", …)` and cloud
  ellipse `cx` attributes directly; zero `setState` per frame.

### Fixed — Audit #6-#10 (`0aadc52`, 2026-06-18)

- **C6 — Sidecar startup is awaited.** `BroadcastSuite` owns the
  six presentation sidecars (`AutoDirector`, `StreakWatcher`,
  `CommentaryLoop`, `PredictionsBoard`, `AudienceCoordinator`,
  `YouTubeChatPoller`) plus the broadcast arbiter. `start()` is
  awaited, so a boot-time failure propagates instead of being
  swallowed by a discarded `create_task`. `attach_crash_logger()`
  supervises every spawned loop.
- **C7 — `ScheduledMoment.state` is real.** `getattr(sm, "state",
  "active")` removed; the field is now a `Literal["active",
  "queued", "preempted"]` populated by the scheduler.
- **C8 — Migration hardening.** `_ensure_columns` is check-then-add
  with `IF NOT EXISTS` on Postgres; `_safe_index` no-ops when the
  column is missing; `schema_version` table stamped once.
- **C9 — Atomic fill persistence.** `record_fill_atomic()` writes
  the Trade row and re-syncs the agent's positions in one
  transaction, with an explicit `flush()` so the
  `broker_order_id` UNIQUE violation surfaces inside the try.
- **C10 — LLM parse validation.** Pydantic v2 `_LlmDecisionModel`
  with `Literal` enums for `bias`/`predictive`/`stance`; `size_pct`
  clamped to `[0, 0.25]`; `reason` truncated to 120 chars;
  `LlmParseError` is a distinct exception class so parse failures
  are not conflated with call failures.
- **C11 — Dead UI controls disabled.** VOD Pipeline toggles in
  `dash/Admin.tsx` and pause/abort in `vod/SessionControl.tsx` are
  all `disabled` with "coming soon" tooltips; not deleted (operator
  prefers the affordance).

### Changed — Refactor: land deferred roadmap (`be7b136`, 2026-06-18)

- **Money is `Decimal` end-to-end.** `VirtualBook.cash`,
  `avg_price`, `realized_pnl`, `qty` are all `Decimal`; inputs are
  coerced at the book boundary via `runtime/money.D()`; JSON/WS/REST
  payloads convert back to `float` at the serialization edge via
  `runtime/money.to_float()`. Sub-cent money grid (4 dp) with
  banker's rounding. Storage columns switched to
  `Numeric(20, 6, asdecimal=True)`.
- **`BroadcastSuite` extraction.** The Orchestrator is no longer a
  god object — the 6 sidecars plus the broadcast arbiter hang off
  `orchestrator._broadcast_suite`, started/stopped as a unit.
  Tests that construct bare `Orchestrator(...)` no longer pollute
  module globals.
- **CI gates mypy + ruff + ESLint.** `[tool.mypy]` block in
  `pyproject.toml`; `web/eslint.config.js` and
  `stream/eslint.config.js` (flat config); `npm run lint` in both
  frontends. CI now: ruff check + ruff format + pytest +
  `npx tsc --noEmit` + `npm run build` for both frontends.

### Documentation

- `dev/audit-findings.md` — round 5 + top-5 + #6-#10 + refactor
  added to the "Round-by-round status deltas" ledger; new gotchas
  #16-#21 cross-referenced.
- `RUNBOOK.md` — new failure-mode rows (fail-fast bind, broadcast
  slot state, LLM parse errors).
- `BACKLOG.md` — 2026-07-17 audit findings preserved.
- `REPO_REVIEW.md` / `REPO_REVIEW_NOTES.md` — senior staff review
  archived as a historical record (all 10 issues now FIXED).

---

## [0.5.0] — 2026-05-09

A broadcast-flavor release: a dedicated streaming app, a sports-style
broadcast layout, dashboard reorganization for live-show focus, full
remote control of the stream from the dashboard, and a stack of vibe
polish (day/night, weather, CRT, mascot pet, recap scene).

### Added — Stream broadcast app

- **Standalone broadcast app** at `stream/` — Tauri 2 + React 19
  fullscreen 1080p window for OBS Window Capture (`a34676c`, 2026-05-02).
  - Multi-scene rotator that cycles Hero → Leaderboard → Brain → Strategy
    on a configurable interval, with crossfade transitions and pause
    while the Admin overlay is open.
  - Hero scene with isometric Agent World XL (camera drift, parallax
    clouds, 2x sprites), left stat pillar, top/bottom tickers,
    promotion toast, template-driven commentary caption.
  - Pre-roll splash card on launch ("TradeFarm — Day N" + agents /
    equity / yesterday's close), length adjustable via Admin overlay
    (set to 0 to skip).
  - Web Audio engine — tick kicks, sonified fills (pentatonic by symbol,
    octave by side), promotion / demotion stingers. Lazy-resumed on
    first user gesture; volume + on/off live-controlled from Admin.
  - Admin overlay (Ctrl+I): backend URL, ticker speed, pre-roll length,
    scene rotation interval, audio toggle/volume + Quit App / Exit
    Fullscreen actions.
  - Settings persisted via Tauri FS plugin, localStorage fallback for
    browser dev mode.
  - Defensive URL handling for the Tauri custom-protocol host so
    REST/WS resolve to `127.0.0.1:8000` instead of the SPA index.html.
  - Native `tradefarm-stream.exe` (~10 MB) plus MSI and NSIS installers.
- **Portfolio-level exit rules** in `risk/manager.py` — stop-loss,
  take-profit, time-stop, trailing stop applied per agent (`fabcfc2`,
  2026-04-21).
- **Agent World panel** in the dashboard — IMMT-style isometric diorama
  with rank sprites, flow arcs, tile extrusion, idle bob, true iso
  projection (`c095be6`, `cbbdba4`, `322520c`, `d2251a5`, 2026-04-21).
- `dev/stream-app-ideas.md` — backlog of unshipped broadcast-app vibe
  ideas with effort estimates (2026-05-02).

### Added — Stream vibe v2 (`8abe884`, 2026-05-09)

- **Day/night sky cycle** in `AgentWorldXL` driven by a `useMarketClock`
  hook polling `/market/clock` — phase-based gradient stops, twinkling
  stars when not in RTH.
- **Weather effects** — rain when day P&L ≤ −1%, sun rays when ≥ +1%,
  snow when market closed, fog in pre-market.
- **Tick countdown ring + equity sparkline** in `TopTicker` — a 30-tick
  rolling buffer feeding a tiny equity sparkline next to the equity stat,
  and a radial countdown ring driven by `auto_tick_interval_sec`.
- **CSS-only CRT toggle** — scanlines + chroma-fringe text-shadow +
  vignette via two `body.crt-on` pseudo-elements; toggleable from the
  Admin overlay and now from the dashboard.
- **Recap scene** — fifth scene auto-shown after 16:00 ET (gated on the
  market-clock phase + ET hour). Big day-P&L hero, top/bottom mover +
  biggest fill cards, strategy ranking bars.
- **Mascot Pet** — wandering chicken/cat/farmer sprite that random-walks
  the bridges in `AgentWorldXL`. Pure flavor; idle/walk state machine
  with smooth CSS transitions and self-contained bob animation.

### Added — V1 sports-broadcast layout

- **`layoutMode: "scenes" | "v1-broadcast"`** stream setting + Admin
  toggle. The new V1 layout is a 1920×1080 sports-broadcast frame:
  scoreboard band, leaderboard rail, race-to-alpha lanes, "the farm"
  8×8 mini-card grid, plays/chat right panel, lower-third banner,
  FARMLINE marquee. Lives under `stream/src/broadcast/v1/`. Ships with
  `PLAYS` working (live fills feed) and a `CHAT` placeholder for a
  future streamer-chat integration.
- **JetBrains Mono webfont** loaded via Google Fonts in
  `stream/index.html` for tabular-numeric pricing.
- **Per-agent rolling sparkline buffer** in `broadcast/v1/adapter.ts`
  (32 points, GC'd on agent removal) — backend doesn't push history,
  so we accumulate it client-side.

### Added — Dashboard reorganization (`8abe884`, 2026-05-09)

- **Scroll-snap two-viewport layout** — viewport 1 holds Agent World
  (full-bleed) + a new live `RecentFillsRail`; viewport 2 holds
  controls (stat grid → tabs → Broadcast → API spend → Open Positions
  strip → Agent Grid). `min-h-[calc(100vh-100px)]` per section keeps
  the live show always visible.
- **Resizable AW ↔ Fills split** via `react-resizable-panels` v4 —
  default 75/25, layout persisted to localStorage.
- **`AgentWorld` `fit="contain"` prop** — when set, the diorama scales
  to fit its container (flex-column SVG with `preserveAspectRatio`)
  instead of overflowing on tall sections.
- **API Spend widget** reading `/llm/stats` with a daily-cap dial.
- **Workflow** tab in the lower TabbedPanel — side-by-side SVG
  flowcharts of the three `decide()` bodies.
- **Open-positions sparkline strip** — aggregated per-symbol view
  with rolling sparklines.
- **Keyboard map overlay** (`?`) — cheat sheet of every shortcut,
  guarded against the command palette.

### Added — Dashboard ↔ Stream remote control

- Six new control sections in `web/src/components/broadcast/`:
  - `BroadcastLayoutSection` — Scenes ↔ V1 Broadcast switcher.
  - `BroadcastSceneSection` — scene buttons + auto-rotate, dimmed
    when stream is in V1 mode.
  - `BroadcastAudioSection` — enable + volume hydrated from heartbeat.
  - `BroadcastCrtSection` — CRT effect toggle.
  - `BroadcastCadenceSection` — rotation cadence slider (0–180s).
  - `BroadcastFullscreenSection` — fullscreen toggle (Tauri only).
- Backend allowlists 4 new cmd types: `stream_layout`, `stream_crt`,
  `stream_cadence`, `stream_fullscreen`.
- Stream heartbeat now publishes `layout_mode`, `crt_enabled`,
  `rotation_sec` so the dashboard reflects actual stream state.

### Changed
- Backend CORS widened to a regex covering `localhost`, `127.0.0.1` (any
  port), and Tauri custom-protocol origins (`tauri.localhost`,
  `tauri://localhost`). API binds 127.0.0.1, so widening CORS does not
  expose anything external (`a34676c`, 2026-05-02).
- Dynamic risk-threshold reads — risk parameters honor live `.env`
  edits without orchestrator restart (`bb1e291`, 2026-04-21).
- Risk log strings made ASCII-safe to stop Unicode warnings on Windows
  consoles (`bb1e291`, 2026-04-21).
- README architecture tree updated to include `academy/`, `dev/`,
  `docs/` modules; new "Documentation" section added with cross-links.

### Fixed
- Idempotent column migration for pre-Academy databases — added
  `ALTER TABLE ... ADD COLUMN ... IF NOT EXISTS` semantics so older
  `tradefarm.db` files survive an Academy upgrade (`0a2d516`,
  2026-04-21).

---

## [0.1.0] — 2026-04-21

Initial public release. The Agent Academy 4-phase delivery plan landed
across one afternoon, on top of the initial 100-agent paper-trading
sandbox import that morning.

### Added — Agent Academy

- **Phase 1: agent journal + outcome linkage** (`4041d70`).
  - New `storage/journal.py` — every decision writes an `agent_notes`
    row; closing trades stamp the originating note with realized P&L.
  - New `tests/test_journal.py`.
  - `agents/base.py` carries `journal_note_id` scratchpad through the
    decide → fill → close cycle.
  - REST: `GET /agents/{id}/notes?limit=N`.
  - Idempotent partial-exit handling.
- **Phase 2: academy ranks + rank-gated capital** (`71bacea`).
  - New `academy/` package with `ranks.py` (compute_stats,
    eligible_rank), `repo.py`, `__init__.py`.
  - Ranks: intern (0.5×), junior (1.0×), senior (1.5×), principal
    (2.0×). Multipliers apply to
    `RiskManager.limits.max_position_notional_pct` (base 0.25).
  - `Agent.rank` + `rank_updated_at` columns added.
  - REST: `GET /academy/ranks`, `GET /agents/{id}/academy`.
  - Settings: `academy_rank_multipliers`,
    `academy_min_trades_junior/senior/principal`.
  - New `tests/test_ranks.py`.
- **Phase 3: retrieval-augmented LLM prompt** (`336b2c7`).
  - New `agents/retrieval.py` — wraps `journal.find_similar` and formats
    the agent's 3 most-similar past setups + outcomes for the prompt.
  - `LlmContext` extended with `retrieved_examples`; user-message block
    appended only when non-empty (byte-identical when disabled).
  - REST: `GET /agents/{id}/retrieval-preview?symbol=`.
  - Settings: `academy_retrieval_k` (default 3),
    `academy_retrieval_enabled` (default True).
  - New `tests/test_retrieval.py`.
- **Phase 4: curriculum / auto-promote-demote** (`8a56583`).
  - New `academy/curriculum.py` — second background task in the
    orchestrator; runs `evaluate_all()` every
    `academy_eval_interval_sec`, only between ticks (avoiding RiskManager
    mid-tick staleness).
  - New `academy_promotions` table.
  - WebSocket: `promotion` and `demotion` events.
  - REST: `POST /academy/evaluate`, `GET /agents/{id}/promotions`.
  - Settings: `academy_eval_interval_sec`,
    `academy_demote_drawdown_pct` (default 0.08),
    `academy_demote_consecutive_losses` (default 5), 10%-of-cohort
    per-pass demotion cap.
  - New `tests/test_curriculum.py`.

### Added — core platform (`a5147d2`)

- 100 agents × $1,000 virtual books on top of one pooled Alpaca paper
  account.
- Three strategy families:
  - `momentum_sma20` — SMA20 momentum baseline.
  - `lstm_v1` — LSTM-only direction predictor.
  - `lstm_llm_v1` — LSTM + LLM overlay with cost gate.
- LSTM brain: 2-layer LSTM(64) per symbol, 19 engineered features,
  3-class direction head + confidence head, class-balanced training
  (`agents/lstm_model.py`, `agents/lstm_train.py`).
- LLM overlay with pluggable provider interface — Anthropic Claude
  Haiku 4.5 (prompt caching) or MiniMax M2.7-highspeed (OpenAI-
  compatible endpoint).
- Cost gate: when LSTM `max_prob < 0.40` the LLM call is skipped
  entirely (~78% reduction at no loss of trades). Tracked via
  `/llm/stats`.
- Walk-forward backtester with per-symbol Sharpe / CAGR / max-drawdown
  / win-rate (`agents/backtest.py`), launchable from the admin modal.
- Vite + React 19 + Tailwind v4 live dashboard — today PnL, open
  positions, monthly PnL chart, brain activity, strategy attribution,
  order status, 100-agent grid with click-through detail modal.
- WebSocket event feed: `tick`, `fill`, `account`, `pnl_snapshot`,
  `heartbeat`, `hello` events pushed to the UI.
- Alpaca paper reconciler (`execution/order_reconciler.py`) — polls
  every 10s, computes actual-vs-optimistic fill delta, applies
  idempotent cash + avg-price corrections to the virtual book.
- Admin console with runtime-editable config persisted to `.env`:
  master AI switch, provider/model/keys, LSTM confidence gate, tick
  interval, RTH gating, execution mode, strategy toggles, backtest
  launcher.
- Initial test suite: `test_virtual_book.py`.

### Documentation
- `docs/plan_tech.md` (engineering) and `docs/plan_product.md` (UX) —
  parallel planning docs (`a5147d2`).
- `docs/PROJECT_PLAN.md` — 2-PM synthesis with the 4-phase Agent
  Academy delivery plan (`ddcd37c`).

---

## Conventions

- Commit subjects use a short scope tag: `feat(stream): …`, `fix(risk): …`,
  `phase 1: …` (during the Academy rollout). Hashes are short SHAs from
  `git log --oneline`.
- "Unreleased" accumulates work since the last tagged release. There are
  currently no git tags; `0.1.0` is the inferred version baked into
  `pyproject.toml`.
