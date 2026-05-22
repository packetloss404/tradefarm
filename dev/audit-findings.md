# 20-agent codebase audit — findings & status

Conducted 2026-05-22 via parallel deep-dive subagents across every subsystem.
20 audits, ~14k words of reports. This file consolidates the findings,
ranked by severity, with a status column tracking what's fixed and what
remains.

## Legend

- **CRIT** — data corruption, security exploit, or silent money math error
- **HIGH** — will fire in normal use, degrades replay or live capture
- **MED** — edge case but plausible
- **LOW** — cosmetic / theoretical / future-proofing

Status: **FIXED** (this commit), **FIX-NEXT** (next session), **DOC**
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

## CRIT — defer to next session (design discussion needed)

| ID | File:line | Finding | Notes |
|---|---|---|---|
| C7 | `execution/virtual_book.py:94-108` | `apply_fill_delta` long→short flip + short opening: realized_pnl + avg_price both wrong. Symptom: any reconciled fill that crosses the position's sign. | **FIX-NEXT** — needs the scheduler to snapshot pos.qty + avg_price at submit-time so the reconciler can split the qty against the snapshot. |
| C8 | `execution/virtual_book.py:57` | `defaultdict(lambda: VirtualPosition(""))` autovivifies entries with empty symbol → consumers read `pos.symbol == ""`. | **FIX-NEXT** — replace defaultdict with plain dict + `setdefault` at all call sites. |
| C9 | `orchestrator/scheduler.py:572` + `academy/curriculum.py:97` | `_tick_in_progress` polling is not a lock. Concurrent tick + curriculum can swap `agent.risk` mid-tick. | **FIX-NEXT** — replace with `asyncio.Lock`. |
| C10 | `storage/models.py:106-124` | `AcademyPromotion` has no UNIQUE constraint. Two overlapping curriculum passes write duplicate rows + duplicate WS events. | **FIX-NEXT** — UNIQUE `(agent_id, to_rank, at)`. |
| C11 | `storage/repo.py:82-165` + `api/main.py:369-447` + `api/recap.py:115-196` | Every live read of Trade / PnlSnapshot / AgentNote mixes live + replay rows. After even one `session.run`, the dashboard shows inflated trade counts and the recap picks replay fills as "biggest fill today". | **FIX-NEXT** — add `session_id IS NULL` to every live read (or a `live_only(query)` helper). |
| C12 | `storage/journal.py:124-142` | `close_outcome` race: SELECT+UPDATE not in a single transaction with row lock. Concurrent closes can both pick the same entry row; second commit clobbers first. Also ignores session_id. | **FIX-NEXT** — `with_for_update()` + add session_id to WHERE. |
| C13 | `storage/models.py:47-64` | `Trade` has no `client_order_id`/`broker_order_id` UNIQUE. Reconciler can write duplicate Trade rows; replay re-runs duplicate too. | **FIX-NEXT** — add `broker_order_id String(64) UNIQUE NULL`. |
| C14 | `yt/upload.py:164-170` | Whole video read into memory + no 401 retry on PUT. 5GB reel = 5GB peak RAM; >1hr upload dies on token expiry. | **FIX-NEXT** — chunked resumable PUT with offset-query on 401. |
| C15 | `orchestrator/broadcast_recap.py` + `broadcast_scheduler.py` | Untracked, never instantiated. The scheduler exists exactly to arbitrate WS output slots; without it, multiple producers stomp the same UI slot. | **FIX-NEXT** — wire into `Orchestrator.__init__`. |
| C16 | `tests/coverage` | Zero tests for `alpaca_broker`, `order_reconciler`, `momentum`, `lstm_agent`, `lstm_llm_agent`, `llm_providers`, `admin.py`, `ws.py`, `audience.py`, `backtest.py`, `eodhd.py`. No frontend test infra at all. | **FIX-NEXT** — start with reconciler + admin allowlist + scheduler.tick_once. |
| C17 | `data/bar_cache.py:37-40` + `eodhd.py:39` | Today's bar is cached as a normal row; covers() returns True; final settled close never re-fetched. Position decisions made on the morning's provisional close until next day. | **FIX-NEXT** — refuse to cache `today_utc()` rows in `merge()`, drop them before write. |

## HIGH — fixed in this commit

| ID | File:line | Finding | Status |
|---|---|---|---|
| H1 | `streak_watcher.py:65`, `auto_director.py:51` | `_utcnow()` bypasses replay clock. | **FIXED** |
| H2 | `agents/backtest.py:28`, `lstm_train.py:35` | `date.today()` — fine for live CLI, but trivial migration to `today_utc()`. | **FIXED** |
| H3 | `config.py:27` | `auto_tick_interval_sec` defaults to `0` (silent disable). This is exactly the bug we hit this week. | **FIXED** (default → 300) |
| H4 | `dash/Admin.tsx` (related to C3) | Error state never auto-clears; SECRET_KEYS masked sentinel POSTed back. | **FIXED** |
| H5 | `dash/Episodes.tsx:387` + `mockData.ts:61` + `dash/Research.tsx` | `new Date("2026-05-19")` hardcoded as "today" — heatmap shifts off real today. | **FIXED** (use today's actual date dynamically) |

## HIGH — defer

| ID | Finding | Notes |
|---|---|---|
| H6 | `commentary_loop.py:298` recreates LLM overlay on every 45s tick — defeats keepalive + prompt cache. | FIX-NEXT |
| H7 | `streak_watcher.py:165` serial DB queries per agent. 100 round-trips/poll. | FIX-NEXT |
| H8 | `predictions.py:256-266` daily reset logic bumps `_session_date` to tomorrow then can't reset again until calendar rolls twice; predictions walk `open → locked → revealed` in one tick. | FIX-NEXT |
| H9 | `youtube_chat.py` no circuit breaker for permanently-revoked refresh token. | FIX-NEXT |
| H10 | `stream/` — `data-scene-ready` only set on `SceneRotator` wrapper; v1-broadcast and PreRoll layouts never signal ready → headless hangs forever. | FIX-NEXT |
| H11 | `stream/` — 15+ `Date.now()` callsites still wall-clock under replay. Banner TTLs, "X seconds ago", recap eligibility, ET hour. | FIX-NEXT (add `replayNow()` shim, route all sites through it) |
| H12 | `stream/hooks/useStreamState` called by multiple components → multiple `/ws` connections per tab. | FIX-NEXT (lift into context provider) |
| H13 | `web/hooks/useEventFeed.feed.account` is sticky — stale equity after WS reconnect. | FIX-NEXT |
| H14 | `config.py` env-var shadowing makes admin `.env` writes invisible after restart if env was set in shell. | FIX-NEXT (warn on boot if env shadows persisted) |
| H15 | `tts/run.py:198` OpenAI SDK `.content`/`.read()` may return coroutine → silent write of `b"<coroutine>"`. | FIX-NEXT (use `with_streaming_response`) |
| H16 | `script/write.py` prompt injection via beat headlines. Today the headlines come from `session.beats` not chat, but the moment chat feeds beats this is exploitable. | FIX-NEXT (wrap each beat in `<beat>…</beat>` delimiters) |
| H17 | `risk/manager.py:85-92` `check_entry` ignores existing position size → per-symbol cap is per-trade not per-position. Agent can add 5×. | FIX-NEXT |
| H18 | `risk/manager.py:87` cap anchored to `starting_capital` not equity. Drawdowns don't shrink cap. | FIX-NEXT (clamp by `min(starting, equity)`) |
| H19 | `risk/manager.py:60,132` trailing peak never reset on position close → re-open same symbol = instant trailing-stop. | FIX-NEXT (clear `_peak` in `VirtualPosition.apply_fill` on flatten) |
| H20 | `risk/manager.py:114-129` time-stop uses wall-clock not trading days. | FIX-NEXT |
| H21 | `risk/manager.py:56-59` `_apply_rank_multiplier` clobbers caller-supplied explicit cap. | FIX-NEXT |
| H22 | `lstm_model.py:80` no FEATURE_NAMES embedded in saved artifact (CLAUDE.md gotcha #6 is unguarded). | FIX-NEXT (persist FEATURE_NAMES; assert on load) |
| H23 | `agents/backtest.py:82-90` decision uses `close[t]` AND fill at `close[t]` — look-ahead bias. | FIX-NEXT (shift to `close[t+1]` / `open[t+1]`) |
| H24 | `lstm_train.py:45` train/val split on windows produces overlap leakage. | FIX-NEXT (split on raw bars + embargo) |
| H25 | `data/eodhd.py:53-56` no retry/backoff on 4xx/5xx; empty 200 silently returns empty bars. | FIX-NEXT |
| H26 | `data/bar_cache.py:68-73` parquet writer not concurrency-safe + no temp-file-then-rename. | FIX-NEXT |
| H27 | `api/backtest.py:32-50` POST `/backtest/run` no rate limit, no per-symbol cap, no max-inflight. | FIX-NEXT |
| H28 | `api/main.py:109-122` CORS allows whole LAN + no auth on destructive endpoints (admin/toggle-ai, admin/config, tick, backtest/run). | FIX-NEXT (shared-secret header middleware) |
| H29 | `metadata.py:181-193` DST-naive default publish-at; comment-vs-code mismatch. | FIX-NEXT (use `zoneinfo.ZoneInfo("America/New_York")`) |
| H30 | `yt/upload.py:182-186` thumbnails.set URL missing `uploadType=media&videoId=…` — may 400. | FIX-NEXT |
| H31 | No CI, ffmpeg undocumented prereq, README's `docs/` links 404. | FIX-NEXT |

## MED — defer (catalogued for future)

- `commentary_loop._recent_fills_from_orch` returns open positions not recent fills → cost gate misfires
- `audience.py:347` rebuilds deque O(N) per pop; missing lock around approve/reject race
- `web/components/BacktestModal.tsx` poll interval leaks on backend disconnect
- `dash/Dashboard.tsx` style-injection survives HMR but body attr doesn't
- `vod/SessionControl` ManifestPanel "fills today" reads ws-buffer cap, not real count
- `stream/AgentWorldXL` 60Hz rAF triggers full SVG re-render of 100 sprites
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

## Top 10 by money-loss / security potential (recommended FIX-NEXT order)

1. **C7** — `apply_fill_delta` short/flip bug (real money math wrong in alpaca_paper)
2. **H17/H18/H19** — RiskManager bypass-via-adds + cap-vs-equity + stale trailing peak (live-trading correctness)
3. **C11** — live queries mix replay rows (dashboard lies after any session.run)
4. **C13** — Trade dedupe (reconciler can write duplicates)
5. **C14** — YT upload in-memory + no 401 retry (can't reliably publish >1hr reel)
6. **C12** — journal.close_outcome race (wrong PnL attribution)
7. **C9/C10** — curriculum race + promotion dedupe (visible WS event duplicates)
8. **H10/H11** — stream `data-scene-ready` coverage + `replayNow()` shim (headless can hang; replay clips show wrong times)
9. **H28** — auth on destructive endpoints (LAN-reachable CSRF risk)
10. **C16** — test coverage for reconciler / scheduler.tick_once / admin allowlist

---

## Process notes

20 deep-dive subagents in two waves, each cleared to spawn nested
subagents for web research / API verification. Total wall time ~5
minutes per wave (parallel). Reports were 600-1000 words each;
synthesized findings here capture the most actionable subset.

Several findings overlap across audits — surfaced redundantly,
confirming they're real. Examples: scheduler wall-clock bypass found
by 3 different audits; session_id filtering gap found by 2.
