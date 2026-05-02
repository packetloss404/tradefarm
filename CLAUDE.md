# CLAUDE.md

Guidance for Claude Code when working on this repo.

## Project in one sentence

100-agent paper-trading sandbox for US equities. Each agent runs one of three
strategies (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`). Stack: Python 3.13 +
FastAPI + SQLAlchemy async + SQLite backend, Vite + React 19 + Tailwind v4
frontend, PyTorch LSTMs, Claude or MiniMax for the LLM overlay.

## Run commands

```bash
# Backend — ALWAYS from project root (it reads ./.env and ./tradefarm.db).
cd /d/projects/tradefarm
uv run uvicorn tradefarm.api.main:app --host 127.0.0.1 --port 8000 \
                                      --reload --reload-dir src

# Frontend — binds localhost:5179 (strictPort=true; don't change).
cd web && npm run dev

# Streaming app (Tauri broadcast — depends on backend at :8000).
# Vite dev server binds 5180; Tauri shell wraps it.
cd stream && npm run tauri dev      # native window
cd stream && npm run dev            # browser-only iteration on http://127.0.0.1:5180

# Tests
uv run pytest -q

# Train LSTM models
uv run python -m tradefarm.agents.lstm_train --universe

# Backtest
uv run python -m tradefarm.agents.backtest --symbol SPY
uv run python -m tradefarm.agents.backtest --universe
```

## Gotchas worth knowing

1. **Backend cwd matters.** `DATABASE_URL=sqlite+aiosqlite:///./tradefarm.db`
   is relative; launching uvicorn from any other directory creates a *new*
   empty `tradefarm.db` at that path and you'll wonder why trades vanished.
   Always `cd /d/projects/tradefarm` first.
2. **Vite port 5179 is intentional, not 5173.** 5173 collides with another
   local project on this machine. `web/vite.config.ts` has `strictPort: true`.
3. **IPv6 binding.** Vite binds `::1` only — use `localhost:5179`, not
   `127.0.0.1:5179`.
4. **Hot-reload occasionally misses new route imports** in `api/main.py`. If
   a newly-added endpoint returns 404, kill and restart uvicorn.
5. **`--reload-dir src` is required.** Without it WatchFiles storms on
   `.venv` churn (torch DLLs, pyc writes) and restarts continuously.
6. **Trained models are 19-feature.** If you ever change `features.py`'s
   `FEATURE_NAMES`, retrain the universe or every inference will shape-mismatch.
7. **Alpaca fills are async.** The scheduler applies an optimistic fill at
   `mark` immediately; the reconciler (in `alpaca_paper` mode) polls every
   10s and applies the actual-vs-mark delta via
   `VirtualBook.apply_fill_delta` (idempotent on `broker_order_id`).
8. **In-memory agent state is not rehydrated on restart.** DB has trades
   and snapshots but Orchestrator.build_default creates fresh books at boot.
   Expect one redundant entry signal per restart until positions re-establish.
9. **LSTM+LLM agents skip the API call** when LSTM max_prob < 0.40 — this is
   intentional (cost gate). `/llm/stats` reports the hit rate.
10. **Writing `.env` via admin panel** uses `python-dotenv.set_key` with
    `quote_mode="never"`. Comma-separated lists (e.g. `DISABLED_STRATEGIES`)
    are the chosen format — don't switch to JSON.

## Architecture landmarks

- **LLM provider dispatch** lives in `src/tradefarm/agents/llm_providers.py`.
  Both providers share `SYSTEM_PROMPT` and the same JSON response schema
  (`llm_overlay_types.py`). Adding a 3rd provider = implement
  `LlmProvider.decide(ctx) -> LlmDecision` and register in `build_provider`.
- **Event bus** is an in-process `asyncio.Queue` fan-out in
  `src/tradefarm/api/events.py`. Frontend subscribes via `/ws`; backend
  publishes via `await publish_event(type, payload)`.
- **Admin mutability** goes through `src/tradefarm/api/admin.py`.
  `EDITABLE` is the allowlist; `SECRET_KEYS` mask on GET. `.env` persistence
  is best-effort (non-fatal on failure; in-memory change still applies).
- **Orchestrator.reload_llm_overlay()** re-points every LSTM+LLM agent at a
  fresh overlay after provider/key/model changes — no restart needed.
- **Reconciler** is started inside `Orchestrator.start_background()` only
  when `execution_mode == "alpaca_paper"`. It uses
  `self._optimistic_marks: dict[client_order_id, mark_price]` which the
  scheduler populates at submit time.

## Conventions

- Python: type hints everywhere, no `# type: ignore` unless a library forces it.
  Structlog for logging (`log.info("event_name", k=v)`). Short docstrings.
- TypeScript: strict mode, no `any`. Components in
  `web/src/components/*.tsx`, hooks in `web/src/hooks/*.ts`. SWR for polling
  REST, `useEventFeed` for live WS slices.
- Tailwind: dark-only theme. Custom colors `--color-profit` (emerald),
  `--color-loss` (rose), `--color-wait` (zinc).
- Tests live in `tests/`. Keep them deterministic (no network, no real LLM).

## Don't

- Don't commit `.env` (has real keys). `.gitignore` covers it.
- Don't delete `models/*.pt` without running the trainer after — agents
  fall back to momentum but the LSTM strategies go silent.
- Don't restart uvicorn with `--reload` watching the whole repo tree; use
  `--reload-dir src`.
- Don't switch from CSV to JSON for list-valued `.env` entries; admin
  persistence depends on the CSV contract.
