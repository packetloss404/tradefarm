// Streaming-app copy of web/src/api.ts. Kept structurally identical so the
// REST + WS contract is shared. If types drift between the dashboard and the
// stream app, promote this to a workspace package — see SPEC §10.

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
  rank?: Rank;
  symbol?: string | null;
  cash: number;
  equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  positions: Record<string, { qty: number; avg_price: number; mark: number }>;
  last_lstm: LstmSnapshot | null;
  last_decision: LlmDecisionRow | null;
};

export type AccountSummary = {
  profit_ai: number;
  loss_ai: number;
  waiting_ai: number;
  total_equity: number;
  realized_pnl: number;
  unrealized_pnl: number;
  last_tick_at: string | null;
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
  status:
    | "new"
    | "accepted"
    | "pending_new"
    | "filled"
    | "partially_filled"
    | "canceled"
    | "rejected";
  submitted_at: string;
  filled_at: string | null;
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

// Settable at boot from settings.ts: when non-empty, all relative `/api/*`
// paths are rewritten to `${BACKEND_BASE}/...`. In Vite dev this stays empty
// and the proxy handles routing.
let BACKEND_BASE = "";
export function setBackendBase(base: string): void {
  BACKEND_BASE = base.replace(/\/$/, "");
}

const TAURI_HOSTS = new Set(["tauri.localhost"]);
const LOCAL_FALLBACK = "http://127.0.0.1:8000";

/**
 * Rewrite `/api/*` to an absolute backend URL.
 *
 * If `setBackendBase()` was called the configured base is used. Otherwise
 * if we're running inside a Tauri custom-protocol webview (host
 * `tauri.localhost`), fall back to `http://127.0.0.1:8000` — without this
 * the relative URL would resolve against the custom-protocol host and the
 * Tauri SPA fallback would return `index.html` instead of a 404, producing
 * an "Unexpected token '<'" JSON parse error.
 *
 * In a plain browser dev tab (Vite proxy) we leave relative URLs alone so
 * the proxy handles routing.
 */
function rewrite(path: string): string {
  if (!path.startsWith("/api")) return path;
  const tail = path.slice(4); // "/account" etc.
  if (BACKEND_BASE) return `${BACKEND_BASE}${tail}`;
  if (typeof location !== "undefined" && TAURI_HOSTS.has(location.hostname)) {
    return `${LOCAL_FALLBACK}${tail}`;
  }
  return path;
}

const fetcher = async <T,>(url: string): Promise<T> => {
  const target = rewrite(url);
  const r = await fetch(target);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  // Sanity guard: if a misconfigured webview swallowed the rewrite and the
  // SPA index.html came back instead of JSON, surface a helpful error
  // rather than an opaque "Unexpected token '<'" parse failure.
  const ct = r.headers.get("content-type") ?? "";
  if (!ct.includes("json")) {
    const body = (await r.text()).slice(0, 80);
    throw new Error(
      `Non-JSON response from ${target} (content-type=${ct || "unknown"}): ${body}`,
    );
  }
  return r.json() as Promise<T>;
};

export const api = {
  account: () => fetcher<AccountSummary>("/api/account"),
  agents: () => fetcher<AgentRow[]>("/api/agents"),
  pnlDaily: (days = 30) => fetcher<DailyPnlPoint[]>(`/api/pnl/daily?days=${days}`),
  orders: (limit = 25) => fetcher<OrderStatus[]>(`/api/orders?limit=${limit}`),
  promotions: (hours = 24, limit = 100) =>
    fetcher<Promotion[]>(`/api/academy/promotions?hours=${hours}&limit=${limit}`),
};
