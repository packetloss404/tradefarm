import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, type AdminConfig } from "../api";

const CONFIG_REFRESH_MS = 60_000;

export type UseTickCountdownReturn = {
  secsToNext: number;
  intervalSec: number;
  /** 0..1 normalised progress through the current interval (1 = just ticked). */
  progress: number;
};

export function useTickCountdown(lastTickIso: string | null): UseTickCountdownReturn {
  const { data: cfg } = useSWR<AdminConfig>("admin-config", api.adminConfig, {
    refreshInterval: CONFIG_REFRESH_MS,
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });

  const intervalSec = cfg?.auto_tick_interval_sec ?? 0;

  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (intervalSec <= 0 || lastTickIso === null) {
    return { secsToNext: 0, intervalSec: intervalSec, progress: 0 };
  }

  const lastTickMs = new Date(lastTickIso).getTime();
  const intervalMs = intervalSec * 1000;
  const elapsedMs = Math.max(0, now - lastTickMs);
  const secsToNext = Math.max(0, Math.ceil((intervalMs - elapsedMs) / 1000));
  const progress = Math.min(1, Math.max(0, 1 - elapsedMs / intervalMs));
  return { secsToNext, intervalSec, progress };
}
