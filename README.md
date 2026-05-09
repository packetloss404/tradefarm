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
- **Three strategy families** (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`) with
  per-strategy enable/disable toggles
- **LSTM brain** — 2-layer LSTM(64) per symbol with 19 engineered features,
  3-class direction head + confidence head, class-balanced training
- **LLM overlay** — Claude Haiku 4.5 (prompt caching) *or* MiniMax
  M2.7-highspeed (OpenAI-compatible endpoint). Pluggable provider interface
- **Cost gate** — when LSTM max-prob < 0.40, the LLM call is skipped entirely;
  cuts ~78% of API calls with no loss of trades
- **Walk-forward backtester** — per-symbol Sharpe / CAGR / max-drawdown / win-rate,
  launchable from the admin modal
- **Live dashboard** (Vite + React 19 + Tailwind v4) — today PnL, open positions,
  monthly PnL chart, brain activity, strategy attribution, order status,
  100-agent grid with click-through detail modal
- **Standalone broadcast app** (Tauri 2 + React) — fullscreen 1920x1080 window
  with the isometric Agent World hero scene, top/bottom tickers, stat pillar,
  promotion toasts and template-driven commentary captions. Designed for OBS
  Window Capture. Native exe + MSI/NSIS installers
- **WebSocket feed** — tick / fill / account / heartbeat events pushed to the UI
- **Alpaca reconciler** — polls Alpaca every 10s, computes actual-vs-optimistic
  fill delta, applies idempotent cash + avg-price corrections to the virtual book
- **Admin console** — runtime-editable config (persists to `.env`):
  master AI switch, provider/model/keys, LSTM confidence gate, tick interval,
  RTH gating, execution mode, strategy toggles, backtest launcher

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
├── api/             # FastAPI app, admin router, ws endpoint, events bus,
│                    #   backtest router
├── data/            # EODHD client (with parquet cache), symbol universe
├── execution/       # Broker protocol, SimulatedBroker, AlpacaBroker,
│                    #   VirtualBook, OrderReconciler
├── market/          # NYSE calendar / RTH helper
├── orchestrator/    # tick loop, scheduler, reconciler loop, curriculum loop
├── risk/            # per-symbol cap, portfolio SL/TP/time-stop/trailing
└── storage/         # SQLAlchemy async models + repo + journal
web/                 # Vite + React 19 + Tailwind v4 dashboard
stream/              # Tauri 2 broadcast app (1920x1080 multi-scene rotator
                     #   for OBS Window Capture, with Web Audio cues)
tests/               # pytest — virtual book, journal, ranks, retrieval,
                     #   curriculum, risk-exits
scripts/             # make_favicon.py
docs/                # plan_product.md, plan_tech.md, PROJECT_PLAN.md
                     #   (Agent Academy 4-phase synthesis)
dev/                 # design notes — feature-backlog.md (cross-surface)
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

## Setup

```bash
git clone git@github.com:packetloss404/tradefarm.git
cd tradefarm

# Python deps
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

| Section        | Controls                                                    |
|----------------|-------------------------------------------------------------|
| AI Control     | Master on/off switch                                        |
| Brain Provider | Anthropic ↔ MiniMax, API key (masked), model override       |
| Tuning         | Min LSTM confidence, tick interval, outside-RTH toggle      |
| Strategies     | Per-strategy freeze toggles with live agent counts          |
| Execution      | `simulated` ↔ `alpaca_paper`                                |
| Backtest       | Launch walk-forward backtest, sortable results              |

Changes are applied live and persisted to `.env`.

## Key API endpoints

| Endpoint                              | Purpose                            |
|---------------------------------------|------------------------------------|
| `GET /health`                         | Liveness                           |
| `GET /account`                        | Aggregate KPIs                     |
| `GET /agents`                         | Full 100-agent snapshot            |
| `GET /agents/{id}/trades?limit=N`     | Per-agent trade history            |
| `GET /pnl/daily?days=N`               | Daily equity rollup                |
| `GET /pnl/by-strategy[/timeseries]`   | Per-strategy attribution           |
| `GET /orders?limit=N`                 | Recent Alpaca paper orders         |
| `GET /llm/stats`                      | LLM call vs skip counters          |
| `POST /tick`                          | Force a tick                       |
| `GET /admin/config`                   | Runtime config (secrets masked)    |
| `POST /admin/config`                  | Patch config, persist to `.env`    |
| `POST /admin/toggle-ai?enabled=bool`  | Master kill switch                 |
| `POST /backtest/run`                  | Kick off backtest job              |
| `GET  /backtest/{job_id}`             | Backtest progress + results        |
| `WS   /ws`                            | Live event stream                  |

## Streaming setup

The broadcast app (`stream/`) renders the same data as the dashboard but
re-laid-out for a 1080p capture and rotates between four scenes:

- **Hero** — left stat pillar (top 5 / pool PnL / biggest fill / roster) +
  isometric Agent World XL diorama (slow camera drift, parallax clouds,
  2x sprites).
- **Leaderboard** — full ranked list of every agent in 4 columns with
  mini PnL bars.
- **Brain** — 3×4 cards of recent LLM decisions, each with LSTM
  probability bars and the overlay's stance / bias / size / reason.
- **Strategy** — per-strategy attribution: equity, realized / unrealized
  PnL, profit/loss/wait counts.

Persistent overlays across all scenes: top equity/PnL ticker, marquee
bottom ticker (fills + rank changes), promotion toast, commentary
caption, and (if enabled) Web Audio: tick kicks, sonified fills,
promotion stingers.

A configurable pre-roll opener ("TradeFarm — Day N") fades in on launch.
Cycle interval, pre-roll length, and audio volume are adjustable from
the in-app **Ctrl+I** Admin overlay. See
[`dev/feature-backlog.md`](./dev/feature-backlog.md) for the
unshipped backlog (CRT shader, TTS narrator, recap MP4, OBS WebSocket
integration, dashboard upgrades, etc.). Day/night sky and weather
shipped 2026-05-09.

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
- [docs/PROJECT_PLAN.md](./docs/PROJECT_PLAN.md) — 4-phase Agent Academy
  delivery plan (already shipped, kept as design archive).
- [docs/plan_tech.md](./docs/plan_tech.md) — engineering planning doc.
- [docs/plan_product.md](./docs/plan_product.md) — UX planning doc.
- [dev/feature-backlog.md](./dev/feature-backlog.md) — single
  cross-surface backlog (stream + dashboard) with shipped log, active
  queue, and idea pool.
- [CLAUDE.md](./CLAUDE.md) — coding conventions, gotchas, and run
  commands for AI assistants working in this repo.

## Cost notes

At default settings (24/7 ticking, 33 LSTM+LLM agents, 5-minute interval, Haiku 4.5
with the 0.40 confidence gate): roughly **$3/day** Claude + **$0.65/day** EODHD
subscription. Flip `TICK_OUTSIDE_RTH=false` to drop to roughly **$1.35/day** by
only ticking during market hours. See `/llm/stats` for the live call-vs-skip rate.

## Licence

MIT.

## Credits

- Concept: [IMMT AI Trading World](https://youtube.com/@immtinvest)
- Models: Anthropic Claude, MiniMax
- Data: EODHD
- Execution: Alpaca
