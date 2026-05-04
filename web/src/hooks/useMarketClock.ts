import { useEffect, useState } from "react";
import useSWR from "swr";

export type MarketPhase = "premarket" | "rth" | "afterhours" | "closed" | "unknown";

type ClockResponse = {
  phase: Exclude<MarketPhase, "unknown">;
  server_now: string;
  opens_at: string | null;
  closes_at: string | null;
};

export type UseMarketClockReturn = {
  phase: MarketPhase;
  openCountdown: string;
  closeCountdown: string;
  opensAtIso: string | null;
  closesAtIso: string | null;
  isOpen: boolean;
};

const POLL_MS = 60_000;

const fetcher = async (url: string): Promise<ClockResponse> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as ClockResponse;
};

function fmtCountdown(deltaMs: number): string {
  if (!Number.isFinite(deltaMs) || deltaMs <= 0) return "0:00";
  const total = Math.floor(deltaMs / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function useMarketClock(): UseMarketClockReturn {
  const { data, error } = useSWR<ClockResponse>("market-clock", () => fetcher("/api/market/clock"), {
    refreshInterval: POLL_MS,
    shouldRetryOnError: true,
    revalidateOnFocus: false,
  });

  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (error || !data) {
    return {
      phase: "unknown",
      openCountdown: "—",
      closeCountdown: "—",
      opensAtIso: null,
      closesAtIso: null,
      isOpen: false,
    };
  }

  const opensAtMs = data.opens_at !== null ? new Date(data.opens_at).getTime() : null;
  const closesAtMs = data.closes_at !== null ? new Date(data.closes_at).getTime() : null;

  return {
    phase: data.phase,
    opensAtIso: data.opens_at,
    closesAtIso: data.closes_at,
    openCountdown: opensAtMs !== null ? fmtCountdown(opensAtMs - now) : "—",
    closeCountdown: closesAtMs !== null ? fmtCountdown(closesAtMs - now) : "—",
    isOpen: data.phase === "rth",
  };
}
