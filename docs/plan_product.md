# Agent Academy — Product / UX Plan

Peer doc: `plan_tech.md` (PM-A). This doc owns the user-visible story.

## 1. User journey per phase

### Phase 1 — Journal + outcomes
Every dot is now a character with a paper trail. Clicking any agent reveals a chronological feed of its own notes ("bought XYZ because SPY reclaimed VWAP, IV low"), and once a position closes the matching note grows a green/rose P&L badge.
**Demo (≤3 sentences):** Open the app, click any dot, scroll to the new **Journal** section in the detail modal, point at 2–3 notes with timestamps and authors; then show one with a `+$4.21` emerald badge and one with a `-$1.80` rose badge. Refresh: new notes appear without re-opening. Open Brain Activity and show the new "Notes this tick" counter ticking.

### Phase 2 — Academy ranks
The grid is no longer uniform — dots now carry a tiny rank pip (I/J/S/P), and the detail modal gets a **Rank** section showing the agent's current rank, progression bar to the next, and current size-cap multiplier. The header gains a `rank dist: I·42 J·31 S·20 P·7` strip.
**Demo:** Point at the header distribution, click a Senior, show the "promoted 3d ago" line and the bar toward Principal, then click an Intern and show its low size-cap and "needs 12 more trades" hint.

### Phase 3 — Retrieval-augmented prompt
The LLM Decision section in the agent modal gains a collapsible **"Drawing on"** block listing the 3 past setups the agent recalled to make this call, each with outcome badge. The agent's reasoning visibly cites them.
**Demo:** Click a trading agent, expand "Drawing on", show three past-setup cards with P&L badges; then scroll up into the decision reason and highlight the phrase "similar to ABC-07-Nov which returned +$3.40."

### Phase 4 — Curriculum
A new **Promotions Board** panel sits below Brain Activity: a live ticker of last 24h promotions and demotions with agent name, from → to, and the stat that triggered it. Rank changes animate on the grid (brief emerald / rose halo).
**Demo:** Scroll to Promotions Board, point at the last 5 events, then switch to the grid and watch a halo fire on the next tick (or trigger via Admin → "Run curriculum pass").

## 2. Acceptance criteria (user POV)

**Phase 1 — Journal + outcomes**
- [ ] User can click any agent dot and see ≥1 journal note with author, timestamp, and body.
- [ ] Resolved notes display a realized P&L badge in profit/loss tone; open notes do not.
- [ ] Notes stream in without reload (consistent with existing 5s SWR cadence).
- [ ] Empty state reads "no notes yet" in zinc italic — matches existing "no trades yet" pattern.
- [ ] Brain Activity header shows a "notes/tick" counter that moves when agents write.
- [ ] Tooltip on hover truncates note body after 2 lines with `…`.

**Phase 2 — Academy ranks**
- [ ] Every dot shows its rank pip; color never overrides profit/loss/wait status color.
- [ ] Agent modal shows current rank, size-cap multiplier, and progress to next rank.
- [ ] Header shows live rank distribution across all 100 agents.
- [ ] Rank tooltip explains the gating stats in plain English.
- [ ] Position-size cap is visibly enforced: an Intern's "size %" in the LLM Decision block never exceeds its cap.
- [ ] Sorting the grid by rank (new control) groups the cohort visually.

**Phase 3 — Retrieval-augmented prompt**
- [ ] For any trading decision, user can expand "Drawing on" and see 1–3 past setups with outcome badges.
- [ ] Each retrieved setup is clickable and scrolls/links to that historical journal entry.
- [ ] When no relevant memory exists, block shows "no comparable past setups".
- [ ] Decision reason text visibly references retrieved setups at least some of the time.
- [ ] Retrieval never delays the modal's first paint — it lazy-loads in the expanded section.

**Phase 4 — Curriculum**
- [ ] Promotions Board panel renders last 24h of rank changes in reverse-chronological order.
- [ ] Each row shows agent name, from-rank → to-rank, trigger stat, and "rel time ago".
- [ ] Grid animates a brief halo on promoted/demoted agents on the tick the change lands.
- [ ] Admin modal gains a "Run curriculum pass" button for on-demand demoability.
- [ ] Empty-state: "no rank changes in the last 24h."

## 3. Dashboard touchpoints

- **Phase 1:** extends `AgentDetailModal.tsx` with a new `<Section label="Journal">`; extends `BrainPanel.tsx` with a small "notes/tick" metric. No new top-level panel.
- **Phase 2:** extends `AgentGrid.tsx` (pip on each dot); extends `AgentDetailModal.tsx` (Rank section); extends header in `App.tsx` (rank-distribution strip, right of `ws:` status).
- **Phase 3:** extends `AgentDetailModal.tsx` only — collapsible subsection inside the existing LLM Decision `<Section>`.
- **Phase 4:** adds one new top-level `<Panel title="Promotions Board">` between `BrainPanel` and `StrategyPanel`; extends `AdminModal.tsx` with a "Run curriculum pass" action.

## 4. Copy

**Ranks (4 names + one-liners, badge tone):**
- **Intern** — just hired; small size caps while we see what you can do. *Tone: zinc (wait).*
- **Junior** — proven a few wins; trusted with a bit more rope. *Tone: sky-400 (neutral-positive).*
- **Senior** — consistent edge across enough trades to matter. *Tone: emerald (profit).*
- **Principal** — top of the floor; biggest size cap and first retrieval pick. *Tone: amber-400 (same as active-trade accent).*

**Size-cap multipliers shown as copy:** Intern 0.5x · Junior 1.0x · Senior 1.5x · Principal 2.0x.

**Microcopy:**
- Journal section label: **Journal** · empty: *"no notes yet"* · resolved badge: *"+$X.XX realized"* / *"-$X.XX realized"*.
- Rank progression tooltip: *"Needs {n} more trades, win-rate ≥ {p}%, Sharpe ≥ {s} over {w}w."*
- Retrieval block label: **Drawing on** · empty: *"no comparable past setups"* · each card subtitle: *"{symbol} · {date} · {outcome}"*.
- Promotion event line: *"**{Agent}** {from} → {to} — {trigger stat}"* (e.g., "win-rate 0.62 over 48 trades").
- Admin button: **Run curriculum pass** · confirm toast: *"evaluated 100 agents · {k} promoted · {j} demoted"*.

## 5. Success metrics

- **Phase 1:** ≥70% of closed trades have a stamped outcome by end of day 1; median agent has ≥5 notes by end of week 1; journal section is opened in ≥40% of modal sessions (instrument a simple counter).
- **Phase 2:** rank distribution becomes non-degenerate within 2 weeks (no rank holds >60% of the cohort); median agent rank climbs over the first 4 weeks; Intern size-cap is hit in <5% of decisions (cap is meaningful but not punitive).
- **Phase 3:** ≥60% of decision-reasons contain a retrieval reference once memory depth ≥10; aggregate win-rate on setups with ≥1 retrieved match is measurably higher than matchless setups (directional, not statistically required).
- **Phase 4:** Promotions Board has ≥1 event/day on average; <10% of promotions reverse within a week (churn check); user opens Promotions Board in ≥25% of sessions.

## 6. Sequencing tradeoffs

- **All-at-once:** one big reveal, strongest narrative ("agents now learn"), but 4–6 weeks of silence for stakeholders and no chance to course-correct ranks/prompts against real data.
- **Monthly:** comfortable for engineering, but Phases 1 and 2 each carry enough standalone value that a month of gap wastes attention; by Phase 4 the early delight has faded.
- **Weekly (recommended):** ship P1 → P2 → P3 → P4 on consecutive Fridays. Each phase is independently demoable (see demo scripts), each builds visibly on the last (journal → ranks lean on journal stats → retrieval lean on journal → curriculum leans on ranks), and the whole story lands in a month. Weekly cadence also lets us watch the Phase-1 metric ("≥70% of closed trades have outcomes") before we anchor Phase 2 on it.

**Recommendation:** weekly, in order, with Phase 1 behind a "Journal (beta)" tag for its first week so we can iterate copy without a formal re-ship.
