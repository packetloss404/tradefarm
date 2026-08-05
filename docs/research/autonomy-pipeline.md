# Autonomy pipeline — research + build plan

research date: 2026-08-04 (post-0.7.0)
scope: end-to-end flow from "day done" to "video on youtube" with no human in the loop.

## tl;dr

- **the pipeline is built, the trigger is not.** every stage is shipped and tested (`render/pipeline.py`), but nothing in the codebase fires it on a schedule. `orchestrator/scheduler.py:685` `run_scheduled()` only ticks the trading sim — zero references to the render/api pipeline modules anywhere in the orchestrator.
- **uploads are dry-run by default, by design.** `render/pipeline.py:288` and `api/pipeline.py:144` both hardcode `upload_dry_run=True` / "never actually upload from the UI; explicit opt-in only". so "autonomy" is blocked at the publish step until the operator flips the policy.
- **run state is in-memory only.** `api/pipeline.py:94` — `_RUNS: deque(maxlen=20)`. a backend restart wipes the audit trail; nothing survives in the DB.
- **tts is opt-in too.** `render/pipeline.py:261` — `tts.enabled_by_default=False`. the chain runs without VO by default; a "fully autonomous" reel ships with no narration unless creds are present *and* the operator opted in.
- **recap scene is excluded for replays.** `render/headless.py:32` skips the recap beat by default because `/api/recap/today` isn't replay-aware. means the final beat (the "wrap the day" beat) is missing from every VOD until that's fixed.

## what's already there

8-step chain. all in `src/tradefarm/`. all ship in 0.7.0. all tested in isolation.

| # | step | module | cli | state |
|---|---|---|---|---|
| 1 | replay the sim | `session/run.py:36` `run_session()` | `python -m tradefarm.session.run --date YYYY-MM-DD` | works. ref-date validation in place (`session/run.py:88-99`). writes `manifest.json` + `Trade`/`AgentNote` rows tagged with `session_id`. |
| 2 | score beats | `session/beats.py` | `python -m tradefarm.session.beats <sid>` | works. 8 beat kinds, 8–15 target beats per session, pure function of the manifest. |
| 3 | render clips | `render/headless.py:411` `render_session()` | `python -m tradefarm.render.headless <sid>` | works. **gated on `stream/` Vite at `localhost:5180`** (the headless URL builder hardcodes that base, `render/headless.py:58`). one playwright context per beat, ~30s per beat at 60× speed. recap kind skipped by default. |
| 4 | stitch clips | `render/stitch.py` | `python -m tradefarm.render.stitch <sid>` | works. two-pass: per-clip trim+normalise, then chained xfade. pairwise fallback if the chained graph blows up. burn-in captions via `drawtext`. |
| 5 | tts | `tts/run.py:316` `run_tts()` | `python -m tradefarm.tts.run <sid> --provider auto` | works. providers: `elevenlabs` / `openai` / `silence`. auto-picks by env key. idempotent: existing wavs reused. |
| 6 | mix | `render/mix.py:356` `mix_session()` | `python -m tradefarm.render.mix <sid> --music …` | works. one ffmpeg invocation, video is stream-copied from `silent_reel.mp4`. sidechain-ducked music bed. |
| 7 | metadata | `yt/metadata.py:209` `build_episode_meta()` | `python -m tradefarm.yt.metadata <sid>` | works. computes chapter markers, default `publish_at` is next 16:30 ET (`yt/metadata.py:186` `default_publish_at()`). chapter math requires ≥3 rendered beats (`yt/metadata.py:135-137`). |
| 8 | upload | `yt/upload.py:283` `upload_episode()` | `python -m tradefarm.yt.upload <sid>` | works. real OAuth (refresh-token dance at `yt/upload.py:79`), 8 MiB chunked resumable PUT (`yt/upload.py:166-255`), thumbnail side-load. |

composers:

- **cli runner**: `render/pipeline.py:393` `run_pipeline()` — chains the 8 in-process, prints banners, skip-on-outputs-present, `--force` to re-run.
- **http wrapper**: `api/pipeline.py:301` `POST /pipeline/run` + `api/pipeline.py:334` list + `api/pipeline.py:340` get-one. runs the chain in `asyncio.to_thread` so the event loop stays responsive (`api/pipeline.py:248`). publishes `pipeline_progress` ws events to the existing event bus (`api/pipeline.py:179-219`).
- **v0.7.0 dashboard surface**: `web/src/vod/derivePipelineNodes.ts` (per changelog `f1e31a8`) — 10-card subsystem grid that maps each prototype card to a real pipeline step. `RunPanel` polls `GET /pipeline/runs/{id}` every 2s.

## what's missing for full autonomy

each gap: severity, why it matters, smallest fix.

### trigger — blocker
nothing schedules the run. `orchestrator/scheduler.py:685` `run_scheduled()` ticks the trading sim every `auto_tick_interval_sec` during rth; it has zero coupling to the render pipeline (no imports of `tradefarm.render.pipeline` or `tradefarm.api.pipeline` anywhere in `orchestrator/`). the operator must either click the dashboard button or run `python -m tradefarm.render.pipeline` by hand. **smallest fix:** add a `run_vod_pipeline_scheduled()` loop in the orchestrator's `start_background()` (`orchestrator/scheduler.py:749`) that fires once per nyse session, gated on `is_market_open()` + a "session closed ≥ N min ago" condition, with a per-day idempotency key so it doesn't double-fire on a restart. ~50 lines.

### cadence / publish-at — blocker
`yt/metadata.py:186` `default_publish_at()` defaults to "next 16:30 ET" but only when `privacy_status="private"`. the chain has no concept of "wait for 16:30 ET before publishing" — it would upload immediately. and "16:30 ET every weekday" vs "30 min after close" vs "fixed at 17:00" is a product call, not a code call. **smallest fix:** new env var `vod_publish_at_et` (default `16:30`), evaluated by the new scheduler loop above; loop sleeps until that time then fires upload.

### content gating — design call, not code call
the chain has no human-approval pause. episode.yaml is generated, then upload fires. two reasonable shapes:
- **auto-publish, reversible.** upload as `private` with a `publish_at` and let the operator click "publish" in the youtube studio. this is what `yt/metadata.py:186` already half-implements.
- **auto-publish, irreversible.** upload as `unlisted` immediately, and the next dashboard visit promotes to `public`. the `episode.yaml` already carries `privacy_status` (`yt/metadata.py:215`), so the wiring is one env-var flip.
- **fully gated.** stop after `yt.metadata` and require a `POST /pipeline/{run_id}/approve` before upload runs. adds a new endpoint and a paused-state in the run state machine. **smallest fix:** add `vod_require_approval: bool` to `config.py`; if true, the chain stops at `metadata` and the run is marked `awaiting_approval` in the DB row. ~30 lines.

### idempotency + retry — major
- per-step output-presence checks are the only idempotency today (`render/pipeline.py:330` `_has_outputs()`). a 308/401 retry inside a single step is in place (`yt/upload.py:240-253`) but a whole-step crash mid-chain leaves partial state and a manual `--force` is needed.
- the chain has **no backoff, no step-level retry**. one transient Chromium crash mid-render and the whole run dies. **smallest fix:** add a `max_attempts: int = 2` and `retry_backoff_sec: float = 30` to `PipelineOpts` (`render/pipeline.py:127`); wrap each `step.run(argv)` call in a retry loop in `_run_step()` (`render/pipeline.py:358`). ~20 lines.
- the ws event stream is best-effort (`api/pipeline.py:191-217`); if the dashboard is closed mid-run, the log is lost. last 200 lines are buffered per run (`api/pipeline.py:199-201`) but the buffer is in-memory.

### notifications — major
zero notification channels wired. the only "publish happened" signal is the operator polling `GET /pipeline/runs/{id}` or the dashboard's run panel. **smallest fix:** at the end of `_run_pipeline_task` (`api/pipeline.py:227`), if the run is `done` or `failed`, fire a webhook `POST` to `vod_notify_webhook` (env var) with `{run_id, session_id, status, video_id, error}`. ~15 lines. supports discord, ntfy, slack incoming-webhook, custom — anything that accepts a json post.

### monitoring — major
`/metrics` already exposes llm counters and `last_tick_timestamp_seconds` (changelog 0.6.0). zero pipeline counters: no `pipeline_runs_total{status}`, no `pipeline_run_duration_seconds`, no `last_publish_timestamp_seconds`. **smallest fix:** in `_run_pipeline_task` increment a `tradefarm_pipeline_runs_total{status="done"|"failed"}` counter and a histogram on run duration. ~10 lines using the same pattern as the existing llm counters.

### asset persistence — major
artifacts live in `out/sessions/<sid>/` indefinitely on the local box. nothing is uploaded to s3/gcs/yt-data-archive. if the box dies, every published reel and its source clips are gone (the youtube copy survives, but the episode.yaml / clip / manifest / beats do not). **smallest fix:** on `done` state, `tar` the `out/sessions/<sid>/` tree minus `clips/*.webm` (large) and `intermediates/` (re-derivable) and rsync to a backup path or upload to a bucket via the existing `scripts/backup_db.py` pattern. ~40 lines.

### failure recovery — nice-to-have
a failed friday run leaves partial state in `out/sessions/<sid_friday>/`. monday's run starts fresh with a new `session_id` — no harm. but the friday artefacts are orphaned and the run is lost from `_RUNS` after 20 entries. **smallest fix:** the same db-backed run state that fixes the notifications gap (see below) also fixes this.

### stream liveness probe — nice-to-have
`render/headless.py:411` `render_session()` will hang for `goto_timeout_ms=30_000` per beat if the stream Vite server isn't up (`render/headless.py:69`). a 10-beat session with no stream means a 5-minute hang, not a fast fail. **smallest fix:** probe `GET http://localhost:5180/` once at the start of the headless step; bail with a clear error if the response isn't 200. ~5 lines.

### thumbnail — nice-to-have
`yt/metadata.py:259` looks for `out/sessions/<sid>/thumb.jpg` but **no stage produces it**. the upload still works without a thumbnail (the api/pipeline.py wrapper handles the missing file), but every published video gets youtube's auto-thumbnail. **smallest fix:** add a `render.thumbnail` step (or fold it into `yt.metadata`) that runs `ffmpeg -i silent_reel.mp4 -ss 1 -vframes 1 -q:v 2 thumb.jpg`. ~20 lines.

### recap scene — nice-to-have
`render/headless.py:32` skips the recap beat because the recap scene's `/api/recap/today` endpoint isn't replay-aware. means the last beat in every VOD is "closing_burst" with no "and that's the day" bookend. **smallest fix:** make the recap endpoint accept `?session_id=&at=` like the rest of the replay chain; drop `recap` from the default skip set in `render/headless.py:177`. ~50 lines endpoint-side.

## quick wins (ship this week)

1. **stream liveness probe** in `render/headless.py:render_session()` — 5 lines, fails fast instead of hanging the run when nobody remembered to start the dev server.
2. **db-backed run state** — replace the `_RUNS` deque in `api/pipeline.py:94` with a `pipeline_runs` table. unblocks monitoring, restart-safety, notifications, and the approval-gate in one move. ~80 lines including migration.
3. **webhook notification** on `done`/`failed` in `api/pipeline.py:_run_pipeline_task` — 15 lines, gives the operator a phone ping on first publish.
4. **per-step retry with backoff** in `render/pipeline.py:_run_step()` — 20 lines, removes the "one transient chromium crash and the whole day is dead" footgun.
5. **thumbnail from silent_reel** — ffmpeg one-liner folded into `yt/mix` or a new tiny `render.thumb` step. 20 lines, every published video gets a real frame instead of yt's auto-thumbnail.

## build plan

ordered by what unblocks the most other work first.

1. **db-backed pipeline run state** — table `pipeline_runs(id, session_id, status, started_at, finished_at, error, last_lines_json)`. the `_RUNS` deque becomes a read-through cache. every later step (monitoring, notifications, approval gate, failure recovery) needs this row. **scope:** ~80 lines + migration. **deps:** none. **success:** restart the backend mid-run, the run row survives.
2. **daily scheduler loop** in `orchestrator/scheduler.py:start_background()`. one new method, one new task, gated on `vod_pipeline_enabled` env var + `is_market_open()`-based "session closed ≥ 5 min ago" predicate + per-day idempotency key in the new `pipeline_runs` table (so a restart on the same day doesn't re-fire). **scope:** ~50 lines. **deps:** #1. **success:** `vod_pipeline_enabled=true` in `.env` and a reel shows up in the `pipeline_runs` table next morning.
3. **webhook notification on terminal state** — one env var `vod_notify_webhook`, one `httpx.post` in `_run_pipeline_task`. fire on `done` (include `video_url`) and `failed` (include `error`). **scope:** ~15 lines. **deps:** #1. **success:** discord/slack channel gets a ping on first publish.
4. **prometheus counters for the pipeline** — `tradefarm_pipeline_runs_total{status}`, `tradefarm_pipeline_run_duration_seconds` histogram. wire into the existing `/metrics` route. **scope:** ~10 lines. **deps:** #1. **success:** `curl /metrics` shows pipeline counters.
5. **per-step retry + backoff** — `max_attempts=2`, `retry_backoff_sec=30` in `PipelineOpts`. wrap `step.run(argv)` in a loop. only retry on transient-looking exceptions (chromium crash, 5xx, httpx timeout); never retry on `SystemExit` from the inner cli. **scope:** ~30 lines. **deps:** none. **success:** kill chromium mid-render, the run recovers.
6. **human-approval gate** — env var `vod_require_approval`. if true, the chain stops after `yt.metadata` and the run row is `awaiting_approval`. new endpoint `POST /pipeline/runs/{id}/approve` resumes at the upload step. **scope:** ~60 lines. **deps:** #1. **success:** `vod_require_approval=true`, the chain halts at `metadata`, a single approve post uploads the reel.
7. **stream liveness probe** in `render/headless.py:render_session()` — `httpx.get(stream_base)` once before the playwright loop; bail with `RuntimeError` if it doesn't 200. **scope:** ~5 lines. **deps:** none. **success:** forgetting to start `stream/` fails the run in 2s instead of 5min.
8. **thumbnail generation** — `ffmpeg -i silent_reel.mp4 -ss 1 -vframes 1 -q:v 2 thumb.jpg`, executed either inside `yt/mix` or as a new tiny step inserted between `mix` and `metadata`. **scope:** ~20 lines. **deps:** none. **success:** every published video has a real thumbnail, not yt's auto-pick.
9. **recap scene replay-awareness** — extend `/api/recap/today` to accept `?session_id=&at=`; drop `recap` from the headless default skip set. ~50 lines endpoint-side, 1-line config change. **scope:** ~50 lines. **deps:** none. **success:** the last beat in the rendered VOD is the recap, not the closing burst.
10. **asset archival** — on `done`, `tar --exclude=clips/*.webm --exclude=intermediates` the `out/sessions/<sid>/` tree and rsync to a backup path or upload to a bucket. **scope:** ~40 lines. **deps:** #1. **success:** a destroyed local box still has the manifest/beats/episode.yaml for every published reel.

## open questions

1. **auto-publish vs human-gate**
   - (a) auto as `private` + `publish_at` next 16:30 ET — youtube holds it; operator clicks "publish" in studio. recoverable.
   - (b) auto as `unlisted` immediately, promote to `public` on next dashboard visit. visible-but-not-surfaced.
   - (c) full human gate — `vod_require_approval=true`, chain stops at `metadata`, `POST /pipeline/{id}/approve` resumes. highest friction, highest trust.
   - tradeoff: (a) is the youtube-native pause button and matches the existing 16:30 ET default. (b) is the lowest-friction auto but irreversible from a "video went out wrong" standpoint. (c) is the only option that gives the operator a real veto before anything leaves the box.
2. **cadence — what time fires the run**
   - (a) fixed `16:30 ET` every weekday (matches `yt.metadata.default_publish_at`).
   - (b) 5 min after `is_market_open()` returns false (i.e. 16:05 ET).
   - (c) cron-style `0 17 * * 1-5` UTC = 13:00 ET (off-hours for the simulator).
   - tradeoff: (a) co-locates with the publish-at so the operator sees the pipeline progress in the same window. (b) is "as soon as data is settled" which is faster but means clips render during the operator's commute. (c) decouples render from publish but makes same-day QA impossible.
3. **tts provider default**
   - (a) `silence` (free, no creds, sounds like a 1950s test pattern) — the default today.
   - (b) `elevenlabs` (~$0.30 per 1k chars, ~$0.50/day at current script lengths).
   - (c) `openai` (~$0.015 per 1k chars, ~$0.03/day, voice quality noticeably worse than elevenlabs flash).
   - tradeoff: (a) is the only free option but a "fully autonomous" reel with no VO is a pretty significant downgrade. (b) is the quality choice at a real cost. (c) is the cost choice with noticeable quality hit. needs a spend cap on whichever cloud provider is picked.
4. **where to archive published assets**
   - (a) keep on local disk; rsync nightly to a backup volume.
   - (b) push to s3/gcs after upload; the youtube copy is the long-term archive, the bucket is the source-of-truth.
   - (c) rely on youtube alone; keep only the latest N sessions on disk.
   - tradeoff: (a) is the smallest change. (b) lets you re-render or re-upload if youtube takes the video down. (c) is the lowest-disk option but every bug-fix on the render path is a "replay from manifest" operation, not a re-render.
5. **notification channel**
   - (a) discord/slack incoming webhook (env var, free, json post).
   - (b) ntfy.sh (one-line `curl -d …` per topic, no account).
   - (c) email via the existing `cloudflare-email-service` skill's worker binding (already in `~/.minimax/skills/`).
   - tradeoff: (a) is the most familiar to the operator and the easiest to test locally. (b) is the lowest-friction mobile ping. (c) is the most "professional" but adds a worker deployment to the release surface.
