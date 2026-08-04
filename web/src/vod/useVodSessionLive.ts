// Live-data variant of useVodMock — pulls AgentRoster, equity, fills
// feed, and manifest counters straight from the backend.
//
// Scope: only the bits Session Control actually reads. Pipeline + beats
// stay empty (no real source until the VOD pipeline lands). The other
// three studio surfaces continue to use useVodMock — flipping them to
// "live" would just show empty state.

import { useMemo } from "react";
import useSWR from "swr";
import { api, type AgentRow, type LlmStats, type AccountSummary, type DailyPnlPoint } from "../api";
import { useEventFeed } from "../hooks/useEventFeed";
import { officeDisplay, officeInitials, VOD_STRATEGIES } from "./data";
import type {
  Agent,
  Beat,
  DaySummary,
  PipelineNode,
  Strategy,
  StrategyRollup,
} from "./types";
import type { VodMock } from "./useVodMock";

const REFRESH_MS = 5_000;

// Backend strategy strings (`momentum_sma20`, `lstm_v1`, `lstm_llm_v1`)
// → VOD studio's three-bucket enum.
function mapStrategy(s: string): Strategy {
  if (s.includes("llm")) return "llm";
  if (s.includes("lstm")) return "lstm";
  return "momentum";
}

function displayFromName(name: string): string {
  // Backend names are "first_last"; fall back to title-casing whatever
  // shape we got (covers `trader_NNN` from the defensive fallback).
  const [a = "", b = ""] = name.split("_");
  if (!a) return name;
  const cap = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : "");
  return b ? `${cap(a)} ${cap(b)}` : cap(a);
}

function initialsFromName(name: string): string {
  const [a = "", b = ""] = name.split("_");
  return ((a[0] ?? "") + (b[0] ?? "?")).toUpperCase();
}

function todaySessionId(): { id: string; label: string; date: string } {
  // Synthesize a session id from today's ET date so SessionControl has
  // something to show. Once a real session runner exists, swap this for
  // /sessions/current.
  const d = new Date();
  const date = d.toISOString().slice(0, 10);
  const label = d.toLocaleDateString("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
  const id = `s_${date}_live`;
  return { id, label: `${label} · session ${id}`, date };
}

function makeAgents(rows: AgentRow[]): Agent[] {
  return rows.map((a) => {
    const pnl = a.realized_pnl + a.unrealized_pnl;
    const strategy = mapStrategy(a.strategy);
    // Prefer the backend name when it matches the office roster, but use
    // the name string verbatim — the office helpers expect agent_id and
    // would diverge if the backend ever changes the mapping.
    const display = displayFromName(a.name) || officeDisplay(a.id);
    const initials = initialsFromName(a.name) || officeInitials(a.id);
    return {
      id: a.id,
      name: a.name,
      display,
      initials,
      strategy,
      rank: (a.rank ?? "intern") as Agent["rank"],
      equity: a.equity,
      pnl,
      pnlPct: pnl / 10,
      sparkline: [],
      // Per-agent trade/win counts aren't on /agents; leave 0. The
      // tooltip just reads pnl anyway.
      trades: 0,
      wins: 0,
    };
  });
}

function makeSummary(
  agents: Agent[],
  acct: AccountSummary | null | undefined,
  llmStats: LlmStats | undefined,
  fillCount: number,
): DaySummary {
  const allocated = agents.length * 1000;
  const totalEquity = acct?.total_equity ?? allocated + agents.reduce((s, a) => s + a.pnl, 0);
  const totalPnl = totalEquity - allocated;
  const byStrategy = {} as Record<Strategy, StrategyRollup>;
  for (const s of VOD_STRATEGIES) {
    const list = agents.filter((a) => a.strategy === s);
    const e = list.reduce((x, a) => x + a.equity, 0);
    const p = list.reduce((x, a) => x + a.pnl, 0);
    byStrategy[s] = {
      agents: list.length,
      equity: e,
      pnl: p,
      pnlPct: list.length === 0 ? 0 : (p / (list.length * 1000)) * 100,
      fills: 0,
    };
  }
  const ranked = [...agents].sort((a, b) => b.pnl - a.pnl);
  return {
    totalEquity,
    allocated,
    totalPnl,
    pnlPct: allocated > 0 ? (totalPnl / allocated) * 100 : 0,
    byStrategy,
    topAgents: ranked.slice(0, 5),
    botAgents: ranked.slice(-3).reverse(),
    promotions: 0,
    demotions: 0,
    fillCount,
    decisionCount: llmStats?.total_decisions ?? 0,
    llmCalls: llmStats?.called ?? 0,
    llmSkipped: llmStats?.skipped_low_confidence ?? 0,
    // /llm/stats doesn't expose spend yet — leave at 0 and the panel
    // shows $0.00 rather than a misleading number.
    llmSpend: 0,
  };
}

export type LiveStatus = "loading" | "ready" | "error";

export type VodSessionLive = VodMock & {
  liveStatus: LiveStatus;
  liveError: string | null;
  /** Real equity points to plot in the chart, oldest → newest. */
  equityCurve: number[];
  /** Real fills off the WS, newest first. */
  liveFills: {
    id: string;
    t: string;
    side: "BUY" | "SELL";
    symbol: string;
    qty: number;
    price: number;
    agent: Agent | undefined;
  }[];
  lastTickIso: string | null;
};

export function useVodSessionLive(): VodSessionLive {
  const { data: account, error: accErr } = useSWR<AccountSummary>("vod-account", api.account, {
    refreshInterval: REFRESH_MS,
  });
  const { data: agentRows, error: agErr, mutate: mutateAgents } = useSWR<AgentRow[]>(
    "vod-agents",
    api.agents,
    { refreshInterval: REFRESH_MS },
  );
  const { data: llmStats } = useSWR<LlmStats>("vod-llm-stats", api.llmStats, {
    refreshInterval: REFRESH_MS,
  });
  const { data: pnlDaily, mutate: mutatePnl } = useSWR<DailyPnlPoint[]>(
    "vod-pnl-daily",
    () => api.pnlDaily(30),
    { refreshInterval: REFRESH_MS * 6 },
  );

  // Reuse the dashboard's event feed so we share the single /ws
  // socket. mutators keep agents + pnl in sync on every tick event.
  const feed = useEventFeed({ mutateAgents, mutatePnl });

  // 800ms heartbeat removed: it was driving a global re-render of the
  // studio tree at 1.25 Hz just to power the ET clock's cursor blink.
  // The leaf ETClock component (widgets.tsx) now owns its own 800ms
  // timer. `renderTick` stays in the return so the VodMock shape
  // doesn't drift between the mock and live paths.
  const renderTick = 0;

  const acct = feed.account ?? account ?? null;
  const lastTickIso = feed.lastTick?.ts ?? acct?.last_tick_at ?? null;

  const agents = useMemo(() => (agentRows ? makeAgents(agentRows) : []), [agentRows]);

  // Equity curve: pnl-daily gives one point per day (good for the
  // intraday/multiday range axis), prepended with today's running total
  // so the chart's right edge keeps moving on every tick.
  const equityCurve = useMemo(() => {
    const base = pnlDaily?.map((p) => p.equity) ?? [];
    if (acct) return [...base, acct.total_equity];
    return base;
  }, [pnlDaily, acct]);

  const liveFills = useMemo(() => {
    const byId = new Map(agents.map((a) => [a.id, a]));
    return feed.fills.map((f, i) => ({
      id: `${f.ts}-${i}`,
      t: new Date(f.ts).toLocaleTimeString("en-US", {
        hour12: false,
        timeZone: "America/New_York",
      }).slice(0, 5),
      side: (f.payload.side === "buy" ? "BUY" : "SELL") as "BUY" | "SELL",
      symbol: f.payload.symbol,
      qty: f.payload.qty,
      price: f.payload.price,
      agent: byId.get(f.payload.agent_id),
    }));
  }, [feed.fills, agents]);

  const session = useMemo(todaySessionId, []);
  const summary = useMemo(
    () => makeSummary(agents, acct, llmStats, liveFills.length),
    [agents, acct, llmStats, liveFills.length],
  );

  // Episode number: count of distinct trading days we have pnl for.
  // Naive but better than hardcoding — once a real session runner
  // exists, swap for the manifest's episode counter.
  const episodeNumber = pnlDaily?.length ?? 0;

  const err = accErr || agErr;
  const liveStatus: LiveStatus = err ? "error" : agentRows && acct ? "ready" : "loading";
  const liveError = err ? (err as Error).message : null;

  // Empty placeholders for fields the live backend doesn't yet provide.
  const beats: Beat[] = [];
  const pipeline: PipelineNode[] = [];

  return {
    sessionDate: session.date,
    sessionLabel: session.label,
    sessionId: session.id,
    episodeNumber,
    agents,
    beats,
    selectedBeats: new Set<string>(),
    toggleBeat: () => {},
    totalDuration: 0,
    pipeline,
    renderProgress: 0,
    renderTick,
    summary,
    // live extras consumed by SessionControl when sourceMode === "live"
    liveStatus,
    liveError,
    equityCurve,
    liveFills,
    lastTickIso,
  };
}
