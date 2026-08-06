import useSWR from "swr";
import { apiUrl } from "../shared/api";

// 0.16.0 — Live recap scene ledger.
//
// Shape mirrors the backend's `BroadcastRecapLedger.to_payload()`
// (recent_limit=20, top_limit=10), which the stream's `LiveRecapScene`
// reads on mount + on every `broadcast_moment` event. The recent + top
// slices are pre-sorted server-side; the scene just renders them.
//
// `data` is `null` until the first fetch resolves (SWR's `data` is
// `undefined` while loading — we normalize to `null` so the scene's
// `if (loading || !data)` early-return reads naturally).
export type RecapLedgerPayload = {
  max_moments: number;
  count: number;
  recent: Array<Record<string, unknown>>;
  top: Array<Record<string, unknown>>;
};

const ledgerFetcher = async (): Promise<RecapLedgerPayload> => {
  const target = apiUrl("/api/recap/ledger");
  const r = await fetch(target);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  const ct = r.headers.get("content-type") ?? "";
  if (!ct.includes("json")) {
    const body = (await r.text()).slice(0, 80);
    throw new Error(
      `Non-JSON response from ${target} (content-type=${ct || "unknown"}): ${body}`,
    );
  }
  return r.json() as Promise<RecapLedgerPayload>;
};

export function useRecapLedger(): {
  data: RecapLedgerPayload | null;
  loading: boolean;
  error: string | null;
} {
  const { data, error, isLoading } = useSWR<RecapLedgerPayload>(
    "recap-ledger",
    ledgerFetcher,
    {
      // Poll every 5s while the scene is mounted; the ledger is
      // in-memory and the canonical `broadcast_moment` event is what
      // actually flips the scene's "live" state, but a slow-fetched
      // ledger (e.g. after a brief WS blip) picks up the moments
      // that landed during the gap.
      refreshInterval: 5_000,
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
