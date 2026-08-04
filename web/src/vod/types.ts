// Pure types for the VOD studio. Re-exports the shapes used by
// ../data.ts so consumers that only need type information (props that
// read fields off the fixtures, mock-only type guards) can import
// from here without dragging the 100-agent / 13-beat / 10-pipeline
// fixture tables into the production bundle.
//
// Adding a new type-only shape? Put it here. Adding a new runtime
// fixture (functions, arrays, constants)? Put it in ./data.ts and
// re-export the matching type from here so consumers can use one
// canonical source.

export type Strategy = "momentum" | "lstm" | "llm";
export type Rank = "intern" | "junior" | "senior" | "principal";

export type Agent = {
  id: number;
  name: string;
  display: string;
  initials: string;
  strategy: Strategy;
  rank: Rank;
  equity: number;
  pnl: number;
  pnlPct: number;
  sparkline: number[];
  trades: number;
  wins: number;
};

export type BeatKind =
  | "open"
  | "big_fill"
  | "divergence"
  | "near_miss"
  | "streak"
  | "chapter_change"
  | "top_loser"
  | "llm_bet"
  | "leaderboard_shift"
  | "agent_rivalry"
  | "promotion"
  | "recap";

export type Beat = {
  id: string;
  t: string;
  tMs: number;
  kind: BeatKind;
  score: number;
  scene: string;
  headline: string;
  sub: string;
  duration: number;
  refs: string[];
  agents: number[];
  selected: boolean;
};

export type BeatMeta = { label: string; hue: number; accent: string };

export type PipelineStatus = "done" | "running" | "queued" | "failed";

export type PipelineNode = {
  id: string;
  label: string;
  cmd: string;
  status: PipelineStatus;
  started: string | null;
  finished: string | null;
  durationSec: number | null;
  progress?: number;
  progressLabel?: string;
  output: string;
  outputSize: string | null;
  summary: string;
  tail: string[];
};

export type StrategyRollup = {
  agents: number;
  equity: number;
  pnl: number;
  pnlPct: number;
  fills: number;
};

export type DaySummary = {
  totalEquity: number;
  allocated: number;
  totalPnl: number;
  pnlPct: number;
  byStrategy: Record<Strategy, StrategyRollup>;
  topAgents: Agent[];
  botAgents: Agent[];
  promotions: number;
  demotions: number;
  fillCount: number;
  decisionCount: number;
  llmCalls: number;
  llmSkipped: number;
  llmSpend: number;
};
