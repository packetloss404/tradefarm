# TradeFarm

100 AI agents paper-trading US stocks and ETFs. Each agent is a mix of LSTM
sequence modelling and an LLM overlay (Anthropic Claude or MiniMax), runs on a
5-minute cadence, and reports into a live dashboard that mirrors IMMT's AI
Trading World layout.

Inspired by [IMMT AI Trading World](https://www.youtube.com/results?search_query=IMMT+AI+Trading+World)
(crypto perpetuals), adapted for US equities via EODHD + Alpaca paper.

## Status

Development sandbox. **Paper trading only.** Not financial advice, not a product.
LSTM validation accuracy is 55–60% on 3-class daily return (vs 51% always-flat
baseline) — meaningful but thin. Treat it as infrastructure for learning, not
edge for trading.

## Features

- **100 agents × $1,000 virtual books** on top of one pooled Alpaca paper account
- **Eight strategy families** (8 buckets, 100 agents spread across them)
  with per-strategy enable/disable toggles:
  `momentum_12_1`, `momentum_sma20`, `mean_reversion_bb`, `rsi2`,
  `donchian_breakout`, `pairs_zscore`, `lstm_v1`, `lstm_llm_v1`
  (`momentum_sma20` is the legacy alias kept for back-compat)
- **LSTM brain** — 2-layer LSTM(64) per symbol with 19 engineered features,
  3-class direction head + confidence head, class-balanced training
- **LLM overlay** — Anthropic Claude (Haiku 4.5 + Sonnet 5 + Opus 4.8 +
  Fable 5, prompt caching), OpenAI GPT-5.6 (Sol / Terra / Luna + aliases),
  *or* MiniMax (M2.7 / M2.7-highspeed / M3). Pluggable provider
  interface with live `/v1/models` discovery so the operator picks
  the current model from a dropdown without touching `.env`
- **Cost gate** — when LSTM max-prob < 0.40, the LLM call is skipped entirely;
  cuts ~78% of API calls with no loss of trades
- **Intraday mark path** — 0.24.0 — during RTH with `INTRADAY_ENABLED=true`,
  the orchestrator refreshes marks from EODHD's 5m bars instead of
  yesterday's daily close (paid-tier endpoint; 401/403 short-circuits
  to the daily mark). Off-RTH the daily path stays in charge regardless
- **Daily recap scheduler** — 0.16.0 — at 4pm ET, fires a `broadcast_moment`
  with the day's leader + a `LiveRecapScene` plays in the rotator.
  Writes a per-day `daily_recap_fired` idempotency row, then snapshots
  per-strategy attribution into `strategy_daily_attribution` so the
  `/pnl/by-strategy/timeseries` endpoint doesn't re-aggregate on every
  chart poll
- **Rivalry Week podcast** — 0.16.0 — every Sunday, a 10–15 min LLM-narrated
  podcast of the week's top-3 rivalries + leaderboard moves, composed
  via the `render.podcast` pipeline
- **Decision feed sidebar** — 0.19.0 — persistent sidebar on the
  dashboard's Today page with the last ~50 per-agent decision-lab
  entries; SWR-polled + WS-subscribed so fresh entries prepend
  immediately. `?agent_id=N`, `?only_llm=true`, `?limit=N` filters
- **Walk-forward backtester** — per-symbol Sharpe / CAGR / max-drawdown / win-rate,
  launchable from the admin modal
- **Multi-page dashboard** (Vite + React 19) — six hash-routed surfaces
  sharing one theme (dark / light / amber-CRT with scanlines, density
  switcher, all in a bottom-right tweaks panel):
  - **Today** (`#today`) — hero strip, cost burn rail, live equity chart,
    25×4 agent pixel grid, tonight's render pipeline, episode preview,
    recent fills, detected moments, open-positions sparkline strip,
    **decision feed sidebar** (0.19.0). Reads live `/api/account`,
    `/api/agents`, `/api/llm/stats`, and the `/ws` fill stream.
  - **Episodes** (`#episodes`) — featured latest episode, 6-week P&L
    heatmap, archive grid with a "beats-as-day-shape" sparkline per
    card.
  - **Research** (`#research`) — 14-session pool equity vs $100k
    baseline, top-10 leaderboard with rank-history sparklines, strategy
    attribution diverging bars, storyline cards (rivalries, streaks,
    leaderboard climbs) with 14-day activity ribbons.
  - **Admin** (`#admin`) — kill switch + brain provider / execution /
    strategies / academy / VOD pipeline / TTS / LLM model picker / danger
    zone, live-editable against `/api/admin/config` with debounced
    auto-save. Both the modal and the legacy single-page `#admin` route
    show the same 8-strategy + LLM picker layout (0.18.0 hotfix).
  - **Agent** (`#agent/<id>`, 0.29.0) — deep-linkable per-agent profile
    page; URL is shareable, page renders the full `AgentDetailModal`
    in a header-and-back-link layout.
  - Original single-page dashboard kept at `#legacy` as a fallback.
- **VOD Studio** (`#vod-studio`) — post-production app for the day's
  auto-generated 10-minute recap episode. Four operator surfaces:
  - **Beat picker** (keystone) — preview pane, scrubber, timeline with
    master/rejected lanes, editable per-beat caption, beat-list rail.
    Toggle `IN`/`OUT` to recompute reel length.
  - **Pipeline status** — 10 subsystems (session → beats → render →
    stitch → script → TTS → mix → thumb → metadata → upload) with
    progress + tail-of-log detail.
  - **Session control** — REC indicator, live equity chart, 100-agent
    roster grid, manifest counters, moments rail, fills feed; flips to
    live backend data with the chrome's `mock ↔ live` toggle.
  - **Episode review** — finished VOD thumbnail, editable title /
    description, auto chapters from selected beats, tags, schedule +
    upload strip.
- **Standalone broadcast app** (Tauri 2 + React) — fullscreen 1920x1080 window
  with the isometric Agent World XL diorama (continuous camera drift,
  parallax clouds, 2x sprites, CSS CRT toggle), top/bottom tickers
  (top has a 30-tick equity sparkline + countdown ring to the next
  tick), stat pillar, promotion toasts and template-driven commentary
  captions. **Broadcast OS** (0.15.0) consumes the canonical
  `broadcast_moment` event and applies priority/TTL/cooldowns to one
  active slot per output type. Designed for OBS Window Capture. Native
  exe + MSI/NSIS installers
- **Broadcast OS extras** (0.16.0 - 0.17.0):
  - Lower-thirds builder — dedicated `lower_third` WS event with a
    recent-rows ring buffer (`GET /api/admin/lower_third/recent`) and
    a quick-input form on the dashboard
  - TTS settings UI — runtime-mutable provider (openai / elevenlabs /
    silence) with voice dropdown, rate slider, save/reset/preview
  - WS event recording — `WsRecorder` writes every `/ws` frame to
    `data_cache/ws_recordings/<session_id>.ndjson` for replay
- **WebSocket feed** — tick / fill / account / heartbeat / agent_decisions_batch
  / promotion / demotion / stream_state / pipeline_progress events pushed
  to the UI. Single WebSocket per tab via the `<LiveProvider>` context
- **Alpaca reconciler** — polls Alpaca every 10s, computes actual-vs-optimistic
  fill delta, applies idempotent cash + avg-price corrections to the virtual book
- **Admin console** — runtime-editable config (persists to `.env`):
  master AI switch, LLM provider/model/keys (3 providers, live model
  discovery), LSTM confidence gate, tick interval, RTH gating, intraday
  path, daily LLM spend cap, daily recap master switch, podcast master
  switch, execution mode, strategy toggles, backtest launcher, danger
  zone (clear `.env`, force-resync)

## Architecture

```
src/tradefarm/
├── academy/         # ranks (intern/junior/senior/principal), rank-gated
│                    #   capital multipliers, curriculum auto-promote/demote,
│                    #   promotions repository
├── agents/          # base, momentum, lstm_agent, lstm_llm_agent, retrieval
│                    #   (similar past setups), features (19 engineered),
│                    #   lstm_model (torch), lstm_train (CLI),
│                    #   llm_overlay + providers, backtest
├── api/             # FastAPI app, admin + backtest + audience + market_clock
│                    #   + recap + stream_control routers, ws endpoint,
│                    #   events bus
├── data/            # EODHD client (with parquet cache), symbol universe
├── execution/       # Broker protocol, SimulatedBroker, AlpacaBroker,
│                    #   VirtualBook (Decimal money), OrderReconciler
├── market/          # NYSE calendar / RTH helper
├── orchestrator/    # tick loop + scheduler + reconciler + curriculum +
│                    #   BroadcastSuite (AutoDirector, StreakWatcher,
│                    #   CommentaryLoop, PredictionsBoard,
│                    #   AudienceCoordinator, YouTubeChatPoller) +
│                    #   broadcast_os / scheduler / recap / decision_feed
├── render/          # VOD pipeline: headless playwright capture, stitch
│                    #   (ffmpeg concat), mix (audio bed + voiceover)
├── risk/            # per-symbol cap, portfolio SL/TP/time-stop/trailing
├── runtime/         # cross-cutting helpers: clock (replay-aware), http
│                    #   (shared httpx.AsyncClient), llm_budget (daily USD
│                    #   ceiling), money (Decimal coercion), session_context
├── script/          # VOD: LLM-generated narration from selected beats
├── session/         # VOD headless driver: run, beats, manifest,
│                    #   replay, replay_query, closing_snapshot
├── storage/         # SQLAlchemy async models + repo + journal
├── thumb/           # VOD: thumbnail frame grab + overlay
├── tools/           # one-shot helpers (youtube_auth refresh-token capture)
├── tts/             # VOD: streaming TTS via OpenAI-compatible endpoint
├── yt/              # VOD: chunked resumable upload + metadata
├── config.py        # pydantic-settings (Settings)
└── __init__.py
web/                 # Vite + React 19 + Tailwind v4 dashboard
                     #   src/dash/   — multi-page dashboard (Today,
                     #                 Episodes, Research, Admin) +
                     #                 tweaks panel + theme tokens
                     #                 (studio-dark / studio-light / amber-crt)
                     #   src/vod/    — VOD Studio (Beat picker, Pipeline,
                     #                 Session control, Episode review)
                     #   src/{App,components,hooks}/  — legacy single-page UI
                     #                 (still mounted at #legacy)
stream/              # Tauri 2 broadcast app (1920x1080 multi-scene rotator
                     #   for OBS Window Capture, with Web Audio cues).
                     #   src/broadcast/  — rotator + scenes (Hero, Leaderboard,
                     #                      Brain, Strategy, Recap) +
                     #                      v1/ (sports-broadcast layout)
tests/               # pytest — virtual book, journal, ranks, retrieval,
                     #   curriculum, risk-exits, render, tts, yt, runtime
scripts/             # make_favicon.py
docs/                # vod-build-roadmap.md, vod-pivot.md,
                     #   session-runner-spec.md, broadcast_os.md
dev/                 # design notes — feature-backlog.md, audit-findings.md,
                     #   _archive/ (plan_product.md, plan_tech.md,
                     #   PROJECT_PLAN.md, design_handoffs_2026-04/,
                     #   screenshot_*.py)
```

**Decision flow per tick**:

```
EODHD bars → features (19) → LSTM(30, seq_len=30)
                                   ↓
                          direction + max_prob
                                   ↓
           max_prob < 0.40  →  skip LLM, synthetic "wait"
                                   ↓
                          LlmOverlay (Anthropic | MiniMax)
                                   ↓
                    bias / predictive / stance / size_pct / reason
                                   ↓
                              RiskManager
                                   ↓
                   Broker (Simulated | AlpacaBroker)
                                   ↓
                VirtualBook (with reconciler deltas)
```

## Requirements

- Python 3.12+ (tested on 3.13 and 3.14)
- Node 20+
- [uv](https://github.com/astral-sh/uv) for Python deps
- API keys:
  - [EODHD](https://eodhd.com/cp/dashboard) — free tier OK for EOD only
  - [Alpaca Paper](https://app.alpaca.markets/paper/dashboard/overview) — free
  - At least one LLM: [Anthropic](https://console.anthropic.com/settings/keys)
    or [MiniMax](https://platform.minimaxi.com)
- Optional (for the broadcast app): Rust 1.77+ via
  [rustup](https://rustup.rs/), plus the Microsoft WebView2 runtime (already
  installed on Windows 11)
- **For the VOD pipeline** (`tradefarm.session.*`, `tradefarm.render.*`,
  `tradefarm.tts.*`, `tradefarm.thumb.*`, `tradefarm.yt.*`):
  - **ffmpeg** on PATH (stitcher + mixer + thumbnail frame-grab all shell
    out to it). Windows: `winget install Gyan.FFmpeg`. macOS: `brew install
    ffmpeg`. Linux: distro package.
  - **`vod` extra** (`uv sync --extra ml --extra dev --extra vod`) which
    pulls Playwright.
  - **Chromium**: `uv run playwright install chromium` (one-time, ~150 MB).

## Setup

```bash
git clone git@github.com:packetloss404/tradefarm.git
cd tradefarm

# Root deps (concurrently launcher for `npm run dev`)
npm install

# Python deps. Add --extra vod for the VOD pipeline (see prereqs above).
uv sync --extra ml --extra dev

# Copy and fill env
cp .env.example .env
# …edit .env with your keys

# Train per-symbol LSTM models (~15 min for the 40-ticker universe)
uv run python -m tradefarm.agents.lstm_train --universe

# Frontend deps
cd web && npm install

# Broadcast app deps (optional — only if you'll stream)
cd ../stream && npm install
```

## Run

Two processes for normal use, three if you also want the broadcast window.

```bash
# Backend (from project root)
uv run uvicorn tradefarm.api.main:app --host 127.0.0.1 --port 8000 \
                                      --reload --reload-dir src

# Dashboard (from web/)
cd web && npm run dev
# → http://localhost:5179/

# Broadcast app (from stream/) — native window for OBS capture
cd stream && npm run tauri dev          # native dev window with hot reload
cd stream && npm run dev                # browser-only iteration on :5180
cd stream && npm run tauri build        # release exe + MSI + NSIS installers
```

Inside the broadcast window: **Ctrl+I** opens Admin (settings + Quit), **F11**
toggles fullscreen, **Esc** closes overlays.

## CLI utilities

```bash
# Backtest one symbol (~2s)
uv run python -m tradefarm.agents.backtest --symbol SPY

# Backtest the whole universe (~60s)
uv run python -m tradefarm.agents.backtest --universe

# Regenerate favicon / logo
python scripts/make_favicon.py
```

## Admin panel

Header → **Admin**. Live-editable sections:

| Section          | Controls                                                    |
|------------------|-------------------------------------------------------------|
| AI Control       | Master on/off switch, daily recap master switch, podcast master switch |
| Brain Provider   | 3 API key fields (Anthropic, OpenAI, MiniMax — all rendering unconditionally), base URLs |
| LLM Model        | Per-provider model picker driven by live `/v1/models` discovery (60-min cache); 8 strategies + cost hints in the Strategies section below |
| Tuning           | Min LSTM confidence, daily LLM spend cap dial, tick interval, intraday path toggle, outside-RTH toggle |
| Strategies       | Per-strategy freeze toggles (8 strategies) with live agent counts |
| Execution        | `simulated` ↔ `alpaca_paper` (set in `.env`; requires restart) |
| Backtest         | Launch walk-forward backtest, sortable results              |
| Academy          | Rank multipliers + min-trades / min-win-rate / min-Sharpe thresholds; eval interval; demote drawdown + consecutive-loss + cap |
| Risk             | Stop-loss, take-profit, trailing-stop, max-hold-days        |
| Retrieval        | Top-K similar setups, on/off toggle                         |
| TTS              | Runtime provider switch (openai / elevenlabs / silence), voice dropdown, rate slider, preview + spend |
| VOD Pipeline     | Per-stage en/disable (read-only summary; stage launchers live in VOD Studio) |
| Danger zone      | Clear `.env` overrides, force-resync `tradefarm.db`         |

Changes are applied live and persisted to `.env`. Secrets (API keys, tokens)
are masked on GET; the masked sentinel `••••` is never POSTed back, so typing
into a key field does not clobber the real value.

The legacy single-page `#admin` route (`web/src/dash/Admin.tsx`)
mirrors the same layout — same 8-strategy list (read from
`/admin/config._meta.known_strategies`), same LLM model picker
component, same `openai` provider option.

## Key API endpoints

| Endpoint                              | Purpose                            |
|---------------------------------------|------------------------------------|
| `GET /health`                         | Liveness                           |
| `GET /readiness`                      | DB + scheduler + last-tick freshness (503 on degraded) |
| `GET /metrics`                        | Prometheus text exposition         |
| `GET /account`                        | Aggregate KPIs                     |
| `GET /agents`                         | Full 100-agent snapshot            |
| `GET /agents/{id}/trades?limit=N`     | Per-agent trade history            |
| `GET /agents/{id}/notes?limit=N`      | Per-agent journal notes            |
| `GET /agents/{id}/retrieval-preview`  | Top-K similar past setups + outcomes |
| `GET /agents/{id}/academy`            | Per-agent rank + history           |
| `GET /agents/{id}/promotions`         | Per-agent promotion log            |
| `GET /pnl/daily?days=N`               | Daily equity rollup                |
| `GET /pnl/by-strategy`                | Per-strategy attribution           |
| `GET /pnl/by-strategy/timeseries`     | Per-strategy equity over time (0.20.0: pre-aggregated via `strategy_daily_attribution` snapshot table) |
| `GET /decisions/recent`               | 0.19.0: persistent per-agent decision-lab feed (`?limit=`, `?agent_id=`, `?only_llm=`) |
| `GET /orders?limit=N`                 | Recent Alpaca paper orders         |
| `GET /llm/stats`                      | LLM call vs skip counters          |
| `GET /tts/stats`                      | TTS spend counter (chars, cost, calls) |
| `GET /llm/models?refresh=true|false`  | 0.18.0: live `/v1/models` discovery (60-min cache); demo catalog fallback when keys missing |
| `POST /llm/select`                    | 0.18.0: set active provider + model |
| `POST /llm/reset`                     | 0.18.0: clear the active override  |
| `GET  /tts/status` / `POST /tts/switch|reset|preview` | 0.17.0: runtime TTS provider switch |
| `GET  /admin/lower_third/recent` / `POST /admin/lower_third/push` | 0.17.0: lower-thirds ring buffer |
| `POST /ws_recording/start|stop` + `GET /ws_recording/list` | 0.17.0: NDJSON record of every `/ws` frame |
| `GET /academy/ranks`                  | All 100 agent ranks                |
| `GET /academy/promotions`             | Promotion ledger                   |
| `POST /academy/evaluate`              | Force a rank-evaluation pass       |
| `GET /market/clock`                   | RTH phase + next open/close        |
| `GET /recap/today`                    | Live read for the Today dashboard surface |
| `GET /audience/pin-requests`          | Pending audience pin requests      |
| `GET /audience/predictions`           | Predictions board state            |
| `GET /backtest`                       | List backtest jobs                 |
| `POST /backtest/run`                  | Kick off backtest job              |
| `GET  /backtest/{job_id}`             | Backtest progress + results        |
| `DELETE /backtest/{job_id}`           | Cancel a running backtest          |
| `POST /stream/cmd`                    | Push command to the broadcast app  |
| `POST /tick`                          | Force a tick                       |
| `GET /admin/config`                   | Runtime config (secrets masked)    |
| `POST /admin/config`                  | Patch config, persist to `.env`    |
| `POST /admin/toggle-ai?enabled=bool`  | Master kill switch                 |
| `WS   /ws`                            | Live event stream                  |

Mutating endpoints (`POST`/`PUT`/`PATCH`/`DELETE`) require the
`X-TradeFarm-Token: <API_SHARED_SECRET>` header when the backend is bound
to a non-loopback host; loopback stays open for local dev. See
[CLAUDE.md Gotcha 12](./CLAUDE.md) for the fail-fast bind rule.

## Streaming setup

The broadcast app (`stream/`) renders the same data as the dashboard but
re-laid-out for a 1080p capture and rotates between five scenes:

- **Hero** — left stat pillar (top 5 / pool PnL / biggest fill / roster) +
  isometric Agent World XL diorama (slow camera drift, parallax clouds,
  2x sprites, **camera dolly** that eases toward the agent with the
  biggest fill for 2s on every notable trade, **speech bubbles** that
  show the LLM's `last_decision.reason` above the matching sprite for 6s,
  **promotion cutscene** that runs a halo + 8-particle burst for 1.5s on
  every rank-up).
- **Leaderboard** — full ranked list of every agent in 4 columns with
  mini PnL bars.
- **Brain** — 3×4 cards of recent LLM decisions, each with LSTM
  probability bars and the overlay's stance / bias / size / reason.
- **Strategy** — per-strategy attribution: equity, realized / unrealized
  PnL, profit/loss/wait counts.
- **Live Recap** (0.16.0) — auto-shown at 4pm ET, summarizes the day's
  leader + key moments.

Persistent overlays across all scenes: top equity/PnL ticker (with a
30-tick rolling sparkline + countdown ring to the next tick),
marquee bottom ticker (fills + rank changes), promotion toast,
commentary caption, and (if enabled) Web Audio: tick kicks, sonified
fills, promotion stingers. The **CSS CRT toggle** (scanlines + chroma
fringe + radial vignette) is one click away in the in-app Admin.

A configurable pre-roll opener ("TradeFarm — Day N") fades in on launch.
Cycle interval, pre-roll length, and audio volume are adjustable from
the in-app **Ctrl+I** Admin overlay. See
[`dev/feature-backlog.md`](./dev/feature-backlog.md) for the
unshipped backlog (TTS narrator, 30-sec social cut, OBS WebSocket
integration, hourly newsroom bulletin, etc.). Day/night sky, weather,
and the 0.18.0 provider model picker shipped; broadcast OS
scheduler (0.15.0) and the recap scene (0.16.0) are the canonical
`broadcast_moment` consumers.

```bash
cd stream
npm run tauri build         # produces:
#   src-tauri/target/release/tradefarm-stream.exe         (~10 MB)
#   src-tauri/target/release/bundle/msi/*.msi             (~3 MB)
#   src-tauri/target/release/bundle/nsis/*-setup.exe      (~2 MB)
```

Point OBS at the `tradefarm-stream` window (Window Capture). The default
backend URL is `http://127.0.0.1:8000`; override via the in-app Admin
overlay (Ctrl+I) to point at a separate trading host.

## Documentation

- [CHANGELOG.md](./CHANGELOG.md) — release history grouped by date.
- [ROADMAP.md](./ROADMAP.md) — what's next, by horizon (now / next / later).
- [docs/vod-build-roadmap.md](./docs/vod-build-roadmap.md) — VOD pipeline
  build plan (Sessions 1-10, mostly shipped).
- [docs/vod-pivot.md](./docs/vod-pivot.md) — narrative behind the
  pivot from live broadcast to daily VOD.
- [dev/_archive/PROJECT_PLAN.md](./dev/_archive/PROJECT_PLAN.md) —
  4-phase Agent Academy delivery plan (shipped; kept as design archive).
- [dev/_archive/plan_tech.md](./dev/_archive/plan_tech.md) — engineering
  planning archive.
- [dev/_archive/plan_product.md](./dev/_archive/plan_product.md) — UX
  planning archive.
- [dev/feature-backlog.md](./dev/feature-backlog.md) — single
  cross-surface backlog (stream + dashboard) with shipped log, active
  queue, and idea pool.
- [dev/audit-findings.md](./dev/audit-findings.md) — most recent
  20-agent codebase audit + status of every finding.
- [CLAUDE.md](./CLAUDE.md) — coding conventions, gotchas, and run
  commands for AI assistants working in this repo.

## Cost notes

At default settings (24/7 ticking, 33 LSTM+LLM agents, 5-minute interval, Haiku 4.5
with the 0.40 confidence gate): roughly **$3/day** Claude + **$0.65/day** EODHD
subscription. Flip `TICK_OUTSIDE_RTH=false` to drop to roughly **$1.35/day** by
only ticking during market hours. See `/llm/stats` and `/tts/stats` for the
live call-vs-skip rate and TTS spend counter.

Operator-tunable env vars (defaults shown):

| Env var | Default | What |
|---|---|---|
| `LLM_PROVIDER` | `anthropic` | Provider dispatch (`anthropic` / `openai` / `minimax`) |
| `DEFAULT_LLM_MODEL` | `claude-haiku-4-5-20251001` | Per-provider default model (overridden live in admin) |
| `DAILY_LLM_SPEND_CAP_USD` | `13.10` | Soft cap surfaced in the dashboard's spend widget |
| `INTRADAY_ENABLED` | `false` | 0.24.0: refresh marks from EODHD 5m bars (paid tier) |
| `INTRADAY_PERIOD` | `5m` | EODHD intraday period (1m / 5m / 1h) |
| `DAILY_RECAP_ENABLED` | `true` | 0.16.0: master switch on the 4pm-ET recap scheduler |
| `PODCAST_ENABLED` | `false` | 0.16.0: master switch on the Sunday Rivalry Week podcast |
| `PODCAST_TTS_PROVIDER` | `openai` | TTS voice for the podcast narration |
| `PODCAST_FIRE_HOUR_ET` | `9` | Sunday hour the podcast fires (ET) |
| `BROADCAST_RECORD_MOMENTS` | unset | 0.16.0: NDJSON path for the moment-record ledger (debug) |

## Licence

MIT.

## Credits

- Concept: [IMMT AI Trading World](https://youtube.com/@immtinvest)
- Models: Anthropic Claude, MiniMax
- Data: EODHD
- Execution: Alpaca
