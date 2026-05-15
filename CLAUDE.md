# CLAUDE.md

Guidance for Claude Code when working on this repo.

## Project in one sentence

100-agent paper-trading sandbox for US equities. Each agent runs one of three
strategies (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`). Stack: Python 3.13 +
FastAPI + SQLAlchemy async + SQLite backend, Vite + React 19 + Tailwind v4
frontend, PyTorch LSTMs, Claude or MiniMax for the LLM overlay.

## Run commands

```bash
# One-command launcher — backend + dashboard + stream Tauri, color-coded
# in a single terminal. Ctrl+C kills all three. Double-click start.bat
# from Explorer for the same effect.
cd /d/projects/tradefarm
npm install            # one-time: installs concurrently at root
npm run dev            # api + dash + stream (Tauri shell) — local rig
# Unattended runs: autorun.bat / autorun.ps1 wraps `npm run dev` in an
# auto-restart loop so Tauri exits + desktop-sleep cascades don't kill
# the rig. 5 crashes within 60s trips a circuit breaker. Ctrl+C to stop.
npm run dev:headless   # same, but stream as browser-only Vite (use the
                       #   dashboard's "Pop out preview" instead of Tauri)
npm run broadcast      # api (binds 0.0.0.0:8000) + stream Tauri — for the
                       #   broadcast VM. OBS captures the Tauri window.
                       #   Double-click broadcast.bat from Explorer.
npm run dashboard      # dashboard Vite only — for the operator workstation
                       #   when the backend lives on a remote VM. Point it
                       #   at the VM by setting TRADEFARM_BACKEND in
                       #   web/.env.local (see web/.env.example).
npm run stream-only    # stream Tauri only — backend assumed remote.

# Or run each individually (still supported):

# Backend — ALWAYS from project root (it reads ./.env and ./tradefarm.db).
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

## Split-machine topology (VM ↔ workstation)

Three pieces wired so the operator can run the broadcast VM headlessly and
control it from the workstation:

1. **VM**: `npm run broadcast` — uvicorn binds **0.0.0.0:8000** (LAN-reachable)
   plus the stream Tauri locally. OBS captures the Tauri window, streams to
   YouTube. Use `broadcast.bat` for one-click start.
2. **Workstation**: `npm run dashboard` — dashboard Vite only on 5179. Set
   `TRADEFARM_BACKEND=<vm-ip>:8000` in `web/.env.local` so Vite proxies
   `/api` and `/ws` to the VM. Browser still hits `http://localhost:5179`
   (Origin stays localhost → existing CORS allow-list matches; LAN IP
   ranges are also permitted defensively).
3. **Stream WS**: the Tauri shell hardcodes `ws://127.0.0.1:8000/ws` so it
   only works when the backend is on the same machine as the Tauri shell.
   `stream-only` (no co-located backend) needs a future
   `wsUrlOverride` plumbed through settings before it's useful.

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
11. **YouTube chat credentials are `.env`-only.** They're sensitive, so they
    are NOT in `admin.py`'s `EDITABLE` allowlist — the admin panel can't
    leak or mutate them. The poller self-disables when any of them are
    missing; first poll seeds the pagination cursor without publishing so
    a restart doesn't replay chat history.

## YouTube chat setup

The stream broadcasts to YouTube, and we surface the live chat into the
dashboard via the YouTube Data API v3. One-time setup:

1. **Google Cloud Console → APIs & Services → Library:** enable
   *YouTube Data API v3*.
2. **APIs & Services → Credentials:** create an *OAuth 2.0 Client ID* of
   type **Desktop app**. Note the client_id and client_secret.
3. **APIs & Services → OAuth consent screen:** add your YouTube Google
   account under "Test users" (required while the app is in Testing mode).
4. Run the helper to capture a refresh token:
   ```bash
   uv run python -m tradefarm.tools.youtube_auth
   ```
   It will prompt for the client_id / client_secret, open a localhost
   one-shot HTTP server, print an auth URL — open it in your browser, grant
   `youtube.readonly`, and the script prints the refresh token to copy into
   `.env`:
   ```
   YOUTUBE_CHAT_ENABLED=true
   YOUTUBE_CLIENT_ID=...
   YOUTUBE_CLIENT_SECRET=...
   YOUTUBE_REFRESH_TOKEN=...
   ```
5. Restart the backend. The `YouTubeChatPoller` (started inside
   `Orchestrator.start_background`) discovers the active broadcast,
   subscribes to live chat, and publishes each new message as a
   `chat_message` event on the WS bus.

**Quota.** The YouTube Data API v3 ships with a 10,000 units/day default
quota. `liveChatMessages.list` is 1 unit per call; honoring the server's
`pollingIntervalMillis` (typically 3-5s) keeps usage well inside quota for
a sub-12-hr broadcast. For all-day streaming, request a quota increase in
the Google Cloud Console (free).

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
- **YouTube chat poller** lives in
  `src/tradefarm/orchestrator/youtube_chat.py`. Started unconditionally
  from `start_background()`; the poller's own `_enabled()` check keeps it
  dormant unless all four `youtube_*` settings are populated. OAuth refresh
  is handled inline (no `google-auth` dependency); on 401 the poller
  refreshes the access token once and retries. Messages are published as
  `chat_message` events with `source: "youtube"` so the frontend ChatStrip
  can prioritize them over the simulated source.

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
