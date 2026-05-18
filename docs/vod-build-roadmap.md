# From manifest.json to a 15-min daily VOD — build roadmap

Concrete, session-by-session build order for the autonomous video
pipeline. Companion to `docs/vod-pivot.md` (the *why*) and
`docs/session-runner-spec.md` (the v0 runner spec).

Read this when picking the project back up.

## Where we are (2026-05-17 EOD)

Shipped: the foundation that lets the pipeline exist.

```
uv run python -m tradefarm.session.run --date-range 2026-05-12:2026-05-16
  ↓
out/sessions/<id>/manifest.json   ← the only output today
```

That manifest is the **input** to every remaining subsystem. From
here, each step transforms it closer to a watchable video. Nothing
visible/playable exists yet.

## The chain to a finished VOD

```
manifest.json → beats.json → rendered video clips → silent reel.mp4
                                                       ↓
                                                  + LLM script
                                                       ↓
                                                  + TTS narration
                                                       ↓
                                                  + music/SFX mix
                                                       ↓
                                                 narrated reel.mp4
                                                       ↓
                                                  + thumbnail
                                                       ↓
                                                  + YT upload
                                                       ↓
                                            published episode
```

Five jumps to **silent reel.mp4** (Phase 1 done). Three more jumps to
**narrated reel.mp4** (Phase 2 done). Two more to **published**.

## Session-by-session build order

Each row is one focused build session. Scope, deliverable, and
honest effort estimate.

### Session 1 — Beat detector  *(start here next)*

**Scope:** Read manifest.json, score events, emit a ranked list of
8-15 beats per session.

**Where it lives:** `src/tradefarm/session/beats.py` (next to the
runner), plus a CLI hook so `python -m tradefarm.session.beats <session_id>`
works standalone.

**Inputs / outputs:**
- in: `out/sessions/<id>/manifest.json`
- out: `out/sessions/<id>/beats.json` — list of `Beat` objects with
  `id`, `score` (0..1), `kind` (`top_winner` / `top_loser` /
  `divergence` / `streak` / `near_miss` / `chapter_change`),
  `event_refs` (pointers into manifest events), `scene_hint`
  (`hero` / `leaderboard` / `brain` / `decision-lab` / `recap`),
  `headline` (one-line label the captions layer will use).

**Reuse:** `auto_director` and `streak_watcher` in
`src/tradefarm/orchestrator/` already score moments live — extract
their heuristics into pure functions the detector can call without an
orchestrator instance.

**Test:** synthetic 1-day manifest with 3 dramatic fills →
top-ranked beat is the largest-notional fill. Edge case: empty
manifest (weekend session) → empty beats list, no crash.

**Effort:** half a focused session. Mostly heuristic-tuning work; no
new infrastructure.

---

### Session 2-3 — Replay mode in stream/   *(the biggest single rock)*

**Scope:** Make the broadcast UI render from journal state at an
arbitrary timestamp instead of from live WS deltas.

**Why this is hard:** today's stream/ scenes (`stream/src/scenes/*.tsx`)
consume `StreamSnapshot` produced by `useStreamData` which polls
`/account`, `/agents`, etc. and merges WS events. For replay we need
those endpoints to accept a `?at=<timestamp>&session_id=<id>` param
and return the historical state. That's a refactor of:
- `useStreamData` / `useStreamCommands` (frontend)
- The corresponding `/agents`, `/account`, `/recent_fills` endpoints
  (backend) to support point-in-time queries

**Where it lives:**
- backend: extend each `/api/*` endpoint with optional `at` param;
  add `at` param to the WS handshake
- frontend: `stream/src/hooks/useStreamData.ts` reads `?replay=`
  query param from `window.location.search`; if present, passes
  `at` to all REST calls and pins WS to historical playback

**Entry URL:**
`http://localhost:5180/?replay=s_2026-05-15_a3f2&at=2026-05-15T15:42:00Z`

**Test:** load the URL in a headless browser, assert
`document.querySelector('[data-equity]')` shows the historical equity
for that timestamp.

**Effort:** 1-2 weeks of work. Genuinely the biggest single piece.
Worth doing as multiple devlog episodes ("turning a live UI into a
deterministic renderer"). Split into:
- Session 2: backend point-in-time endpoints + WS replay handshake
- Session 3: frontend hooks consume `?at=` param

---

### Session 4 — Headless renderer

**Scope:** Iterate beats, for each beat navigate Playwright to
`/?replay=<session>&at=<beat_ts>&scene=<scene_hint>`, capture either
a 5s video clip (Playwright's `page.video`) or a 60-frame screenshot
sequence at 30fps. Write per-beat .mp4 files to disk.

**Where it lives:** `src/tradefarm/render/headless.py` (new top-level
module). Probably a `RenderJob` dataclass + a `render_session(session_id)`
async function.

**Reuse:** we already proved Playwright works headlessly today
(`dev/screenshot_stream.py`, captured 11 shots end-to-end). Same
pattern, just looping over beats and longer captures.

**Effort:** half a session, IF replay mode (sessions 2-3) is solid.
Otherwise this just produces broken renders.

---

### Session 5 — ffmpeg stitcher + on-screen captions  *(end of Phase 1)*

**Scope:** Concatenate per-beat clips with crossfades, overlay
on-screen text from `beats.json` (headline + chapter label), drop a
royalty-free music bed, output `out/sessions/<id>/reel.mp4`.

**Where it lives:** `src/tradefarm/render/stitch.py`. Either invoke
ffmpeg via subprocess (simpler) or use `ffmpeg-python` library (more
typed). Subprocess is fine for v0.

**End state after this session:** a watchable silent 5-10 min video
gets generated per session. No narration yet. **This is the format-
validation milestone** — if the silent reel feels like it could
become a real show with VO added, the pivot is working.

**Effort:** half to full session. Music library + caption styling
are the time-sinks.

---

### Phase 2 (3 sessions)

| Session | Build | End state |
|---|---|---|
| 6 | LLM script writer (Claude per-beat narration) | text scripts saved |
| 7 | TTS (ElevenLabs/OpenAI) per script line | .wav files per beat |
| 8 | Audio mixer (sidechain ducking, stingers) | narrated reel.mp4 |

After session 8: the **first watchable, narrated, fully-AI-generated
TradeFarm episode**.

---

### Phase 3 (2 sessions)

| Session | Build | End state |
|---|---|---|
| 9 | Thumbnail generator (SDXL or DALL-E + PIL composite) | thumb.jpg per episode |
| 10 | YT Data API upload + metadata + chapters | published episode |

After session 10: **the autonomous pipeline runs end-to-end on a cron;
new TradeFarm episodes appear on YouTube without a human in the loop.**

## Total estimated effort

- Phase 1: 4-5 focused sessions (sessions 2-3 are the rock)
- Phase 2: 3 sessions
- Phase 3: 2 sessions

**~9-10 focused sessions to a fully autonomous daily VOD pipeline.**

Realistic timeline at 1 focused session per week: ~2.5 months.
Realistic at 2-3 per week: ~4 weeks.

## If you only have one more session, do session 1.

Beat detector unlocks every downstream piece, is genuinely small, and
gives you a `beats.json` to look at — which is the first
human-readable "story shape" output of the pipeline. Even before any
rendering exists, eyeballing `beats.json` tells you whether the
heuristics are picking interesting moments. If they're not, that
problem is way cheaper to find at session 1 than at session 5.

## Common follow-up questions

**Can we ship Phase 1 without replay mode?** Yes, technically — you
could screenshot the *live* dashboard at simulated timestamps. But
the live UI shows current state (zero P&L on Sunday), not historical.
The whole pipeline depends on rendering historical state, which is
what replay mode enables. There is no shortcut around sessions 2-3.

**Can we use existing video-gen AI to skip the rendering stack?** No,
those generate generic stock footage. The whole point is rendering
the *actual* TradeFarm UI showing the *actual* day's decisions. A
generic AI video wouldn't show your agents, your scores, your
diorama.

**What if the silent v0 reel feels weak?** Almost certainly will at
first. The fix is iterating on the beat detector (which moments to
pick) and on-screen captions (how to introduce drama without VO).
Both are session-1 work that's revisitable cheaply.

## Cross-references

- `docs/vod-pivot.md` — the why (read first if returning cold)
- `docs/session-runner-spec.md` — what got built today
- Memory: `session-2026-05-17-pickup` — short pointer for next session
- Memory: `pivot-to-vod-2026-05-17` — decision rationale
