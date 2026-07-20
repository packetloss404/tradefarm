# AutoStream — Vibe-Code Stream Ideas

A scratchpad of ideas for automating a vibe-coded TradeFarm stream.
Source: brainstorm session 2026-05-02. Nothing here is committed; this is
the "what could be cool" backlog.

## Audio / mood

- **Lo-fi tick beat** — schedule a soft kick on every `tick` event; pitch
  up on fills, layer a pad when a rank-up fires. The 5-min tick cadence is
  basically a tempo.
- **Sonification** — turn each fill into a single piano note, key chosen
  by sector (XLK = bright, XLU = dark). Long-only buys go up the scale,
  sells go down.
- **Adaptive ambient score** — a single droning pad whose filter cutoff
  tracks `total_equity / total_allocated`. Profitable day = brighter;
  drawdown = filtered, muffled.
- **TTS narrator** — feed `LlmDecision.reason` to a low-cost TTS
  (ElevenLabs flash or piper local). Personality voices per rank.
- **"Vibe meter"** — on-screen gauge driven by recent-PnL z-score,
  cross-faded with a music-energy index from a VST or local synth loop.

## Agent World extras

- **Day/night cycle** — sky tint slides from `#0c1322` → `#fef3c7` mapped
  to NYSE open/close. Stars twinkle pre-market.
- **Weather** — rain particles when day PnL < -1%, sun rays when > +1%,
  snow when market closed. Pure SVG/CSS, free vibes.
- **Camera dolly** — periodically zoom into the Battlefield zone to focus
  on one agent that just filled, then ease back out (think SimCity intro).
- **Confetti cutscene on promotion** — pause the world for 1.5s, particle
  burst, the promoted sprite floats up with a halo, return to normal.
- **Pixel-art skin toggle** — same coordinate engine, swap SVG sprites
  for 16-bit PNGs and switch font to a pixel face. Genre dial: "modern" /
  "retro" / "wireframe".
- **Mascot pet** — a small chicken/cat sprite that randomly walks the
  bridges, idle bobs, never trades. Pure flavor.

## Story / commentary layer

- **Hourly newsroom segment** — LLM writes a 2-line bulletin every hour
  ("Senior Agent #023 had its best day yet…") with a dedicated "ON AIR"
  lower-third, narrated via TTS over a stinger.
- **Agent of the Day card** — pre-roll on stream start: top performer's
  name, rank journey, current holding, win-rate. Generated server-side at
  midnight.
- **Rivalry banter** — when two agents take opposite sides of the same
  symbol within one tick, generate a one-line snipe between them.
- **Trade-of-the-tick replay** — biggest-impact fill gets a 4-sec slow-mo
  overlay: zoom on agent + price tag + cause (LSTM prob, LLM reason).

## Twitch / chat integration

- **!agent NAME** chat command — viewer picks any agent and sees its
  journal in chat.
- **!bet SYMBOL up/down** — viewer "vibe vote" feeds an aggregated sidebar
  gauge; track viewer accuracy vs the LSTMs over time. Read-only, no real
  bets.
- **Channel-points name claim** — viewer redeems points to rename an
  agent; persisted to a `display_name` column.
- **Predictions** — auto-create Twitch Prediction every market open
  ("Will TradeFarm be green at close?") and resolve at 4pm ET.

## Code-side vibe (for live-coding co-streams)

- **Editor heat trail** — a tail in your editor showing the last N typed
  lines as glowing residue (purely cosmetic neovim/VS Code overlay).
- **CPU/build-progress chime** — short stinger when `pytest`/`tsc -b`
  succeeds in the background.
- **"What's the agent thinking" sidebar** — pin a single agent to a dock
  that updates as you live-edit code; useful when demoing strategy
  changes.

## Production polish

- **CRT/VHS shader** — full-screen WebGL filter (chromatic aberration +
  subtle scanlines + grain). Toggle hotkey from the Admin overlay.
- **Lower-thirds builder** — generic "title / subtitle" component that
  can be pushed via WS event so on-air banners can be triggered by a
  button or CLI.
- **Daily recap reel** — at market close, the backend dumps the day's
  top-3 events; a headless ffmpeg job composes a 30-sec MP4 (Agent World
  screencaps + commentary subtitles) for short-form posts.
- **OBS WebSocket integration** — let backend events flip OBS scenes
  (e.g., switch to "Promotion Cutscene" scene when a rank-up arrives).

## Top picks (cheapest wins first)

1. **Lo-fi tick beat + sonified fills** — biggest vibe upgrade for minutes
   of dev work, zero ongoing cost.
2. **Day/night sky + weather** in Agent World — readable from across the
   room, no extra data needed, fits the diorama tone.
3. **Hourly TTS newsroom bulletin** — ties existing LLM/journal data into
   a recurring stream beat with very little code.

## Open questions / decisions to make later

- Audio engine: Web Audio API in the Tauri webview vs a separate Rust
  side process via `cpal`? Webview is simpler, native is sturdier.
- Twitch integration: server-side bot vs browser-source overlay?
- Asset budget: do we need a pixel-art commission, or stick with SVG +
  emojis?
- Stream identity: one persona ("TradeFarm Live") or multiple
  personalities (Anchor, Color Commentator, Quant)?
