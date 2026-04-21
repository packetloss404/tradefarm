export type LstmSnapshot = {
  direction: "up" | "flat" | "down";
  probs: [number, number, number];
  confidence: number;
};

export type LlmDecisionRow = {
  bias: "long" | "flat" | "short";
  predictive: "long" | "flat" | "short";
  stance: "trade" | "wait";
  size_pct: number;
  reason: string;
};

export type Rank = "intern" | "junior" | "senior" | "principal";

export type AgentRow = {
  id: number;
  name: string;
  strategy: string;
  status: "profit" | "loss" | "waiting" | "trading";
  // Phase 2 (Agent Academy). Older backends won't emit this; callers must
  // fall back to "intern" when undefined.
  rank?: Rank;
  // Phase 3: the agent's pinned symbol (LSTM / LSTM+LLM agents). Older
  // backends omit this; null is fine for non-pinned agents (momentum).
  symbol?: string | null;
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Record<string, { qty: number; avg_price: number; mark: number }>;
  last_lstm: LstmSnapshot | null;
  last_decision: LlmDecisionRow | null;
};

export type RankDefinition = {
  rank: Rank;
  tone: string;
  pip: string;
  multiplier: number;
  base_cap_pct: number;
  effective_cap_pct: number;
};

export type AcademyOverview = {
  ranks: RankDefinition[];
  distribution: Record<Rank, number>;
  thresholds: {
    min_trades_junior: number;
    min_trades_senior: number;
    min_trades_principal: number;
    min_win_rate_senior: number;
    min_sharpe_principal: number;
    min_weeks_active_principal: number;
  };
};

export type AgentAcademy = {
  agent_id: number;
  rank: Rank;
  tone: string;
  multiplier: number;
  effective_cap_pct: number;
  stats: {
    n_closed_trades: number;
    win_rate: number;
    sharpe: number;
    weeks_active: number;
  };
  eligible_rank: Rank;
  next_rank: Rank | null;
  gaps: {
    trades_needed?: number;
    win_rate_target?: number;
    sharpe_target?: number;
    weeks_needed?: number;
  };
};

export type AccountSummary = {
  profit_ai: number;
  loss_ai: number;
  waiting_ai: number;
  total_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  last_tick_at: string | null;
  // Phase 1 (Academy): per-tick journal counters. Optional — older backends
  // won't emit these.
  notes_this_tick?: number;
  outcomes_this_tick?: number;
};

export type TickResult = { fills: number; blocked: number; symbols: number };

export type DailyPnlPoint = { date: string; equity: number; pnl_pct: number };

export type OrderStatus = {
  broker_order_id: string;
  client_order_id: string;
  agent_id: number | null;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  status: "new" | "accepted" | "pending_new" | "filled" | "partially_filled" | "canceled" | "rejected";
  submitted_at: string;
  filled_at: string | null;
};

export type StrategySummaryRow = {
  strategy: string;
  agent_count: number;
  realized_pnl_total: number;
  unrealized_pnl_total: number;
  equity_total: number;
  trades_today: number;
  win_rate: number;
  best_agent_name: string;
  worst_agent_name: string;
};

export type StrategyTimeseriesPoint = { date: string; strategy: string; equity_total: number };

export type AgentTrade = {
  id: number;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  executed_at: string | null;
  reason: string;
};

export type AgentNote = {
  id: number;
  agent_id: number;
  kind: "entry" | "exit" | "observation";
  symbol: string;
  content: string;
  metadata: Record<string, unknown>;
  created_at: string | null;
  outcome_trade_id: number | null;
  outcome_realized_pnl: number | null;
  outcome_closed_at: string | null;
};

// Phase 3 — one past stamped setup the LSTM+LLM agent pulled as retrieval context.
export type RetrievedExample = {
  symbol: string;
  direction_hint: string;
  content: string;
  realized_pnl: number;
  closed_at_iso: string;
  note_id: number;
};

export type AdminSecretField = { set: boolean; masked: string };

export type AdminConfig = {
  ai_enabled: boolean;
  llm_provider: "anthropic" | "minimax";
  llm_model: string;
  anthropic_api_key: AdminSecretField;
  minimax_api_key: AdminSecretField;
  minimax_base_url: string;
  llm_min_confidence: number;
  auto_tick_interval_sec: number;
  tick_outside_rth: boolean;
  execution_mode: "simulated" | "alpaca_paper";
  disabled_strategies: string[];
  _meta: {
    secret_keys: string[];
    valid_providers: string[];
    valid_execution: string[];
    model_defaults: Record<string, string>;
    known_strategies: string[];
    strategy_agent_counts: Record<string, number>;
  };
};

export type AdminPatch = Partial<{
  ai_enabled: boolean;
  llm_provider: "anthropic" | "minimax";
  llm_model: string;
  anthropic_api_key: string;
  minimax_api_key: string;
  minimax_base_url: string;
  llm_min_confidence: number;
  auto_tick_interval_sec: number;
  tick_outside_rth: boolean;
  execution_mode: "simulated" | "alpaca_paper";
  disabled_strategies: string[];
  persist: boolean;
}>;

export type BacktestResult = {
  symbol: string;
  error?: string;
  total_return_pct?: number;
  cagr_pct?: number;
  sharpe?: number;
  max_drawdown_pct?: number;
  win_rate?: number;
  n_trades?: number;
  avg_trade_return_pct?: number;
  n_bars?: number;
};

export type BacktestJob = {
  job_id: string;
  status: "running" | "done";
  total: number;
  done: number;
  symbols?: string[];
  current: string | null;
  results: BacktestResult[];
  started_at: string;
  finished_at: string | null;
};

const fetcher = async <T>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
};

export const api = {
  account: () => fetcher<AccountSummary>("/api/account"),
  agents: () => fetcher<AgentRow[]>("/api/agents"),
  pnlDaily: (days = 30) => fetcher<DailyPnlPoint[]>(`/api/pnl/daily?days=${days}`),
  orders: (limit = 25) => fetcher<OrderStatus[]>(`/api/orders?limit=${limit}`),
  strategySummary: () => fetcher<StrategySummaryRow[]>("/api/pnl/by-strategy"),
  strategyTimeseries: (days = 7) =>
    fetcher<StrategyTimeseriesPoint[]>(`/api/pnl/by-strategy/timeseries?days=${days}`),
  agentTrades: (agentId: number, limit = 20) =>
    fetcher<AgentTrade[]>(`/api/agents/${agentId}/trades?limit=${limit}`),
  agentNotes: (agentId: number, limit = 20) =>
    fetcher<AgentNote[]>(`/api/agents/${agentId}/notes?limit=${limit}`),
  agentRetrieval: (agentId: number, symbol: string, k = 3) =>
    fetcher<RetrievedExample[]>(
      `/api/agents/${agentId}/retrieval-preview?symbol=${encodeURIComponent(symbol)}&k=${k}`,
    ),
  academyOverview: () => fetcher<AcademyOverview>("/api/academy/ranks"),
  agentAcademy: (agentId: number) =>
    fetcher<AgentAcademy>(`/api/agents/${agentId}/academy`),
  adminConfig: () => fetcher<AdminConfig>("/api/admin/config"),
  adminPatch: async (patch: AdminPatch): Promise<{ changed: Record<string, unknown>; overlay: { provider: string | null; model: string | null } | null }> => {
    const r = await fetch("/api/admin/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  adminToggleAi: async (enabled: boolean): Promise<{ ai_enabled: boolean }> => {
    const r = await fetch(`/api/admin/toggle-ai?enabled=${enabled}`, { method: "POST" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  backtestRun: async (symbols: string[] | null): Promise<{ job_id: string; total: number; status: string }> => {
    const r = await fetch("/api/backtest/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbols }),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  backtestStatus: (jobId: string) => fetcher<BacktestJob>(`/api/backtest/${jobId}`),
  backtestCancel: async (jobId: string): Promise<void> => {
    await fetch(`/api/backtest/${jobId}`, { method: "DELETE" });
  },
  tick: async (): Promise<TickResult> => {
    const r = await fetch("/api/tick", { method: "POST" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
};
