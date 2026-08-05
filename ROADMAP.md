# Roadmap

Forward-looking work for TradeFarm, organized by horizon. Items shipped
since the last release live in [CHANGELOG.md](./CHANGELOG.md). The full
broadcast-app idea backlog (with effort estimates) lives in
[`dev/feature-backlog.md`](./dev/feature-backlog.md); this file
captures the intersection of "interesting" + "likely to be tackled".

**0.9.0 shipped 2026-08-04.** A "tighten the autonomy loop" release —
the 0.8.0 known gaps are addressed one-by-one. The scheduler's
power-loss race is closed (`live_today`), the headless renderer
captures 9:16 shorts + recap clips on the same loop, every
published video gets a real thumbnail, the recap endpoint is
replay-aware, the VOD studio's intern cast data is now full
shape, the pipeline persists per-step timings, and the weekly
Strategy Wars beat + rollup infra ship. 823 tests passing
(up from 690). See [CHANGELOG.md](./CHANGELOG.md) for the full
release notes. The current focus is the post-0.9.0 audit
findings (the 0.9.0 carryovers — TTS defaults, asset
archival, shorts visual verification — live in
[CHANGELOG.md](./CHANGELOG.md#known-carryovers-deferred-to-010))
plus the content side's [youtube-interesting
doc](./docs/research/youtube-interesting.md) recommends the
Intern Watch / Strategy Wars / Rivalry Week weekly formats
(Strategy Wars shipped; Intern Watch and Rivalry Week surfaces
still pending).

Status legend:

- `now`        — in flight or up next (≤ 1–2 weeks)
- `next`       — committed for the current quarter (1–3 months)
- `later`      — committed direction but not scheduled (3–6 months)
- `considering`— on the radar; needs more thought before commitment

---

## Now — current focus

The 0.9.0 release (2026-08-04) closed every 0.8.0 known gap: the
scheduler's `live_today` flag, the recap-scene replay path, the
thumbnail pipeline step, the full intern cast list, the
per-step timing roll-up, the weekly rollup + Strategy Wars
detector. The rivalry beat's duration now scales with its
90-min window so the headless renderer's clip is long
enough to show the full back-and-forth. **The current focus is
the post-0.9.0 audit findings + the remaining content
formats** (Intern Watch and Rivalry Week surfaces still
pending; the Strategy Wars detector is shipped), not new
features. The research docs at `docs/research/` are the
source of truth for what's left.

### Audit-followup quick wins (≤ 1 day each, picked from the 2026-08 review)

These are the **new** findings from the post-0.6.0 audit (see
`REPO_REVIEW.md` + `BACKLOG.md` for the full list). They're grouped
by impact — pick any one when the operator wants a small, contained PR.

- **Backend — `pnl_daily` denominator hardcoded to 1000.0.**
  `api/main.py:675` ignores `agent_starting_capital`. The `/account`
  endpoint already does it right; this one is a one-line fix + a test.
  *~15 min.*
- **Backend — finish the shared-httpx-client migration.** Two LLM
  hot paths (`llm_providers.py:119` for MiniMax,
  `commentary_loop.py:430` for commentary) still spin a fresh
  `httpx.AsyncClient` per call. Mirror the `eodhd.py:72-74` pattern.
  *~30 min.*
- **Backend — env-var shadowing warning at boot.** `Settings()` loads
  from shell env + `.env`; the admin-panel `.env` write is invisible
  if the shell env wins. Log a `env_shadow` warning on first load.
  *~1 hour.*
- **Backend — replace `_recent_fills_from_orch`'s open-positions
  stand-in** with a real fill ring buffer (last 50 fills). The cost
  gate currently misfires on a flat market with positions still open
  from earlier fills. *~2 hours.*
- **Backend — MiniMax provider retries + base-URL allowlist.** No
  retry on transient 5xx/429; `minimax_base_url` accepts any URL.
  Mirror `eodhd.py:77-89` retry pattern + a `urlparse(scheme=https)`
  guard. *~1 hour.*
- **Backend — add a real `/api/fills/count?since=…` endpoint.** The
  VOD "fills today" stat currently reads the WS buffer cap (20), not
  the real count. *~1 hour.*
- **Backend — fix 4 stale "skeleton" docstrings** in
  `session/{run,manifest,replay,closing_snapshot}.py`. *~10 min.*
- **Backend — audience lock** (still OPEN from round 1). One
  `asyncio.Lock` around approve/reject + replace the deque rebuild
  with an `OrderedDict`. *~30 min.*
- **Backend — pin `pandas<3` and rebuild the venv.** Currently
  running untested pandas 3.0.2. *~30 min + lockfile regen.*
- **Frontend — `RecentFillsRail` age label bug.** `Date.now()` only
  re-evaluates on a new fill, so a 5-minute-old fill reads "0s".
  Add a 1s re-render or own the tick in a child. *~30 min.*
- **Frontend — single `WebSocket` per tab via a context provider.**
  Dashboard opens 3, stream opens 2. The H12 multi-WS issue from
  prior rounds was only half-fixed. *~½ day.*
- **Frontend — gate mock data behind `import.meta.env.DEV`.** Both
  `dash/mockData.ts` and `vod/mockData.ts` ship in the prod bundle.
  *~1 hour.*
- **Frontend — kill the 800ms `useVodSessionLive` heartbeat.** Re-renders
  the whole dashboard tree 1.25×/sec to power a cursor-blink. Move
  the cursor-blink to a leaf component. *~30 min.*
- **Frontend — a11y pass on the legacy modals.** `AdminModal.tsx` and
  `BacktestModal.tsx` need `role="dialog"`, `aria-modal`, focus trap,
  return-focus on close. *~1 hour.*
- **Frontend — replace `disabled={!isOnline}` with a warning banner.**
  If the stream heartbeat ever goes stale, the entire Broadcast
  panel greys out at the worst possible moment. *~½ day.*
- **Docs — prune tracked debug screenshots** in
  `docs/screenshots/2026-05-17/` (28 PNGs, 12 MB, not referenced).
  *~10 min.*
- **Docs — move/rename `dev/design_handoff_*` to `dev/_archive/`.**
  The 3 handoff trees are now historical. *~10 min.*

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
- **Lower-thirds builder** — generic title/subtitle component driven
  by a new `lower_third` WS event so a CLI can pop banners on demand.

### Dashboard
- **Persistent LLM-decision feed** — the current commentary caption is
  transient (single line). Add a sidebar that holds the last N decisions
  for quick review. Mirrors the Brain scene in the broadcast app.
- **Per-agent profile page** — promote the modal into a routed page so
  it deep-links and survives reload. Still a modal-style overlay on the
  main grid.

### Operations
- **WebSocket event recording** — log every `/ws` frame to a
  `data_cache/ws_recordings/` ndjson per session so we can replay
  sessions for testing without standing up real ticks. Useful for
  audio-engine tuning and pre-recorded promo clips.

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
  _(Shipped 2026-05-09 — `stream/src/components/MascotPet.tsx`.)_

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
