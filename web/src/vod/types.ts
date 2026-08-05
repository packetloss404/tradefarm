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

// 8-bucket view: the 7 live strategies (momentum_12_1, mean_reversion_bb,
// rsi2, donchian_breakout, pairs_zscore, lstm, llm) plus the legacy
// "momentum" alias that the prototype's old data.ts used for the
// "momentum_sma20" mock. Live agents in `useVodLiveData` map into these
// 8 buckets; the prototype's mock agents (in data.ts) randomly pick
// from all 8. The pre-0.7 `Strategy = "momentum" | "lstm" | "llm"`
// 3-bucket union is kept as `StrategyLegacy` for back-compat with the
// existing useVodSessionLive hook, which only knows the old 3-bucket
// view.
export type StrategyLegacy = "momentum" | "lstm" | "llm";
export type StrategyBucket =
  | StrategyLegacy
  | "momentum_12_1"
  | "mean_reversion_bb"
  | "rsi2"
  | "donchian_breakout"
  | "pairs_zscore";
// Default export name kept as `Strategy` so consumers reading
// `import { Strategy }` still get a valid type. This is the 8-bucket
// view going forward; `StrategyLegacy` is the narrower 3-bucket view.
export type Strategy = StrategyBucket;

export type Rank = "intern" | "junior" | "senior" | "principal";

// 0.9.0-era manifest extra: the 5 lowest-cash intern agents at
// session start, with the static metadata the VOD studio needs to
// render an Intern Watch card without a re-query.
export type InternCastRow = {
  agent_id: number;
  name: string;
  rank: string;
  rank_index: number;
  strategy: string;
  starting_capital: number;
};

// 0.8.0-era manifest extra: top-2 rivalry triples (a, b, symbol,
// count, a_pnl, b_pnl) for the Rivalry Week surface.
export type RivalryRow = {
  a: number;
  b: number;
  symbol: string;
  count: number;
  a_pnl: number;
  b_pnl: number;
};

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
  // 0.10.0 — optional fields the Intern Watch / Rivalry Week
  // surfaces use for the mock-fixture fallback. The live path
  // doesn't need them (the manifest's `lowest_ranks` +
  // `rivalries` carry the structured data).
  cash?: number;
  symbol?: string;
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
