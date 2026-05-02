import { useEffect, useRef, useState } from "react";
import type { FillEvent, PromotionEvent } from "./useStreamData";
import type { AgentRow } from "../shared/api";

export type Highlight = {
  id: string;
  kind: "big_fill" | "promotion" | "demotion" | "hot_tick" | "glory";
  text: string;
  at: number;
};

const DWELL_MS = 6_000;
const QUEUE_MAX = 8;
const BIG_FILL_NOTIONAL = 50;       // |qty * price - mark*qty| ish; treat fill notional as proxy
const HOT_TICK_FILL_COUNT = 5;

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function nameForAgent(agents: AgentRow[], id: number): string {
  return agents.find((a) => a.id === id)?.name ?? `Agent #${id}`;
}

/**
 * Detects stream-worthy moments client-side and emits short caption strings.
 * No live LLM calls in v1 (templates only).
 *
 * Triggers:
 *   - fill with notional >= BIG_FILL_NOTIONAL
 *   - promotion / demotion event
 *   - >= HOT_TICK_FILL_COUNT fills inside the same tick window
 */
export function useCommentary(opts: {
  agents: AgentRow[];
  fills: FillEvent[];
  promotions: PromotionEvent[];
  enabled: boolean;
}): { current: Highlight | null; queueSize: number } {
  const { agents, fills, promotions, enabled } = opts;
  const [queue, setQueue] = useState<Highlight[]>([]);
  const seenFillKeys = useRef(new Set<string>());
  const seenPromotionKeys = useRef(new Set<string>());
  const lastHotTickAt = useRef<number>(0);

  // Big-fill detection
  useEffect(() => {
    if (!enabled || fills.length === 0) return;
    const fresh: Highlight[] = [];
    let recentTickFills = 0;
    const now = Date.now();
    for (const f of fills) {
      const key = `${f.ts}-${f.payload.agent_id}-${f.payload.symbol}-${f.payload.qty}-${f.payload.price}`;
      if (seenFillKeys.current.has(key)) continue;
      seenFillKeys.current.add(key);
      const evtAt = new Date(f.ts).getTime();
      if (now - evtAt < 3_000) recentTickFills++;
      const notional = Math.abs(f.payload.qty * f.payload.price);
      if (notional >= BIG_FILL_NOTIONAL) {
        fresh.push({
          id: `fill-${key}`,
          kind: "big_fill",
          text: `${nameForAgent(agents, f.payload.agent_id)} ${f.payload.side}s ${f.payload.qty} ${f.payload.symbol} @ $${f.payload.price.toFixed(2)}`,
          at: now,
        });
      }
    }
    // Hot tick rollup
    if (recentTickFills >= HOT_TICK_FILL_COUNT && now - lastHotTickAt.current > 8_000) {
      lastHotTickAt.current = now;
      fresh.push({
        id: `hot-${now}`,
        kind: "hot_tick",
        text: `Hot tick — ${recentTickFills} fills across the farm.`,
        at: now,
      });
    }
    if (fresh.length) {
      setQueue((prev) => [...prev, ...fresh].slice(-QUEUE_MAX));
    }
  }, [fills, agents, enabled]);

  // Promotion / demotion
  useEffect(() => {
    if (!enabled || promotions.length === 0) return;
    const fresh: Highlight[] = [];
    for (const p of promotions) {
      const key = `${p.ts}-${p.payload.agent_id}-${p.payload.to_rank}`;
      if (seenPromotionKeys.current.has(key)) continue;
      seenPromotionKeys.current.add(key);
      const verb = p.type === "promotion" ? "promoted to" : "demoted to";
      fresh.push({
        id: `prom-${key}`,
        kind: p.type,
        text: `${p.payload.agent_name} ${verb} ${cap(p.payload.to_rank)}.`,
        at: Date.now(),
      });
    }
    if (fresh.length) setQueue((prev) => [...prev, ...fresh].slice(-QUEUE_MAX));
  }, [promotions, enabled]);

  // Drain head of queue every DWELL_MS
  const [current, setCurrent] = useState<Highlight | null>(null);
  useEffect(() => {
    if (current || queue.length === 0) return;
    const head = queue[0]!;
    setCurrent(head);
    const t = setTimeout(() => {
      setCurrent(null);
      setQueue((prev) => prev.slice(1));
    }, DWELL_MS);
    return () => clearTimeout(t);
  }, [current, queue]);

  return { current, queueSize: queue.length };
}
