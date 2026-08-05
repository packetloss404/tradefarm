// Runtime values for the dashboard mock fixtures. The Today page
// reuses the VOD mock (agents, beats, pipeline, summary); only the
// dash-only fixtures live here.
//
// Split from the old mockData.ts so type-only consumers (admin config
// props, episode card metadata) can import from ./types.ts and stay
// out of the production bundle.
//
// 0.13.0 — gated behind `import.meta.env.DEV` (see the matching
// comment in `vod/data.ts`). The dash-only heavy exports
// (EPISODES, STORYLINES, POOL_HISTORY, LB_HISTORY, DEFAULT_ADMIN_CONFIG)
// are noop/empty in production builds. Vite tree-shakes the dev
// branch based on the static `import.meta.env.DEV` literal.

import { seededRngStr, VOD_AGENTS } from "../vod/data";
import type { DashAdminConfig, Episode, LbHistory, Storyline, StorylineKind } from "./types";

const _IS_DEV = import.meta.env.DEV;

const EPISODE_TITLES = [
  "Quiet open, ugly close",
  "Five winners in a row",
  "LLM gets it wrong on NVDA",
  "Henry climbs to senior",
  "The day momentum_sma20 stopped working",
  "Brian vs Lisa, round three",
  "A walk through Tuesday",
  "Recap: a +2.4% day on no LLM calls",
  "Drawdown lessons",
  "Anna catches the gap",
  "Friday cleanup",
  "A boring Monday is still a Monday",
  "Ten fills, all green",
  "NVDA goes vertical",
  "Earnings risk: skip",
  "Mei takes #1 after 47 days",
];

const HUES = [145, 280, 50, 200, 350, 12];

function dayShape(seed: number): { t: number; score: number; hue: number }[] {
  const r = seededRngStr(`day-${seed}`);
  const n = 6 + Math.floor(r() * 8);
  const beats: { t: number; score: number; hue: number }[] = [];
  for (let i = 0; i < n; i++) {
    const t = (i + 0.4 + r() * 0.4) / n;
    const score = 0.35 + r() * 0.6;
    const hueIdx = Math.floor(r() * 6);
    beats.push({ t, score, hue: HUES[hueIdx] ?? 200 });
  }
  return beats;
}

function makeEpisodes(): Episode[] {
  const today = new Date("2026-05-19");
  const eps: Episode[] = [];
  for (let i = 0; i < 16; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() - (15 - i));
    const day = d.getDay();
    if (day === 0 || day === 6) continue;
    const r = seededRngStr(`ep-${i}`);
    const u = r();
    let pnlPct: number;
    if (u < 0.55) pnlPct = (r() - 0.4) * 2.4;
    else pnlPct = (r() - 0.5) * 6;
    eps.push({
      number: 32 + i,
      date: d.toISOString().slice(0, 10),
      title: EPISODE_TITLES[i] ?? `Day ${32 + i}`,
      pnlPct,
      pnlAbs: pnlPct * 1000,
      duration: 540 + Math.floor(r() * 240),
      views: i === 15 ? null : Math.floor(80 + r() * 1800),
      fills: 220 + Math.floor(r() * 180),
      beats: 8 + Math.floor(r() * 8),
      promotions: r() < 0.3 ? 1 : 0,
      demotions: r() < 0.1 ? 1 : 0,
      dayShape: dayShape(i),
      uploadedAt: i === 15 ? null : "16:30 ET",
      status: i === 15 ? "rendering" : "published",
      thumbHue: HUES[i % 6] ?? 200,
    });
  }
  return eps.reverse();
}

export const EPISODES: Episode[] = _IS_DEV ? makeEpisodes() : [];

// --- Storylines ---------------------------------------------------------

export const STORYLINES: Storyline[] = _IS_DEV ? [
  {
    id: "sl_brian_lisa",
    kind: "rivalry",
    headline: "Brian Anderson vs Lisa Garcia",
    sub: "Same symbol, opposing sides — 11 occurrences across 8 days",
    score: 0.91,
    daysActive: 8,
    startDate: "2026-05-09",
    agents: [10, 5],
    standings: { 10: 4, 5: 3 },
    trend: "escalating",
    nextHook: "Both held AVGO into close — 4th time this week",
  },
  {
    id: "sl_sarah_streak",
    kind: "streak",
    headline: "Sarah Brown · winning streak",
    sub: "7 closed trades, all green. Sharpe-30d 2.14",
    score: 0.78,
    daysActive: 4,
    startDate: "2026-05-14",
    agents: [3],
    standings: null,
    trend: "hot",
    nextHook: "Sharpe approaches principal eligibility threshold",
  },
  {
    id: "sl_mei_climb",
    kind: "leaderboard",
    headline: "Mei Patel · climbing the leaderboard",
    sub: "From #14 to #1 in 11 sessions",
    score: 0.86,
    daysActive: 11,
    startDate: "2026-05-04",
    agents: [98],
    standings: null,
    trend: "completed",
    nextHook: "Now defending #1 — Michael held it for 47 days",
  },
  {
    id: "sl_momentum_decline",
    kind: "strategy",
    headline: "momentum_sma20 · cooling off",
    sub: "−2.8% week, lowest of three strategies. 6 demotion candidates",
    score: 0.64,
    daysActive: 6,
    startDate: "2026-05-12",
    agents: [],
    standings: null,
    trend: "declining",
    nextHook: "Consider freezing the strategy and rebalancing capital",
  },
  {
    id: "sl_llm_skip",
    kind: "cost",
    headline: "LSTM+LLM · cost gate hitting 78%",
    sub: "Skipping ~3,700 LLM calls/day. $2.84 spend vs $13.10 budget",
    score: 0.42,
    daysActive: 14,
    startDate: "2026-05-01",
    agents: [],
    standings: null,
    trend: "steady",
    nextHook: "Healthy — gate working as designed",
  },
] : [];

export const STORYLINE_KIND_META: Record<StorylineKind, { label: string; accent: string; hue: number }> = {
  rivalry:     { label: "RIVALRY",     accent: "#fb923c", hue: 12 },
  streak:      { label: "STREAK",      accent: "#34d399", hue: 145 },
  leaderboard: { label: "LEADERBOARD", accent: "#fbbf24", hue: 50 },
  strategy:    { label: "STRATEGY",    accent: "#c084fc", hue: 280 },
  cost:        { label: "COST",        accent: "#86c5ff", hue: 200 },
};

// --- Multi-day pool equity ----------------------------------------------

export function makePoolHistory(): number[] {
  const points: number[] = [];
  let v = 96000;
  const r = seededRngStr("pool-history");
  for (let i = 0; i < 60; i++) {
    v += (r() - 0.45) * 600 + Math.sin(i / 6) * 80;
    points.push(v);
  }
  points[points.length - 1] = 101840;
  return points;
}

export const POOL_HISTORY: number[] = _IS_DEV ? makePoolHistory() : [];

// --- Leaderboard history ------------------------------------------------

export function makeLeaderboardHistory(): LbHistory {
  const days = 14;
  const series = [] as LbHistory["series"];
  const ranked = [...VOD_AGENTS].sort((a, b) => b.pnl - a.pnl).slice(0, 10);
  for (let d = 0; d < days; d++) {
    const r = seededRngStr(`lb-${d}`);
    const ranks = ranked.map((a, i) => {
      const noise = Math.floor((r() - 0.5) * 4);
      return { id: a.id, rank: i + 1 + noise };
    });
    series.push({ day: d, ranks });
  }
  series[series.length - 1] = {
    day: days - 1,
    ranks: ranked.map((a, i) => ({ id: a.id, rank: i + 1 })),
  };
  return { agents: ranked, series };
}

export const LB_HISTORY: LbHistory = _IS_DEV ? makeLeaderboardHistory() : { agents: [], series: [] };

// --- Admin config defaults ---------------------------------------------
//
// In dev, the operator can poke at the admin form with realistic
// placeholder values. In prod, the live ``/admin/config`` fetch
// returns the real values, and the form falls back to a
// minimal/empty shell so a missing backend doesn't leak a
// placeholder API key like ``"••••GH8X"`` into a production build.
export const DEFAULT_ADMIN_CONFIG: DashAdminConfig = _IS_DEV
  ? {
      ai_enabled: true,
      execution_mode: "simulated",
      llm_provider: "anthropic",
      llm_model: "claude-haiku-4-5",
      anthropic_api_key: "••••••••••••GH8X",
      minimax_api_key: "",
      llm_min_confidence: 0.4,
      llm_daily_budget_usd: 5.0,
      auto_tick_interval_sec: 300,
      tick_outside_rth: false,
      agent_count: 100,
      agent_starting_capital: 1000,
      disabled_strategies: "",
      academy_eval_interval_sec: 600,
      academy_retrieval_enabled: true,
      academy_retrieval_k: 3,
      academy_demote_drawdown_pct: 0.08,
      academy_demote_consecutive_losses: 5,
    }
  : {
      ai_enabled: true,
      execution_mode: "simulated",
      llm_provider: "anthropic",
      llm_model: "",
      anthropic_api_key: "",
      minimax_api_key: "",
      llm_min_confidence: 0.4,
      llm_daily_budget_usd: 5.0,
      auto_tick_interval_sec: 300,
      tick_outside_rth: false,
      agent_count: 100,
      agent_starting_capital: 1000,
      disabled_strategies: "",
      academy_eval_interval_sec: 600,
      academy_retrieval_enabled: true,
      academy_retrieval_k: 3,
      academy_demote_drawdown_pct: 0.08,
      academy_demote_consecutive_losses: 5,
    };
