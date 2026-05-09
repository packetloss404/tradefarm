import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRow, AccountSummary } from "../../shared/api";
import type { FillEvent, PromotionEvent, StreamSnapshot } from "../../hooks/useStreamData";
import type { StrategyKey } from "./tokens";

/** Per-agent rolling sparkline buffer length. */
const SPARK_LEN = 32;

/* -------------------------------------------------------------------------- *
 * View-model types — mirror the shapes the V1 design components were written
 * against. Anything internal-to-the-broadcast lives here.
 * -------------------------------------------------------------------------- */

export type V1Agent = {
  id: number;
  name: string;
  initials: string;
  strategy: StrategyKey;
  status: "profit" | "loss" | "trading" | "waiting";
  rank: "intern" | "junior" | "senior" | "principal";
  symbol: string | null;
  equity: number;
  pnl: number;
  pnlPct: number;
  sparkline: number[];
};

export type V1Fill = {
  id: string;
  t: number;
  agentId: number;
  agentName: string;
  initials: string;
  strategy: StrategyKey;
  rank: "intern" | "junior" | "senior" | "principal";
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
};

export type V1Promotion = {
  id: string;
  t: number;
  agentId: number;
  agentName: string;
  initials: string;
  fromRank: "intern" | "junior" | "senior" | "principal";
  toRank: "intern" | "junior" | "senior" | "principal";
  direction: "up" | "down";
  reason: string;
};

export type V1Account = {
  totalEquity: number;
  allocated: number;
  pnl: number;
  pnlPct: number;
  profit: number;
  loss: number;
  waiting: number;
  trading: number;
  tick: number;
};

export type V1ViewModel = {
  agents: V1Agent[];
  fills: V1Fill[];
  promotions: V1Promotion[];
  account: V1Account;
};

/* -------------------------------------------------------------------------- *
 * Mapping helpers
 * -------------------------------------------------------------------------- */

const RANKS_ORDER = ["intern", "junior", "senior", "principal"] as const;
type RankKey = (typeof RANKS_ORDER)[number];

function strategyKey(s: string): StrategyKey {
  // Backend uses long-form ids (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`);
  // collapse to the design's three-bucket palette.
  if (s.startsWith("momentum")) return "momentum";
  if (s.startsWith("lstm_llm")) return "llm";
  return "lstm";
}

function rankKey(r: AgentRow["rank"]): RankKey {
  if (r && (RANKS_ORDER as readonly string[]).includes(r)) return r as RankKey;
  return "intern";
}

function initialsFromName(name: string, fallbackId: number): string {
  if (!name) return String(fallbackId).padStart(2, "0");
  const parts = name.trim().split(/\s+/);
  if (parts.length === 0 || !parts[0]) return String(fallbackId).padStart(2, "0");
  const a = parts[0]?.[0] ?? "";
  const b = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? "") : (parts[0]?.[1] ?? "");
  return (a + b).toUpperCase();
}

function primarySymbol(a: AgentRow): string | null {
  if (a.symbol) return a.symbol;
  const held = Object.entries(a.positions).find(([, p]) => p.qty !== 0);
  return held ? held[0] : null;
}

function totalPnl(a: AgentRow): number {
  return a.realized_pnl + a.unrealized_pnl;
}

function statusFor(a: AgentRow, p: number): V1Agent["status"] {
  // Prefer the backend's classification; fall back to a P&L threshold for
  // the design's brighter green/red bands.
  if (p > 8) return "profit";
  if (p < -8) return "loss";
  if (a.status === "trading" || a.status === "waiting") return a.status;
  return primarySymbol(a) ? "trading" : "waiting";
}

/* -------------------------------------------------------------------------- *
 * Sparkline buffer — the backend doesn't push per-agent equity history, so we
 * build one client-side. On every snapshot the latest equity for each agent
 * is appended; oldest dropped at SPARK_LEN.
 * -------------------------------------------------------------------------- */

function useSparklineBuffers(agents: AgentRow[]): Map<number, number[]> {
  const bufRef = useRef<Map<number, number[]>>(new Map());
  // Bump this counter on every append so dependent useMemo recomputes.
  const [, force] = useState<number>(0);

  // Track equity changes per agent; only append when the value moves so we
  // don't fill the buffer with identical samples on idle ticks.
  const lastSeenRef = useRef<Map<number, number>>(new Map());

  useEffect(() => {
    let changed = false;
    const liveIds = new Set<number>();
    for (const a of agents) {
      liveIds.add(a.id);
      const eq = a.equity;
      const last = lastSeenRef.current.get(a.id);
      if (last !== eq) {
        lastSeenRef.current.set(a.id, eq);
        const buf = bufRef.current.get(a.id) ?? [];
        const next = buf.length >= SPARK_LEN ? [...buf.slice(1), eq] : [...buf, eq];
        bufRef.current.set(a.id, next);
        changed = true;
      }
    }
    // Garbage-collect buffers for agents that disappeared from the snapshot.
    // Without this, a long-running stream with agent churn would leak entries
    // into both maps indefinitely.
    for (const id of bufRef.current.keys()) {
      if (!liveIds.has(id)) {
        bufRef.current.delete(id);
        lastSeenRef.current.delete(id);
        changed = true;
      }
    }
    if (changed) force((n) => n + 1);
  }, [agents]);

  return bufRef.current;
}

/* -------------------------------------------------------------------------- *
 * Top-level adapter hook
 * -------------------------------------------------------------------------- */

export function useBroadcastViewModel(snapshot: StreamSnapshot): V1ViewModel {
  const sparklines = useSparklineBuffers(snapshot.agents);

  const agents = useMemo<V1Agent[]>(() => {
    return snapshot.agents.map((a) => {
      const pnl = totalPnl(a);
      // Seed pnlPct as pnl over the per-agent default $1000 allocation. The
      // backend doesn't expose initial allocation; keep this in sync if/when
      // it does.
      const pnlPct = pnl / 10; // pnl / 1000 * 100
      const buffer = sparklines.get(a.id) ?? [];
      // Always include the current equity as the right-most sample so even
      // freshly-mounted agents have something to draw.
      const spark = buffer.length === 0 ? [a.equity, a.equity] : buffer;
      return {
        id: a.id,
        name: a.name,
        initials: initialsFromName(a.name, a.id),
        strategy: strategyKey(a.strategy),
        status: statusFor(a, pnl),
        rank: rankKey(a.rank),
        symbol: primarySymbol(a),
        equity: a.equity,
        pnl,
        pnlPct,
        sparkline: spark,
      };
    });
  }, [snapshot.agents, sparklines]);

  // Build a lookup so fill/promotion enrichment doesn't re-scan agents on each
  // event row.
  const byId = useMemo(() => {
    const m = new Map<number, V1Agent>();
    for (const a of agents) m.set(a.id, a);
    return m;
  }, [agents]);

  const fills = useMemo<V1Fill[]>(() => {
    return snapshot.fills.map((ev) => fillToV1(ev, byId));
  }, [snapshot.fills, byId]);

  const promotions = useMemo<V1Promotion[]>(() => {
    return snapshot.promotions.map((ev) => promotionToV1(ev, byId));
  }, [snapshot.promotions, byId]);

  const account = useMemo<V1Account>(() => buildAccount(snapshot.account, agents, snapshot.lastTick), [
    snapshot.account,
    agents,
    snapshot.lastTick,
  ]);

  return { agents, fills, promotions, account };
}

function fillToV1(ev: FillEvent, byId: Map<number, V1Agent>): V1Fill {
  const p = ev.payload;
  const a = byId.get(p.agent_id);
  return {
    id: ev.ts + ":" + p.agent_id + ":" + p.symbol,
    t: new Date(ev.ts).getTime(),
    agentId: p.agent_id,
    agentName: a?.name ?? `agent ${p.agent_id}`,
    initials: a?.initials ?? initialsFromName(a?.name ?? "", p.agent_id),
    strategy: a?.strategy ?? "momentum",
    rank: a?.rank ?? "intern",
    symbol: p.symbol,
    side: p.side,
    qty: p.qty,
    price: p.price,
  };
}

function promotionToV1(ev: PromotionEvent, byId: Map<number, V1Agent>): V1Promotion {
  const p = ev.payload;
  const a = byId.get(p.agent_id);
  const fromIdx = RANKS_ORDER.indexOf(p.from_rank);
  const toIdx = RANKS_ORDER.indexOf(p.to_rank);
  const direction: "up" | "down" = toIdx > fromIdx ? "up" : "down";
  return {
    id: ev.ts + ":" + p.agent_id,
    t: new Date(ev.ts).getTime(),
    agentId: p.agent_id,
    agentName: p.agent_name || a?.name || `agent ${p.agent_id}`,
    initials: a?.initials ?? initialsFromName(p.agent_name, p.agent_id),
    fromRank: p.from_rank,
    toRank: p.to_rank,
    direction,
    reason: p.reason,
  };
}

function buildAccount(
  account: AccountSummary | null,
  agents: V1Agent[],
  lastTick: StreamSnapshot["lastTick"],
): V1Account {
  const totalEquity = account?.total_equity ?? agents.reduce((s, a) => s + a.equity, 0);
  const allocated = Math.max(1, agents.length) * 1000;
  const pnl = totalEquity - allocated;
  const pnlPct = (pnl / allocated) * 100;
  const profit = account?.profit_ai ?? agents.filter((a) => a.status === "profit").length;
  const loss = account?.loss_ai ?? agents.filter((a) => a.status === "loss").length;
  const waiting = account?.waiting_ai ?? agents.filter((a) => a.status === "waiting").length;
  const trading = Math.max(0, agents.length - profit - loss - waiting);
  // Use the tick event count as a monotonic cadence cue for animation pulses.
  const tick = lastTick ? new Date(lastTick.ts).getTime() : 0;
  return { totalEquity, allocated, pnl, pnlPct, profit, loss, waiting, trading, tick };
}
