# TradeFarm — Operator Runbook

What to do when things go wrong. Pair this with [CLAUDE.md](./CLAUDE.md)
(developer gotchas) and [dev/audit-findings.md](./dev/audit-findings.md)
(known-issue catalog).

---

## 1. Quick triage

When something looks wrong, hit these three URLs first:

```
http://localhost:8000/health        # process is alive (200 = ok)
http://localhost:8000/readiness     # DB + scheduler + last-tick freshness
http://localhost:8000/metrics       # Prometheus counters (LLM cost, tick rate, errors)
```

`/readiness` returns 503 with `failed_checks: {…}` when any of these
fail: DB unreachable, orchestrator not initialized, last tick > 3×
the configured interval, scheduler task dead.

---

## 2. Failure → fix matrix

| Symptom | Likely cause | Fix |
|---|---|---|
| Dashboard shows "no data" or stale equity | Backend dead or scheduler loop crashed. | `/readiness` will identify which. If `scheduler_task: dead`, check `.backend.log` for the traceback and restart. If `db: error`, see §5. |
| Last tick > 30 min old | `auto_tick_interval_sec=0` in `.env` OR scheduler loop crashed silently. | Check `/admin/config` → `auto_tick_interval_sec`. Should be ≥60 (default 300). Fix via admin panel + `persist=true`. |
| LSTM+LLM agents stuck on `stance=wait` | `llm_overlay_init_failed` at boot (bad API key) OR daily budget exhausted (Round-5 BB). | Check `/llm/stats` for `overlay_state` + `budget`. If `blocked_today > 0`, the daily ceiling tripped — bump `llm_daily_budget_usd` in `.env` or wait until UTC midnight. |
| `llm_error` events on the WS bus | Provider API down OR auth expired. | Check `/llm/stats`; rotate the relevant key via admin panel (Anthropic/MiniMax key rotation is zero-downtime; YouTube refresh-token needs `youtube_auth` + restart). |
| Backtest stuck | One of the parallel sym backtests hangs on EODHD. | `GET /backtest/{job_id}` shows `current`. Cancel via `DELETE` (best-effort), restart backend if cancel doesn't take. |
| Reconciler logging `reconcile_fetch_failed` | Alpaca paper API is unreachable. | Wait it out — reconciler retries every 10s with exponential cushion. Idempotent on `broker_order_id` (DB UNIQUE), no risk of double-counting on recovery. |
| `db_path_unexpected` in logs | Backend launched from a directory other than project root (CLAUDE.md gotcha #1). | Stop the backend, `cd D:\projects\tradefarm`, restart. |
| `out/` directory ballooning | Stitcher intermediates not cleaned. | `rm -rf out/sessions/*/.stitch-intermediates/` is safe (recreated on next stitch). The reels/clips/manifest under `out/sessions/<id>/` are the source-of-truth. |
| Stream broadcast frozen on "MARKETS CLOSED" splash | Stuck-preroll bug (see memory: `bug_preroll_never_completes`). | Hard-refresh the Tauri window; check `stream/src/components/PreRollScene.tsx`. Long-term: pinned to be fixed before next broadcast. |
| `playwright is not installed` from VOD pipeline | Missing `vod` extra OR Chromium not installed. | `uv sync --extra vod && uv run playwright install chromium`. |
| `ffmpeg not available` from stitcher/mixer/thumb | System ffmpeg missing. | Windows: `winget install Gyan.FFmpeg`. macOS: `brew install ffmpeg`. Linux: distro pkg. |

---

## 3. Cost containment

The two cost surfaces:

1. **Anthropic / MiniMax LLM**. Set `llm_daily_budget_usd` in `.env`
   (or via admin panel). Once tripped, agents skip the LLM and fall
   back to LSTM-only until the UTC day rolls over. `/metrics` exposes
   `tradefarm_llm_budget_spent_usd`; set a Grafana alert at 80% of
   ceiling.
2. **EODHD**. Free tier is 100k calls/day. Each `tick_once` loads
   per-symbol bars; with the cache hit, that's ~zero requests/tick.
   First boot of the day refetches today's bar for every symbol
   (~40 requests) per the audit-fix "today's bar is provisional".
   No automated ceiling — monitor at the provider dashboard.

YouTube Data API quota (10k units/day default): the chat poller is
1 unit per call honoring `pollingIntervalMillis` (3-5s). One upload
is ~1.6k units. A typical day is ~3k units. Request a quota increase
for all-day streaming.

---

## 4. Secret rotation

| Secret | Rotation path | Restart? |
|---|---|---|
| `ANTHROPIC_API_KEY` | Admin panel → BRAIN PROVIDER → API key | No (`reload_llm_overlay` swaps live) |
| `MINIMAX_API_KEY` | Admin panel (provider = MiniMax) | No |
| `ALPACA_API_KEY` / `_SECRET` | Edit `.env`, restart | Yes |
| `EODHD_API_KEY` | Edit `.env`, restart | Yes |
| `YOUTUBE_REFRESH_TOKEN` | `uv run python -m tradefarm.tools.youtube_auth`, edit `.env`, restart | Yes |
| `API_SHARED_SECRET` | Edit `.env`, restart (this rotates the dashboard token too) | Yes |

The admin-panel rotations log to `.backend.log` with `key=*_API_KEY`
and emit `env_persist_failed` if `.env` couldn't be written; the
admin POST response includes `persisted: {key: bool}` so the operator
sees the result.

---

## 5. Database recovery

The system of record is a single SQLite file: `tradefarm.db` at project
root. Back it up daily:

```bash
uv run python -m scripts.backup_db --retain 30
```

This writes `backups/tradefarm-YYYYMMDD-HHMMSS.db` and prunes copies
older than 30 days. Uses SQLite's online backup API (safe to run
while the backend is writing). Schedule via Task Scheduler / cron at
00:30 UTC.

To restore: stop the backend, `cp backups/<chosen>.db tradefarm.db`,
restart. The orchestrator rehydrates agent state from the DB at boot.

If the live DB is corrupt: SQLite's `pragma integrity_check;`
identifies the damage. `sqlite3 tradefarm.db ".recover" | sqlite3
tradefarm-recovered.db` salvages most rows.

---

## 6. Split-machine topology

Per CLAUDE.md, the broadcast VM runs `npm run broadcast`
(uvicorn 0.0.0.0:8000 + Tauri stream) and the workstation runs
`npm run dashboard` (Vite 5179 + `TRADEFARM_BACKEND=<vm-ip>:8000`).

- The stream Tauri shell hardcodes `ws://127.0.0.1:8000/ws` — it
  must be co-located with the backend until `wsUrlOverride` lands.
- The workstation dashboard talks REST + WS via Vite proxy; Origin
  stays `localhost:5179` so the CORS allow-list matches.
- When the VM is reachable at 0.0.0.0, also set `API_SHARED_SECRET`
  in `.env` and pass it via the `X-TradeFarm-Token` header from the
  dashboard's `web/.env.local`. Without that, anyone on the LAN can
  hit `/admin/*` and `/tick`.

---

## 7. Watching the live broadcast

OBS captures the Tauri stream window. If it goes black or stale:

1. Check the Tauri shell process is running (Task Manager / `ps`).
2. Check the backend `/health` from the VM (`curl localhost:8000/health`).
3. Refresh the WS in the Tauri window (Ctrl+R inside the window).
4. If the YouTube live chat poller stops, the WS event `chat_message`
   stream goes silent — `/llm/stats` shows `youtube_chat_running:
   false`. Check the poller's `youtube_chat_refresh_circuit_open`
   warning: a permanently-revoked refresh token requires re-running
   `tools.youtube_auth` and a restart.

---

## 8. VOD pipeline failures

The end-to-end pipeline:

```
session.run → session.beats → render.headless → render.stitch →
script.write → tts.run → render.mix → thumb.gen → yt.metadata →
yt.upload
```

Each stage writes its outputs under `out/sessions/<session_id>/` and
exits non-zero on failure with a structured log. Common stalls:

- `headless` hangs: stream Vite (port 5180) not running, or the
  beat clip's scene URL doesn't include a `data-scene-ready="true"`
  element. The renderer waits up to 20s; check the page in a
  browser at `http://localhost:5180/?scene=<scene_id>`.
- `stitch` fails with "no packets": one of the headless clips is
  shorter than the planned trim window. Re-run `render.headless`
  with `--scene-ready-timeout 30000` if scene-ready was slow.
- `yt.upload` 308 stall (audit-fix P): YouTube reports incomplete
  with no Range header. The chunked PUT will retry the same offset
  up to 5 times and bail with a clear error. Re-run after checking
  network/quota.

For a completely fresh re-run, delete the relevant artifacts:

```bash
rm -rf out/sessions/<sid>/clips out/sessions/<sid>/*.mp4 \
       out/sessions/<sid>/script.json out/sessions/<sid>/vo \
       out/sessions/<sid>/thumb.jpg out/sessions/<sid>/episode.yaml
```

Leave `manifest.json` + `beats.json` alone — those are session-runner
outputs and re-running `session.run` is the slowest step.

---

## 9. When in doubt

```
git log --oneline -n 20          # what changed recently
git status                       # uncommitted state
tail -200 .backend.log           # most recent backend output
ls -la out/sessions/             # which sessions exist
sqlite3 tradefarm.db ".tables"   # DB schema sanity
```

If the system is fundamentally wedged: stop everything (Ctrl+C on
`npm run dev` or kill each process), `git stash` any local changes,
`git pull origin main`, restart. The DB survives.

If you broke `.env` editing: the file format is `KEY=value` per line,
no quotes (we use `dotenv.set_key(quote_mode="never")`). Comments
start with `#`. The admin panel now rejects newline/CR/NUL injection
attempts in any value (audit fix HIGH-1), so a typo is recoverable
by hand-editing the file.
