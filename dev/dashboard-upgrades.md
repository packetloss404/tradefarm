# Dashboard upgrades — backlog

Captured during the v2 brainstorm. The four picks below were shipped in
`feat(dashboard): v2`. Everything else lives here as a one-line idea + a
rough effort estimate (S = a couple of hours, M = an afternoon, L = a day or
more) + the data source it needs.

## Shipped (v2)

- Sticky KPI header with tick countdown + market clock + ON AIR badge.
- Broadcast panel — scene buttons, lower-third, audio toggle, replay
  pre-roll, liveness dot.
- Tabbed lower row — Brain / Promotions / Strategies / Orders fold into a
  single panel with tab persistence.
- Command palette (Ctrl+K) — fuzzy nav to agents, symbols, scenes, admin.

## Now / next

- **Agent Grid v2 — crypto-style cards.** Mockup-faithful redesign with
  sparkline, rank pip, P&L, exposure, confidence gauge, risk meter.
  Effort: M. Source: `/agents`, `/agents/{id}/sparkline` (new),
  `RiskManager.exposure()`.
- **Agent detail modal — sparkline + last 20 fills + LLM rationale.**
  Effort: S. Source: existing `/agents/{id}` + `/agents/{id}/notes`.
- **Symbol drawer.** Click a fill ticker → side drawer with last-30-day
  candles, agent rosters holding it, recent fills. Effort: M. Source:
  `/symbol/{sym}` (new endpoint).
- **Sector / strategy heatmap mini-tab.** Color tiles for
  momentum_sma20 / lstm_v1 / lstm_llm_v1 P&L. Effort: S. Source:
  `/strategies/perf` (new aggregate endpoint).

## Stream remote-control v2

- **Per-agent spotlight.** Force the broadcast app to pin a single agent
  into Hero/Brain. Effort: S. Source: extend `stream_scene` payload with
  `pin_agent_id`.
- **Macros.** Save preset banner+scene combos ("Open bell", "Closing recap")
  and fire from Cmd-K. Effort: S, client-only.
- **OBS-style program/preview.** Two-card panel — current scene + next, with
  a TAKE button. Effort: M.
- **Recap scene.** Auto-builds a 30-second top-of-day summary card on
  market close; trigger on demand. Effort: M. Source: `/recap/today` (new).

## HUD additions

- **Open positions sparkline strip** above the agent grid. One row per
  symbol with mark, P&L, qty. Effort: S. Source: `/positions`.
- **Latency panel.** Last 5 ticks: fetch ms / decide ms / submit ms.
  Effort: S. Source: scheduler instrumentation (new).
- **API spend widget.** Pulled from `/llm/stats` plus a daily cap dial.
  Effort: S.
- **Slow-clients badge.** Surface dropped-WS clients from the bus.
  Effort: S. Source: bus metrics (new).

## Power-user / nav

- **Keyboard map overlay** (`?`). Cheat sheet of every shortcut. Effort: S.
- **URL deep links** (`#agent=42`, `#tab=strategies`). Effort: S.
- **Saved views.** Persist current grid sort/filter as a named view.
  Effort: M.
- **Alerts pane.** Threshold-based desktop notifications (P&L drawdown >
  3%, halted stock detected, LLM provider 5xx). Effort: M.

## Quality of life

- **Light-mode parity.** Currently dark-only; toggle for day-time desks.
  Effort: M (Tailwind theme refactor).
- **Density toggle.** Compact / comfortable rows in tables. Effort: S.
- **Onboarding tour.** First-run popovers explaining sticky header / cmd-K
  / broadcast wire. Effort: S.
- **Mobile read-only view.** Layout collapses to a single column, drops
  admin/broadcast. Effort: M.

## Considering

- **Multi-tab workspaces.** Tabs at top of dashboard for "trading" vs
  "research" vs "broadcast" layouts. Effort: L.
- **Replay scrubber.** Step through any past tick from journal. Effort: L.
  Source: `/journal/replay/{at}` (new).

## Out of scope

- Anything that requires a non-paper broker.
- Real-time charting at sub-second resolution (would replace SWR polling
  with a streaming chart lib — too much rework for v2).
