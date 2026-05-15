import { useEffect, useRef, useState } from "react";
import type { FillEvent, PromotionEvent } from "./useStreamData";
import type { AgentRow } from "../shared/api";
import type { CommentaryState } from "./useStreamCommands";

export type Highlight = {
  id: string;
  kind: "big_fill" | "promotion" | "demotion" | "hot_tick" | "glory" | "commentary";
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
 * Now also accepts server-pushed LLM commentary (`commentary` prop) which
 * preempts any active template highlight — server takes are richer and varied,
 * templates are the fallback when the server has nothing to say.
 *
 * Triggers:
 *   - fill with notional >= BIG_FILL_NOTIONAL
 *   - promotion / demotion event
 *   - >= HOT_TICK_FILL_COUNT fills inside the same tick window
 *   - server-pushed `stream_commentary` (preempts current highlight)
 */
export function useCommentary(opts: {
  agents: AgentRow[];
  fills: FillEvent[];
  promotions: PromotionEvent[];
  enabled: boolean;
  commentary?: CommentaryState | null;
}): { current: Highlight | null; queueSize: number } {
  const { agents, fills, promotions, enabled, commentary } = opts;
  const [queue, setQueue] = useState<Highlight[]>([]);
  const seenFillKeys = useRef(new Set<string>());
  const seenPromotionKeys = useRef(new Set<string>());
  const seenCommentaryIds = useRef(new Set<string>());
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

  // Server commentary preempts whatever is on-screen. We swap `current`
  // directly (no queueing) so the LLM take lands immediately, then dwell it
  // for DWELL_MS the same way templates dwell.
  useEffect(() => {
    if (!enabled || !commentary) return;
    if (seenCommentaryIds.current.has(commentary.id)) return;
    seenCommentaryIds.current.add(commentary.id);
    const hl: Highlight = {
      id: `commentary-${commentary.id}`,
      kind: "commentary",
      text: commentary.text,
      at: Date.now(),
    };
    setCurrent(hl);
    const t = setTimeout(() => setCurrent(null), DWELL_MS);
    return () => clearTimeout(t);
  }, [commentary, enabled]);

  return { current, queueSize: queue.length };
}
