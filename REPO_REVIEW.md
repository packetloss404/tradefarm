# TradeFarm — Senior Staff Engineering Review

_Read-only review. No application code was modified. Findings are grounded in direct file reads; the highest-severity items were verified line-by-line._

---

## A. Executive summary

TradeFarm is a **100-agent paper-trading sandbox for US equities that doubles as a live-broadcast production system**. Three strategies (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`) trade on a 5-minute tick; an Orchestrator drives the tick loop, an in-process event bus fans state to a React operator **dashboard** (`web/`) and a Tauri/OBS **broadcast overlay** (`stream/`), and a VOD pipeline (headless render → ffmpeg stitch/mix → thumbnail → YouTube upload) turns sessions into videos. The stack is Python 3.12+/FastAPI/SQLAlchemy-async/SQLite + PyTorch LSTMs + Claude/MiniMax overlay, fronted by Vite/React 19/Tailwind v4. The codebase is **unusually disciplined for a solo/sandbox project**: strict TypeScript (no `any`, `noUncheckedIndexedAccess`), parameterized SQL everywhere, list-form subprocess calls, timing-safe auth, path-traversal guards, a real CI gate, and a test suite (62 files) whose docstrings cite the specific bugs they regress against. Many prior audit rounds are visible in the code.

That said, the **engineering effort is lopsided**: the *broadcast/VOD* machinery is heavily built and well-tested, while the *money-critical trading core* carries the riskiest unaddressed defects (a reconciled long→short flip corrupts `avg_price`; the advertised restart-safe trade dedup is inert because no code writes `broker_order_id`; all money is `float`). Operationally it ships **open-by-default mutating endpoints behind a LAN-wide CORS allowlist**, has **no mypy in CI despite a "type hints everywhere" mandate**, **no frontend tests**, **no agent/feature-vector tests**, and a **loose `pandas>=2.2` pin that has already resolved to an untested 3.x**. The frontend has a 60fps full-tree re-render loop in the broadcast overlay and several non-functional UI controls presented as live.

**Rating: Needs work.** It is a well-organized, working sandbox — appropriate for its stated purpose (paper trading + broadcast) — but **not production ready** for anything handling real money or exposed beyond a trusted LAN, and it has a handful of correctness defects in the trading core that should be fixed before relying on its P&L numbers.

---

## B. Top 10 highest-priority issues

### 1. Reconciled long→short flip corrupts `avg_price` (and therefore all downstream P&L)
- **Severity:** Critical · **Area:** bug / money-math
- **Files:** `src/tradefarm/execution/virtual_book.py:177-239`
- **What:** `apply_reconciled_fill` admits it cannot recover the pre-fill average on a position flip and falls back to `prev_avg = post_avg` (the optimistic mark). The residual position's `avg_price` is then recomputed from that wrong base, poisoning every later `unrealized_pnl`, `equity`, and `should_exit` for that symbol. The code comment itself says "We don't have it."
- **Why it matters:** Silent, permanent corruption of an agent's books — exactly the kind of error that's invisible until the broadcast shows wrong numbers. Nothing at the book layer *enforces* flat-only, so any sell qty > held qty (fractional drift, an LLM size bug) reaches this path.
- **Fix:** Enforce flat-only at the book boundary (reject `sell qty > held qty`) so the unrecoverable branch is unreachable; **or** persist the pre-fill avg alongside `_optimistic_marks` so the reconciler can correct properly. Add a flip regression test (one already exists for the forward path in `tests/execution/test_virtual_book_reconcile.py`).

### 2. Restart-safe trade dedup is inert — `broker_order_id` is never written
- **Severity:** Critical · **Area:** bug / data integrity
- **Files:** `src/tradefarm/storage/repo.py:57-72`, `src/tradefarm/storage/models.py` (UNIQUE on `trades.broker_order_id`), `src/tradefarm/orchestrator/scheduler.py` reconcile path
- **What:** `record_trade()` takes no `broker_order_id` and inserts every row with it NULL. The reconcile path corrects the in-memory book and emits a WS event but **writes no Trade row**. So the DB UNIQUE constraint that CLAUDE.md gotcha #7 sells as the double-counting safety net guards a column nobody populates. The only dedup is the in-memory `_reconciled_ids` LRU (`virtual_book.py:72`), lost on restart — and `_optimistic_marks` is also in-memory, so post-restart the reconciler hits the `mark is None` branch and silently skips fills.
- **Why it matters:** The documented idempotency/persistence guarantees do not exist. Correctness depends on never restarting mid-settlement — which the autorun/desktop-sleep setup makes likely.
- **Fix:** Either make the reconciler persist Trade rows with `broker_order_id` (so the constraint actually fires) and persist `_optimistic_marks`, or stop advertising restart-safe idempotency in the docs.

### 3. Mutating endpoints are open by default; broadcast mode binds `0.0.0.0`
- **Severity:** High · **Area:** security
- **Files:** `src/tradefarm/api/main.py:132-152` (auth middleware), `src/tradefarm/config.py:42` (`api_shared_secret=""` default), `package.json` (`broadcast:api` binds `0.0.0.0:8000`)
- **What:** When `api_shared_secret` is unset (the default), the middleware short-circuits and every `POST` is open: `/tick`, `/admin/config` (writes API keys to `.env`), `/admin/toggle-ai`, `/backtest/run`. `npm run broadcast` binds the LAN interface. An operator who forgets to set the secret exposes secret-rewriting endpoints to the whole network.
- **Why it matters:** LAN-reachable `.env` rewrite = key exfiltration/replacement. The secure default is backwards (open unless you opt in).
- **Fix:** Refuse to bind `0.0.0.0` unless `api_shared_secret` is set (fail fast at startup), or default the broadcast flavor to require the token.

### 4. CORS allows the entire RFC-1918 private address space
- **Severity:** High · **Area:** security
- **Files:** `src/tradefarm/api/main.py:165-174`
- **What:** `allow_origin_regex` matches `10.x`, `192.168.x`, `172.16-31.x` on any port. Any page on any LAN host (coffee-shop/corporate Wi-Fi) is a permitted origin. Mitigated by `allow_credentials=False`, but combined with #3 a malicious LAN page can drive `/admin/config`.
- **Why it matters:** Widens the blast radius of #3 from "someone on the LAN crafting requests" to "any web page the operator visits while on a shared network."
- **Fix:** Replace the regex with an explicit allowlist of the actual workstation IP(s); make LAN ranges opt-in via env.

### 5. The broadcast overlay re-renders the full 100-agent SVG at 60fps
- **Severity:** High · **Area:** performance
- **Files:** `stream/src/components/AgentWorldXL.tsx:452-465`
- **What:** A `requestAnimationFrame` loop calls `setCameraTick` every frame purely to force a re-render so a camera drift (from `performance.now()`) recomputes — and the tick value is then discarded (`void cameraTick`). This reconciles thousands of SVG nodes (100 agent sprites, tiles, weather particles) 60×/sec.
- **Why it matters:** This is the dominant CPU cost on the OBS-captured 1080p output and will pin a core, risking dropped frames on the actual product (the stream).
- **Fix:** Animate an isolated wrapper `<g transform>`/`viewBox` via CSS or SMIL `animateTransform` instead of re-rendering the React tree.

### 6. `Orchestrator` is a god-object; sidecar `start()` tasks are fire-and-forget
- **Severity:** High · **Area:** architecture / async correctness
- **Files:** `src/tradefarm/orchestrator/scheduler.py:121-169, 605-685, 800-849`
- **What:** One 849-line class owns trade execution **and** eight presentation sidecars (auto_director, streak_watcher, commentary, youtube_chat, predictions, audience, broadcast ledger + scheduler). `start_background()` is 80 lines of near-identical `asyncio.create_task(self._x.start())` whose returned tasks are **discarded** — if a sidecar's `start()` raises before its inner loop spawns, the failure is swallowed and that sidecar silently never runs. There's also a startup race: the server begins serving before those deferred coroutines execute. Every sidecar holds a back-reference to the whole Orchestrator and reaches into siblings' privates (e.g. `youtube_chat.py:362` `getattr(self.orch, "_audience", None)`).
- **Why it matters:** Silent partial-startup failures are the hardest production bugs to notice; the coupling makes the trading core untestable in isolation.
- **Fix:** `await` each `start()` directly (they only kick off loops); extract the eight sidecars into a single `BroadcastSuite` the Orchestrator starts/stops as a unit; expose a read-only state interface instead of ambient attribute access.

### 7. `broadcast_slot` events always report state `"active"` (dead queue indicator)
- **Severity:** Medium · **Area:** bug
- **Files:** `src/tradefarm/orchestrator/broadcast_os.py:251`
- **What:** `"state": getattr(sm, "state", "active")` — `sm` is a `ScheduledMoment` (`broadcast_scheduler.py`) which has no `state` attribute, so the getattr always returns the `"active"` default. Preempted/queued moments are never reported as such.
- **Why it matters:** The dashboard's queue-depth/preemption indicator is silently dead — a feature that looks built but isn't.
- **Fix:** Add the field to `ScheduledMoment` and populate it in the scheduler, or compute state at emit time.

### 8. All money is `float`; no migration framework; persistence isn't atomic with fills
- **Severity:** Medium · **Area:** data / correctness
- **Files:** `src/tradefarm/execution/virtual_book.py` (cash/avg_price/realized all float), `src/tradefarm/storage/models.py` (Float columns), `src/tradefarm/storage/db.py:52-159` (hand-rolled idempotent ALTERs, no IF NOT EXISTS, dialect guesswork), `src/tradefarm/storage/repo.py:57-104`
- **What:** Money is binary float, with `abs(...) < 1e-9` epsilon guards that classify partial-close vs flip; over a multi-day fractional-share run, drift can misclassify. Schema changes are applied by re-running raw `ALTER TABLE ADD COLUMN` each boot with a fragile sqlite-vs-postgres detection and no IF-NOT-EXISTS guard. `record_trade`/`snapshot_pnl`/`sync_positions` each open independent sessions, so a crash mid-sequence leaves DB and in-memory state inconsistent (and in-memory is rebuilt fresh on restart).
- **Why it matters:** P&L shown on stream can drift from a Decimal recomputation; the migration approach will break the day a column rename or Postgres move happens.
- **Fix:** Use `Decimal` or integer cents for cash/realized/avg_price; adopt Alembic with a schema-version table; wrap the fill→persist sequence in a single transaction.

### 9. LLM responses are parsed without schema validation
- **Severity:** Medium · **Area:** bug / robustness
- **Files:** `src/tradefarm/agents/llm_providers.py:34-48`, `lstm_llm_agent.py:159-206`
- **What:** `_parse_decision_json` does bare `data["bias"]`/`data["predictive"]`/`data["stance"]`; a missing key raises `KeyError` that gets mislabeled upstream as `llm_call_failed`. There's no validation that enums are in range or that `size_pct` is within bounds (only one agent path clamps to 0.25; the stored `LlmDecision` is unvalidated).
- **Why it matters:** Malformed/hostile model output is conflated with network failure and can carry out-of-range sizing into the surface layer.
- **Fix:** Parse into a pydantic model with `Literal` enums and bounded `size_pct`; clamp/validate at parse time; distinguish parse errors from call failures in logs.

### 10. Non-functional UI controls shipped as if live (several imply destructive actions)
- **Severity:** Medium · **Area:** bug / UX
- **Files:** `web/src/dash/Admin.tsx:956-979` (5 `onChange={() => {}}` toggles in "VOD Pipeline"), `web/src/dash/Episodes.tsx`, `web/src/dash/Research.tsx`, `web/src/vod/SessionControl.tsx` (pause/abort do nothing), `web/src/vod/BeatPicker.tsx`
- **What:** Multiple toggles/buttons render enabled with no-op handlers; some (pause/abort, Danger Zone) imply destructive operations.
- **Why it matters:** An operator clicking "abort" and seeing nothing happen — or worse, assuming it worked — is a real operational hazard during a live broadcast.
- **Fix:** Disable non-wired controls with a "coming soon" affordance; wire or remove the destructive ones.

---

## C. Quick wins (< 1 hour each, good impact)

- **Fail fast on insecure broadcast:** in `config.py`/startup, raise if host is `0.0.0.0` and `api_shared_secret` is empty. (Issue #3)
- **Narrow CORS:** replace the RFC-1918 regex with an env-driven explicit allowlist; default to localhost only. (Issue #4)
- **Fix `broadcast_slot` state** at `broadcast_os.py:251`, or delete the dead field + indicator. (Issue #7)
- **Add mypy to CI** — `mypy` is already a dev dep; add a `[tool.mypy]` block and one CI step. Enforces the stated "type hints everywhere" rule.
- **Pin pandas:** `pandas>=2.2,<3` and `uv lock`, OR finish the 3.x audit. Currently running an untested major version. (`pyproject.toml`)
- **Disable dead UI controls** (Issue #10) — mechanical `disabled` + tooltip pass over the listed files.
- **`pnl_daily` denominator bug:** `main.py:593` hardcodes `* 1000.0` instead of `settings.agent_starting_capital` (the `/account` endpoint already does it right). One-line fix.
- **Add ESLint** with `@typescript-eslint`, `react-hooks`, `jsx-a11y` to both frontends + a `lint` script + CI step. (Catches issues #5, #10, and the a11y gaps.)
- **Enable extra ruff rule groups** (`I` import-sort, `B` bugbear, `UP` pyupgrade) — currently only defaults run.
- **Purge tracked debug screenshots** under `docs/screenshots/2026-05-17/*` (~28 throwaway PNGs) and `dev/_archive/` dead plans.
- **Delete/fix `OrderReconciler.run()`** (`order_reconciler.py:172`) — it calls the async `poll_once()` without awaiting; it's dead code that the class docstring still advertises.
- **Reconcile docs:** CLAUDE.md says Python 3.13, `pyproject.toml` says `>=3.12`.

---

## D. Larger refactors (grouped by priority)

**Priority 1 — Trading-core correctness (do before trusting P&L)**
- Move money to `Decimal`/cents across `virtual_book.py` + `storage/models.py`. (Issue #8)
- Make reconciliation persistent and idempotent end-to-end: write Trade rows with `broker_order_id`, persist `_optimistic_marks`, enforce flat-only. (Issues #1, #2)
- Adopt Alembic; add a schema-version table; wrap fill→persist in one transaction. (Issue #8)

**Priority 2 — Decouple the Orchestrator**
- Extract a `BroadcastSuite` owning the eight sidecars with a shared `PollingLoop` base (removes ~150 lines of duplicated start/stop/lifecycle). Give sidecars a read-only orchestrator-state interface instead of back-references. Decompose `_tick_once_inner` (~270 lines) into `_collect_signals`/`_apply_risk_exits`/`_execute_fills`/`_snapshot_and_publish`. (Issue #6)

**Priority 3 — Frontend consolidation**
- Introduce an npm/pnpm **workspace** so `web/` and `stream/` share React/Vite/Tailwind/tsconfig and the duplicated `useLiveEvents`/`useMarketClock`/`tokens`/`replayMode` modules stop drifting. (Collapses 3 npm lockfiles toward 1.)
- Replace the 60fps re-render loop (Issue #5); memoize the 100-cell grids and chart geometry; extract the triplicated equity-chart SVG.
- Decide the fate of the legacy `App.tsx` + `components/AdminModal.tsx` (a second full dashboard) vs the new `dash/` — keeping both doubles the maintenance surface.
- Gate or tree-shake out the shipped mock data (`dash/mockData.ts`, `vod/mockData.ts`).

**Priority 4 — Observability & operations**
- Track and supervise background tasks (restart-on-crash, surface failures). (Issue #6)
- WS slow-client handling: today events between queue depth 100–200 are silently dropped with no gap signal to the client (`events.py:38-41` vs `ws.py:65`) — emit a "resync" signal so the frontend reconnects instead of rendering stale state.
- Add a Dockerfile + `.sh` launchers for non-Windows reproducibility.

---

## E. Suggested roadmap

**Phase 1 — Stabilize (correctness & safety)**
1. Issues #1, #2 (reconciliation/flip + dedup), #3, #4 (auth/CORS), #9 (LLM validation).
2. Quick wins: pandas pin, `pnl_daily` denominator, fail-fast on insecure bind, fix/delete `OrderReconciler.run()`.
3. Add the first 5–10 tests below so these fixes are regression-locked.

**Phase 2 — Clean up (DX, hygiene, enforcement)**
1. ESLint + mypy in CI; extra ruff rules; coverage measurement (`pytest-cov`, no hard gate yet).
2. Purge tracked debug artifacts + dead `dev/_archive`/duplicated handoff trees; reconcile doc drift.
3. Disable/wire dead UI controls (Issue #10).

**Phase 3 — Improve architecture**
1. Decouple Orchestrator into `BroadcastSuite` + `PollingLoop`; decompose `_tick_once_inner`.
2. Frontend workspace + shared modules; kill the 60fps loop; retire one of the two dashboards.
3. Money → Decimal; Alembic migrations; atomic fill persistence.

**Phase 4 — Harden for production**
1. Supervised background tasks + health/readiness that use the replay clock consistently (`main.py:280-284` uses wall-clock vs replay-stamped `last_tick_at`).
2. WS resync protocol; structured metrics/tracing; per-route auth dependency instead of relying solely on global middleware.
3. minimax_base_url scheme/host allowlist (`llm_providers.py:99`); rate limits; Dockerized deploy.

---

## F. Questions for the repo owner

1. **Will this ever execute real (non-paper) orders?** That single answer reclassifies the float-money and reconciliation issues from "P&L looks slightly off on stream" to "Critical, fix now."
2. **Restart frequency:** the autorun/desktop-sleep loop implies frequent restarts. Given in-memory state (`_optimistic_marks`, `_reconciled_ids`, agent books) is lost on restart, how much trade/PnL inaccuracy across a restart is acceptable? (Drives the priority of Issue #2.)
3. **Is the backend ever exposed beyond a trusted LAN?** Determines how urgent Issues #3/#4 are.
4. **Legacy `web/src/App.tsx` + `AdminModal.tsx`** — intentional safety net or should it be deleted? (It's a full second dashboard.)
5. **pandas 3.x** — adopt deliberately (with an audit) or roll back to `<3`?
6. **Two LLM providers (Claude + MiniMax):** is MiniMax actively used? It re-introduces a per-call `httpx.AsyncClient` (`llm_providers.py:113`) and lacks retries, unlike the Anthropic path.
7. **Postgres ever?** `db.py` has half-built dialect detection but no migration system — is SQLite the permanent backend?

---

## Appendix — coverage of the 14 requested areas

1. **Project structure** — §A, §B#6; clean `src/` package layout, but `dev/` carries duplicated design-handoff trees + `dev/_archive` dead plans, and `docs/screenshots/2026-05-17/*` is committed debug bloat.
2. **Setup & DX** — README/RUNBOOK are genuinely good; blockers are Windows-only launchers, no Docker, heavy multi-toolchain bootstrap (torch + Chromium + Rust), three separate `npm install` roots. (§C, §D-P4)
3. **Architecture** — Orchestrator hub + event bus + sidecars + dual frontends; god-object coupling is the main issue (§B#6, §D-P2).
4. **Code quality** — strong type discipline; large files (`scheduler.py` 849, `main.py` 716, `dash/Admin.tsx` 1006); inline-style sprawl in new dashboard pages contradicting the Tailwind convention; magic numbers but mostly named.
5. **Bugs/correctness** — §B#1, #2, #7, #8, #9; plus predictions reset off-by-one date (`predictions.py:284-306`) and risk-exit partial-close guard (`scheduler.py:408-412`).
6. **Security** — §B#3, #4; minimax SSRF (M1); many positives (parameterized SQL, list-form subprocess + ffmpeg escaping, path-traversal guards, secret masking, timing-safe auth, `.env` untracked).
7. **Dependencies** — pandas 3.x loose pin (top risk), numpy unbounded, 4 lockfiles, two frontends duplicating React/Vite/Tailwind; otherwise lean and current.
8. **Testing** — execution/reconcile/risk well covered; **gaps:** no agent/`features.py` tests, thin API tests (`/tick`, `/admin/*`, `/ws` untested), zero frontend tests. First tests to add below.
9. **Performance** — §B#5 (60fps loop); per-call httpx clients in MiniMax + commentary loop; unmemoized 100-cell grids + `setInterval`s; tick uses a `Semaphore(20)` (reasonable).
10. **Observability/ops** — fire-and-forget tasks (§B#6); WS silent-drop window; wall-clock vs replay-clock in readiness/pnl; structlog used well otherwise.
11. **UI/UX** — dead/destructive controls (§B#10); a11y is the weakest dimension (clickable `<div>`s without keyboard/role, unlabeled form atoms, no dialog focus traps); good WS plumbing with backoff.
12. **Database/data** — float money, no migrations/versioning, non-atomic fill persistence, fragile dialect detection (§B#8); session-id scoping is done well.
13. **Documentation** — README/RUNBOOK/CLAUDE.md are above average; misleading parts: documented restart-safe dedup that doesn't exist (#2), 3.12-vs-3.13 drift, `OrderReconciler.run()` docstring advertises broken code.
14. **Build/CI/CD** — CI does lint+format+test (py) and typecheck+build (web/stream); gaps: no mypy, no frontend tests, no coverage, `vod` extra untested, no explicit Python matrix.

### First 5–10 tests to add
1. **`features.py` golden test** — freeze the 19-feature vector for a fixed bar series (CLAUDE.md flags silent breakage on `FEATURE_NAMES` change).
2. **Reconciled flip** — assert `avg_price`/`realized_pnl` correctness on a long→short reconciled fill (locks Issue #1).
3. **Trade persistence + dedup** — assert `record_trade` writes `broker_order_id` and a duplicate insert is rejected (locks Issue #2).
4. **Strategy decisions** — `MomentumAgent`/`LstmAgent.decide()` produce expected buy/sell/hold on crafted inputs.
5. **LLM parse validation** — malformed/out-of-range JSON is rejected/clamped, and parse errors are distinct from call failures (locks Issue #9).
6. **API `/tick`** integration via `TestClient` — one manual tick mutates state and emits events.
7. **API `/admin/config`** — auth required when secret set; secret keys masked on GET; injection rejected.
8. **`pnl_daily` denominator** — uses `agent_starting_capital`, not hardcoded 1000.
9. **WS event bus** — subscribe, publish, receive; slow-client overflow signals resync rather than silently dropping.
10. **Frontend smoke (vitest)** — `useLiveEvents` reconnect/backoff + replay-clock helpers.
