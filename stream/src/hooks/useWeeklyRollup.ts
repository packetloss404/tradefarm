import useSWR from "swr";
import { apiUrl } from "../shared/api";

// 0.16.0 — Live recap scene weekly rollup.
//
// Shape mirrors the backend's `weekly_rollup.read_weekly_rollup()`
// response. The stream's `LiveRecapScene` reads this on mount to
// render the "weekly rollup" line (strategy momentum %, mean-rev %,
// fills) and the rivalries section. The rollup is on disk (not
// in-memory like the ledger) so 404 means "no session for this week
// yet" — the scene degrades gracefully to a "this week so far" frame.
//
// `data` is `null` while loading AND on 404 (so a `if (!data)` guard
// in the scene covers both cases).
export type WeeklyRivalry = {
  a: number;
  b: number;
  symbol: string;
  count: number;
  a_pnl: number;
  b_pnl: number;
};

export type WeeklyRollupPayload = {
  week_id: string;
  date_range: [string, string];
  strategy_rollup: Record<string, { agents: number; equity: number; pnl: number; fills: number; pnlPct: number }>;
  rivalries: WeeklyRivalry[];
  promotions: Array<Record<string, unknown>>;
  sessions: Array<Record<string, unknown>>;
  pool_pnl: number;
  pool_pnl_pct: number;
};

const rollupFetcher = async (weekId: string): Promise<WeeklyRollupPayload | null> => {
  const target = apiUrl(`/api/recap/weekly/${weekId}`);
  const r = await fetch(target);
  // 404 means "no rollup on disk for this week yet" — return null so
  // the scene can render a "this week so far" frame. Any other error
  // surfaces to the SWR error state.
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const ct = r.headers.get("content-type") ?? "";
  if (!ct.includes("json")) {
    const body = (await r.text()).slice(0, 80);
    throw new Error(
      `Non-JSON response from ${target} (content-type=${ct || "unknown"}): ${body}`,
    );
  }
  return r.json() as Promise<WeeklyRollupPayload>;
};

export function useWeeklyRollup(
  weekId: string | null,
): {
  data: WeeklyRollupPayload | null;
  loading: boolean;
  error: string | null;
} {
  // The key is null when we have no week id yet (e.g. on first
  // render before the moment fires). SWR treats a null key as
  // "don't fetch" so the hook returns the loading state without
  // hammering a 400.
  const { data, error, isLoading } = useSWR<WeeklyRollupPayload | null>(
    weekId ? `weekly-rollup:${weekId}` : null,
    () => rollupFetcher(weekId as string),
    {
      // 5-minute poll; the rollup is updated when a session closes,
      // not on every tick, so aggressive polling is wasteful.
      refreshInterval: 5 * 60_000,
      revalidateOnFocus: false,
      revalidateIfStale: true,
    },
  );

  return {
    data: data ?? null,
    loading: isLoading && !data && !error,
    error: error ? (error as Error).message : null,
  };
}
