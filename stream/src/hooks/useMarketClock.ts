import useSWR from "swr";
import { api, type MarketClock, type MarketPhase } from "../shared/api";

const POLL_MS = 30_000;

export function useMarketClock(): {
  phase: MarketPhase;
  clock: MarketClock | null;
} {
  const { data } = useSWR<MarketClock>("stream-market-clock", api.marketClock, {
    refreshInterval: POLL_MS,
    revalidateOnFocus: false,
  });
  return {
    phase: data?.phase ?? "rth",
    clock: data ?? null,
  };
}
