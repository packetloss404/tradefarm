# TradeFarm on YouTube — research + build menu

research date: 2026-08-04 (post-0.7.0)
scope: what would make the project genuinely interesting as a YouTube channel — what an audience would actually watch, return for, and share.

## tl;dr

- **characters beat markets.** 100 named agents, ranks, journal notes, and per-tick inner-monologue decisions already exist in the data. the system treats them as rows; the channel has to treat them as people. the show is *The Office meets Wall Street*, not *Bloomberg*.
- **the prototype fixture is starving the show.** `web/src/vod/data.ts` ships 3 strategies, 1 mock day, 12 fixed beats. live system emits 7 strategies, 100 agents, a real tape. every operator preview validates the wrong ceiling.
- **the detector undershoots by design, and that's bottleneck #2.** `session/beats.py` caps at 8–15 beats per day. 100 agents × 7 strategies × 23,400 ticks — we throw away 99.9% of the drama.
- **the 5 new strategies are character gold.** `bb oversold px=99.5<lower=100.2`, `donchian breakout px=412.50>upper=410.20`, `pairs z=-2.34<-2 long KO vs PEP`, `rsi2 oversold 3.5<5`, `mom12-1 rising +12.3%>+9.8%` — all quotable lines the audience can repeat. lean into the jargon.
- **shorts are the unlock, not long-form.** 60-second vertical clips of single dramatic moments are how you get found. we have the headless renderer; we don't have a 9:16 capture path.

## quick wins (this week, 1-2 days each)

1. **"The Day in 60 Seconds"** — a vertical clip per session, hero scene + the day's top 3 beats stacked. new `src/tradefarm/render/shorts.py` (~150 LOC, ffmpeg-only — no extra Playwright), mirroring `headless.py` but for `9:16 @ 1080x1920`. shorts are the only YT format that surfaces in feeds for new channels.

2. **Refresh the prototype data** — `web/src/vod/data.ts` ships 3 strategies, 1 mock session. pull a real session's manifest + a week's journal notes into a new `data.live.ts` and have the studio prefer live over mock. ~50 LOC, zero new infra. every render preview currently validates the wrong ceiling.

3. **"Today's tape" hero sparkline** — extend `stream/src/components/TopTicker.tsx` to show the last 6 hours of the tape as a sparkline strip per agent, hero scene only. reuses `last_marks`, no backend changes. ~30 LOC. gives the hero scene a "this is a real day, real prices" feel.

4. **Beat kind: `agent_rivalry`** — already in the studio's `BeatPicker` (`web/src/vod/data.ts:264`) but missing from the detector (`session/beats.py:124`) and the beat-kind enum (`web/src/vod/types.ts:30-42`). add the scorer in `session/beats.py`: walk fills, find agents that took opposite sides of the same symbol ≥3 times in one day, surface the top 1–2. ~80 LOC.

5. **"Today's agents" pre-roll card** — extend `stream/src/scenes/PreRollScene.tsx` to iterate `snapshot.agents` (currently static). 30-sec opening card, one row per agent, strategy badge + name + status. cast list.

## current content surface

**7 stream scenes** (rotation per `SceneRotator.tsx:31`): hero, leaderboard, showdown, brain, decision-lab, strategy, recap. `BeatPicker` knows 6 (no `strategy`). `headless.py:70` skips recap (its endpoint isn't replay-aware).

**12 beat kinds in the studio** (`web/src/vod/types.ts:30-42`): open, big_fill, divergence, near_miss, streak, chapter_change, top_loser, llm_bet, leaderboard_shift, agent_rivalry, promotion, recap. the **detector scores 8** — `session/beats.py:18-33`: near_miss, chapter_change, promotion, llm_bet, agent_rivalry, leaderboard_shift need manifest data we don't emit. the studio is a brochure for a feature we don't run.

**agent identity** — 100 office-style names from `agents/names.py` (michael_smith through wei_yuki, 1:1 with agent_id). 7 strategies, 4 ranks. per-agent state: book, last_lstm, last_decision (LLM stance/bias/size_pct/reason), last_signal. 5 of 7 strategies now produce a specific, quotable reason per signal.

**journal notes** — every decision writes an `agent_notes` row (`storage/journal.py:79`). closed positions stamp the entry with realized PnL. retrievable via `/agents/{id}/notes?limit=N`. surfaced nowhere in stream or VOD.

**rank/promotion system** — intern/junior/senior/principal, capital multipliers 0.5×/1.0×/1.5×/2.0× (`academy/ranks.py`). promoted every `academy_eval_interval_sec`; demoted on drawdown or 5-loss streak. `promotion`/`demotion` events fire on WS (`academy/curriculum.py:187`). the live system has the events; `session/beats.py` doesn't score them.

**LLM inner monologue** — every `LstmLlmAgent.decide()` produces a 1-line reason capped at 80 chars (`agents/llm_overlay_types.py:23-45`), surfaced via `agent_decisions_batch` (`orchestrator/decision_feed.py:158`). the *most* audience-ready text in the system. `BrainScene` shows 12 cards, `DecisionLabScene` a 12-row ticker; no narrator reads it aloud.

**what's not surfaced:** the 14 hardcoded pairs in `data/pairs.py` (a pairs agent always knows its pair — KO/PEP, XOM/CVX — free storyline per episode), the LLM daily spend ceiling + skip rate (a "budget" story), the `Agent.disabled` flag (operators can freeze agents; the audience doesn't know who we muted), per-agent `last_marks` over time, demotion events (we have the trigger; nothing renders "you're fired" theatrically).

## episode format ideas (the menu)

1. **"The Intern Watch"** — 12-min Friday, 5 lowest-ranked `intern` agents. roll-call, 3 trades per intern (entry reason + LLM reason + outcome), close with promotion/demotion results. **highest ceiling** — character-driven, every week a different cast, demotion gives a built-in cliffhanger. the 4-rank capital multiplier (0.5× → 1.0×) is a *learnable payoff* the audience returns to learn. "I root for the underdog" — most of YT.

2. **"Strategy Wars — week N"** — 10-min mid-week. opening leaderboard (7 strategies, average P&L per slot), 3 representative trades per strategy, ranked by P&L impact. the recurring intro ("this week, momentum +14.2%, BB +9.1%, RSI-2 -2.3%, pairs +5.4%, Donchian +11.2%, LSTM +1.1%, LSTM+LLM +6.8%") becomes the channel's *theme song*. **highest ceiling for findability** — the "7 algorithms go head-to-head every week" pitch is a one-line tagline, and the recurring slot makes the algorithm audience (Linus / Sentdex / Prime) comfortable.

3. **"Rivalry Week"** — 7-min episode profiling the two agents who took opposite sides of the same symbol ≥3 times in the past 5 sessions. opening card with both names + their lifetime score vs each other, chronological replay, close on a single-tick showdown. **highest ceiling for shareability** — rivalry is the only narrative that doesn't need an explainer in the first 30 seconds.

4. **"The WAIT Room"** — 4-min Sunday, just the best LLM inner-monologue lines of the week, agent avatar + LLM reason in the lower-third. 100% derived from `decision_feed.reason` strings. cheaper than 1–3 and the most clip-friendly for shorts.

5. **"Agent of the Week"** — 6-min deep-dive on one agent. announced in the previous week's Intern Watch. ceiling medium — depends on whether the picked agent had a narrative week.

6. **"Pairs Trade Monday"** — 5-min on the 14 `pairs_zscore` agents. KO/PEP is Coca-Cola vs Pepsi. finance audience eats this; casual gated by jargon.

7. **"Lunch Hour Briefing"** — 2-min at 12:30 ET, every weekday. 4 beats max, no intro/outro, Bloomberg-style bulletin. ceiling is the *cadence* — 5 videos/week compounds habit.

8. **"LLM Cost vs Signal"** — 10-min monthly: for every LSTM+LLM decision, did the LLM *agree*, *override*, or get *cost-gated*? ceiling high, needs new detector work.

**top 3 by ceiling:** 1 (Intern Watch), 2 (Strategy Wars), 3 (Rivalry Week). all three share a property: *recurring slots with a fixed intro*. the daily recap is a content format; the weekly recurring is a channel.

## audience hypothesis

primary: 22-35, tech/coding culture, watches Linus / Sentdex / Prime / Theo. already follows AI vs AI (chess, Go, Diplomacy). the "100 agents, 7 strategies, 1 paper account" pitch is the channel tagline.

secondary: finance-curious who watch Patrick Boyle / meet-kevin but find them too serious. the 100-agent league format is the hook — humans root for humans (or human-named algorithms).

**"Bloomberg terminal meets sitcom" — does it land?** the Bloomberg layer is the part that already exists. the *sitcom* part doesn't. the sitcom is in the data (Marcus Wagner, Mei Patel, the journal notes, the rank-up, the demotion) — we just don't render it that way. lean into the sitcom. the Bloomberg part is the scoreboard; the sitcom is the show.

**how we get them:** shorts of the day's top 3 beats (vertical, captioned, 30–60s) on YT Shorts + TikTok + Reels. every short is one beat with the agent's face/name + the LLM's 1-line reason as the hook line. *this is the only acquisition channel that doesn't require an existing audience.*

## what's missing

content the system has but doesn't surface:

- **6 unscored beat kinds** — near_miss, llm_bet, agent_rivalry, leaderboard_shift, promotion, chapter_change. all in `web/src/vod/types.ts:30-42` and the mock `data.ts:160-252`. detector stubs in `session/beats.py:31-32` say "data not in the manifest today." fixing all six is ~300 LOC of detector scorers.
- **strategy vs strategy attribution over time** — the recap scene shows day P&L but not the *strategy-level* P&L split over a multi-day window.
- **the 14 pairs as a chart** — pairs_zscore agents know their pair (`data/pairs.py:8`). nothing renders the spread.

content that needs new code:

- **`render/shorts.py` capture path.** headless renders 16:9. shorts need 9:16. ffmpeg crop+resize from existing clips, ~150 LOC.
- **a weekly manifest type.** manifest is per-day (`session/manifest.py:36`). a weekly rollup that sums fills, promotions, and per-agent P&L is new.
- **a `vlog` beat kind** — a beat that's "today's most-quotable LLM line" + the agent's avatar + the closed P&L. no detector work, just a different render template.
- **strategy-family aggregation in the manifest** — `web/src/vod/data.ts:362` has per-strategy rollups in the mock; the live detector doesn't emit them. 30 LOC in `session/beats.py`.

## build spec for the top 3 picks

### 1. "The Intern Watch" (highest ceiling)

- **detector** — `_score_promotions()` in `session/beats.py` after `_score_streaks`. pulls `AcademyPromotion` rows, one beat per (agent, from_rank → to_rank) with `kind="promotion"`. demotions are `kind="top_loser"` with `metadata["from_rank"]`, `to_rank`. ~80 LOC + entries in `SCENE_FOR_KIND` / `DURATION_FOR_KIND` / `KIND_PRIORITY` (`beats.py:97-133`).
- **manifest** — `manifest.interns_under_watch: list[int]` (5 lowest-ranked `intern` ids at session start). 5 LOC in `session/run.py`.
- **render / scenes / kinds** — no new passes, scenes, or kinds. `promotion` already in `types.ts:41`. narrator: name + strategy + journal-note excerpt + rank + "stays at intern" or "promoted to junior."

### 2. "Strategy Wars" (highest ceiling for findability)

- **detector** — `_score_strategy_leaderboard(agents, th) -> Beat` after `_score_top_movers` in `session/beats.py`. emits `kind="strategy_war"` at close with `metadata={per_strategy_pnl, per_strategy_agent_count}`. ~60 LOC.
- **manifest** — `manifest.strategy_rollup: dict[str, StrategyRollup]` (same shape as `web/src/vod/types.ts:79`), computed at session end. ~30 LOC in `session/run.py`.
- **render** — reuse `stream/src/scenes/StrategyScene.tsx`. **add `strategy` to `BeatPicker` scenes** (`web/src/vod/BeatPicker.tsx:33-41` lists 6, no `strategy`) and to `headless.py:70` `SCENES_WITH_REPLAY_SUPPORT`. extend `StrategyScene` with a "vs last week" delta row (~50 LOC).
- **new kinds** — `strategy_war`. add to `types.ts:30-42` and `BEAT_KIND_META` (`web/src/vod/data.ts:254-267`). narrator: "momentum up, BB down, the mean reversion regime continues. this is week 6 of momentum's run." — needs the previous week's `strategy_rollup`, i.e. the weekly rollup.

### 3. "Rivalry Week" (highest ceiling for shareability)

- **detector** — `_score_rivalries(fills, th) -> list[Beat]` after `_score_divergence` (`session/beats.py:352`). scan for `(agent_a, agent_b, symbol)` triples with `a.side != b.side` and count ≥ 3 inside a 90-min rolling window. emit top 1–2 by overlap. ~100 LOC.
- **manifest** — `manifest.rivalries: list[{a, b, symbol, count, a_pnl, b_pnl}]` at close, ~30 LOC in `session/run.py`.
- **render** — `rivalry` beat plays on the `showdown` scene. multi-tick needs the headless renderer to feed the scene a longer window — `headless.py:84` `DEFAULT_SCENE_BY_KIND["rivalry"] = "showdown"`, render URL needs a custom `until` (current caps at `beat.t + beat.duration_sec`). ~40 LOC in `headless.py` `build_url`.
- **new kinds** — `rivalry`. add to `types.ts:30-42` and `BEAT_KIND_META`. narrator: "Marcus Wagner and Lisa Garcia, fourth time today on the same symbol. Wagner's up $32, Garcia's down $41. lifetime record: 3–1 Wagner." — needs cross-day history.

### shared infrastructure all three need

- **weekly rollup writer** — `session/weekly_rollup.py`. reads `manifest` + `AcademyPromotion` + closed `Trade` rows over a 7-day window, writes `out/weekly/<week_id>/rollup.json`. feeds Strategy Wars's "last week" delta and Rivalry Week's lifetime record. ~200 LOC.
- **shorts capture path** — `render/shorts.py` mirroring `headless.py` at `1080x1920` with a 60s cap. ~150 LOC.
- **prototype data refresh** — `web/src/vod/data.live.ts` + a toggle in `VodStudio.tsx` to prefer live over mock. ~50 LOC.

## open question

**ship the prototype data refresh first, or go straight to weekly formats?** the data refresh is 50 LOC and 1 day; unblocks every operator-facing demo but ships zero new viewers. the three episode formats are 1–2 weeks each and unblock audience growth. my read: ship the data refresh + the top 2 quick wins (shorts + Intern Watch detector) in week 1, then pick the episode formats against a real session tape. user owns that call.
