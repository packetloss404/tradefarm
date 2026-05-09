# Agent Academy — Technical Plan (PM-A)

Scope: turn stateless agents into learning entities with journaled decisions, outcome linkage, rank-gated capital, retrieval-augmented prompts, and curriculum-driven promotion/demotion. This file is the engineering angle only; PM-B owns UX.

## 1. Dependency DAG

```
Phase 1 (Journal + outcome linkage)
    |
    +---> Phase 2 (Ranks + rank-gated RiskManager)
    |         |
    |         +---> Phase 4 (Curriculum auto-promote/demote)
    |
    +---> Phase 3 (Retrieval-augmented LLM prompt)
```

- Phase 1 is the root; it owns the `agent_notes` table and the close-trade outcome stamping that every later phase consumes.
- Phase 2 and Phase 3 are independent siblings: 2 reads closed-outcome aggregates (win_rate, Sharpe, n_closed); 3 reads raw notes+outcomes for similarity retrieval. They can ship in parallel after 1.
- Phase 4 depends on Phase 2 (it mutates ranks that Phase 2 defines) and *should* ship after Phase 3 lands so newly-promoted agents immediately benefit from retrieval context.
- **Critical path: 1 -> 2 -> 4.** Phase 3 is parallelizable; delaying it does not block release of rank gating.

## 2. Per-phase technical scope

### Phase 1 — Journal + outcome linkage
- **New files:** `src/tradefarm/storage/journal.py` (repo helpers for notes), `tests/test_journal.py`.
- **Modified:** `storage/models.py` (add `AgentNote`), `storage/repo.py` (re-export helpers; on sell-fill, resolve originating note), `orchestrator/scheduler.py` (call `journal.write_note` at decision time, call `journal.close_outcome` when `record_fill` produces a position-closing event — detectable via `VirtualPosition.apply_fill` returning nonzero `realized`), `agents/base.py` (add `self.journal_note_id: int | None` scratchpad), `agents/lstm_llm_agent.py` + `momentum.py` + `lstm_agent.py` (populate note content).
- **New tables/columns:** `agent_notes` — fields: `id`, `agent_id`, `kind` ("entry"|"exit"|"observation"), `symbol`, `content` (text, the digest/thesis), `metadata` (JSON: LSTM probs, size_pct, LLM reason), `created_at`, `outcome_trade_id` (nullable FK to trades), `outcome_realized_pnl` (nullable float), `outcome_closed_at` (nullable datetime). The implementer finalizes types (JSON vs TEXT-stringified-JSON depends on SQLite vs Postgres support).
- **New endpoints:** `GET /agents/{id}/notes?limit=`.
- **New settings:** none (journal always on).
- **Contract to Phase 2/3:**
  - `journal.write_note(agent_id, kind, symbol, content, metadata) -> note_id`
  - `journal.close_outcome(agent_id, symbol, realized_pnl, trade_id) -> int` (stamps the most recent open-entry note for that (agent, symbol); idempotent)
  - `journal.recent_outcomes(agent_id, n) -> list[NoteWithOutcome]`
  - `journal.find_similar(agent_id, symbol, *, limit) -> list[NoteWithOutcome]` (v1: match by symbol + recency; embeddings TBD — implementer's call)

### Phase 2 — Academy ranks + rank-gated capital
- **New files:** `src/tradefarm/academy/__init__.py`, `academy/ranks.py` (rank enum + scoring), `academy/repo.py`, `tests/test_ranks.py`.
- **Modified:** `storage/models.py` (add `rank` column to `Agent`, default `"intern"`, plus `rank_updated_at`), `risk/manager.py` (`RiskManager.__init__` accepts `rank`; `max_position_notional_pct` becomes `base * rank_multiplier`), `orchestrator/scheduler.py` (pass agent rank into `RiskManager`, rebuild limits when rank changes), `api/main.py` (expose rank in `/agents`).
- **New endpoints:** `GET /academy/ranks`, `GET /agents/{id}/academy` (stats + current rank + next-rank thresholds).
- **New settings:** `academy_rank_multipliers` (CSV or dict-string, e.g. `intern=0.4,junior=0.7,senior=1.0,principal=1.3`), `academy_min_trades_junior`, `..._senior`, `..._principal`.
- **Contract to Phase 4:**
  - `ranks.compute_stats(agent_id) -> RankStats` (win_rate, sharpe, n_closed_trades, weeks_active) — reads Phase 1's stamped notes + existing `trades`/`pnl_snapshots`.
  - `ranks.eligible_rank(stats) -> Rank` (pure function; no DB writes).
  - `academy_repo.set_rank(agent_id, rank, reason) -> None` (writes `Agent.rank` + promotion log row).

### Phase 3 — Retrieval-augmented prompt
- **New files:** `agents/retrieval.py` (wraps `journal.find_similar` + formats into prompt lines).
- **Modified:** `agents/llm_overlay_types.py` (extend `LlmContext` with `retrieved_examples: list[RetrievedExample]` — default empty to preserve existing call sites), `agents/llm_overlay_types.user_message` (appends a "Past similar setups" block when non-empty), `agents/lstm_llm_agent.py` (pull retrieval before building ctx; cost-gate still fires before retrieval to avoid wasted DB hits).
- **New tables/columns:** none for v1. (TBD implementer's call: an `agent_note_embeddings` table iff they choose to do embeddings; the contract says metadata retrieval is fine for v1.)
- **New endpoints:** `GET /agents/{id}/retrieval-preview?symbol=` (debug/UI).
- **New settings:** `academy_retrieval_k` (default 3), `academy_retrieval_enabled` (bool, default True).
- **Contract to Phase 4:** none (Phase 4 does not read retrieval state).

### Phase 4 — Curriculum
- **New files:** `academy/curriculum.py` (the periodic task), `tests/test_curriculum.py`.
- **Modified:** `orchestrator/scheduler.py` (register a second background task that runs `curriculum.evaluate_all()` every N ticks or every N minutes — reuse the `start_background` pattern), `api/main.py` (expose `POST /academy/evaluate` for manual kick).
- **New tables/columns:** `academy_promotions` (agent_id, from_rank, to_rank, reason, at). Reuses Phase 2's rank column.
- **New endpoints:** `POST /academy/evaluate`, `GET /agents/{id}/promotions`.
- **New settings:** `academy_eval_interval_sec` (0 disables), `academy_demote_drawdown_pct` (default 0.08), `academy_demote_consecutive_losses` (default 5).
- **Contract:** emits `"promotion"` / `"demotion"` websocket events on `publish_event` so PM-B's UI can react.

## 3. Risks + mitigations

1. **New SQLAlchemy tables silently missing on boot.** `init_db` calls `Base.metadata.create_all`, so any model imported before `init_db()` runs will be created — but if a new module is only imported lazily (e.g. from `academy/__init__.py`), its tables won't register. *Mitigation:* import `AgentNote`, rank column, and promotions model from `storage/models.py` directly; add a smoke test that asserts `AgentNote.__table__` exists after `init_db()`.
2. **Outcome stamping races on partial exits.** A sell that only partially closes a long still returns `realized > 0` from `VirtualPosition.apply_fill`, but the *entry* note is still live. *Mitigation:* `close_outcome` stamps the oldest unstamped entry note for (agent, symbol) and allows multiple exits to stamp separate notes; or, alternatively, accumulate realized into the existing stamped field. Implementer picks one and documents it — default recommendation: one note gets stamped per full flat-out, not per partial.
3. **Rank change mid-tick leaves stale `RiskManager` caps.** Phase 2 rebuilds `RiskManager.limits` when `Agent.rank` changes, but the orchestrator holds `RiskManager` instances in-process. *Mitigation:* `academy_repo.set_rank` emits an in-process event that the orchestrator subscribes to; or, simpler, Phase 4 schedules rank re-evaluation only between ticks, never during.
4. **Prompt bloat from retrieval.** Past examples inflate the user message, blowing past Haiku's sweet spot and raising per-call cost. *Mitigation:* hard cap `academy_retrieval_k` at 3 in v1; strip `metadata` keys not needed for the prompt; keep SYSTEM_PROMPT cached (already ephemeral) so retrieval churn hits only the non-cached user message.
5. **Demote cascades (mass demotion during a broad drawdown) gut all capital at once.** *Mitigation:* cap demotions per evaluation pass (e.g. max 10% of agents per run); require `n_closed_trades >= academy_min_trades_junior` before demotion is even considered (no demoting an intern who hasn't traded).
6. **Backtest / replay divergence.** `agents/backtest.py` constructs agents without the journal wired in. *Mitigation:* journal writes should tolerate a `None` session (no-op); Phase 1 tests cover the backtest path explicitly.

## 4. Test strategy

**Phase 1 (pytest):**
- `test_journal_write_and_read`: write a note, fetch it by agent.
- `test_close_outcome_stamps_pnl`: simulate entry note then close-outcome, assert fields populated.
- `test_partial_exit_does_not_double_stamp`: partial sell then full sell → exactly one note stamped per documented rule.
- **End-to-end assertion:** construct one `LstmLlmAgent`, run `tick_once()` twice with bars that produce buy-then-sell, assert the sell-tick's closing trade's originating `AgentNote.outcome_realized_pnl` is populated and non-zero.

**Phase 2 (pytest):**
- `test_rank_scoring_thresholds`: table-driven (stats → expected rank).
- `test_risk_manager_uses_rank_multiplier`: same signal, two ranks → different `check_entry` cap.
- `test_insufficient_trades_stays_intern`: n_closed < min → rank stays intern regardless of win_rate.
- **End-to-end assertion:** seed an agent with 20 winning journaled outcomes, call `ranks.evaluate(agent_id)`, assert `Agent.rank == "senior"` and that its `RiskManager.limits.max_position_notional_pct` equals `base * senior_multiplier`.

**Phase 3 (pytest):**
- `test_retrieval_ranks_by_symbol_match`: seed 5 notes, ask for similar, assert same-symbol ones come first.
- `test_user_message_includes_retrieval_block`: non-empty retrieval → prompt text contains "Past similar setups"; empty → prompt is byte-identical to today's.
- `test_retrieval_disabled_setting`: with `academy_retrieval_enabled=False`, prompt unchanged.
- **End-to-end assertion:** run two `tick_once()` calls where the first produces a winning closed outcome; on the second tick for the same symbol, assert the `LlmOverlay.decide` call received an `LlmContext` with `len(retrieved_examples) >= 1` and that one of them references the first tick's symbol.

**Phase 4 (pytest):**
- `test_promotion_threshold_reached`: simulated stats → `curriculum.evaluate_all()` writes a promotion row and updates `Agent.rank`.
- `test_demote_on_drawdown_streak`: stats with consecutive losses → demotion.
- `test_per_run_demotion_cap`: rig 50 agents over threshold, confirm at most N get demoted per pass.
- **End-to-end assertion:** start an intern, feed it enough winning stamped notes to clear the junior threshold, call `POST /academy/evaluate`, assert `GET /agents/{id}/promotions` returns one row and `GET /agents/{id}/academy` reports `rank="junior"`.

## 5. Backwards-compat contract

- `MomentumAgent` and `LstmAgent` behavior unchanged — they get journal hooks but their decision output is byte-identical for the same inputs.
- `LstmLlmAgent` with `academy_retrieval_enabled=False` (or zero notes) must produce the exact same `user_message` string as today. Phase 3 tests assert this.
- Existing rows in `agents`, `positions`, `trades`, `pnl_snapshots` remain valid. New columns on `agents` (`rank`, `rank_updated_at`) must have defaults so `SELECT *` from older rows still works; `create_all` will add them on boot for SQLite dev DBs — production migration is TBD (implementer's call: likely a one-shot Alembic or raw-SQL backfill).
- `RiskManager(starting_capital=...)` continues to work without a `rank` argument — default `rank="intern"` must yield a `rank_multiplier` of 1.0 in the absence of the new setting (i.e. Phase 2 only *reduces* intern caps if the operator opts in via settings).
- `/agents` response shape: new fields (`rank`, `note_count`) are additive; existing keys stay.
- `LlmContext` gains `retrieved_examples` with a default of `[]` so existing construction sites in `lstm_llm_agent.py` (and any future consumer) don't break.
- No change to websocket event names already in use (`fill`, `account`, `tick`, `reconcile`). New events (`promotion`, `demotion`) are additive.

## 6. Rollback unit

- **Phase 1:** delete `storage/journal.py`, `tests/test_journal.py`, remove `AgentNote` from `models.py`, revert the journal-hook lines in `scheduler.py` and the three agent files. Drop table `agent_notes` manually (SQLite dev; production via migration down). Scheduler returns to today's behavior.
- **Phase 2:** drop the `rank` and `rank_updated_at` columns from `agents` (migration down), revert `risk/manager.py` signature to not accept rank, remove `academy/` package and its tests, revert the orchestrator's rank-passing line. Any agent still in the DB defaults to full caps.
- **Phase 3:** remove `agents/retrieval.py`, revert `llm_overlay_types.py` (drop `retrieved_examples` field + prompt block), revert the two retrieval-call lines in `lstm_llm_agent.py`. No schema change to undo (unless the implementer chose embeddings, in which case drop that table). Phase 2 ranks continue to function.
- **Phase 4:** remove `academy/curriculum.py`, revert the second-background-task wiring in `scheduler.py`, remove `POST /academy/evaluate` + `GET /agents/{id}/promotions`, drop the `academy_promotions` table. Ranks set before rollback persist; they just stop being auto-updated.

Each phase's rollback unit is a single PR that is a pure revert of that phase's commits — no cross-phase fix-ups required because the contracts are additive.
