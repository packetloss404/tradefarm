# TradeFarm VOD Pivot — what stays, what goes, what's new

Decision date: 2026-05-17.

## Context

The original product was an 8-hour autonomous YouTube live stream of
the trading sandbox: 100 LSTM/LLM/momentum agents trading paper US
equities, narrated by an auto-director, with live YouTube chat
integration and audience interactivity (predictions, sentiment, agent
pinning).

The problem we hit: **content density**. The strategies are
structurally quiet. Even during RTH:
- LSTM agents skip the LLM call below 0.40 max_prob (cost gate)
- momentum_sma20 only fires on cross events
- Daily-bar features mean long WAIT stretches
- Most ticks produce zero fills

We compensated with DecisionLab, broadcast moments rail, audience
interactivity, YT chat fan-out — all real engineering, all real
features, none enough to make 8 hours of *nothing* tolerable.

The decision: stop optimizing for live. **Pivot to a fully-AI-generated
10-15 min daily VOD** ("Today on TradeFarm"), plus periodic devlog
episodes about *building* the autonomous pipeline. TradeFarm becomes
the substrate for a coding-in-public AI engineering portfolio — the
trading sim isn't the show, the show is *the autonomous content
pipeline visibly working (and sometimes failing) on real data*.

Live broadcasts aren't deleted — they're reserved for event days (CPI,
FOMC, earnings spikes) when there's natural drama to react to.

---

## What stays (substrate, mostly unchanged)

- **Orchestrator + agents.** The 100-agent simulation (`scheduler.py`,
  `momentum.py`, `lstm_agent.py`, `lstm_llm_agent.py`). Trading logic
  is the input to the pipeline.
- **Office display names.** Added 2026-05-17 (`agents/names.py`).
  Personalities matter more in a curated edit than a live feed.
- **Virtual book + journal + recap engines.** Source of truth for the
  beat detector to read from.
- **Broadcast moments detection** (`broadcast_os.py`,
  `broadcast_scheduler.py`, `broadcast_recap.py`, `streak_watcher.py`,
  `auto_director.py`). Repurposed: instead of firing live macros,
  these now *score and label* moments for the daily edit's beat picker.
- **LSTM models + LLM overlay.** Unchanged.
- **Recap v2** (the 30-second close-of-day reel). This becomes the
  seed for the full 10-15 min edit — extend it, don't replace it.
- **The broadcast UI scenes** (Hero, Leaderboard, Brain, Decision Lab,
  Strategy, Recap, Showdown). These are the *visual vocabulary* of the
  reel. They need to render headlessly against historical state, not
  live state.

## What goes

- **Live-stream cadence assumptions** in `start.bat`, `autorun.bat`,
  `broadcast.bat`, `npm run broadcast`. These stay for event-day use
  but stop being the default mental model.
- **ChatStrip + simulated chat + YouTube chat integration as a
  primary surface.** YT chat is a live-only thing. Move the YT
  poller behind a `LIVE_EVENT` flag; it stays dormant during VOD
  production. Simulated chat in stream/ becomes optional scene flavor.
- **Audience interactivity layer** for the default flow: predictions
  board, sentiment gauge, audience pin banner. Same as above —
  gated behind `LIVE_EVENT`, default off.
- **PreRollScene's "MARKETS CLOSED" branch** when running in replay
  mode. The reel always shows live-RTH content from the simulated
  session, not idle-state. Keep the component for event streams.
- **Dashboard BroadcastPanel "fire macro now" buttons.** Macros are
  picked by the beat detector during edit, not by a human operator
  in real-time.
- **The `auto_tick_interval_sec` scheduler loop as the primary
  cadence.** The VOD pipeline runs a *session* (e.g. 6.5 hours of
  market activity, time-compressed to 10 min wall-clock) and then
  produces an edit. Continuous live ticking is reserved for event
  streams.

## What's new (the 10 subsystems, in build order)

The autonomous pipeline. Each subsystem is its own deliverable; each
can ship and demonstrate independently.

### Phase 1 — Silent v0 (proves the pipeline works)

1. **Session runner.** Driver that runs a full simulated trading day
   (or replays last week's bars at 10x) headlessly and writes
   journal/snapshot/fill data to disk. Today's `npm run dev` is the
   live-RTH version of this; we need a `npm run session -- --date
   2026-05-15 --speed 10x` flavor.

2. **Beat detector.** Reads the session output and picks 8-15 beats:
   biggest winner, biggest loser, agent rivalry, near-miss decision,
   leaderboard shift, big-cap LLM bet, etc. The existing
   `auto_director`, `streak_watcher`, `broadcast_recap` already score
   moments — extend them to produce a ranked, deduplicated beat list
   with timestamps and `scene_id` hints.

3. **Replay mode in stream/.** Add `?replay=<timestamp>` URL param
   that hydrates the scene rotator from journal state at that
   timestamp instead of live WS. This is the load-bearing
   architectural change. ~1 week of work.

4. **Headless renderer.** Playwright (already proven this session)
   navigates to `localhost:5180/?replay=<ts>&scene=<id>` for each
   beat, takes a video clip (or frame sequence), writes to `out/`.

5. **ffmpeg stitcher.** Concat the per-beat clips with crossfades,
   overlay on-screen captions (no VO yet), drop a music bed, write
   final mp4. Caption text comes from the beat detector's labels.

**End of Phase 1: silent 10-min daily reel, manually uploaded to YT.
Validates the format before sinking effort into TTS and script.**

### Phase 2 — Script + voice

6. **Script writer.** LLM gets the beat list + agent personalities +
   journal excerpts, writes punchy 10-30s narration per beat. This is
   the AI subsystem most likely to produce bland output — budget time
   for iteration. Devlog episode candidate.

7. **TTS narration.** ElevenLabs (premium voice) or OpenAI TTS
   (cheaper) per beat. Output per-beat .wav files keyed by beat_id.

8. **Audio mixer.** ffmpeg sidechain ducking: music bed under VO,
   stingers on transitions. This is genuinely complex; expect a
   devlog episode about it.

### Phase 3 — Publish + storylines

9. **Thumbnail generator.** AI-picks the most dramatic beat's frame,
   overlays a clickable title. Probably DALL-E / SDXL + PIL
   compositing.

10. **YT metadata + upload.** Title, description, chapters (from
    beat timestamps), tags auto-generated. Upload via YT Data API.
    Multi-day storyline tracker maintains running arcs (agent
    rivalries, multi-day winning streaks) so episode N can reference
    episode N-1.

### Phase 4 — Live event mode

When CPI/FOMC/earnings, flip a flag that re-enables ChatStrip,
audience interactivity, YT chat poller. Same UI, different mode.
Low-effort because we kept the components, just gated them.

---

## Risks

- **Replay mode in stream/ is harder than it sounds.** Scenes assume
  live WS deltas — converting to deterministic journal-driven state
  may require a refactor of `useStreamData`, `useStreamCommands`,
  etc. Budget 1-2 weeks.
- **LLM script quality is the make-or-break of Phase 2.** Generic
  recap narration will sink the format. Plan to spend real time on
  prompt engineering / personality voicing and accept that early
  episodes may be public learning.
- **Audio mixing is underestimated.** Automated ducking + stinger
  placement that doesn't sound amateurish is its own engineering
  problem. Likely needs a small dedicated tool.
- **Storyline coherence across episodes.** Multi-day arcs require
  state that survives restarts — promotions ledger already does
  this for academy ranks; we need similar for narrative threads
  (which agent has been on a hot streak, who tilted, etc.).
- **YT upload + monetization** for fully-AI content is an evolving
  policy area. Expect to adapt.

## Status as of 2026-05-17 EOD

**Shipped today (8 commits on `main`, oldest → newest):**

| Commit | What |
|---|---|
| `a2e2066` | fix(stream): pre-roll splash auto-completes again (useCallback fix) |
| `b076ff8` | feat(agents): office-style names (`michael_smith` … `yuki_okafor`) |
| `5c02251` | feat(runtime): injectable `now_utc()` / `today_utc()` (ContextVar) |
| `936b19c` | refactor(runtime): migrate 6 trading-path call sites to `now_utc()` |
| `cd00d12` | feat(storage): nullable `session_id` columns + indexes on trades, pnl_snapshots, agent_notes |
| `4f7b7e0` | refactor(data): union-per-symbol parquet bar cache (replaces per-range layout) |
| `ed87080` | feat(runtime): `session_id` ContextVar propagation through repo + journal writes |
| `5534eba` | feat(session): **v0 session runner shipped** (`tradefarm.session.run`) — 4-agent parallel build off interface-locked skeletons |

215 tests passing. The Phase 1 keystone (session runner) works end-to-end:
`uv run python -m tradefarm.session.run --date-range 2026-05-12:2026-05-16`
produces a tagged manifest + DB rows.

**Not done in Phase 1 (small carry-overs):**

- Three `datetime.now()` call sites still on wall-clock, deferred because
  they live in files with unrelated fill-of-tick WIP:
  `scheduler.py` (`last_tick_at` + risk-exit check),
  `auto_director.py:51`, `streak_watcher.py:65`.
  Live behavior unaffected; replay produces slightly off timestamps on
  director/streak events. Pick up after the WIP lands.
- `--no-llm` flag on the runner CLI (default-on works; flag would be for
  cheap dev iteration).
- Stale `data_cache/eod_*.parquet` files from the pre-refactor layout —
  harmless, never consulted, can be deleted whenever.

## Pick up here next

**The beat detector** is the next subsystem (Phase 1 step 2 of the
10-piece pipeline). It reads `out/sessions/<id>/manifest.json`, scores
events, and emits a ranked 8-15 beat list for the script writer / visual
director downstream. Pure logic — no rendering, no new I/O. Smallest
remaining unit before things get rendering-heavy.

Suggested scope for v0:
- Input: `manifest.json` path
- Output: `out/sessions/<id>/beats.json` — a flat list of `Beat` objects
  with `id`, `score`, `kind` (`top_winner` / `top_loser` / `near_miss` /
  `streak` / `divergence` / etc.), `event_refs` (pointers into the
  manifest), `scene_hint` (`hero` / `leaderboard` / `brain` / etc.)
- Scoring re-uses `streak_watcher` and `auto_director` logic where it
  already exists; new logic only for beats those don't cover.
- Test: feed a synthetic 1-day manifest with 3 dramatic fills, assert
  the top beat is the largest-notional fill.

After the beat detector, the next big lift is **replay mode in `stream/`**
(Phase 1 step 3), which the risks section above flags as 1-2 weeks of
work because scenes assume live WS+SWR state.

## Cross-references for the next session

- This doc: `docs/vod-pivot.md` (decision rationale, full 10-piece pipeline)
- Spec: `docs/session-runner-spec.md` (locked decisions + the v0 runner shape — now built)
- Memory: `pivot-to-vod-2026-05-17` (why the pivot happened)
- Memory: `bug-preroll-never-completes` (fixed; relevant when working on
  stream/ because the replay-mode renderer boots through the same
  App.tsx that had the bug)
- Code entry points:
  - `src/tradefarm/session/run.py` (the runner) — the beat detector
    sits next to it as `src/tradefarm/session/beats.py` (suggested)
  - `src/tradefarm/orchestrator/auto_director.py` + `streak_watcher.py`
    — load-bearing scoring heuristics to reuse
  - `src/tradefarm/agents/names.py` — personalities for the script writer
    (Phase 2)
  - `src/tradefarm/runtime/clock.py` / `runtime/session_context.py` —
    injection primitives the runner uses

## Cross-references

- Memory: `pivot-to-vod-2026-05-17` (decision rationale, what changes
  for future work)
- Memory: `bug-preroll-never-completes` (fixed this session; still
  matters because the replay-mode renderer boots through the same
  App.tsx)
- Code: `src/tradefarm/orchestrator/broadcast_os.py`,
  `broadcast_scheduler.py`, `broadcast_recap.py` — load-bearing for
  the beat detector
- Code: `src/tradefarm/agents/names.py` — personalities for the
  script writer
