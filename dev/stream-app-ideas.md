# TradeFarm Stream — Idea Backlog

Concrete features for the broadcast app at `stream/`. The first three (Web
Audio engine, scene rotator, configurable pre-roll opener) shipped on
2026-05-02. Everything below is the unshipped backlog from the same
brainstorm — kept here so we don't lose them.

Effort estimates assume a single dev familiar with the app, no asset
work, and reuse of existing data shapes.

---

## 1. AgentWorldXL extras

### 1.1 Day/night sky cycle
Animate the existing `<linearGradient id="sky-xl">` stops based on a clock
fed from a new `/market/clock` endpoint (or just `Date.now()` mapped to
an ET schedule). Pre-market = dark with twinkling stars; RTH = bright
blue; after-hours = orange dusk; weekend = navy.

- New endpoint: `GET /market/clock` → `{ phase: "premarket"|"rth"|"afterhours"|"closed", server_now: ISO }`.
- Stream side: `useMarketClock()` hook polls every 30s; gradient stops are
  derived in `AgentWorldXL` via `useMemo`.
- Stars: a layer of `<circle>` with random `<animate>` opacity, only
  rendered when `phase !== "rth"`.

Effort: ~1 day.

### 1.2 Weather effects
- Rain particles: SVG `<line>` falling vertically at varied speeds;
  triggered when `today_pnl_pct < -1%`.
- Sun rays: rotating radial-gradient `<g>` triggered when > +1%.
- Snow: gentle drifting circles, triggered when market is closed.
- Fog: low-alpha rectangle near the horizon — pre-market only.

All particles render inside the existing SVG and respect the camera drift
transform. Effort: ~½ day.

### 1.3 Camera dolly cinematic
Every ~30s (or driven by a "big fill" event), animate the SVG `viewBox`
to zoom into the agent that just had the biggest fill. Hold 2s, ease back
to overview.

- Reuse the existing `cameraOffset` rig; add a `cameraTarget` ref.
- Trigger from `StatPillar`'s biggestFill memo via a callback.
- Pause normal camera drift while a dolly is in progress.

Effort: ~½ day.

### 1.4 Speech bubbles on agents
Show truncated `last_decision.reason` for any agent that filled in the
last 30s. SVG `<foreignObject>` with a rounded chip above the sprite.
Fade after 6s.

- Add a `bubble: { agentId, text, expiresAt }[]` state in `AgentWorldXL`.
- Push entries from a `useEffect` watching `snapshot.fills`.
- Render only the first 3 to avoid clutter.

Effort: ~½ day.

### 1.5 Promotion cutscene
When a promotion event arrives, freeze the world drift for 1.5s, particle
burst at the sprite, halo grows, sprite floats up 20px, return.

- New `PromotionCutscene` overlay component.
- AgentWorldXL exposes a `pauseDrift()` method via a context or imperative
  handle so the cutscene can hold the camera still.

Effort: ~½ day.

### 1.6 Trade trail
When an agent's zone changes (village → battle → glory), draw a glowing
arc along the bridge they "walked", fading over 2s. Reuses the existing
bridge geometry.

- Track previous zone per agent; on diff, push a `trail` entry with bridge
  endpoints + timestamp.
- Render trails as `<path>` with `stroke-dasharray` animated dashes.

Effort: ~½ day.

### 1.7 Zone activity heat
Each island's grass alpha-blends toward white based on count of recent
fills + decisions in that zone over the last 60s. Subtle pulsing.

- Aggregate `fills` and `agents.last_decision` into a per-zone counter.
- Pipe through to the `<rect>` fill via a CSS variable update.

Effort: ~½ day.

### 1.8 Pixel-art skin toggle
Keep iso math, swap `<symbol>` defs for 16-bit PNG sprites + a pixel font
for labels. Add a `theme` setting: `"modern" | "retro" | "wireframe"`.

- Asset cost is the real cost (commission a sprite sheet or use OpenGameArt).
- Wireframe theme is the freebie: single-stroke SVG version of every
  sprite.

Effort: ~1 day code + asset budget separately.

### 1.9 Mascot pet
Small chicken/cat/farmer sprite that wanders the bridges on a random walk,
never trades. Pure flavor.

- New `MascotPet` component inside AgentWorldXL.
- Random-walk state machine: idle (3s) → walk to neighbor tile (2s) → idle.

Effort: ~½ day.

---

## 2. HUD elements

### 2.1 Tick countdown ring
Small radial progress in TopTicker counting down to the next scheduled
tick. Driven by `auto_tick_interval_sec` from `/admin/config` and the
`last_tick_at` from `/account`.

Effort: ~2 hours.

### 2.2 Equity sparkline
Tiny 30-tick sparkline next to the Equity stat in TopTicker.

- Backend: extend `/pnl/daily` with intraday option, OR keep a rolling
  buffer of `account.total_equity` snapshots client-side (cheaper).
- Render with a custom SVG polyline — no chart lib needed.

Effort: ~½ day.

### 2.3 Stock ticker tape
Strip below TopTicker showing live marks for the ~10 most-held symbols
(aggregated from `/agents`). Marquee crawl, color-coded vs prior close.

- Reuse the marquee logic from `BottomTicker` with a new data source.

Effort: ~½ day.

### 2.4 Win streak counter
"7 green ticks in a row" — derive from a rolling tick history of
`today_pnl` deltas.

- Add to TopTicker as a small badge that only renders when streak >= 3.

Effort: ~2 hours.

### 2.5 LLM decision feed sidebar
Pin a persistent stack of the last 5 decisions on a sidebar (instead of
the current single transient `CommentaryCaption`). Useful on the Brain
scene; also nice as a persistent rail on Hero.

- Reuse `useCommentary` highlight stream; render a vertical FIFO with
  per-entry fade-in / slow scroll.

Effort: ~½ day.

### 2.6 Champion belt
When a new agent overtakes #1, animate a "championship belt" handoff
between sprites in StatPillar.

- Track previous top agent in a ref; on diff, queue a 2s overlay with
  belt sprite + sound stinger.

Effort: ~½ day.

---

## 3. Audio (post-v1)

### 3.1 Adaptive ambient pad
Long droning pad whose lowpass cutoff tracks `today_pnl_pct`. Profitable
day = brighter; drawdown = filtered, muffled.

- Add a `ambient` track in `StreamAudio` with a continuously-running
  `OscillatorNode` + `BiquadFilterNode`.
- A `setMood(pct: number)` method updates the cutoff target with smooth
  `linearRampToValueAtTime`.

Effort: ~1 day.

### 3.2 TTS narrator
Pipe the LLM-generated commentary text through TTS. Two paths:

- ElevenLabs flash-v2 (cloud, ~$0.15/min) — best voices, latency ~400ms.
- piper.exe spawned by the Rust side (local, free, GPU optional) —
  acceptable quality, zero recurring cost.

Implementation:
- New `/api/stream/narrate` endpoint that accepts text and returns audio
  bytes (or a relative URL to the bytes).
- Stream side: `<audio>` element ducked while playing; queue via
  `streamAudio.duck(0.2, durationSec)`.

Effort: ~1 day for either path.

### 3.3 Music genre per scene
Different background loop per scene: lo-fi for Hero, synthwave for
Leaderboard, ambient for Brain, deep house for Strategy. Crossfade on
scene change.

Effort: ~1 day + music asset rights.

---

## 4. Story / commentary

### 4.1 Hourly newsroom bulletin
Every hour at :00, the rotator forces a 20-sec "ON AIR" lower-third with
a 2-line LLM-generated bulletin.

- New endpoint: `POST /stream/bulletin` → calls Claude with the last
  hour's journal entries and returns 2 lines + a confidence score.
- Trigger via a server-side cron + WS broadcast OR client-side
  `setInterval` aligned to the wall clock.
- Render as a new `BulletinScene` that the rotator force-injects.

Effort: ~1 day + ongoing Claude calls (~$0.05/hour).

### 4.2 Agent of the Day card
Pre-roll variant — pick top-PnL agent over last 24h, render a
baseball-card-style splash with rank journey, win rate, current holding.

- Reuse `PreRollScene` as the layout chassis; data from `/agents` +
  `/pnl/daily`.
- Setting: `agentOfDayEnabled` boolean; if true, show after the existing
  pre-roll splash.

Effort: ~½ day.

### 4.3 Trade-of-the-tick replay
At end of every tick where any fill > $50 notional, replay the moment in
0.4x speed for 4 seconds with caption + LSTM prob + LLM reason.

- Capture the AgentWorldXL state at fill time (camera + sprite positions).
- Render as a modal overlay scene that plays animation backwards then
  forwards.

Effort: ~1 day.

### 4.4 Rivalry banter
If two agents take opposite sides of the same symbol in one tick,
generate a one-line snipe via the existing LLM overlay.

- Detect server-side in the orchestrator's tick fanout.
- Push as a new WS event type `banter` → render as a special caption
  variant in `CommentaryCaption`.

Effort: ~½ day + small LLM cost.

### 4.5 Recap scene at 4pm ET
Day's stats: top movers, biggest fill, best agent, worst agent, total PnL,
strategy ranking. Auto-shown by the rotator any time after 16:00 ET.

- Add a 5th rotator scene `RecapScene`.
- Logic in `SceneRotator`: if `now >= 16:00 ET`, force `idx = recap` once
  per cycle.

Effort: ~1 day.

---

## 5. Production polish

### 5.1 CRT/VHS shader
Full-screen WebGL filter (chromatic aberration + scanlines + grain).
Toggle from the Admin overlay.

- Single `<canvas>` sibling to the SVG, fragment shader sampling the
  rendered DOM via `html2canvas` (slow) or via OffscreenCanvas + a fixed
  background sample (cheap).
- Easier path: pure CSS (linear-gradient scanlines + drop-shadow chroma) —
  not as good, free.

Effort: ~1 day for WebGL, ~2 hours for CSS-only.

### 5.2 Lower-thirds builder
Generic "title / subtitle" component that subscribes to a new
`lower_third` WS event so a CLI can pop banners on demand.

- New backend route: `POST /admin/lower-third { title, subtitle, ttl_sec }`.
- New event: `{ type: "lower_third", payload: {...} }`.
- Stream side: persistent component rendering the most recent banner with
  enter/exit animation.

CLI utility: `uv run python -m tradefarm.stream.banner "BREAKING: ..."`.

Effort: ~½ day.

### 5.3 Daily recap MP4
At 16:05 ET, headless Playwright + ffmpeg compose a 30-sec highlight reel
for posting to socials.

- New job `tradefarm.stream.recap_recorder`:
  1. Start the stream app pointed at a "recap mode" URL.
  2. Take 1080p screenshots every 100ms while the recap scene plays.
  3. ffmpeg to MP4 with the day's TTS bulletin as audio.
- Outputs to `data_cache/recaps/YYYY-MM-DD.mp4`.

Effort: ~2 days.

### 5.4 OBS WebSocket integration
Push stream events to OBS so it can switch scenes (e.g., "go to Promotion
Cutscene scene" when a rank-up arrives).

- Add `obs-websocket-js` to the Rust shell or stream UI.
- Map TradeFarm events → OBS scene names via a config file.

Effort: ~1 day.

### 5.5 Multi-window mode
Spawn a smaller secondary Tauri window for OBS Browser Source capture
(transparent background, just one widget).

- New Tauri window labeled `widget` with a different React route
  (`?view=widget`) that renders only e.g. the Leaderboard.
- Useful for streamers who want to overlay TradeFarm on top of their own
  game/IDE capture.

Effort: ~1 day.

### 5.6 Replay mode
Playback recorded WS sessions at any speed for testing or end-of-day
recap. Useful for tuning the audio engine without waiting on real ticks.

- Add a `data_cache/ws_recordings/` writer in the orchestrator.
- Stream-side replayer that fakes a WebSocket and feeds events at a
  configurable rate.

Effort: ~1 day.

---

## Suggested next bundle (v2)

If we want a "Stream Vibe v2" pack of comparable size to what just
shipped, the highest impact-per-day is:

1. **Day/night sky + weather** — diorama feels alive instead of static.
2. **Tick countdown ring + equity sparkline** in TopTicker — the two HUD
   missing pieces.
3. **CSS-only CRT toggle** — instant retro vibe without WebGL.
4. **Recap scene at 4pm ET** — closes the broadcast day.

That's ~3 days of work and gets us to a "ship it on Twitch" feel.

## Out-of-scope / requires research

- Twitch chat integration (`!agent` commands, predictions, channel
  points) — needs OAuth setup, separate doc.
- Real-time TTS voice cloning per rank — interesting but expensive.
- 3D mode (Three.js scene with proper shadows and orbit camera) — a much
  bigger rewrite, not incremental on the current SVG diorama.
