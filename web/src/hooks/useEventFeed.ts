import { useCallback, useRef, useState } from "react";
import type { AccountSummary } from "../api";
import { useLiveEvents, type LiveEvent, type LiveStatus } from "./useLiveEvents";

const BUFFER_CAP = 50;
const FILL_CAP = 20;

type TickEvent = Extract<LiveEvent, { type: "tick" }>;
type FillEvent = Extract<LiveEvent, { type: "fill" }>;

export type EventFeed = {
  status: LiveStatus;
  /** Most recent `account` payload pushed by the server, or `null` before first event. */
  account: AccountSummary | null;
  /** Most recent `tick` envelope (includes `ts`), or `null` before first tick. */
  lastTick: TickEvent | null;
  /** Up to the last {@link FILL_CAP} fill events, newest first. */
  fills: FillEvent[];
  /** Rolling buffer of the last {@link BUFFER_CAP} events of any type, newest first. */
  buffer: LiveEvent[];
};

/** SWR `mutate` callbacks that should be refreshed when a `tick` event arrives. */
export type FeedMutators = {
  mutateAgents?: () => Promise<unknown> | unknown;
  mutatePnl?: () => Promise<unknown> | unknown;
};

/**
 * Aggregates the `/ws` stream into React-friendly slices. Heartbeats are
 * appended to the rolling buffer but do not touch account/tick/fill slices,
 * so header KPIs and the agent grid don't re-render every few seconds for
 * no reason. On `tick`, the provided SWR mutators are fired so the full
 * agents + pnl-daily caches refresh without having to poll.
 */
export function useEventFeed(mutators: FeedMutators = {}): EventFeed {
  const [account, setAccount] = useState<AccountSummary | null>(null);
  const [lastTick, setLastTick] = useState<TickEvent | null>(null);
  const [fills, setFills] = useState<FillEvent[]>([]);
  const [buffer, setBuffer] = useState<LiveEvent[]>([]);
  const mutRef = useRef(mutators);
  mutRef.current = mutators;

  const handler = useCallback((ev: LiveEvent) => {
    setBuffer((prev) => {
      if (prev.length === 0) return [ev];
      const next = prev.length >= BUFFER_CAP ? prev.slice(0, BUFFER_CAP - 1) : prev;
      return [ev, ...next];
    });

    switch (ev.type) {
      case "account":
        setAccount(ev.payload);
        break;
      case "tick":
        setLastTick(ev);
        void mutRef.current.mutateAgents?.();
        void mutRef.current.mutatePnl?.();
        break;
      case "fill":
        setFills((prev) => {
          const next = prev.length >= FILL_CAP ? prev.slice(0, FILL_CAP - 1) : prev;
          return [ev, ...next];
        });
        break;
      case "heartbeat":
      case "hello":
      case "pnl_snapshot":
        // buffer-only; pnl_snapshot is read via SWR mutate on tick
        break;
    }
  }, []);

  const status = useLiveEvents(handler);
  return { status, account, lastTick, fills, buffer };
}
