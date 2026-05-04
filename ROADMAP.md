# Roadmap

Forward-looking work for TradeFarm, organized by horizon. Items shipped
since the last release live in [CHANGELOG.md](./CHANGELOG.md). The full
broadcast-app idea backlog (with effort estimates) lives in
[`dev/stream-app-ideas.md`](./dev/stream-app-ideas.md); this file
captures the intersection of "interesting" + "likely to be tackled".

Status legend:

- `now`        — in flight or up next (≤ 1–2 weeks)
- `next`       — committed for the current quarter (1–3 months)
- `later`      — committed direction but not scheduled (3–6 months)
- `considering`— on the radar; needs more thought before commitment

---

## Now — current focus

### Stream Vibe v2 (broadcast app polish)
Round out the broadcast app before promoting it from "personal demo" to
"share with viewers" status.

- **Day/night sky cycle** in `AgentWorldXL` — animate the existing
  `<linearGradient id="sky-xl">` stops based on a new `/market/clock`
  endpoint. Pre-market = stars, RTH = bright, after-hours = dusk.
  *~1 day.*
- **Weather effects** — rain particles on red days, sun rays on green,
  snow when market closed. SVG-only, no asset cost. *~½ day.*
- **Tick countdown ring** in `TopTicker` — visual progress to next
  scheduled tick. *~2 hours.*
- **Equity sparkline** in `TopTicker` — 30-tick rolling line. *~½ day.*
- **CSS-only CRT toggle** — scanlines + chroma fringe, hotkey from
  Admin overlay. *~2 hours.*
- **Recap scene at 4pm ET** — fifth rotator scene auto-shown after
  market close: top movers, biggest fill, best/worst agent, total PnL,
  strategy ranking. *~1 day.*

Together this is roughly a week of work and gets the broadcast app to a
"ship it on Twitch" feel.

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
  `data_cache/recaps/YYYY-MM-DD.mp4`.
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
