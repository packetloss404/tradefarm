# AutoStream — Vibe-Code Stream Ideas

A scratchpad for automating a vibe-coded TradeFarm live stream.
Source: brainstorm session 2026-05-02. Nothing here is committed — this is
the "what could be cool" backlog.

> **How to read this doc.** Each item carries an inline effort/impact tag
> so you can eyeball priorities without scrolling to the bottom.
> Format: `[effort · impact]` where effort = low / med / high and impact
> = the same scale.

---

## 1 · Audio & Mood

Audio sells "alive-ness" more than any visual. Start here.

- **Lo-fi tick beat** `[low · high]` — fire a soft kick on every `tick`
  event; pitch-shift on fills, layer a pad on rank-ups. The 5-min tick
  cadence doubles as a tempo grid.
- **Sonified fills** `[low · high]` — map each fill to a piano note keyed
  by sector (XLK = bright, XLU = dark). Buys ascend the scale; sells
  descend. Pairs naturally with the tick beat.
- **Adaptive ambient score** `[med · med]` — a single drone pad whose
  filter cutoff tracks `total_equity / total_allocated`. Green day =
  bright and open; drawdown = muffled and filtered. Layer an on-screen
  "vibe gauge" driven by the same PnL z-score for visual reinforcement.
- **TTS narrator** `[med · high]` — pipe `LlmDecision.reason` to a
  low-cost TTS engine (ElevenLabs Turbo or local Piper). Give each rank
  tier its own voice personality.

## 2 · Agent World — Visuals

The diorama is the hook. These items make it worth watching with the
sound off.

- **Day/night cycle** `[low · high]` — sky tint slides from `#0c1322` →
  `#fef3c7` mapped to NYSE open/close. Stars twinkle pre-market; sunset
  glow fades after the bell.
- **Weather layer** `[low · high]` — rain particles when day PnL < −1 %,
  sun rays when > +1 %, snow when market is closed. Pure SVG/CSS — zero
  data cost, maximum vibes.
- **Camera dolly** `[med · med]` — periodically zoom into the Battlefield
  zone to spotlight the agent that just filled, then ease back out
  (think SimCity intro fly-by).
- **Confetti rank-up cutscene** `[med · med]` — pause the world for 1.5 s,
  fire a particle burst, float the promoted sprite upward with a halo,
  then resume.
- **Pixel-art skin toggle** `[high · low]` — swap SVG sprites for 16-bit
  PNGs and switch font to a pixel face. Genre dial: "modern" / "retro" /
  "wireframe". Fun, but art asset cost is real — save for later.
- **Mascot pet** `[low · low]` — a small chicken/cat sprite that randomly
  walks the bridges, idle-bobs, never trades. Pure flavor, quick win if
  you need a break task.

## 3 · Story & Commentary

Narrative turns data into drama. These make the stream feel like a
broadcast, not a dashboard.

- **Hourly newsroom bulletin** `[low · high]` — LLM writes a 2-line
  update every hour ("Senior Agent #023 posted its best day yet…") shown
  via an "ON AIR" lower-third and narrated over a stinger. Ties into
  existing journal data.
- **Agent of the Day card** `[med · med]` — pre-roll on stream start:
  top performer's name, rank arc, current holding, win rate. Generated
  server-side at midnight.
- **Rivalry banter** `[med · med]` — when two agents take opposite sides
  of the same symbol within one tick, generate a one-line quip between
  them ("Agent #07 thinks XLK is done? Agent #12 disagrees — loudly.").
- **Trade-of-the-tick replay** `[med · high]` — biggest-impact fill gets
  a 4-sec slow-mo overlay: zoom on agent + price tag + cause (LSTM
  probability, LLM reasoning). A signature recurring segment.
- **Periodic "What am I watching?" explainer** `[low · high]` — *(new)*
  every 30–60 min, auto-display a brief on-screen card or TTS line
  explaining the stream concept for new viewers. Crucial for retention
  when a raid or front-page moment hits.

## 4 · Twitch & Chat Integration

Give viewers a reason to stay and come back.

- **!agent NAME** `[low · med]` — viewer picks any agent and gets its
  journal summary in chat.
- **!bet SYMBOL up/down** `[med · med]` — "vibe vote" that feeds an
  aggregated sidebar gauge; track viewer accuracy vs. the LSTMs over
  time. Read-only, no real money.
- **Channel-point name claim** `[low · med]` — viewer redeems points to
  rename an agent; persisted to a `display_name` column.
- **Auto Twitch Predictions** `[med · med]` — create a Prediction at
  market open ("Will TradeFarm be green at close?") and resolve at
  4 pm ET.
- **Clip-worthy moment auto-capture** `[med · high]` — *(new)* hook into
  OBS replay-buffer or the Twitch clip API to auto-save highlights when
  a rank-up, large PnL swing, or rivalry trade fires. Feed captured
  clips into the daily recap pipeline or post directly to social.

## 5 · Dev Tooling (for live-coding co-streams)

Make the coding part of the stream look as cool as the trading.

- **Editor heat trail** `[low · low]` — a tail in your editor showing
  the last N typed lines as glowing residue (cosmetic Neovim/VS Code
  overlay).
- **Build-success chime** `[low · low]` — play a short stinger when
  `pytest` / `tsc -b` succeeds in the background. Instant audio
  feedback.
- **"What's the agent thinking" sidebar** `[med · med]` — pin a single
  agent to a dock panel that live-updates as you edit code; useful for
  demoing strategy changes in real time.

## 6 · Production Polish

The boring stuff that makes everything else look professional.

- **Lower-thirds builder** `[low · med]` — generic "title / subtitle"
  component triggered via WS event, so banners can fire from a button
  or CLI.
- **CRT / VHS shader** `[med · low]` — full-screen WebGL filter
  (chromatic aberration + scanlines + grain). Toggle hotkey from Admin
  overlay. Cool, but easy to overdo — keep it subtle.
- **OBS WebSocket integration** `[med · high]` — let backend events flip
  OBS scenes (e.g., switch to "Promotion Cutscene" on rank-up). Key
  enabler for cutscenes and auto-capture above.
- **Daily recap reel** `[high · high]` — at close, the backend dumps the
  day's top-3 events; a headless ffmpeg job composes a 30-sec MP4
  (Agent World screencaps + commentary subtitles) for short-form posts.
- **Stream health dashboard** `[med · med]` — *(new)* a lightweight
  internal page (or Admin overlay tab) showing OBS connection status,
  audio levels, TTS queue depth, and last-tick timestamp. Prevents
  silent failures during unattended streaming hours.

---

## Top Picks — Cheapest Wins First

The ranking heuristic: **low effort + high impact first**, with a bias
toward items that unlock or improve other items downstream.

| # | Item | Why it's first |
|---|------|---------------|
| 1 | **Lo-fi tick beat + sonified fills** | Biggest vibe upgrade for minutes of work, zero ongoing cost. |
| 2 | **Day/night sky + weather** | Readable from across the room, no extra data, sets the diorama tone. |
| 3 | **Hourly TTS newsroom bulletin** | Ties existing LLM/journal data into a recurring stream segment with minimal code. |
| 4 | **OBS WebSocket integration** | Enabler — once scenes can switch programmatically, cutscenes, auto-capture, and recap all get easier. |
| 5 | **"What am I watching?" explainer** | Near-zero effort, directly improves viewer retention. |

## Open Questions

These need answers before the related work starts. Suggested defaults in
**bold** so the list doesn't stall.

| Question | Options | Suggested default |
|----------|---------|-------------------|
| Audio engine | Web Audio API in Tauri webview vs. native Rust via `cpal` | **Web Audio** — simpler, good enough for lo-fi layers; revisit if latency is painful. |
| Twitch integration path | Server-side bot vs. browser-source overlay | **Server-side bot** — easier to test headless, overlay can still consume its events for display. |
| Art assets | Pixel-art commission vs. SVG + emojis | **SVG + emojis for v1**, commission later if pixel-art toggle gains traction. |
| Stream persona | Single brand ("TradeFarm Live") vs. multi-voice (Anchor, Color Commentator, Quant) | **Single brand to start**, add a second voice only when rivalry banter ships. |
