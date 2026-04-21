# Project Plan — Agent Academy

Feature goal: turn each TradeFarm agent from stateless-per-tick into a learning
entity with episodic memory, outcome linkage, rank-gated capital, retrieval-
augmented decisions, and automatic promotion/demotion.

This doc synthesizes [plan_tech.md](./plan_tech.md) (PM-A, engineering) and
[plan_product.md](./plan_product.md) (PM-B, UX). When the two disagreed I
defaulted to the technical view on contracts, the product view on copy.

## Sequencing

User directive: **four sequential phases, commit between each**. PM-A noted
Phases 2 and 3 *could* ship in parallel (they share no writer path), but we
hold them serial to keep each commit clean and demoable.

```
Phase 1 (Journal + outcomes)         ← critical
        ↓
Phase 2 (Academy ranks + risk gate)
        ↓
Phase 3 (Retrieval-augmented prompt)
        ↓
Phase 4 (Curriculum / auto-promote-demote)
```

## Rank system (source of truth for copy)

| Rank | One-liner | Tone | Size-cap multiplier |
|---|---|---|---|
| **Intern** | just hired; small size caps while we see what you can do | zinc (wait) | 0.5× |
| **Junior** | proven a few wins; trusted with a bit more rope | sky-400 | 1.0× |
| **Senior** | consistent edge across enough trades to matter | emerald (profit) | 1.5× |
| **Principal** | top of the floor; biggest cap and first retrieval pick | amber-400 | 2.0× |

Multipliers apply to `RiskManager.limits.max_position_notional_pct` (base 0.25).

---

## Phase 1 — Journal + outcome linkage

**Goal**: every decision writes a note; closing trades stamp the originating note with realized P&L.

### Technical scope
- **New**: `src/tradefarm/storage/journal.py`, `tests/test_journal.py`
- **Modified**: `storage/models.py` (add `AgentNote`), `storage/repo.py` (re-export), `orchestrator/scheduler.py` (write at decision, stamp on close-fill via `VirtualPosition.apply_fill`'s `realized` return), `agents/base.py` (scratchpad `self.journal_note_id`), the three concrete agents (note content)
- **Schema**: `agent_notes(id, agent_id, kind ∈ {entry,exit,observation}, symbol, content, metadata JSON, created_at, outcome_trade_id NULL, outcome_realized_pnl NULL, outcome_closed_at NULL)`
- **Endpoints**: `GET /agents/{id}/notes?limit=N`
- **Contract exposed to later phases**:
  - `journal.write_note(agent_id, kind, symbol, content, metadata) → note_id`
  - `journal.close_outcome(agent_id, symbol, realized_pnl, trade_id) → int` (stamps oldest unstamped entry, idempotent)
  - `journal.recent_outcomes(agent_id, n) → list[NoteWithOutcome]`
  - `journal.find_similar(agent_id, symbol, *, limit) → list[NoteWithOutcome]` (v1: symbol match + recency; embeddings deferred)

### UX
- **Agent detail modal**: new `<Section label="Journal">` with a chronological feed; resolved notes show a realized-P&L badge (profit/loss tone)
- **Brain Activity panel**: small "notes/tick" counter
- **Demo**: click a dot → scroll to Journal → show 2-3 notes with timestamps, one with `+$4.21` emerald badge, one with `-$1.80` rose badge

### Acceptance
- Any dot → ≥1 note with author, timestamp, body
- Resolved notes have P&L badges; open notes don't
- Notes stream without reload (SWR 5s)
- Empty state: *"no notes yet"* (zinc italic, matches existing "no trades yet")
- Hover truncates body after 2 lines with `…`

### Success metric
≥70% of closed trades have a stamped outcome by end of day 1.

### Risks + mitigations
- **Partial-exit double-stamp**: `close_outcome` stamps the oldest unstamped entry for (agent, symbol); full flat-out = one stamp. Implementer documents the rule in the module docstring.
- **Backtest path has no session**: journal writes tolerate a `None` context and no-op; `agents/backtest.py` must continue to produce identical output.

### Rollback
Delete `storage/journal.py`, drop `agent_notes`, revert hooks in scheduler + agents + models.

---

## Phase 2 — Academy ranks + rank-gated capital

**Goal**: compute each agent's rank from its journaled outcomes; scale its position-size cap accordingly.

### Technical scope
- **New**: `src/tradefarm/academy/__init__.py`, `academy/ranks.py`, `academy/repo.py`, `tests/test_ranks.py`
- **Modified**: `storage/models.py` (`Agent.rank`, `rank_updated_at` with `intern` default), `risk/manager.py` (accepts `rank`, applies multiplier), `orchestrator/scheduler.py` (pass rank into RiskManager), `api/main.py` (expose rank in `/agents`)
- **Settings**: `academy_rank_multipliers`, `academy_min_trades_junior/senior/principal`
- **Endpoints**: `GET /academy/ranks`, `GET /agents/{id}/academy`
- **Contract**:
  - `ranks.compute_stats(agent_id) → RankStats(win_rate, sharpe, n_closed_trades, weeks_active)`
  - `ranks.eligible_rank(stats) → Rank` (pure function)
  - `academy_repo.set_rank(agent_id, rank, reason) → None`

### UX
- **Dot pip** on each agent: I / J / S / P in the rank's tone color (never overrides profit/loss status dot)
- **Agent modal**: new "Rank" section with current rank, multiplier, progression bar + "needs N more trades, win-rate ≥ p%, Sharpe ≥ s over Nw"
- **Header**: rank-distribution strip (right of `ws:` status): `I·42 J·31 S·20 P·7`
- **Demo**: header → click a Senior → show bar toward Principal → click an Intern → show low cap + "needs 12 more trades"

### Acceptance
- Every dot shows pip; color doesn't override status dot
- Rank tooltip explains gating in plain English
- Intern cap visibly enforced: LLM size-pct never exceeds its rank cap
- Grid sort-by-rank control groups cohort

### Success metric
Rank distribution becomes non-degenerate within 2 weeks (no single rank > 60% of the 100 agents).

### Risks
- **Mid-tick rank change staleness**: Phase 4 evaluates only between ticks (see Phase 4 design)
- **Default stays intern ⇒ 0.5× cap**: opt-in via setting so existing behavior is preserved until the operator flips the multipliers config

### Rollback
Drop `rank`/`rank_updated_at`, revert `RiskManager` signature (default = no multiplier), remove `academy/` package.

---

## Phase 3 — Retrieval-augmented prompt

**Goal**: each LLM decision sees the agent's own 3 most-similar past setups + outcomes.

### Technical scope
- **New**: `agents/retrieval.py` (wraps `journal.find_similar`, formats for prompt)
- **Modified**: `agents/llm_overlay_types.py` (extend `LlmContext` with `retrieved_examples: list[RetrievedExample]`, default `[]`; `user_message` appends a "Past similar setups" block only when non-empty), `agents/lstm_llm_agent.py` (pull retrieval after the cost gate, before overlay call)
- **Settings**: `academy_retrieval_k` (default 3), `academy_retrieval_enabled` (default True)
- **Endpoints**: `GET /agents/{id}/retrieval-preview?symbol=` (debug/UI)
- **Contract**: v1 retrieval is metadata-only (same-symbol + recency). Embeddings deferred; if the implementer adds a vector column, the rest of the system must not depend on it.

### UX
- **Agent modal**: inside the existing "LLM Decision" section, a collapsible **"Drawing on"** subsection showing 3 past-setup cards with outcome badges; empty → *"no comparable past setups"*; each card clickable to scroll to that journal entry
- **Demo**: click a trading agent → expand "Drawing on" → point at three past-setup cards with P&L badges → scroll up into the decision reason and highlight *"similar to ABC-07-Nov which returned +$3.40"*

### Acceptance
- Any decision → 1-3 past setups visible with outcome badges (or empty-state message)
- Retrieval lazy-loads (never delays modal first paint)
- With `academy_retrieval_enabled=False`, the prompt string is byte-identical to pre-Phase-3

### Success metric
≥60% of decision-reasons contain a retrieval reference once memory depth ≥10.

### Risks
- **Prompt bloat**: hard-cap k=3; only include minimal metadata in the prompt block; system prompt stays cached (ephemeral)
- **Byte-identical-prompt guarantee**: asserted via test `test_user_message_unchanged_when_empty`

### Rollback
Remove `agents/retrieval.py`, revert `LlmContext` + `user_message`, remove retrieval call in `lstm_llm_agent.py`. No schema change to undo.

---

## Phase 4 — Curriculum / auto-promote-demote

**Goal**: rank changes happen automatically, visibly, and safely.

### Technical scope
- **New**: `academy/curriculum.py`, `tests/test_curriculum.py`
- **Modified**: `orchestrator/scheduler.py` (second background task reusing `start_background` pattern, runs `curriculum.evaluate_all()` every N seconds; **evaluates between ticks only** to avoid RiskManager mid-tick staleness), `api/main.py` (`POST /academy/evaluate` for manual kick)
- **Schema**: `academy_promotions(id, agent_id, from_rank, to_rank, reason, at)`
- **Endpoints**: `POST /academy/evaluate`, `GET /agents/{id}/promotions`
- **Settings**: `academy_eval_interval_sec` (0 disables), `academy_demote_drawdown_pct` (default 0.08), `academy_demote_consecutive_losses` (default 5), per-pass demotion cap (e.g. 10% of cohort)
- **WS**: publish `"promotion"` / `"demotion"` events for UI reactivity

### UX
- **New panel**: `<Panel title="Promotions Board">` between `BrainPanel` and `StrategyPanel`; last 24h of rank changes in reverse-chronological order, each row: `{Agent} {from} → {to} — {trigger}` + rel time
- **Grid animation**: brief emerald/rose halo on promoted/demoted dots on the tick the change lands
- **Admin modal**: new "Run curriculum pass" button with confirm toast
- **Demo**: scroll to Promotions Board → point at last 5 events → switch to grid → watch a halo on next tick (or trigger manually via Admin)

### Acceptance
- Panel renders last 24h in reverse-chronological order
- Each row shows agent, from-rank → to-rank, trigger stat, rel time
- Grid animates halo on the tick the change lands
- Admin button `Run curriculum pass` produces confirm toast *"evaluated 100 agents · {k} promoted · {j} demoted"*
- Empty state: *"no rank changes in the last 24h."*

### Success metric
Promotions Board averages ≥1 event/day; <10% of promotions reverse within a week.

### Risks
- **Cascade demotions during broad drawdowns**: cap per pass to 10% of agents; require `n_closed_trades ≥ min_junior` before demotion is considered
- **Mid-tick RiskManager staleness**: evaluate only between ticks (gate on `orchestrator._tick_in_progress` or equivalent)

### Rollback
Remove `academy/curriculum.py`, revert the second-background-task wiring, drop `academy_promotions` table. Existing ranks persist; they just stop being auto-updated.

---

## Backwards-compat contract (applies across all phases)

- `MomentumAgent` and `LstmAgent` behavior unchanged for the same inputs.
- `LstmLlmAgent` with retrieval disabled (or zero notes) produces byte-identical `user_message`.
- Existing rows in `agents`, `positions`, `trades`, `pnl_snapshots` remain valid.
- New columns on `agents` (`rank`, `rank_updated_at`) have defaults so older rows stay valid under `SELECT *`.
- `RiskManager(starting_capital=...)` keeps working without `rank` arg (default yields 1.0× multiplier).
- New WS event names (`promotion`, `demotion`) are additive; existing events unchanged.

## Execution protocol

Each phase is handed to one implementation subagent with:
- this plan and the two source docs as context
- the phase's technical scope + acceptance criteria + contract
- instruction to write tests as specified
- instruction to leave integration points clean (no cross-phase hacks)

After each phase: I verify build + tests pass, stage a focused commit with a
subject like `phase 1: journal + outcome linkage`, push, and move to the next.
