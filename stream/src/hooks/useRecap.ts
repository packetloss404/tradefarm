import useSWR from "swr";
import { apiUrl } from "../shared/api";

// agent_name is nullable because the backend resolves it from the live
// orchestrator roster — if an agent has been retired since the trade closed,
// the field comes back as null rather than a stale name.
export type RecapBiggestFill = {
  agent_id: number;
  agent_name: string | null;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
  notional: number;
  at: string;
};

export type RecapTopWinner = {
  agent_id: number;
  agent_name: string | null;
  realized_pnl: number;
  symbol: string;
};

export type RecapBiggestLoss = {
  agent_id: number;
  agent_name: string | null;
  realized_pnl: number;
  symbol: string;
};

export type RecapPromotion = {
  agent_id: number;
  agent_name: string | null;
  from: string;
  to: string;
  at: string;
};

export type RecapPrediction = {
  id: string;
  question: string;
  winning_option: string | null;
  tally: Record<string, number>;
  total_votes: number;
  status: "open" | "locked" | "revealed";
};

export type RecapDay = {
  date: string;
  session_pnl_pct: number;
  session_total_equity: number;
  total_fills: number;
  biggest_fill: RecapBiggestFill | null;
  top_winners: RecapTopWinner[];
  biggest_loss: RecapBiggestLoss | null;
  promotions: RecapPromotion[];
  predictions: RecapPrediction[];
};

const recapFetcher = async (): Promise<RecapDay> => {
  const target = apiUrl("/api/recap/today");
  const r = await fetch(target);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const ct = r.headers.get("content-type") ?? "";
  if (!ct.includes("json")) {
    const body = (await r.text()).slice(0, 80);
    throw new Error(
      `Non-JSON response from ${target} (content-type=${ct || "unknown"}): ${body}`,
    );
  }
  return r.json() as Promise<RecapDay>;
};

export function useRecap(): {
  data: RecapDay | null;
  loading: boolean;
  error: string | null;
} {
  const { data, error, isLoading } = useSWR<RecapDay>("recap-today", recapFetcher, {
    refreshInterval: 0,
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
    revalidateIfStale: false,
  });

  return {
    data: data ?? null,
    loading: isLoading && !data && !error,
    error: error ? (error as Error).message : null,
  };
}
