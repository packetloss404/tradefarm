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
  // 0.14.0 — daily LLM spend cap (USD). Backend enforces this via
  // ``runtime.llm_budget``; the dashboard surfaces it as the
  // "of $X/day" cap on the API Spend widget + the admin form's
  // "Daily LLM budget" row. Optional for backends that don't
  // expose it yet.
  llm_daily_budget_usd?: number;
  auto_tick_interval_sec: number;
  tick_outside_rth: boolean;
  execution_mode: "simulated" | "alpaca_paper";
  disabled_strategies: string[];
  // Phase 4 — curriculum settings (optional so older backends don't break).
  academy_eval_interval_sec?: number;
  academy_demote_drawdown_pct?: number;
  academy_demote_consecutive_losses?: number;
  academy_demote_cap_pct?: number;
  _meta: {
    secret_keys: string[];
    valid_providers: string[];
    valid_execution: string[];
    model_defaults: Record<string, string>;
    known_strategies: string[];
    strategy_agent_counts: Record<string, number>;
  };
};

export type Promotion = {
  id: number;
  agent_id: number;
  agent_name: string | null;
  from_rank: Rank;
  to_rank: Rank;
  reason: string;
  stats_snapshot: string;
  at: string | null;
};

export type PromotionEventPayload = {
  agent_id: number;
  agent_name: string;
  from_rank: Rank;
  to_rank: Rank;
  reason: string;
  at: string;
};

export type CurriculumResult = {
  promoted: PromotionEventPayload[];
  demoted: PromotionEventPayload[];
  unchanged: number;
  evaluated_at: string;
};

export type AdminPatch = Partial<{
  ai_enabled: boolean;
  llm_provider: "anthropic" | "minimax";
  llm_model: string;
  anthropic_api_key: string;
  minimax_api_key: string;
  minimax_base_url: string;
  llm_min_confidence: number;
  llm_daily_budget_usd?: number;
  auto_tick_interval_sec: number;
  tick_outside_rth: boolean;
  execution_mode: "simulated" | "alpaca_paper";
  disabled_strategies: string[];
  persist: boolean;
}>;

// Per-agent admin override responses. Mirrors the response shape of
// `/api/admin/agents` and the two POST endpoints. Distinct from the
// per-strategy `disabled_strategies` field on `AdminConfig` — the
// per-agent flag is stored on `agents.disabled` in the DB and the
// scheduler reads it once per tick.
export type AdminAgentRow = {
  id: number;
  name: string;
  strategy: string;
  disabled: boolean;
  cash: number;
};

export type AdminAgentSetDisabledResult = {
  agent_id: number;
  disabled: boolean;
};

export type AdminAgentBulkSetDisabledResult = {
  updated: number[];
};

export type PipelineRunRow = {
  run_id: string;
  session_id: string;
  date: string | null;
  enabled: string[];
  force: boolean;
  dry_run: boolean;
  status: "pending" | "running" | "done" | "failed";
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  last_lines: string[];
};

export type LlmStats = {
  called: number;
  skipped_low_confidence: number;
  total_decisions: number;
  skip_rate: number;
  threshold: number;
};

// 0.17.0 — lower-third builder payloads. Mirror the server-side schema
// in `tradefarm.api.lower_third_log` and the lower_third WS event
// payload shape. `ttl_sec` is required on the wire (the server-side
// default of 8 is applied when the operator omits it) so the recent
// list can always be rendered without per-row conditional state.
export type LowerThirdColor = "profit" | "loss" | "neutral";

export type LowerThirdPayload = {
  id: string;
  title: string;
  subtitle: string;
  ttl_sec: number;
  color: LowerThirdColor | null;
  // ISO-8601 wall-clock timestamp the server stamped at record-time;
  // the dashboard's recent-list uses it for the relative age label.
  pushed_at: string;
};

export type LowerThirdPushInput = {
  title: string;
  subtitle?: string;
  ttl_sec?: number;
  color?: LowerThirdColor;
  id?: string;
};

// 0.17.0 — TTS settings panel types. The provider union is the same
// three values the backend's `VALID_TTS_PROVIDERS` accepts; the
// response shapes mirror the Pydantic response models in
// `src/tradefarm/api/admin.py` so the SWR fetcher's `as Promise<X>`
// casts are safe.
export type TtsProvider = "openai" | "elevenlabs" | "silence";
export type TtsConfigPayload = {
  provider: TtsProvider;
  voice: string;
  speaking_rate: number;
};
export type TtsStatusPayload = {
  config: TtsConfigPayload;
  available_providers: TtsProvider[];
  has_creds: Record<TtsProvider, boolean>;
  voices_by_provider: Record<TtsProvider, string[]>;
  cost_per_1k_chars_usd: Record<TtsProvider, number>;
  creds_present: boolean;
};
export type TtsPreviewPayload = {
  provider: TtsProvider;
  voice: string;
  duration_sec: number;
  cost_usd: number;
  total_calls: number;
  total_cost_usd: number;
  audio_base64: string;
  mime: string;
};
export type TtsStatsPayload = {
  chars_synthesized: number;
  cost_usd: number;
  calls: number;
  active_provider: TtsProvider;
};

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
  llmStats: () => fetcher<LlmStats>("/api/llm/stats"),
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
  promotions: (hours = 24, limit = 100) =>
    fetcher<Promotion[]>(`/api/academy/promotions?hours=${hours}&limit=${limit}`),
  // Per-agent admin override endpoints. Separate from the per-strategy
  // `disabled_strategies` set in `AdminConfig` — disabling a single
  // agent bypasses the whole strategy and freezes just that one row's
  // decisions + risk-exits until re-enabled.
  adminAgents: () => fetcher<AdminAgentRow[]>("/api/admin/agents"),
  adminAgentSetDisabled: async (
    agentId: number,
    disabled: boolean,
  ): Promise<AdminAgentSetDisabledResult> => {
    const r = await fetch(`/api/admin/agents/${agentId}/disabled`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  adminAgentBulkSetDisabled: async (
    agentIds: number[],
    disabled: boolean,
  ): Promise<AdminAgentBulkSetDisabledResult> => {
    const r = await fetch("/api/admin/agents/bulk-disabled", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent_ids: agentIds, disabled }),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  runCurriculum: async (): Promise<CurriculumResult> => {
    const r = await fetch("/api/academy/evaluate", { method: "POST" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  tick: async (): Promise<TickResult> => {
    const r = await fetch("/api/tick", { method: "POST" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  // VOD pipeline runner. POST /pipeline/run kicks off a background
  // task; the result includes a run_id the UI uses to filter
  // `pipeline_progress` WS events. The runner publishes those
  // events as the chain walks its steps; the operator's view of
  // progress is "Run pipeline" button + a live log panel fed off
  // the WS bus.
  pipelineRun: async (req: {
    date?: string;
    session_id?: string;
    include_tts?: boolean;
    include_upload?: boolean;
    skip_headless?: boolean;
    force?: boolean;
    dry_run?: boolean;
    music?: string;
  }): Promise<{ run_id: string; session_id: string; status: string; enabled: string[] }> => {
    const r = await fetch("/api/pipeline/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  pipelineRuns: () => fetcher<PipelineRunRow[]>("/api/pipeline/runs"),
  pipelineRunStatus: (runId: string) =>
    fetcher<PipelineRunRow>(`/api/pipeline/runs/${runId}`),
  // 0.17.0 — lower-third builder endpoints. `pushLowerThird` posts to
  // the admin endpoint; the server assigns the id when the request
  // omits one. `getRecentLowerThirds` reads the in-memory ring buffer
  // (newest-first) for the dashboard's replay list.
  pushLowerThird: async (
    payload: LowerThirdPushInput,
  ): Promise<LowerThirdPayload> => {
    const r = await fetch("/api/admin/lower_third/push", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json() as Promise<LowerThirdPayload>;
  },
  getRecentLowerThirds: async (limit = 10): Promise<LowerThirdPayload[]> => {
    const data = await fetcher<{ items: LowerThirdPayload[] }>(
      `/api/admin/lower_third/recent?limit=${limit}`,
    );
    return data.items;
  },
  // 0.17.0 — TTS settings panel endpoints. The status payload drives
  // the form's availability map (gating cloud providers on
  // `has_creds[provider]`); the switch endpoint accepts a full
  // config (provider + voice + speaking_rate) and the reset endpoint
  // reverts to the env-var defaults.
  ttsStatus: () => fetcher<TtsStatusPayload>("/api/admin/tts/status"),
  ttsSwitch: async (req: {
    provider: "openai" | "elevenlabs" | "silence";
    voice: string;
    speaking_rate: number;
  }): Promise<{ previous: TtsConfigPayload; active: TtsConfigPayload }> => {
    const r = await fetch("/api/admin/tts/switch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  ttsReset: async (): Promise<{ previous: TtsConfigPayload }> => {
    const r = await fetch("/api/admin/tts/reset", { method: "POST" });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  ttsPreview: async (req: {
    text: string;
    provider?: "openai" | "elevenlabs" | "silence";
    voice?: string;
  }): Promise<TtsPreviewPayload> => {
    const r = await fetch("/api/admin/tts/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    });
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
  ttsStats: () =>
    fetcher<TtsStatsPayload>("/tts/stats"),
  // 0.16.0 — Rivalry Week weekly podcast tab. Reads the weekly
  // rollup (which now carries a `podcast` field when
  // `out/weekly/<week_id>/podcast/episode_*.mp4` exists on disk).
  // The endpoint is owned by Dev B's recap scene work; if the
  // backend isn't running that handler yet the fetcher raises and
  // the SWR consumer falls back to the empty list.
  // TODO: swap the `unknown` response for the real WeeklyRollup
  // type once Dev B's recap scene /api/weekly endpoint ships.
  getWeeklyRollup: async (weekId: string): Promise<unknown> => {
    const r = await fetch(`/api/weekly/${encodeURIComponent(weekId)}`);
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
    return r.json();
  },
};
