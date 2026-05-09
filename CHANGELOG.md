# Changelog

All notable changes to this project. The format is loosely based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
follows [Semantic Versioning](https://semver.org/) starting from `0.1.0`.

Dates are when the commit landed on `main`. Hashes link to the canonical
commit on GitHub.

## [Unreleased]

(Nothing pending — see [0.5.0] below.)

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
