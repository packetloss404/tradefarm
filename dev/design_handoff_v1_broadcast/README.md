# Handoff: tradefarm Streamer Layout · V1 (Sports Broadcast)

## Overview

This is a **1920×1080 broadcast overlay** for live-streaming a 100-agent paper-trading farm to YouTube/Twitch. It frames the activity of the agents as a sports broadcast: a top scoreboard, a left leaderboard, a center "race to alpha" + agent grid, a right swappable PLAYS / CHAT panel, a lower-third storyline strip, and a bottom news ticker.

The design assumes a single **simulated tick stream** (~600ms cadence) feeding all panels — agent equity, fills, promotions/demotions. In production this should be replaced with the real backend feed (websocket / SSE).

## About the Design Files

The files in this bundle are **design references created in HTML** — a working React-via-Babel prototype showing intended look, behavior, and animation. They are **not production code to copy verbatim**.

The task is to **recreate this design inside the target codebase's existing environment** (its component library, design tokens, state management, data layer) — not to ship `preview.html`. The Babel-in-browser setup here exists only so the prototype runs without a build step.

If the target codebase doesn't yet have an environment, React + TypeScript with a typed websocket feed is a reasonable choice. The full visual style (colors, typography, layout) is intended to be reproduced **pixel-perfectly**.

## Fidelity

**High-fidelity.** All colors, typography sizing, spacing, borders, animations, and copy are final. Recreate pixel-perfectly using the codebase's existing libraries and patterns.

## Files in this Bundle

- `screenshots/01-broadcast-plays.png` — full 1920×1080 frame, PLAYS tab active.
- `screenshots/02-broadcast-chat.png` — full 1920×1080 frame, CHAT tab active.
- `preview.html` — runnable preview. Open in a browser to see the design live (auto-scales to viewport).
- `v1-broadcast.jsx` — the **only design file** for V1. Every visual component is here.
- `shared.jsx` — small utilities used by V1 (`Sparkline`, `LiveDot`, `MarketBadge`, `ETClock`, `useNow`, `useTickPulse`, `useAnimatedNumber`, `fmtMoney`, `fmtPct`, `stratColor`, `pnlColor`).
- `mock-data.jsx` — the simulated tick stream (`useStreamMock`) plus the `STRATEGIES`, `RANKS`, `STRATEGY_LABEL`, `STRATEGY_HUE`, etc. constants. Replace `useStreamMock` with the real backend feed; keep the constants.

## Canvas

- **Resolution:** 1920×1080, fixed. The overlay is meant to render at exactly this size into the broadcaster's compositor (OBS, Streamlabs). Do not make it responsive.
- **Background:** `#08090d` (V1_BG).
- **Default font:** `"Helvetica Neue", Helvetica, Arial, sans-serif`.
- **Numeric / monospace font:** `"JetBrains Mono", monospace` — used everywhere a value is meant to read as a "price tag" (P&L numbers, ticker symbols, timestamps, agent IDs, all-caps labels).
- **Body text smoothing:** `-webkit-font-smoothing: antialiased`.

## Top-Level Layout

```
┌──────────────────────────────── Scoreboard · 96px ─────────────────────────────────┐
│ [Logo]  TRADEFARM        FUND EQUITY · DAY P&L · P&L% · PROFITABLE       Clock·LIVE│
├──────────────┬─────────────────────────────────────┬───────────────────────────────┤
│              │  RACE TO ALPHA · LIVE               │ [PLAYS]  [CHAT]               │
│  Leaderboard │  ─────────────────────────          ├───────────────────────────────┤
│  TOP 12·ALPHA│  6 lane bars (animated horses)      │  swappable feed:              │
│              ├─────────────────────────────────────┤                               │
│  380px wide  │  THE FARM · 64 ACTIVE               │  PLAYS = fills feed (7)       │
│              │  8×8 mini-card grid                 │  CHAT  = streamer chat (22)   │
│              │                                     │  360px wide                   │
│              │                                     │                               │
│              │  ┌──── Lower Third (absolute) ────┐ │                               │
│              │  │ PROMOTION/DEMOTION banner      │ │                               │
│              │  └────────────────────────────────┘ │                               │
├──────────────┴─────────────────────────────────────┴───────────────────────────────┤
│ FARMLINE marquee · 60px · scrolling fills + promos                                  │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

CSS structure (the root):

```jsx
<div style={{
  width: 1920, height: 1080, background: '#08090d', color: '#fafafa',
  fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
  display: 'flex', flexDirection: 'column', position: 'relative', overflow: 'hidden',
}}>
  <V1Scoreboard />               {/* 96px tall */}
  <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '380px 1fr 360px', minHeight: 0 }}>
    <V1Leaderboard />
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0,
                  borderLeft: '1px solid #22262f', borderRight: '1px solid #22262f' }}>
      <V1RaceLanes />
      <V1Grid />
    </div>
    <V1RightPanel />              {/* PLAYS / CHAT */}
  </div>
  <V1LowerThird />                {/* absolute, bottom: 76, height: 64 */}
  <V1Ticker />                    {/* 60px tall */}
</div>
```

## Design Tokens

### Colors

```
V1_BG        #08090d   page background
V1_PANEL     #10131a   panel background
V1_PANEL_HI  #171b25   elevated mini-card / hover
V1_LINE      #22262f   borders, dividers
V1_AMBER     #fbbf24   primary accent (also used for tick-flash glows)

text          #fafafa  primary
text dim      #d4d4d8  secondary
text muted    #9ca3af  labels
text hint     #71717a  timestamps, footnotes
text faint    #52525b  empty-state

profit       #10b981   bull green
profit hi    #34d399   bull bright
loss         #f43f5e   bear red
loss hi      #fb7185   bear bright
```

### Strategy hues (oklch chroma 0.18, lightness 0.72)

```
momentum  hue 24    → amber-ish        oklch(0.72 0.18 24)
lstm      hue 200   → cyan-blue        oklch(0.72 0.18 200)
llm       hue 280   → violet           oklch(0.72 0.18 280)
```

Dim variant for fills: `oklch(0.5 0.12 H)`.

### Rank colors (small dot indicators)

```
intern    #71717a
junior    #a1a1aa
senior    #fbbf24
principal #22d3ee
```

### Typography scale

| Use | Family | Size | Weight | Letter-spacing |
|---|---|---|---|---|
| Brand wordmark | Helvetica | 22 | 800 | 0.5 |
| Brand sub-label | Helvetica | 11 | 600 | 2.4 |
| Scoreboard label | Helvetica | 9 | 700 | 2 |
| Scoreboard value | JetBrains Mono | 30 | 800 | -0.5 |
| Section title (caps) | Helvetica | 13–16 | 800 | 1.6–2 |
| Leader rank # | JetBrains Mono | 14 | 800 | – |
| Leader name | Helvetica | 12 | 600 | – |
| Leader meta | JetBrains Mono | 9 | 400 | 1 |
| Leader pnl% | JetBrains Mono | 13 | 800 | – |
| Lane name | JetBrains Mono | 11 | 700 | – |
| Mini-card name | Helvetica | 9 | 400 | – |
| Mini-card pnl% | JetBrains Mono | 10 | 800 | – |
| Fill agent name | Helvetica | 11 | 400 | – |
| Fill side badge | JetBrains Mono | 9 | 800 | 1 |
| Fill price/qty | JetBrains Mono | 10–11 | 700 | – |
| Chat username | JetBrains Mono | 12 | 800 | – |
| Chat message | Helvetica | 12 | 400 | – |
| Chat badge (SUB/MOD/VIP) | JetBrains Mono | 8 | 800 | 0.6 |
| Lower third headline | Helvetica | 18 | 800 | – |
| Lower third meta | JetBrains Mono | 12 | 400 | 1 |
| Ticker | JetBrains Mono | 14 | 400 | – |
| FARMLINE bug | JetBrains Mono | 14 | 900 | 2 |
| ET clock | JetBrains Mono | 28 | 700 | 1 |

Ratio: caps labels are always tracked-out (letter-spacing 1.4–2.4); numeric values are mono and slightly negative-tracked (-0.5).

### Spacing

- Page padding: 0 (full bleed)
- Scoreboard padding: `0 32px`
- Panel section padding: `12px 16px` (header), `8px 12px` to `16px 20px` (body, varies)
- Mini-card gap: `4px`
- Race-lane gap: `6px`
- Grid gutter (top-level 3-col split): borders only, no gap

### Borders & shadows

- Panel border: `1px solid #22262f`
- Scoreboard bottom border: `2px solid #fbbf24` (the brand stripe)
- Section divider: `1px solid #22262f`
- Mini-card left rail: `3px solid <stratColor>`
- Top-3 leaderboard tint: `linear-gradient(90deg, rgba(251,191,36,0.08), transparent)`
- Logo glow: `0 0 24px rgba(251,191,36,0.35)`
- Lane horse glow: `0 0 10px <stratColor>`
- Tick-flash text shadow (Scoreboard): `0 0 12px <color>55` for ~300ms after each tick

### Border-radius

- Logo block: `6px`
- Panel mini-cards: `2px`
- Race-lane bar: `4px`
- Lane horse marker: `4px`
- Side badge / pill: `2–4px`

## Components — Detail

### 1. Scoreboard (`V1Scoreboard`)

3-column grid: `[320px logo] [1fr scoreboard cells] [auto status]`, height 96px, padding `0 32px`, background `linear-gradient(180deg, #0c0e14 0%, #060709 100%)`, bottom border `2px solid #fbbf24`.

**Logo block:** 52×52 amber tile (`#fbbf24`), black "TF" inside (JetBrains Mono 26 / 900). To the right: "TRADEFARM" (22 / 800) and "100-AGENT LIVE BROADCAST" (11 / 600 / +2.4 tracking).

**Scoreboard cells (4):** equally spaced, separated by 1px×56px vertical dividers (`#22262f`).

| Cell | Label | Value | Color |
|---|---|---|---|
| 1 | FUND EQUITY | `$XXX,XXX` | `#fafafa` |
| 2 | DAY P&L | `+$XX,XXX` or `−$XX,XXX` | green/red |
| 3 | P&L % | `+X.XX%` | green/red |
| 4 | PROFITABLE | `XX/100` | `#fbbf24` |

Label: 9 / 700 / +2 tracking, color `#9ca3af`. Value: JetBrains Mono 30 / 800 / -0.5 tracking. **The equity and P&L values animate** (cubic ease, ~400ms) between ticks via `useAnimatedNumber`.

**Right block:** market badge (`MarketBadge` — green RTH · NYSE pill) → ET clock (28 / 700) → "ET" hint → `LiveDot` (red pulsing dot + "LIVE").

### 2. Leaderboard (`V1Leaderboard`)

380px column. Header: 12px-padded, "TOP 12 · ALPHA" + amber `LEADERS` chip. Below: 12 rows of `V1LeaderRow`.

**Row layout:** 4-col grid `[24 rank] [1fr name+meta] [80 sparkline] [56 pnl%]`, gap 8, padding `8px 12px`, bottom border `1px solid #22262f`. **Rows 1–3 get the amber gradient tint.**

- Rank: JetBrains Mono 14 / 800. Color: `#fbbf24` for #1, `#fde68a` for 2–3, `#9ca3af` else.
- Avatar: 18×18 strategy-color square with 9 / 800 black initials (JetBrains Mono).
- Name: 12 / 600, ellipsis on overflow.
- Meta line: `MOM · JR AAPL` style — JetBrains Mono 9 / +1 tracking, `#71717a`.
- Sparkline: last 20 points, 70×22, strokeWidth 1.5, fillBelow at 18% opacity.
- P&L%: JetBrains Mono 13 / 800, right-aligned, green/red.

### 3. Race lanes (`V1RaceLanes`)

In the center column, top section. Header row: "RACE TO ALPHA · LIVE" + the legend hint "POSITION · 24h P&L NORMALIZED".

6 lanes. Each lane is a 36px tall bar, `1px solid #22262f`, 4px radius, with a barber-stripe finish line on the right (`repeating-linear-gradient(0deg, #fff 0 6px, #000 6px 12px)`, 12px wide, opacity 0.7).

**Progress fill:** `linear-gradient(90deg, dimStratColor, stratColor)` at 45% opacity, width = pnl percentile mapped 0..100% of lane width. **Animates** with `useAnimatedNumber` (600ms ease).

**Horse marker:** 32px square, strategy color, 4px radius, centered on the progress edge with `0 0 10px <stratColor>` glow. Initials inside (JetBrains Mono 11 / 900 / black).

**Lane label** "L1"…"L6" inside the bar at the left edge (10 / 800 / +1.5 tracking, white, text-shadow `0 0 4px #000`).

**Right side:** agent name (white, with `0 0 6px rgba(0,0,0,0.8)` shadow) + pnl% (mono).

Repeating-linear-gradient track texture: `repeating-linear-gradient(90deg, transparent 0 36px, rgba(255,255,255,0.025) 36px 38px)`.

### 4. Agent grid (`V1Grid`)

Center column, lower section. Header: "THE FARM · 64 ACTIVE" + 3 legend chips (MOM / LSTM / LSTM+LLM colored squares).

Grid: `repeat(8, 1fr)` × 8 rows, gap 4px, row height 46px → 64 cells of `V1MiniCard`.

**Mini-card** (46px tall):
- Background `#171b25`, left border `3px solid <stratColor>`, 2px radius.
- Top row: agent ID `#003` (mono 9 / 800 / `#9ca3af`) + name first-segment (9 / `#d4d4d8` / ellipsis).
- Bottom row: 12-pt sparkline (50×14 / strokeWidth 1) + pnl% (mono 10 / 800).

### 5. Right panel — PLAYS / CHAT (`V1RightPanel`)

360px column. **Top: a 2-col tab switcher** (`V1Tab`) — `PLAYS` (amber dot, "fills" sub-label) and `CHAT` (purple dot `#a78bfa`, "live · 12.4K" sub-label).

Tab styling:
- Padding `12px 14px`. Bottom border 2px (amber when active, transparent when inactive).
- Active tab gets `#171b25` background.
- Active tab dot pulses (`pulse-dot` class, 1.2s ease-in-out).
- Label: 13 / 800 / +1.6 tracking. Sub: mono 9 / 600 / +1.2 tracking, color `#71717a`.

#### PLAYS (`V1Plays`)

Stack of up to 7 `V1FillCard`s. Each card:
- Bottom border `1px solid #22262f`, padding `10px 12px`.
- **Freshest card** has `linear-gradient(90deg, #fbbf2422, transparent)` background.
- Layout: `[32 avatar] [1fr name + meta] [auto timestamp]`, gap 10, items center.
- Avatar: 32×32, strategy color, 4px radius, mono 11 / 800 black initials.
- Name: 11 / `#d4d4d8` / ellipsis.
- Meta: side badge (BUY = `#10b98133`/`#34d399`, SELL = `#f43f5e33`/`#fb7185`, mono 9 / 800 / +1) → `qty SYMBOL` (mono 11 / 700 / white) → `@ $price` (mono 10 / `#71717a`).
- Timestamp: mono 9 / `#71717a`, right-aligned, `HH:MM:SS`.

#### CHAT (`V1Chat`)

Twitch-style stream chat, fills bottom-up. Uses `useStreamerChat({fills, promotions})` to produce messages from three sources:

1. **Ambient chatter** every ~1100ms (burst of 1–3 messages). Random viewer + random line from a 30-line ambient pool (e.g. `momentum eating today fr`, `lstm_v1 absolutely cooking 🔥`, `KEKW the carry desk`).
2. **Reactions to fills**: 55% of new fills produce one chat reaction referencing the agent or symbol (e.g. `pog AAPL`, `that's a chunky NVDA ticket`).
3. **System messages** on every promotion/demotion: amber strip with PROMOTION/DEMOTION label, agent name, rank transition (`JR→SR`), and reason.

Capacity: 50 messages buffered, last 22 rendered. `scrollRef` auto-scrolls to bottom on update.

**Chat row** (`V1ChatRow`, kind=chat):
- Padding `3px 12px`, line-height 1.45, baseline alignment, gap 5.
- Freshest row: `rgba(251,191,36,0.04)` background that transitions away over 400ms.
- Badges (SUB/MOD/VIP) are 8 / 800 / +0.6 mono pills, 1×4 padding, 2px radius:
  - `SUB` = `#fbbf24` bg / black text
  - `MOD` = `#10b981` bg / black text
  - `VIP` = `#ec4899` bg / black text
  - Translated up 1px so they hang from baseline.
- Username: mono 12 / 800. Color is per-chatter (see `V1_CHATTERS` constant — 14 chatters with hand-picked colors).
- Colon separator: `#52525b`.
- Message: 12 / 400, `#e5e7eb`, `wordBreak: break-word`.

**System chat row** (kind=system):
- `linear-gradient(90deg, #fbbf2422, transparent)` background, left border `3px solid #fbbf24`.
- Up/down arrow (`↑`/`↓`) in amber, mono 12 / 900.
- "PROMOTION" / "DEMOTION" label (mono 11 / 800 / +1, `#fde68a`) · agent name · rank transition · reason.

**Composer (fake):** at the bottom, `1px solid #22262f` top border, `#0a0c12` background, padding `8px 12px`. A black input pill (`flex: 1`, mono 11 / `#71717a`) reading `Send a message ▌` (the `▌` blinks via `cursor-blink`). To the right, an amber `CHAT` button (mono 11 / 800 / +1, black text, 7×12 padding, 3px radius).

### 6. Lower third (`V1LowerThird`)

Absolute, `left: 32, right: 32, bottom: 76, height: 64`. `linear-gradient(90deg, rgba(8,9,13,0.95), rgba(8,9,13,0.6))` background, `4px solid #fbbf24` left border, `backdrop-filter: blur(8px)`, `pointerEvents: none`.

Two states:

**Promotion** (when `promotions[0]` exists): amber `PROMOTION` (or `DEMOTION`) chip → 44×44 lstm-color avatar with initials → headline (18 / 800: agent name) and meta (`JR → SR · Sharpe>2.0 30d`) → big up/down arrow (mono 22 / 800 in green or red).

**Storyline fallback**: amber `STORYLINE` chip → "{X} agents in profit · {Y} actively trading" (16 / 600).

### 7. FARMLINE ticker (`V1Ticker`)

60px tall, black background, `2px solid #fbbf24` top border.

**Bug:** amber block, mono 14 / 900 / +2, black text, "FARMLINE", padding `0 18px`.

**Marquee:** items rendered twice and scrolled with `@keyframes v1-marquee` (60s linear infinite, `translateX(0)` → `translateX(-50%)`).

Items:
- **Promotions** first (up to 5): amber color, prefixed with `↑ PROMOTED` / `↓ DEMOTED`, full reason in parens.
- **Fills** next (up to 12): `#e5e7eb` color, format `SYMBOL · SIDE qty@$price · agent name`.
- Each item separated by `· ` with a `#52525b` bullet, mono 14, padding `0 24px`.

## Interactions & Behavior

- **Tab switch (PLAYS / CHAT):** local `useState`, instant. Active tab shows amber underline + dim panel highlight + pulsing dot.
- **All other panels:** read-only, animated by the tick stream — no user interaction.
- **Tick cadence:** 600ms (`TICK_MS` in `mock-data.jsx`).
  - Each tick: every agent's equity drifts (with `lstmDir` bias and per-agent drift), sparkline rolls forward (32 points retained).
  - 78% of ticks emit 1–2 fills (chat sometimes reacts).
  - 4% of ticks emit a promotion (65% promote, 35% demote).
- **Animations:**
  - Scoreboard equity / day P&L: 400ms cubic-out interpolation between ticks.
  - Race lane progress: 600ms cubic-out interpolation between ticks.
  - Tick-flash glow on scoreboard values: 250ms text-shadow pulse on each tick.
  - Pulse-dot (LIVE indicator, active tab dot): 1.2s ease-in-out scale 1↔0.5 + opacity 1↔0.4.
  - Chat freshest-row highlight: 400ms `background` transition.
  - Cursor blink (chat composer): 1s step-end blink.
  - FARMLINE marquee: 60s linear loop.

## State Management

Single React hook `useStreamMock()` returns:

```ts
{
  agents: Agent[],          // 100 agents (see shape below)
  fills: Fill[],            // last 30 fills, freshest first
  promotions: Promotion[],  // last 20 events (up & down), freshest first
  account: {
    totalEquity, allocated, pnl, pnlPct,
    profit, loss, waiting, trading,  // counts by agent.status
    tick,
  },
  byStrategy: {
    momentum: { agents, equity, pnl, pnlPct, winners },
    lstm:     { ... },
    llm:      { ... },
  },
  tick: number,
}
```

### Agent shape

```ts
{
  id: number,           // 1..100
  name: string,         // "Tickbelinda Stan"
  initials: string,     // "TS"
  strategy: 'momentum' | 'lstm' | 'llm',
  status: 'profit' | 'loss' | 'trading' | 'waiting',
  rank: 'intern' | 'junior' | 'senior' | 'principal',
  symbol: string | null,
  equity: number,
  pnl: number,
  pnlPct: number,
  sparkline: number[],  // 32 points, equity history
  lstmConf: number,     // 0.2..0.99
  lstmDir: 'up' | 'flat' | 'down',
  llmStance: 'trade' | 'wait',
  drift: number,        // private random bias per tick
}
```

### Fill shape

```ts
{
  id: string,
  t: number,                  // ms epoch
  agentId, agentName, initials,
  strategy, rank,
  symbol: string,
  side: 'buy' | 'sell',
  qty: number,                // 1..9
  price: number,              // 50..900
}
```

### Promotion shape

```ts
{
  id: string, t: number,
  agentId, agentName, initials,
  fromRank, toRank,
  direction: 'up' | 'down',
  reason: string,             // "Sharpe>2.0 30d", "Drawdown>12%", etc.
}
```

### Replacing the mock with a real feed

In production, replace `useStreamMock()` with a hook that subscribes to the backend (websocket / SSE) and exposes the **same return shape**. The components below it never need to change.

The chat hook `useStreamerChat({fills, promotions})` should also be re-pointed at the real chat feed (Twitch IRC / YouTube live chat API). The 14-chatter constant + ambient line pool can stay as fallback content for offline rehearsal mode.

## Assets

No external assets — every visual element is rendered with HTML/CSS/SVG. Sparklines are inline SVG (`Sparkline` in `shared.jsx`). Icons (`↑`, `↓`, `●`, `★`, `🚀`, `🔻`, `▌`) are Unicode glyphs, not images.

## Notes on production reimplementation

- The Babel-in-browser setup is for prototyping only. In production, build with the codebase's existing toolchain (Vite/Next/etc.).
- All inline-styled components should be ported to the codebase's preferred styling (CSS Modules, Tailwind, styled-components, vanilla-extract). The token list above is canonical.
- Numbers must reflow without layout shift — that's why every numeric value uses `JetBrains Mono` (tabular figures). If the codebase uses a different mono, ensure it has tabular-num support, or use `font-variant-numeric: tabular-nums`.
- The 60s marquee is keyframe-animated — pause it on `prefers-reduced-motion` if accessibility matters for the broadcaster's compositor preview.
- The 600ms tick cadence is tuned for a "live but not anxious" feel. The real backend may push faster than that — debounce updates to ≥300ms for the visible animations to read clearly on stream.
