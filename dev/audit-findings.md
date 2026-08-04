# 20-agent codebase audit — findings & status

Conducted 2026-05-22 via parallel deep-dive subagents across every subsystem.
20 audits, ~14k words of reports. This file consolidates the findings,
ranked by severity, with a status column tracking what's fixed and what
remains.

**Update 2026-05-22 (post-rounds-2-3-4):** the original ledger below
was written after round 1 only. Rounds 2 (clusters A/B/C —
execution + storage + RiskManager), 3 (D-I — data, ML, sidecars, YT,
API hardening), and 4 (J/K/L — stream, broadcast wiring, CI, docs)
have since landed. Statuses below have been updated in place; a
per-round summary is at the bottom under **"Round-by-round status
deltas."**

## Legend

- **CRIT** — data corruption, security exploit, or silent money math error
- **HIGH** — will fire in normal use, degrades replay or live capture
- **MED** — edge case but plausible
- **LOW** — cosmetic / theoretical / future-proofing

Status: **FIXED** (committed), **FIX-NEXT** (next session), **DOC**
(architectural; needs design), **WONTFIX** (acceptable given context).

---

## CRIT — fixed in this commit

| ID | File:line | Finding | Status |
|---|---|---|---|
| C1 | `scheduler.py:220,260` | Risk exits + `last_tick_at` use `datetime.now()` / `pd.Timestamp.now()` — bypass `now_utc()`. Under replay, every time-stop fires spuriously on positions whose `opened_at` is the replayed close but `now` is today. | **FIXED** |
| C2 | `events.py:17`, `decision_feed.py:27` | `_now_iso()` stamps WS event envelopes with wall-clock under replay. | **FIXED** |
| C3 | `dash/Admin.tsx:85-101` | Every keystroke fires `api.adminPatch`. Typing into the masked API-key field (`••••GH8X`) POSTs the dots back, **clobbering the real key in `.env`**. Real data loss. | **FIXED** (debounce + sentinel guard) |
| C4 | `render/headless.py:425` | `render_session(session_id, …)` bypassed the path-traversal guard added to REST + WS. CLI exposure only but the guard is free. | **FIXED** |
| C5 | `youtube_chat.py:209` | OAuth error response body logged verbatim — Google sometimes echoes client_secret fragments. | **FIXED** (scrubbed log + safe summary) |
| C6 | `market/hours.py:31` | `next_open` uses `min(dt.day + 10, 28)` — at month-end + long weekend returns "no market open found" because the window moves *backwards*. | **FIXED** |

## CRIT — fixed in rounds 2/3/4

| ID | File:line | Finding | Status |
|---|---|---|---|
| C7 | `execution/virtual_book.py:94-108` | `apply_fill_delta` long→short flip + short opening: realized_pnl + avg_price both wrong. | **FIXED (round 2)** — replaced with `apply_reconciled_fill(symbol, side, qty, mark_price, actual_price, broker_order_id, at=…)`; correct cash + avg + realized math from delta + recovered pre-fill state. See `tests/execution/test_virtual_book_reconcile.py`. CLAUDE.md gotcha #7 updated. |
| C8 | `execution/virtual_book.py:57` | `defaultdict(lambda: VirtualPosition(""))` autovivifies entries with empty symbol. | **FIXED (round 2)** — plain dict + `_get_or_create(symbol)` helper. |
| C9 | `orchestrator/scheduler.py:572` + `academy/curriculum.py:97` | `_tick_in_progress` polling is not a lock. | **FIXED (round 3)** — `self._tick_lock: asyncio.Lock`; `tick_once()` wraps the body in `async with self._tick_lock`. `_tick_in_progress` stays as a status flag (informational). |
| C10 | `storage/models.py:106-124` | `AcademyPromotion` has no UNIQUE constraint. | **FIXED (round 2)** — `UniqueConstraint("agent_id","from_rank","to_rank","at", name="uq_academy_promotions_unique_crossing")`. |
| C11 | `storage/repo.py:82-165` + `api/main.py` + `api/recap.py` | Live reads mix live + replay rows. | **FIXED (round 2)** — `session_id IS NULL` added to live recap (`api/recap.py`); `journal.close_outcome` uses `_session_id_predicate()`; replay reads bound by current_session_id. |
| C12 | `storage/journal.py:124-142` | `close_outcome` race + ignores session_id. | **FIXED (round 2)** — `.with_for_update(skip_locked=True)` + `_session_id_predicate()` in the WHERE. SQLite no-op, real on Postgres. |
| C13 | `storage/models.py:47-64` | `Trade` has no `broker_order_id` UNIQUE. | **FIXED (round 2)** — added `broker_order_id String(64) NULL` + `UniqueConstraint("broker_order_id", name="uq_trades_broker_order_id")`. Also `agent_id` + `executed_at` indexed. |
| C14 | `yt/upload.py:164-170` | Whole video read into memory + no 401 retry. | **FIXED (round 3)** — chunked resumable PUT with 401-refresh-and-retry; see `src/tradefarm/yt/upload.py` + `tests/yt/test_upload.py`. |
| C15 | `orchestrator/broadcast_recap.py` + `broadcast_scheduler.py` | Untracked, never instantiated. | **FIXED (round 4)** — constructed in `Orchestrator.__init__`, installed as module globals only by `start_background()` (so tests don't trash global arbiter state) and uninstalled by `stop_background()`. CLAUDE.md gotcha #15 added. |
| C16 | `tests/coverage` | Zero tests for many subsystems. | **PARTIAL** — added `tests/execution/test_virtual_book_reconcile.py`, `tests/test_audit_fixes.py`, `tests/test_audit_round2_fixes.py`, `tests/test_risk_audit_fixes.py`, `tests/data/test_bar_cache_audit.py`, `tests/test_pipeline_hardening.py`, `tests/yt/test_upload.py`, `tests/yt/test_metadata.py`, `tests/orchestrator/test_broadcast_*.py`. Still no tests for `alpaca_broker`, `lstm_llm_agent`, `audience`, `backtest` CLI, `eodhd` (network-dependent); no frontend test infra. |
| C17 | `data/bar_cache.py` + `eodhd.py` | Today's bar cached, never re-fetched after settlement. | **FIXED (round 3)** — `covers()` returns False when `end >= _wall_today_utc()`; `merge()` filters today's row out of `persistable`. Tests in `tests/data/test_bar_cache_audit.py`. |

## HIGH — fixed in this commit

| ID | File:line | Finding | Status |
|---|---|---|---|
| H1 | `streak_watcher.py:65`, `auto_director.py:51` | `_utcnow()` bypasses replay clock. | **FIXED** |
| H2 | `agents/backtest.py:28`, `lstm_train.py:35` | `date.today()` — fine for live CLI, but trivial migration to `today_utc()`. | **FIXED** |
| H3 | `config.py:27` | `auto_tick_interval_sec` defaults to `0` (silent disable). This is exactly the bug we hit this week. | **FIXED** (default → 300) |
| H4 | `dash/Admin.tsx` (related to C3) | Error state never auto-clears; SECRET_KEYS masked sentinel POSTed back. | **FIXED** |
| H5 | `dash/Episodes.tsx:387` + `mockData.ts:61` + `dash/Research.tsx` | `new Date("2026-05-19")` hardcoded as "today" — heatmap shifts off real today. | **FIXED** (use today's actual date dynamically) |

## HIGH — status after rounds 2/3/4

| ID | Finding | Status |
|---|---|---|
| H6 | `commentary_loop.py:298` recreates LLM overlay on every 45s tick. | FIX-NEXT (still open) |
| H7 | `streak_watcher.py:165` serial DB queries per agent. | **FIXED (round 4 / via streak_watcher refactor)** — see commit `bbee2d5`. |
| H8 | `predictions.py:256-266` daily reset double-walks `open → locked → revealed` in one tick. | **FIXED (round 2)** — see `tests/test_audit_round2_fixes.py::test_predictions_reset_evening_does_not_walk_to_revealed`. |
| H9 | `youtube_chat.py` no circuit breaker for revoked refresh token. | **FIXED (round 3)** — circuit breaker + scrubbed-log on auth-error body (also closes C5). See `tests/orchestrator/test_youtube_chat.py`. |
| H10 | `stream/` — `data-scene-ready` only on `SceneRotator`; PreRoll/v1-broadcast never signal ready → headless hangs. | **FIXED (round 4)** — ready signalling extended; headless renderer no longer hangs. |
| H11 | `stream/` — `Date.now()` callsites wall-clock under replay. | **FIXED (round 4)** — `replayNow()` / `replayDate()` shim in `stream/src/shared/replayMode.ts`. CLAUDE.md gotcha #13 added. |
| H12 | `stream/hooks/useStreamState` opens multiple `/ws` per tab. | FIX-NEXT (still open) |
| H13 | `web/hooks/useEventFeed.feed.account` sticky after reconnect. | **FIXED (round 4)** — see `web/src/hooks/useEventFeed.ts` diff. |
| H14 | `config.py` env-var shadowing hides admin `.env` writes. | FIX-NEXT (still open) |
| H15 | `tts/run.py:198` may write `b"<coroutine>"`. | **FIXED (round 3)** — uses `with_streaming_response`; see `tests/tts/test_run.py`. |
| H16 | `script/write.py` prompt injection via beat headlines. | **FIXED (round 3)** — `<beat>…</beat>` delimiters; see `tests/script/test_write.py`. |
| H17 | `risk/manager.py` per-symbol cap was per-trade. | **FIXED (round 2)** — `check_entry` accounts for existing notional; see `tests/test_risk_audit_fixes.py::test_check_entry_rejects_adds_that_breach_cap`. |
| H18 | Cap anchored to `starting_capital` not equity. | **FIXED (round 2)** — `cap_anchor = min(starting, max(0, equity))`. |
| H19 | Trailing peak never reset on close. | **FIXED (round 2)** — `_peak_seeded_at[symbol]` + reset when `pos.opened_at > peak_seeded_at`. |
| H20 | Time-stop used wall-clock days. | **FIXED (round 2)** — `market.hours.trading_days_between(opened_at, now)`. |
| H21 | `_apply_rank_multiplier` clobbered explicit caller cap. | **FIXED (round 2)** — gated on `self._limits_explicit` flag. |
| H22 | `lstm_model.py` no FEATURE_NAMES embedded — gotcha #6 unguarded. | **FIXED (round 3)** — `save()` embeds `feature_names`; `load()` `RuntimeError`s on mismatch (legacy artifacts → structured warning). CLAUDE.md gotcha #6 updated. |
| H23 | `backtest.py` look-ahead bias (decision at `close[t]` + fill at `close[t]`). | **FIXED (round 3)** — shifted to next-bar open. |
| H24 | `lstm_train.py` window overlap leakage in train/val split. | **FIXED (round 3)** — split on raw bars + embargo gap. |
| H25 | `data/eodhd.py` no retry/backoff. | **FIXED (round 3)** — `EOD_MAX_RETRIES=3` with exp backoff + jitter cap; empty-200 logged distinctly. |
| H26 | `bar_cache.py` parquet writer not concurrency-safe. | **FIXED (round 3)** — per-symbol `threading.Lock` + temp-file-then-`os.replace`. Tests in `tests/data/test_bar_cache_audit.py`. |
| H27 | `/backtest/run` no rate limit / per-symbol cap / max-inflight. | **FIXED (round 3)** — added limits in `api/backtest.py`. |
| H28 | CORS allows LAN + no auth on destructive endpoints. | **FIXED (round 3)** — `settings.api_shared_secret` + `X-TradeFarm-Token` middleware in `api/main.py`. NEW operator knob; documented in CLAUDE.md gotcha #12 + `.env.example`. |
| H29 | `metadata.py` DST-naive publish-at. | **FIXED (round 3)** — `zoneinfo.ZoneInfo("America/New_York")`. |
| H30 | `yt/upload.py` thumbnails.set URL malformed. | **FIXED (round 3)** — `uploadType=media&videoId=…`; tests in `tests/yt/test_upload.py`. |
| H31 | No CI, ffmpeg undocumented prereq, README docs links 404. | **FIXED (round 4)** — `.github/workflows/ci.yml` (ruff check + ruff format + pytest + frontend typecheck/build), README "Requirements" section now lists ffmpeg / `--extra vod` / Playwright Chromium prereqs. |

## MED — defer (catalogued for future)

- `commentary_loop._recent_fills_from_orch` returns open positions not recent fills → cost gate misfires
- `audience.py:347` rebuilds deque O(N) per pop; missing lock around approve/reject race
- `web/components/BacktestModal.tsx` poll interval leaks on backend disconnect
- `dash/Dashboard.tsx` style-injection survives HMR but body attr doesn't
- `vod/SessionControl` ManifestPanel "fills today" reads ws-buffer cap, not real count
- ~~`stream/AgentWorldXL` 60Hz rAF triggers full SVG re-render of 100 sprites~~ — **FIXED (round 6, C5)**: rAF mutates `camGroupRef.setAttribute("transform", …)` + cloud ellipse `cx` directly, zero `setState` per frame.
- `stream/RecapScene` remounts on every scene rotation, restarts sequence
- `web/api.ts` SWR errorRetryInterval not set → single 5xx white-screens dashboard
- 30+ more — see individual audit reports in agent traces

## LOW — defer (catalogued)

- Skeleton-comment lies in `session/run.py`, `manifest.py`, `replay.py`, `closing_snapshot.py` (modules are fully implemented but docstrings say "skeleton")
- `web/src/lib/buildCommands.ts:70` no-op symbol-filter command
- `stream/components/MacroFireBurst.tsx:78` audio wiring deferred
- `metadata.py` em-dash `−` vs ASCII `-` breaks `grep`-on-amount
- ~20 more cosmetic findings

---

## Top 10 by money-loss / security potential (post-0.6.0 status)

All ten items from the original (round-1) top-10 have been closed across
rounds 2-8. List preserved for the audit trail:

1. **C7** — apply_fill_delta short/flip — **FIXED** (round 2,
   renamed `apply_reconciled_fill`; reinforced by round-6 C1 flat-only
   invariant that makes the flip path unreachable)
2. **H17/H18/H19** — RiskManager cap + trailing peak + time-stop —
   **FIXED** (round 2)
3. **C11** — live queries mix replay rows — **FIXED** (round 2)
4. **C13** — Trade dedupe — **FIXED** (round 2, `broker_order_id` UNIQUE)
5. **C14** — YT upload in-memory + no 401 retry — **FIXED** (round 3)
6. **C12** — journal.close_outcome race — **FIXED** (round 2)
7. **C9/C10** — curriculum race + promotion dedupe — **FIXED** (rounds 2 + 3)
8. **H10/H11** — stream scene-ready + `replayNow()` — **FIXED** (round 4)
9. **H28** — auth on destructive endpoints — **FIXED** (round 3,
   `API_SHARED_SECRET`; reinforced by round-6 C3 fail-fast bind + C4
   default-safe CORS)
10. **C16** — test coverage — **PARTIAL** (556 tests / 72 files at
    0.6.0; `alpaca_broker`, `lstm_llm_agent`, `audience`, `backtest`
    CLI, `eodhd`, and the frontend still have no test infra)

**Post-0.6.0 priority surface (the next top-10 candidates):**

- H6 — `commentary_loop` recreates LLM overlay each 45s tick (defeats
  keepalive + prompt cache)
- H12 — multiple `/ws` per tab (lift `useStreamState` into a context;
  only half-fixed in round 4)
- H14 — env-var shadowing hides admin `.env` writes after restart
- Backend `pnl_daily` denominator hardcoded to 1000.0 (ignores
  `agent_starting_capital`)
- Backend two LLM hot paths (`llm_providers.py`,
  `commentary_loop.py`) still spin a fresh `httpx.AsyncClient` per
  call (mirror the `eodhd.py:72-74` pattern)
- Backend MiniMax provider has no retry on transient 5xx/429 and
  accepts any `minimax_base_url`
- Backend `_recent_fills_from_orch` returns open positions, not
  recent fills → cost gate misfires on flat markets with positions
  still open from earlier fills
- Frontend `RecentFillsRail` age label uses `Date.now()` only on a
  new fill (5-min-old fill reads "0s")
- Frontend mock data ships in the prod bundle
  (`dash/mockData.ts` + `vod/mockData.ts`)
- Frontend 800ms `useVodSessionLive` heartbeat re-renders the whole
  tree 1.25×/sec to power a cursor-blink

See `REPO_REVIEW.md` + `BACKLOG.md` for the full 2026-07-17 audit list.

---

## Process notes

20 deep-dive subagents in two waves, each cleared to spawn nested
subagents for web research / API verification. Total wall time ~5
minutes per wave (parallel). Reports were 600-1000 words each;
synthesized findings here capture the most actionable subset.

Several findings overlap across audits — surfaced redundantly,
confirming they're real. Examples: scheduler wall-clock bypass found
by 3 different audits; session_id filtering gap found by 2.

---

## Round-by-round status deltas

### Round 1 — `74ef1ce` (CRITs C1-C6 + HIGHs H1-H5)

Wall-clock-under-replay fixes, admin keystroke clobber, render path
traversal, YouTube OAuth log scrub, month-end `next_open` window bug.
Default `auto_tick_interval_sec` 0 → 300.

### Round 2 — `65c86d4` (clusters A/B/C: execution + storage + RiskManager)

C7, C8, C10, C11 (partial), C12, C13; H17-H21. The
`apply_fill_delta → apply_reconciled_fill` rewrite is the
load-bearing change — fully reworked the reverse-and-reapply math.

### Round 2 (catches) — `263dbad` (regression catches + deeper session_id plumbing)

H8 predictions-reset double-walk; finished C11 session_id plumbing on
`recent_outcomes` + similar; `Orchestrator(...)` no longer installs
broadcast arbiter at construction (test pollution).

### Round 3 — `e1dbbfd` (clusters D-I: data, ML, sidecars, YT, API hardening)

C14, C17; H9, H15, H16, H22-H30. Includes the new
`API_SHARED_SECRET` middleware (H28), the FEATURE_NAMES guard in
`lstm_model.save/load` (H22), and the per-symbol parquet write lock
+ atomic rename (H26).

### Round 3 (catches) — `02d1293` (bar_cache, lifespan, ordering, defensive guards)

`bar_cache._wall_today_utc()` distinct from `today_utc()` (replay-safe);
lifespan teardown-on-startup-error; scheduler `_tick_lock` (C9);
defensive guards on `slice_range` empty frames.

### Round 4 — `bbee2d5` (clusters J/K/L: stream, broadcast wiring, CI, docs)

C15 (broadcast scheduler/ledger install on start, uninstall on stop);
H7, H10, H11 (`replayNow()` shim), H13, H31 (CI, ffmpeg docs).

### Round 5 — `1031652` (production polish + runbook)

Alpaca SDK calls offloaded to `asyncio.to_thread` so a 500ms broker
round-trip no longer pauses the tick loop. Per-book reconciled-id LRU
cap (10k). Shared `httpx.AsyncClient` singleton (`runtime/http.py`).
Daily LLM spend ceiling (`runtime/llm_budget.py`,
`llm_daily_budget_usd`). New `/metrics` (Prometheus) and `/readiness`
endpoints. Postgres compatibility in `storage/db.py` with
`schema_version` migration ledger. `RUNBOOK.md` rewrite for round-5
surface. 22 new test files.

### Round 6 — `941150c` (audit top-5)

C1 flat-only invariant on `VirtualBook` — sells are clamped to held
qty, long→short flip is unreachable, reconciler reverses-and-reapplies
to recover pre-fill state. C2 `broker_order_id` dedup is live (column +
UNIQUE + idempotent writes end-to-end). C3 fail-fast on insecure bind
(`_assert_secure_bind()` refuses to start without
`api_shared_secret` on a non-loopback host). C4 default-safe CORS
(loopback + Tauri only; RFC-1918 LAN opt-in via `CORS_ALLOW_LAN`).
C5 `AgentWorldXL` 60fps loop mutates `camGroupRef` + cloud ellipse
`cx` directly — zero `setState` per frame.

### Round 7 — `0aadc52` (audit #6-#10)

C6 `BroadcastSuite` owns the six sidecars + broadcast arbiter; `start()`
is awaited so a boot-time failure propagates instead of being
swallowed by a discarded `create_task`. C7 `ScheduledMoment.state` is
a real `Literal["active","queued","preempted"]`. C8 migration hardening
(check-then-add + `IF NOT EXISTS` on Postgres + `schema_version`
stamping). C9 atomic fill persistence (`record_fill_atomic()` writes
the Trade row and re-syncs positions in one transaction). C10 LLM
parse validation — Pydantic v2 `_LlmDecisionModel` with `Literal`
enums, `size_pct` clamped `[0, 0.25]`, `LlmParseError` distinct from
call failures. C11 dead UI controls disabled with "coming soon"
tooltips.

### Round 8 — `be7b136` (deferred roadmap)

Money is `Decimal` end-to-end (`runtime/money.D()` at the book
boundary, `to_float()` at the JSON/WS/REST edge; sub-cent money grid
with banker's rounding; storage columns
`Numeric(20, 6, asdecimal=True)`). `BroadcastSuite` extraction
(Orchestrator no longer a god object; six sidecars + arbiter hang off
`orchestrator._broadcast_suite`). CI gates mypy + ruff + ESLint
(`[tool.mypy]` block, flat ESLint configs, `npm run lint` in both
frontends).

---

## New gotchas surfaced (folded into CLAUDE.md)

- **Gotcha #12** — `API_SHARED_SECRET` middleware semantics
- **Gotcha #13** — replay clock must be used everywhere
  (`runtime.clock.now_utc` / `replayNow()`); the one exception is
  `bar_cache._wall_today_utc()`
- **Gotcha #14** — `Orchestrator.tick_once()` is serialised by
  `asyncio.Lock`
- **Gotcha #15** — Broadcast scheduler / recap ledger install on
  `start_background()`, NOT in `__init__`
- **Gotcha #16** — CORS is default-safe + env-driven
  (`build_cors_origin_regex(settings)`); loopback + Tauri only by
  default, RFC-1918 LAN ranges opt-in via `CORS_ALLOW_LAN=true`
- **Gotcha #17** — Money is `Decimal` end-to-end. Coerce at the book
  boundary via `runtime/money.D()`; convert back to `float` at the
  JSON/WS/REST edge via `runtime/money.to_float()`. Sub-cent money
  grid (4 dp) with banker's rounding. Storage columns are
  `Numeric(20, 6, asdecimal=True)`.
- **Gotcha #18** — `BroadcastSuite` owns the six presentation sidecars
  (`AutoDirector`, `StreakWatcher`, `CommentaryLoop`,
  `PredictionsBoard`, `AudienceCoordinator`, `YouTubeChatPoller`) plus
  the broadcast arbiter; hangs off `orchestrator._broadcast_suite`.
  Tests can construct bare `Orchestrator(...)` without polluting
  module globals.
- **Gotcha #19** — `BroadcastSuite.start()` is `await`ed. A boot-time
  failure propagates instead of being swallowed by a discarded
  `create_task`. Each sidecar's inner `_run()` loop has a
  crash-logging done-callback.
- **Gotcha #20** — `VirtualBook` flat-only invariant. Sells with
  `qty > held_qty` are clamped to the held position; the long→short
  flip path is unreachable. Reconciler reverses-and-reapplies the
  optimistic fill math to recover pre-fill state.
- **Gotcha #21** — `LlmParseError` is a distinct exception class. Pydantic
  v2 `_LlmDecisionModel` validates `bias`/`predictive`/`stance` as
  `Literal` enums, clamps `size_pct` to `[0, 0.25]`, truncates
  `reason` to 120 chars. Parse failures are not conflated with call
  failures.

## New deferred items (not yet ticketed)

- `H12` — multiple `/ws` connections per tab (lift `useStreamState`
  into a context provider)
- `H14` — config env-var shadowing makes admin `.env` writes invisible
  if env was set in shell; warn on boot
- `H6` — `commentary_loop` recreates LLM overlay each 45s tick (still
  defeats keepalive + prompt cache)
- `AgentWorldXL` 60Hz re-render MED item closed in round 6 C5 (now
  marked FIXED above). All other MED / LOW items unchanged from
  round 1.
