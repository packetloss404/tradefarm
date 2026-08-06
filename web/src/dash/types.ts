// Pure types for the dashboard mock fixtures (episodes archive,
// storylines, leaderboard history, admin config defaults). The runtime
// values live in ./data.ts so consumers that only need the shape can
// stay out of the production bundle.

import type { Agent } from "../vod/types";

export type Episode = {
  number: number;
  date: string;
  title: string;
  pnlPct: number;
  pnlAbs: number;
  duration: number;
  views: number | null;
  fills: number;
  beats: number;
  promotions: number;
  demotions: number;
  dayShape: { t: number; score: number; hue: number }[];
  uploadedAt: string | null;
  status: "published" | "rendering";
  thumbHue: number;
};

export type StorylineKind = "rivalry" | "streak" | "leaderboard" | "strategy" | "cost";
export type StorylineTrend = "escalating" | "hot" | "completed" | "declining" | "steady";

export type Storyline = {
  id: string;
  kind: StorylineKind;
  headline: string;
  sub: string;
  score: number;
  daysActive: number;
  startDate: string;
  agents: number[];
  standings: Record<number, number> | null;
  trend: StorylineTrend;
  nextHook: string;
};

export type LbDay = { day: number; ranks: { id: number; rank: number }[] };
export type LbHistory = { agents: Agent[]; series: LbDay[] };

export type DashAdminConfig = {
  ai_enabled: boolean;
  execution_mode: "simulated" | "alpaca_paper";
  // 0.18.0 — OpenAI added to the provider union. Older backends
  // (pre-0.18.0) might not have the field; the form reads through
  // `liveMeta` to know what's available.
  llm_provider: "anthropic" | "minimax" | "openai";
  llm_model: string;
  anthropic_api_key: string;
  openai_api_key?: string;
  minimax_api_key: string;
  llm_min_confidence: number;
  // 0.14.0 — daily LLM spend cap (USD). Optional for older backends
  // that don't expose it; the admin form falls back to "0" (no cap)
  // when the field is missing.
  llm_daily_budget_usd?: number;
  auto_tick_interval_sec: number;
  tick_outside_rth: boolean;
  agent_count: number;
  agent_starting_capital: number;
  disabled_strategies: string;
  academy_eval_interval_sec: number;
  academy_retrieval_enabled: boolean;
  academy_retrieval_k: number;
  academy_demote_drawdown_pct: number;
  academy_demote_consecutive_losses: number;
};
