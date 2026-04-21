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
- **WebSocket feed** — tick / fill / account / heartbeat events pushed to the UI
- **Alpaca reconciler** — polls Alpaca every 10s, computes actual-vs-optimistic
  fill delta, applies idempotent cash + avg-price corrections to the virtual book
- **Admin console** — runtime-editable config (persists to `.env`):
  master AI switch, provider/model/keys, LSTM confidence gate, tick interval,
  RTH gating, execution mode, strategy toggles, backtest launcher

## Architecture

```
src/tradefarm/
├── agents/          # base, momentum, lstm_agent, lstm_llm_agent,
│                    #   features (19 engineered), lstm_model (torch),
│                    #   lstm_train (CLI), llm_overlay + providers, backtest
├── api/             # FastAPI app, admin router, ws endpoint, events bus,
│                    #   backtest router
├── data/            # EODHD client (with parquet cache), symbol universe
├── execution/       # Broker protocol, SimulatedBroker, AlpacaBroker,
│                    #   VirtualBook, OrderReconciler
├── market/          # NYSE calendar / RTH helper
├── orchestrator/    # tick loop, scheduler, reconciler loop
├── risk/            # per-symbol cap, stop-loss, trailing stop, daily loss
└── storage/         # SQLAlchemy async models + repo
web/                 # Vite + React 19 + Tailwind v4 dashboard
tests/               # pytest (virtual book roundtrips + delta math)
scripts/             # make_favicon.py
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
```

## Run

Two processes. Keep them in separate terminals.

```bash
# Backend (from project root)
uv run uvicorn tradefarm.api.main:app --host 127.0.0.1 --port 8000 \
                                      --reload --reload-dir src

# Frontend (from web/)
cd web && npm run dev
```

Open **http://localhost:5179/**.

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
