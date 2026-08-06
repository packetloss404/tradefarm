# Roadmap

Forward-looking work for TradeFarm, organized by horizon. Items shipped
since the last release live in [CHANGELOG.md](./CHANGELOG.md). The full
broadcast-app idea backlog (with effort estimates) lives in
[`dev/feature-backlog.md`](./dev/feature-backlog.md); this file
captures the intersection of "interesting" + "likely to be tackled".

**0.18.0 shipped 2026-08-05.** A "live LLM
model discovery + McLove the admin panel"
release. The dashboard's free-form `llm_model`
text input is replaced with a live-discovered
dropdown that calls each provider's
`/v1/models` endpoint, caches for 60 minutes,
and shows the current top-line models with
cost hints. The OpenAI provider ships for
the first time (the user explicitly asked for
it; it wasn't in the codebase). The admin
modal gets a full McLove pass — section
reordering, dead-UI removal, a11y upgrade,
friendly error states on every async action.
A research subagent verified the user's
model-name mentions ("haiku/sonnet/opus/
fable", "M3", "GPT 5.6 all 3 variants") —
all real, current model names. Four subagents
shipped under the orchestrator's integration;
orchestrator removed a provider-radio
conflict between the new picker and the
existing Brain Provider section (the picker
now owns provider + model as a single
source of truth). 1069 tests pass (+52 since
0.17.0). See [CHANGELOG.md](./CHANGELOG.md)
for the full release notes.
lower-thirds builder + WS recording" release.
The TTS settings UI flips the active TTS
provider at runtime (no env-var restart) with
a save/reset/preview affordance per provider;
the lower-thirds builder ships a dedicated
`lower_third` WS event + dashboard quick-input
form + in-memory recent-rows ring buffer for
replay; the WS event recording layer logs every
`/ws` frame to NDJSON for replay fixtures and
audio-engine tuning. Three parallel dev
subagents shipped the three work streams; the
orchestrator integrated and fixed one
cross-cutting issue (the preview endpoint's
`asyncio.run` from inside a running event
loop — replaced with `await`). 1017 tests pass
(+96 since 0.16.0). See [CHANGELOG.md](./CHANGELOG.md)
for the full release notes.
Rivalry Week podcast + scheduler tuning fixtures"
release. Closes three backlog items in one
swing: item **4.5** (recap scene at 4pm ET), the
Rivalry Week podcast format from the round-8
research, and **milestone 3** of
`docs/broadcast_os.md` (replay fixtures). Three
parallel dev subagents shipped under the
orchestrator's integration; orchestrator fixes
two cross-cutting mypy errors and three
pre-existing `test_vod_scheduler.py` failures
that the 0.11.0 carryover fix had missed. 921
tests pass (+60 since 0.15.0). See
[CHANGELOG.md](./CHANGELOG.md) for the full
release notes.

Status legend:

- `now`        — in flight or up next (≤ 1–2 weeks)
- `next`       — committed for the current quarter (1–3 months)
- `later`      — committed direction but not scheduled (3–6 months)
- `considering`— on the radar; needs more thought before commitment

---

## Now — current focus

The 0.19.0 release (2026-08-05) shipped the
"persistent LLM-decision feed sidebar" — a
new `<DecisionFeedSidebar />` on the dashboard's
Today page that holds the last ~50 per-agent
decision-lab entries for quick review.
Backed by a process-wide bounded ring buffer
(`RecentDecisionsLedger`, 200 entries) that
a lifespan-spawned subscriber feeds from the
event bus; a freshly-reloaded page sees recent
history before any new tick lands. Refresh
via SWR + live WS subscription; filters
`?agent_id=N`, `?only_llm=true`, `?limit=N`.
22 new tests (14 unit + 8 endpoint). Web
bundle: 385 KB / 111.7 KB gzipped. See
CHANGELOG.md for the full release notes.

Remaining 0.19.0 candidates (in priority
order):
1. **Per-strategy daily attribution snapshot**
   table — M-effort, backend-only. New table
   that pre-aggregates
   `/pnl/by-strategy/timeseries` so the
   endpoint doesn't re-aggregate from
   `pnl_snapshots` on every request.
2. **Intraday data path** — L-effort, data
   layer. 5-min EODHD instead of daily bars;
   agents reason on closer-to-live conditions.

0.18.0 follow-ups still pending: operator-
driven visual QA on the new picker against
real API keys (current visual state is the
demo catalog, which is correct behavior
without keys).

### Audit-followup quick wins (≤ 1 day each, picked from the 2026-08 review)

These are the **new** findings from the post-0.6.0 audit (see
`REPO_REVIEW.md` + `BACKLOG.md` for the full list). They're grouped
by impact — pick any one when the operator wants a small, contained PR.

- ✅ **Backend — `pnl_daily` denominator hardcoded to 1000.0** — shipped in round 6 B1.
- ✅ **Backend — `llm_providers.py` shared-httpx-client migration** — shipped in round 5 AA.
- ✅ **Backend — `commentary_loop.py:430` shared-httpx-client migration** — shipped in 0.12.0.
- ✅ **Backend — `tts/run.py:119` (elevenlabs) shared-httpx-client migration** — shipped in 0.12.0.
- ✅ **Backend — `yt/upload.py` 4 callsites shared-httpx-client migration** — shipped in 0.12.0.
- ✅ **Backend — env-var shadowing warning at boot** — `config.py:_check_env_shadows` fires on every boot when shell env disagrees with `.env`.
- ✅ **Backend — replace `_recent_fills_from_orch`'s open-positions stand-in** — shipped in round 6 (orchestrator's bounded ring buffer).
- ✅ **Backend — MiniMax provider retries + base-URL allowlist** — shipped in round 6 MED-minimax.
- ✅ **Backend — add a real `/api/fills/count?since=…` endpoint** — shipped in an earlier round (`api/main.py:812`).
- ✅ **Backend — fix 4 stale "skeleton" docstrings** — none found; the modules are fully documented.
- ✅ **Backend — audience lock** — shipped in 0.12.0 (asyncio.Lock + dict refactor; closes the double-publish race).
- ✅ **Backend — pin `pandas<3` and rebuild the venv** — shipped in round 6.
- ✅ ~~**Frontend — `RecentFillsRail` age label bug.**~~ Already
  shipped — `RecentFillsRail.tsx` has a `useState` + `setInterval`
  that ticks `now` every 1s so a stale fill's age label stays
  accurate (the parent only re-renders on new fill events). The
  fix is in the file at the top of the `RecentFillsRail`
  function; nothing to do.
- ✅ ~~**Frontend — single `WebSocket` per tab via a context
  provider.**~~ Already shipped in 0.13.0/0.14.0 — both apps
  wrap the root in `<LiveProvider urlOverride={wsUrl}>` (see
  `web/src/main.tsx:41` + `stream/src/App.tsx:193`). The
  provider owns the single `new WebSocket(target)` and the
  hooks (`useLiveEvents`, `useLiveContext`) are fan-out
  registrations. The H12 multi-WS issue is fully closed.
- ✅ ~~**Frontend — gate mock data behind `import.meta.env.DEV`.**~~
  Already shipped in 0.13.0 — Vite tree-shakes the dev branch of
  `web/src/vod/data.ts` + `web/src/dash/data.ts` exports in
  production (see 0.13.0 CHANGELOG). The prod bundle is 360 KB
  / 108 KB gzipped, which is the proof.
- ✅ ~~**Frontend — kill the 800ms `useVodSessionLive` heartbeat.**~~
  Already shipped in 0.10.0/0.11.0 — the cursor-blink moved to the
  `ETClock` leaf and the global 1.25Hz re-render is gone (see
  `useVodSessionLive.ts:206-211`).
- ✅ ~~**Frontend — a11y pass on the legacy modals.**~~ Already
  shipped in 0.13.0/0.14.0 — `AdminModal.tsx` + `BacktestModal.tsx`
  have `role="dialog"`, `aria-modal`, `useFocusTrap`,
  return-focus on close, and `aria-label` coverage (see 0.13.0
  + 0.14.0 CHANGELOGs).
- ✅ ~~**Frontend — replace `disabled={!isOnline}` with a warning
  banner.**~~ Already shipped in 0.13.0 — the Broadcast panel's
  audio + cadence controls stay clickable when the stream
  heartbeat goes stale; the `OfflineWarning` banner is the only
  state flag. See 0.13.0 CHANGELOG.

**Docs:**

- ✅ ~~**Docs — prune tracked debug screenshots** in
  `docs/screenshots/2026-05-17/`.~~ Already pruned — the
  directory no longer exists.
- ✅ ~~**Docs — move/rename `dev/design_handoff_*` to `dev/_archive/`.**~~
  Already moved — the handoffs live at
  `dev/_archive/design_handoffs_2026-04/`.

---

## Next — current quarter

### Trading core
- **Intraday data path** — current EODHD client serves daily bars. Add
  a 5-minute path (or the EODHD intraday endpoint) so the agents are
  reasoning on something closer to live conditions. Today the 5-minute
  tick uses the latest daily bar's close repeatedly inside RTH.
- **Embedding-backed retrieval** — Phase 3 retrieval is currently
  symbol-match + recency. Add a vector column to `agent_notes` (or
  external sqlite-vec / DuckDB index) and use embeddings of the
  decision-reason text for similarity. Keep symbol-match as a fallback
  so retrieval works even before the embedding job catches up.
- **Per-strategy daily attribution snapshot** — store daily roll-ups
  in a new table so `/pnl/by-strategy/timeseries` doesn't have to
  re-aggregate from `pnl_snapshots`. Reduces a hot query.

### Stream app
- **Speech bubbles on agents** — show truncated `last_decision.reason`
  above any sprite that filled in the last 30s.
- **Camera dolly cinematic** — periodic 4-second cinematic close-up on
  the agent that just had the biggest fill. Hold, ease back.
- **Promotion cutscene** — pause the world, particle burst, halo
  growth, sprite floats. Replaces the current static halo.
- ✅ ~~**Lower-thirds builder** — generic title/subtitle
  component driven by a new `lower_third` WS event so a
  CLI can pop banners on demand.~~ Shipped in 0.17.0:
  `lower_third` event + `<LowerThirdBuilder />` panel +
  recent-rows ring buffer for replay.

### Dashboard
- ✅ ~~**Persistent LLM-decision feed** — the current commentary
  caption is transient (single line). Add a sidebar that holds
  the last N decisions for quick review. Mirrors the Brain scene
  in the broadcast app.~~ Shipped in 0.19.0: new
  `<DecisionFeedSidebar />` on the Today page backed by
  `RecentDecisionsLedger` (200-entry ring buffer) +
  `GET /api/decisions/recent` endpoint + WS subscription to
  `agent_decisions_batch`. Filters: agent_id, only_llm, limit.
- **Per-agent profile page** — promote the modal into a routed page so
  it deep-links and survives reload. Still a modal-style overlay on the
  main grid.

### Operations
- ✅ ~~**WebSocket event recording** — log every `/ws` frame
  to a `data_cache/ws_recordings/` ndjson per session so we
  can replay sessions for testing without standing up real
  ticks.~~ Shipped in 0.17.0: `WsRecorder` class + admin
  start/stop/list endpoints + `load_ws_recording` +
  `replay_ws_recording` helpers.

---

## Later — committed direction

### Models
- **Transformer baseline** — replace LSTM(64) with a small TFT or
  Informer variant for the same 19 features. Useful as a control even
  if it doesn't ship to all agents.
- **Online learning loop** — once an agent has accumulated enough
  outcome-stamped journal entries, fine-tune its LSTM head on its own
  closed-trade history. Gated by Phase 2 rank (Senior+ only) to avoid
  Intern overfitting.
- **Better feature engineering** — order-flow imbalance, options-flow
  signals (when intraday data lands), sector rotation index.

### Trading
- **Live (real-money) Alpaca path** — *out of scope while paper-only is
  the explicit project status.* Listed here so the boundary is
  documented; flipping it is intentional, not accidental.
- **Asset class expansion** — futures, forex, or crypto via Alpaca's
  expanded API. Keep one strategy family at a time to limit the
  blast radius.

### Stream / production
- **TTS narrator** — pipe `commentary.current.text` to either
  ElevenLabs flash-v2 (cloud, ~$0.15/min) or a locally-spawned
  `piper.exe` (free). Duck the music while speaking.
- **Hourly newsroom bulletin** — every hour at `:00`, the rotator
  forces a 20-sec "ON AIR" lower-third with a 2-line LLM-generated
  bulletin from the last hour's journal entries.
- **Daily recap MP4** — at 16:05 ET, headless Playwright + ffmpeg
  compose a 30-sec highlight reel for socials. Output to
  `data_cache/recaps/YYYY-MM-DD.mp4`. _(Effectively shipped: the
  VOD pipeline builds daily 10–15 min recaps via
  `tradefarm.session.*` → `render.headless` → `render.stitch` →
  `script.write` → `tts.run` → `render.mix` → `thumb.gen` →
  `yt.upload`. The 30-sec social cut is a follow-on.)_
- **OBS WebSocket bridge** — let backend events flip OBS scenes
  (e.g. switch to a "Promotion Cutscene" scene when a rank-up arrives).

### Infrastructure
- **Postgres backend** as an alternative to SQLite — still default to
  SQLite for the dev sandbox; PG only when running 24/7 on a real
  host. Driven by a single `DATABASE_URL` change.
- **Observability** — Prometheus metrics endpoint (already implicit
  via `/llm/stats`, `/account` polling) wired into a Grafana
  dashboard. Useful for noticing reconciler lag or LSTM cost-gate
  drift.
- **Session replay UI** — load a `data_cache/ws_recordings/*.ndjson`
  into the dashboard or stream app and play it back at any speed.

---

## Considering — not yet committed

These are deliberately not on a horizon. Listed so we don't forget the
question.

- **Twitch chat integration** — `!agent NAME` commands, channel-points
  agent renaming, viewer prediction polls. Needs OAuth glue and a
  separate auth doc; meaningful only if the broadcast app has an
  audience.
- **Pixel-art skin toggle** — same iso math, swap SVG sprites for 16-bit
  PNGs. Asset budget is the real cost.
- **3D mode** for `AgentWorldXL` — Three.js scene with proper shadows
  and orbit camera. A rewrite, not an extension.
- **Multi-window broadcast mode** — spawn a smaller secondary Tauri
  window with a transparent background for OBS Browser Source capture.
- **Public hosted demo** — a read-only mirror of the dashboard at a
  public URL. Implies removing all admin endpoints, anonymizing keys,
  and rate-limiting the WS feed. Not trivial.
- **Mascot pet** in `AgentWorldXL` — a small farmer/chicken that
  wanders the bridges. Pure flavor; would survive a 2-day sprint.
  ~~_(Shipped 2026-05-09 — `stream/src/components/MascotPet.tsx`.)_~~

---

## Out of scope (intentional non-goals)

- **Real-money trading**. The repo's status banner says paper-trading
  only. We will not flip the bit silently.
- **Financial-product polish** — order types beyond the simple market
  intents, broker support beyond Alpaca, P&L attribution to taxes /
  reporting. This is a research sandbox, not a brokerage.
- **Mobile-native apps** — the dashboard is desktop-first by design.
  Responsive styling fixes are welcome, but a React Native build is
  not on the table.

---

## Process notes

- The `docs/PROJECT_PLAN.md` 4-phase Agent Academy plan shipped
  serially (one commit per phase) on 2026-04-21. Future multi-phase
  efforts should follow the same pattern: one synthesis doc up front,
  one commit per acceptance-criteria-met phase.
- Each item in the "now" / "next" buckets should be small enough that a
  single PR closes it. If it isn't, split it before starting.
- "Considering" items can be promoted directly to "now" when a
  contributor wants to take them; no ceremony.
