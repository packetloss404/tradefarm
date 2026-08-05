# Changelog

All notable changes to this project. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
follows [Semantic Versioning](https://semver.org/) starting from `0.1.0`.

Dates are when the commit landed on `main`. Hashes link to the canonical
commit on GitHub.

## [Unreleased]

- None yet.

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
