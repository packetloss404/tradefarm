import { useCallback, useRef, useState } from "react";
import useSWR from "swr";
import {
  api,
  type AccountSummary,
  type AgentRow,
  type DailyPnlPoint,
  type PromotionEventPayload,
} from "../shared/api";
import { useLiveEvents, type LiveEvent, type LiveStatus } from "../shared/useLiveEvents";

const REFRESH_MS = 5_000;
const FILL_BUFFER = 20;
const PROMOTION_BUFFER = 30;

type FillEvent = Extract<LiveEvent, { type: "fill" }>;
type PromotionEvent = Extract<LiveEvent, { type: "promotion" | "demotion" }>;
type TickEvent = Extract<LiveEvent, { type: "tick" }>;

export type StreamSnapshot = {
  status: LiveStatus;
  account: AccountSummary | null;
  agents: AgentRow[];
  pnlDaily: DailyPnlPoint[];
  fills: FillEvent[];
  promotions: PromotionEvent[];
  lastTick: TickEvent | null;
  error: string | null;
};

/**
 * Single data hook for the stream UI: composes SWR-polled REST snapshots with
 * the live `/ws` event stream. Mirrors the dashboard's `useEventFeed` shape
 * but bundles the SWR data so consumers don't need to know about cache keys.
 */
export function useStreamData(wsUrlOverride?: string): StreamSnapshot {
  const { data: account, error: accErr, mutate: mutateAccount } = useSWR<AccountSummary>(
    "stream-account",
    api.account,
    { refreshInterval: REFRESH_MS },
  );
  const { data: agents, error: agErr, mutate: mutateAgents } = useSWR<AgentRow[]>(
    "stream-agents",
    api.agents,
    { refreshInterval: REFRESH_MS },
  );
  const { data: pnlDaily, mutate: mutatePnl } = useSWR<DailyPnlPoint[]>(
    "stream-pnl-daily",
    () => api.pnlDaily(30),
    { refreshInterval: REFRESH_MS * 6 },
  );

  const [liveAccount, setLiveAccount] = useState<AccountSummary | null>(null);
  const [fills, setFills] = useState<FillEvent[]>([]);
  const [promotions, setPromotions] = useState<PromotionEvent[]>([]);
  const [lastTick, setLastTick] = useState<TickEvent | null>(null);

  const mutRef = useRef({ mutateAgents, mutatePnl, mutateAccount });
  mutRef.current = { mutateAgents, mutatePnl, mutateAccount };

  const handler = useCallback((ev: LiveEvent) => {
    switch (ev.type) {
      case "account":
        setLiveAccount(ev.payload);
        break;
      case "tick":
        setLastTick(ev);
        void mutRef.current.mutateAgents();
        void mutRef.current.mutatePnl();
        break;
      case "fill":
        setFills((prev) => {
          const next = prev.length >= FILL_BUFFER ? prev.slice(0, FILL_BUFFER - 1) : prev;
          return [ev, ...next];
        });
        break;
      case "promotion":
      case "demotion":
        setPromotions((prev) => {
          const next = prev.length >= PROMOTION_BUFFER ? prev.slice(0, PROMOTION_BUFFER - 1) : prev;
          return [ev, ...next];
        });
        void mutRef.current.mutateAgents();
        break;
      default:
        break;
    }
  }, []);

  const status = useLiveEvents(handler, wsUrlOverride);

  const err = (accErr || agErr) as Error | undefined;
  return {
    status,
    account: liveAccount ?? account ?? null,
    agents: agents ?? [],
    pnlDaily: pnlDaily ?? [],
    fills,
    promotions,
    lastTick,
    error: err?.message ?? null,
  };
}

export type { FillEvent, PromotionEvent, TickEvent, PromotionEventPayload };
