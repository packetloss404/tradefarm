# AutoStream — Vibe-Code Stream Ideas (Technical Review)

A scratchpad of ideas for automating a vibe-coded TradeFarm stream.
Source: brainstorm session 2026-05-02. Nothing here is committed; this is
the "what could be cool" backlog.

> **Reviewer note (2026-05-09):** Each idea below has been annotated with
> technical feasibility, estimated effort, pitfalls, and dependency risks.
> The "Top picks" section has been re-ranked based on this analysis.
> Items marked ⚠️ DECEPTIVE COMPLEXITY look simple but hide non-trivial work.

---

## Audio / mood

- **Lo-fi tick beat** — schedule a soft kick on every `tick` event; pitch
  up on fills, layer a pad when a rank-up fires. The 5-min tick cadence is
  basically a tempo.

  > **Feasibility: HIGH** | **Effort: ~2–4 hrs**
  > Use the Web Audio API inside the Tauri webview — `AudioContext` +
  > `OscillatorNode` / pre-decoded `AudioBuffer` samples. No extra deps.
  > Pitfall: browser autoplay policy requires a user-gesture unlock; add a
  > one-click "unmute" overlay on stream start. Webview audio is fine for
  > this scope; no reason to pull in Rust-side `cpal` just for a kick drum.
  > Library hint: `tone.js` is overkill here — raw Web Audio is ~30 LOC.

- **Sonification** — turn each fill into a single piano note, key chosen
  by sector (XLK = bright, XLU = dark). Long-only buys go up the scale,
  sells go down.

  > **Feasibility: HIGH** | **Effort: ~3–5 hrs**
  > Map sector → MIDI note number, then play via Web Audio `OscillatorNode`
  > (sine/triangle) or a short piano `.ogg` sample set (~12 notes, <1 MB).
  > Pitfall: polyphony stacking — if 20 fills arrive on the same tick, you
  > get a chord cluster. Cap simultaneous voices to ~4 and queue/drop excess.
  > Dependency risk: none if using raw Web Audio; moderate if pulling in a
  > sampler lib like `smplr` or `soundfont-player`.

- **Adaptive ambient score** — a single droning pad whose filter cutoff
  tracks `total_equity / total_allocated`. Profitable day = brighter;
  drawdown = filtered, muffled.

  > **Feasibility: HIGH** | **Effort: ~3–6 hrs**
  > `BiquadFilterNode.frequency` driven by a lerped equity ratio. Use a
  > looping pad sample or two detuned oscillators with a slow LFO.
  > Pitfall: avoid abrupt cutoff jumps — lerp/slew the value over ~500 ms.
  > Plays nicely with the tick beat; merge into the same `AudioContext`.

- **TTS narrator** — feed `LlmDecision.reason` to a low-cost TTS
  (ElevenLabs flash or piper local). Personality voices per rank.

  > ⚠️ **DECEPTIVE COMPLEXITY**
  > **Feasibility: MEDIUM** | **Effort: ~8–16 hrs**
  > *Looks simple but has several traps:*
  > 1. **Latency** — ElevenLabs turbo endpoint is ~300–600 ms; for a live
  >    stream you need to queue and pre-render to avoid dead air or stacking.
  > 2. **Cost** — ElevenLabs charges per character. If `reason` strings
  >    average 40 words and you have 50 fills/hr, that's ~$0.50–1.00/hr at
  >    flash tier. Budget for truncation or summarisation before TTS.
  > 3. **Piper local** alternative: zero cost, ~100 ms on CPU, but voice
  >    quality is noticeably lower and you'll need to ship a ~50 MB model.
  >    Runs natively so Tauri sidecar (`Command::new_sidecar`) works.
  > 4. **"Personality voices per rank"** is a scope trap — each voice is a
  >    separate model/voice-ID. Start with 1 voice, parameterize later.
  > Dependency risk: HIGH for cloud TTS (API key, quota, network latency);
  > LOW for Piper (vendored binary, no network).

- **"Vibe meter"** — on-screen gauge driven by recent-PnL z-score,
  cross-faded with a music-energy index from a VST or local synth loop.

  > **Feasibility: MEDIUM** | **Effort: ~6–10 hrs**
  > The PnL z-score gauge alone is ~2 hrs (SVG arc + reactive binding).
  > The "music-energy index from a VST" part is where it gets hairy: you'd
  > need to run an analyser node (`AnalyserNode.getByteFrequencyData`) on
  > the existing audio mix, compute RMS/spectral centroid, and blend with
  > the PnL score. Skip the VST idea — analyse the Web Audio output bus.
  > Pitfall: z-score needs a rolling window; choose a lookback (e.g., 20
  > ticks) and decide what "recent" means before coding.

---

## Agent World extras

- **Day/night cycle** — sky tint slides from `#0c1322` → `#fef3c7` mapped
  to NYSE open/close. Stars twinkle pre-market.

  > **Feasibility: HIGH** | **Effort: ~2–3 hrs**
  > Pure CSS/SVG. Interpolate a background-color based on clock time.
  > Stars: scatter small SVG circles with a CSS `@keyframes opacity` flicker.
  > Pitfall: make sure the clock is server-authoritative (ET), not the
  > viewer's local TZ. Pass the market-phase enum from the Rust backend.

- **Weather** — rain particles when day PnL < -1%, sun rays when > +1%,
  snow when market closed. Pure SVG/CSS, free vibes.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > Rain/snow: CSS `@keyframes` falling particles (20–40 `<div>`s, absolute
  > positioned, `animation-delay` staggered). Sun rays: a radial gradient
  > overlay. Lightweight and no JS needed beyond toggling a CSS class.
  > Pitfall: particle count — too many DOM elements hurt framerate in
  > Tauri's webview. Cap at ~40 particles and use `will-change: transform`.
  > GPU compositing note: Tauri's webview (WebView2 on Windows, WKWebView
  > on macOS) handles CSS animations well; no WebGL needed.

- **Camera dolly** — periodically zoom into the Battlefield zone to focus
  on one agent that just filled, then ease back out (think SimCity intro).

  > ⚠️ **DECEPTIVE COMPLEXITY**
  > **Feasibility: MEDIUM** | **Effort: ~10–16 hrs**
  > Sounds like a CSS `transform: scale() translate()` but:
  > 1. You need to compute the correct translate offset to center a specific
  >    agent sprite — requires knowing the agent's world-space position.
  > 2. Easing back out must not interrupt if a *new* fill fires mid-dolly.
  >    Need a cancellable animation queue / state machine.
  > 3. UI elements (lower-thirds, gauges) must NOT scale — they need to be
  >    outside the transformed container or use `counter-transform`.
  > Library hint: GSAP (free for non-commercial) has `timeline` + `killAll`.
  > Alternative: CSS `view-transition` API (experimental, Chromium 111+).
  > Start with a simpler "highlight pulse" on the agent sprite instead.

- **Confetti cutscene on promotion** — pause the world for 1.5s, particle
  burst, the promoted sprite floats up with a halo, return to normal.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > `canvas-confetti` (4 KB, zero-dep) for the burst. Pause = stop the
  > tick timer for 1.5s (or freeze the render loop). Float-up = CSS
  > `translateY` transition on the sprite. Halo = SVG `<circle>` with a
  > glow filter.
  > Pitfall: "pause the world" means you must buffer incoming backend events
  > during the cutscene and replay them after. If you just freeze the UI
  > while ticks still arrive, state drifts. Queue events in a ring buffer.

- **Pixel-art skin toggle** — same coordinate engine, swap SVG sprites
  for 16-bit PNGs and switch font to a pixel face. Genre dial: "modern" /
  "retro" / "wireframe".

  > ⚠️ **DECEPTIVE COMPLEXITY**
  > **Feasibility: MEDIUM** | **Effort: ~20–40 hrs (including asset creation)**
  > The code toggle is ~4 hrs (CSS class swap, conditional `<img>` src).
  > The real cost is **asset production**: every sprite needs a pixel-art
  > variant. If you have N agent types × M states × 3 themes, the asset
  > matrix explodes. "Wireframe" is cheap (SVG stroke-only), "retro" needs
  > commissioned pixel art or a lot of time in Aseprite.
  > Recommendation: Ship "modern" + "wireframe" first (both SVG, minimal
  > asset work). Add pixel-art as a stretch goal after the stream is live.

- **Mascot pet** — a small chicken/cat sprite that randomly walks the
  bridges, idle bobs, never trades. Pure flavor.

  > **Feasibility: HIGH** | **Effort: ~3–5 hrs**
  > A-star or random walk on the bridge graph, lerped CSS `translate`.
  > Idle bob = a 2-frame CSS animation. Cheapest flavor item on the list.
  > Pitfall: z-index — make sure the pet renders above bridges but below
  > agent info popups.

---

## Story / commentary layer

- **Hourly newsroom segment** — LLM writes a 2-line bulletin every hour
  ("Senior Agent #023 had its best day yet…") with a dedicated "ON AIR"
  lower-third, narrated via TTS over a stinger.

  > **Feasibility: HIGH** | **Effort: ~6–10 hrs**
  > Prompt the existing LLM (GPT-4o-mini or similar) with the last hour's
  > journal entries; constrain output to ≤280 chars. Render as a lower-third
  > `<div>` with slide-in CSS animation. TTS is optional here — text-only
  > version ships in ~4 hrs; adding TTS doubles the effort (see TTS
  > narrator notes above).
  > Pitfall: LLM hallucination — the bulletin may invent stats. Feed only
  > structured data (agent ID, PnL, rank, fill count) and use a rigid
  > template prompt. Validate numeric claims against source data.
  > Cost: GPT-4o-mini at ~$0.15/1M input tokens → ~$0.001/bulletin.

- **Agent of the Day card** — pre-roll on stream start: top performer's
  name, rank journey, current holding, win-rate. Generated server-side at
  midnight.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > A cron job (or Tokio `interval`) at midnight ET queries the DB for the
  > top agent, renders a JSON blob, and the frontend reads it on stream
  > init. Display as a full-screen card for 8–10 sec, then fade out.
  > Pitfall: "midnight" is tricky — use `chrono-tz` with `America/New_York`
  > and handle DST transitions. Or just trigger on market close (4 PM ET)
  > which is more reliable and more relevant.

- **Rivalry banter** — when two agents take opposite sides of the same
  symbol within one tick, generate a one-line snipe between them.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > Detection: compare fills within a tick window grouped by symbol; if one
  > is BUY and one is SELL → trigger. LLM generates a one-liner (or use a
  > canned template bank of ~20 lines for zero cost).
  > Pitfall: frequency — in a 50-agent system, opposite fills may be common.
  > Rate-limit to ≤1 banter/tick and ≤4/hour to avoid spam.

- **Trade-of-the-tick replay** — biggest-impact fill gets a 4-sec slow-mo
  overlay: zoom on agent + price tag + cause (LSTM prob, LLM reason).

  > **Feasibility: MEDIUM** | **Effort: ~8–12 hrs**
  > "Biggest impact" needs a scoring function (e.g., `abs(fill_pnl)` or
  > `abs(unrealized_change)`). Slow-mo overlay = camera dolly (see above)
  > + a data card. This inherits the dolly complexity.
  > Alternative: skip zoom, just show a highlighted card overlay at the top
  > of the screen for 4 sec — drops effort to ~4 hrs.

---

## Twitch / chat integration

- **!agent NAME** chat command — viewer picks any agent and sees its
  journal in chat.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > Use `tmi.js` (Node) or `twitch-irc` (Rust crate) to listen for chat
  > commands. Query the agent journal from the DB/API and post a truncated
  > response (Twitch chat limit: 500 chars).
  > Pitfall: rate limits — Twitch allows ~20 messages/30s for bots. If the
  > stream gets popular, you'll need cooldowns per user (~30s) and a global
  > rate limiter.
  > Architecture decision: run the bot as a Tauri sidecar process or a
  > separate microservice. Sidecar is simpler for single-instance streams.

- **!bet SYMBOL up/down** — viewer "vibe vote" feeds an aggregated sidebar
  gauge; track viewer accuracy vs the LSTMs over time. Read-only, no real
  bets.

  > **Feasibility: HIGH** | **Effort: ~6–10 hrs**
  > Parse chat → tally votes in a HashMap, push aggregated percentages to
  > the frontend via WebSocket. The accuracy tracking over time needs a
  > small DB table (`viewer_votes`) with a resolution timestamp.
  > Pitfall: define the resolution window — "up/down" relative to what
  > baseline and timeframe? Per-tick close vs. next-tick close is simplest.
  > Pitfall: vote stuffing — one vote per user per symbol per tick.

- **Channel-points name claim** — viewer redeems points to rename an
  agent; persisted to a `display_name` column.

  > **Feasibility: MEDIUM** | **Effort: ~6–10 hrs**
  > Requires Twitch PubSub or EventSub subscription to channel point
  > redemptions. The Twitch API here is well-documented but needs OAuth
  > with `channel:read:redemptions` scope. You must also create the custom
  > reward via API or dashboard.
  > Pitfall: profanity filter — you MUST sanitize display names. Use a
  > word-list filter (e.g., `rustrern/censor` crate or a simple blocklist).
  > Pitfall: persistence — if an agent dies/is reassigned, what happens to
  > the name? Define lifecycle rules.

- **Predictions** — auto-create Twitch Prediction every market open
  ("Will TradeFarm be green at close?") and resolve at 4pm ET.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > Twitch API `POST /predictions` + `PATCH /predictions` at market open
  > and close. Needs `channel:manage:predictions` OAuth scope.
  > Pitfall: if the stream goes offline mid-day, unresolved predictions
  > auto-cancel after 24 hrs (Twitch behavior). Handle reconnect/resume.
  > This is a cheap, high-engagement feature — good ROI.

---

## Code-side vibe (for live-coding co-streams)

- **Editor heat trail** — a tail in your editor showing the last N typed
  lines as glowing residue (purely cosmetic neovim/VS Code overlay).

  > ⚠️ **DECEPTIVE COMPLEXITY**
  > **Feasibility: LOW–MEDIUM** | **Effort: ~15–25 hrs**
  > For VS Code: you need a proper extension using `DecorationRenderOptions`
  > with decaying opacity. Tracking "last N edited lines" requires hooking
  > `onDidChangeTextDocument`. The extension API is well-documented but
  > debugging is slow (extension host reload cycles).
  > For Neovim: `extmarks` with `hl_group` and a Lua timer to fade them.
  > Either way, this is a standalone editor plugin project, not a quick win.
  > Recommend: defer entirely. Use an existing VS Code extension like
  > "Scope Dimming" or "Line Highlighter" for a 90% approximation at 0 hrs.

- **CPU/build-progress chime** — short stinger when `pytest`/`tsc -b`
  succeeds in the background.

  > **Feasibility: HIGH** | **Effort: ~2–3 hrs**
  > Shell alias or a wrapper script: `pytest && play_sound success.wav ||
  > play_sound fail.wav`. On Windows: `[System.Media.SoundPlayer]` in
  > PowerShell or `soxi`/`ffplay`. On Linux/macOS: `aplay`/`afplay`.
  > Alternatively, VS Code task `presentation.reveal` + `problemMatcher`
  > can trigger a terminal bell. Dead simple. No code integration needed.

- **"What's the agent thinking" sidebar** — pin a single agent to a dock
  that updates as you live-edit code; useful when demoing strategy changes.

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > A small always-on-top Tauri window (or a panel in the existing webview)
  > subscribed to a single agent's event stream via WebSocket filter. Show
  > `LlmDecision.reason`, current position, last fill, LSTM probability.
  > Pitfall: hot-reloading strategy code while the agent is live —
  > ensure the sidebar reconnects gracefully on backend restart.

---

## Production polish

- **CRT/VHS shader** — full-screen WebGL filter (chromatic aberration +
  subtle scanlines + grain). Toggle hotkey from the Admin overlay.

  > **Feasibility: HIGH** | **Effort: ~4–8 hrs**
  > Plenty of open-source GLSL shaders for this (shadertoy "CRT" has
  > hundreds). Integrate via a `<canvas>` overlay with a WebGL context
  > reading from a framebuffer, or use CSS `backdrop-filter` for a simpler
  > (but less authentic) scanline effect.
  > Pitfall: compositing a WebGL shader over an existing DOM-based UI
  > requires either (a) rendering the UI to a texture first (expensive) or
  > (b) applying it as a CSS filter on the root element. Option (b) is
  > simpler but won't do chromatic aberration. A pragmatic middle ground:
  > SVG `<filter>` with `<feTurbulence>` for grain + CSS `repeating-linear-
  > gradient` for scanlines. Gets 80% of the look at 20% of the effort.
  > Library hint: `postprocessing` (npm) if you already have a Three.js
  > scene; otherwise raw SVG filters are lighter.

- **Lower-thirds builder** — generic "title / subtitle" component that
  can be pushed via WS event so on-air banners can be triggered by a
  button or CLI.

  > **Feasibility: HIGH** | **Effort: ~3–5 hrs**
  > A `<div>` with slide-in animation, driven by a WebSocket message
  > `{ type: "lower_third", title: "...", subtitle: "...", duration_ms: 5000 }`.
  > This is a foundational component — build it early so that newsroom,
  > banter, and promotion cutscenes can all reuse it.
  > Implementation: CSS `transform: translateX(-100%)` → `translateX(0)`
  > with `transition`. Auto-dismiss via `setTimeout`.

- **Daily recap reel** — at market close, the backend dumps the day's
  top-3 events; a headless ffmpeg job composes a 30-sec MP4 (Agent World
  screencaps + commentary subtitles) for short-form posts.

  > ⚠️ **DECEPTIVE COMPLEXITY**
  > **Feasibility: MEDIUM** | **Effort: ~20–30 hrs**
  > The concept is straightforward but the implementation is a full
  > mini-pipeline:
  > 1. Capture screenshots at key moments (need a screenshot hook in the
  >    frontend → save to disk via Tauri `fs` API).
  > 2. Generate subtitle `.srt` from event data.
  > 3. Compose via `ffmpeg` CLI: image sequence → video + subtitle burn-in.
  > 4. Upload to a CDN or post to social media API.
  > Each step is individually simple but the glue code, error handling,
  > and testing across platforms is substantial. The `ffmpeg` binary must be
  > bundled or assumed present — adds ~80 MB to distribution.
  > Recommendation: V1 = just generate a static image collage (Rust
  > `image` crate, ~4 hrs). Video can come later.

- **OBS WebSocket integration** — let backend events flip OBS scenes
  (e.g., switch to "Promotion Cutscene" scene when a rank-up arrives).

  > **Feasibility: HIGH** | **Effort: ~4–6 hrs**
  > OBS WebSocket plugin (v5, ships with OBS 28+) exposes a JSON-RPC API
  > on `ws://localhost:4455`. Use the `obws` Rust crate or raw WebSocket.
  > Key calls: `SetCurrentProgramScene`, `SetSourceFilterEnabled`.
  > Pitfall: OBS must be running and the WebSocket server enabled. Add a
  > health-check on stream start and a clear error if OBS is unreachable.
  > Pitfall: scene names are strings — typos silently fail. Validate scene
  > list on connect with `GetSceneList`.

---

## Top picks — RE-RANKED by technical review

Original ranking was reasonable but under-weighted hidden complexity.
Revised ranking below factors in effort, dependencies, and compound value
(items that unlock other features score higher).

1. **Lo-fi tick beat + sonified fills** — ✅ Agree with #1. ~4–8 hrs total.
   Pure Web Audio, zero deps, zero cost. Immediate vibe payoff.

2. **Lower-thirds builder** — 🆕 Promoted to #2. ~3–5 hrs. This is a
   **force multiplier**: newsroom, banter, rivalry, and Agent of the Day
   all need a lower-third component. Build it first, reuse everywhere.

3. **Day/night sky + weather** — Moved from #2 to #3. ~6–9 hrs total.
   Still a great cheap win. Slightly more effort than lower-thirds but
   purely cosmetic — doesn't unlock other features.

4. **Hourly TTS newsroom bulletin (text-only V1)** — Adjusted from #3.
   ~6 hrs for text-only (skip TTS in V1). Pairs with the lower-thirds
   builder for near-free UI. Add TTS as a separate phase.

5. **Twitch Predictions** — 🆕 Added. ~4–6 hrs. Highest viewer-engagement
   ROI on the list. Simple API, well-documented, recurring content.

6. **Confetti cutscene on promotion** — 🆕 Added. ~4–6 hrs. High visual
   impact, uses `canvas-confetti`, fairly contained scope.

**Deferred from "quick wins":**
- TTS narrator — too many hidden costs (latency, $, voice management).
- Camera dolly / trade-of-tick replay — animation state machine complexity.
- Pixel-art skin toggle — asset production cost dwarfs code cost.
- Daily recap reel — full video pipeline; start with a static image.
- Editor heat trail — standalone plugin project, not a stream feature.

---

## Open questions / decisions to make later — with technical guidance

- **Audio engine:** Web Audio API in the Tauri webview vs a separate Rust
  side process via `cpal`? Webview is simpler, native is sturdier.

  > **Recommendation:** Start with Web Audio API. It's sufficient for all
  > audio ideas listed here (beats, sonification, ambient pad). The Tauri
  > webview (WebView2/WKWebView) supports the full Web Audio spec. Only
  > move to `cpal` if you hit latency issues (unlikely for non-interactive
  > audio) or need audio output when the webview is hidden.

- Twitch integration: server-side bot vs browser-source overlay?

  > **Recommendation:** Server-side bot (Rust process or Node sidecar).
  > A browser-source overlay can only *display* data; it can't listen to
  > chat commands or call the Twitch API for predictions/point redemptions.
  > You need a server-side component regardless, so start there. The
  > overlay is just a frontend route that OBS loads as a browser source.

- Asset budget: do we need a pixel-art commission, or stick with SVG +
  emojis?

  > **Recommendation:** SVG + emojis for V1. Pixel art is a scope and
  > budget trap (see pixel-art skin toggle notes). Emojis render at native
  > resolution and need zero asset management. If the stream grows, pixel
  > art can be a funded stretch goal.

- Stream identity: one persona ("TradeFarm Live") or multiple
  personalities (Anchor, Color Commentator, Quant)?

  > **Recommendation:** Single persona for V1. Multiple personalities
  > means multiple TTS voices, multiple prompt templates, and a "who speaks
  > when" state machine. Start with one voice/personality and parameterize
  > the prompt so splitting into personas later is a config change, not a
  > rewrite.
