// Live-data variant of useVodMock — pulls AgentRoster, equity, fills
// feed, and (when available) a session's manifest + beats from the
// backend. Powers the new "data source" pill in the VOD studio's
// header: the operator can flip every surface (BeatPicker, Pipeline,
// Session, Episode) between the prototype mock and this live view.
//
// Scope (round 1): only the surfaces that the backend already has
// data for. Pipeline + Episode stay mock-only until the autonomy
// team lands the db-backed run state.
//
// Falls back to `useVodMock` on ANY error so a flapping backend
// never blocks the operator from the rest of the studio.
//
// Manual QA (the web package has no test framework — keep these
// steps in a code-review checklist):
//   1. Backend up on http://127.0.0.1:8000 + a session with
//      manifest.json + beats.json + clips/ written.
//   2. Studio header shows a "live" pill (green dot) when toggled.
//   3. BeatPicker shows beats from the session's beats.json
//      (NOT the 13-beat mock fixture).
//   4. PipelineBoard shows live pipeline run state if a run is
//      in flight, otherwise the mock fixture.
//   5. Toggle the pill off — every surface reverts to the mock.
//   6. Kill the backend, refresh, toggle the pill on — the studio
//      must fall back to mock + a non-blocking error indicator.
//
// Type contract: returns a `VodLiveData` that extends `VodMock` so
// every consumer that already accepts `useVodMock()` accepts
// `useVodLiveData()` without any props change.

import { useMemo } from "react";
import useSWR from "swr";
import { api, type AgentRow, type LlmStats, type AccountSummary, type DailyPnlPoint } from "../api";
import { useEventFeed } from "../hooks/useEventFeed";
import { officeDisplay, officeInitials, VOD_STRATEGIES, VOD_STRATEGY_LABEL } from "./data";
import type {
  Agent,
  Beat,
  DaySummary,
  PipelineNode,
  StrategyBucket,
  StrategyRollup,
} from "./types";
import type { VodMock } from "./useVodMock";

const REFRESH_MS = 5_000;

// Backend strategy strings -> VOD studio's 8-bucket union. Mirrors
// the mapping useVodSessionLive.ts does but with the full 8-bucket
// view. The "momentum" bucket is reserved for the legacy
// momentum_sma20 alias; live agents are bucketed to momentum_12_1.
function mapStrategy(s: string): StrategyBucket {
  if (s.includes("llm")) return "llm";
  if (s.includes("lstm")) return "lstm";
  if (s.includes("momentum_12_1") || s === "momentum_12_1") return "momentum_12_1";
  if (s.includes("bb") || s === "mean_reversion_bb") return "mean_reversion_bb";
  if (s.includes("rsi2") || s === "rsi2") return "rsi2";
  if (s.includes("donchian") || s === "donchian_breakout") return "donchian_breakout";
  if (s.includes("pairs") || s === "pairs_zscore") return "pairs_zscore";
  // Catch-all: any momentum-family strategy we don't have a dedicated
  // bucket for lands in the legacy "momentum" slot. Pre-0.7 rows
  // (strategy="momentum_sma20") land here.
  return "momentum";
}

function displayFromName(name: string): string {
  const [a = "", b = ""] = name.split("_");
  if (!a) return name;
  const cap = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : "");
  return b ? `${cap(a)} ${cap(b)}` : cap(a);
}

function initialsFromName(name: string): string {
  const [a = "", b = ""] = name.split("_");
  return ((a[0] ?? "") + (b[0] ?? "?")).toUpperCase();
}

// Beat shape is the studio's 12-kind list; raw beats come from the
// detector's JSON which uses the same kind strings. We adapt on the
// way in.
function mapBeat(raw: Record<string, unknown>, idx: number): Beat {
  const t = String(raw.t ?? "");
  const headline = String(raw.headline ?? "");
  const sub = String(raw.sub ?? "");
  const kind = String(raw.kind ?? "open") as Beat["kind"];
  // The detector's `t` is an ISO datetime; the studio wants an
  // HH:MM-style string. Parse with the local timezone and reformat.
  let displayT = t;
  try {
    const d = new Date(t);
    if (!isNaN(d.getTime())) {
      displayT = d.toLocaleTimeString("en-US", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
        timeZone: "America/New_York",
      });
    }
  } catch {
    // keep the raw value
  }
  return {
    id: String(raw.id ?? `b_live_${idx}`),
    t: displayT,
    tMs: idx * 60_000,  // 1 minute per beat as a stand-in clock
    kind,
    score: Number(raw.score ?? 0.5),
    scene: String(raw.scene_hint ?? "hero"),
    headline,
    sub,
    duration: Number(raw.duration_sec ?? 20),
    refs: Array.isArray(raw.event_refs)
      ? raw.event_refs.map((r: unknown) => String(r))
      : [],
    agents: Array.isArray(raw.agent_ids)
      ? raw.agent_ids.map((a: unknown) => Number(a))
      : [],
    selected: true,
  };
}

function makeAgents(rows: AgentRow[]): Agent[] {
  return rows.map((a) => {
    const pnl = a.realized_pnl + a.unrealized_pnl;
    const strategy = mapStrategy(a.strategy);
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
  strategyRollup: Record<string, StrategyRollup> | null,
): DaySummary {
  const allocated = agents.length * 1000;
  const totalEquity =
    acct?.total_equity ?? allocated + agents.reduce((s, a) => s + a.pnl, 0);
  const totalPnl = totalEquity - allocated;
  const byStrategy = {} as Record<StrategyBucket, StrategyRollup>;
  for (const s of VOD_STRATEGIES) {
    if (strategyRollup && strategyRollup[VOD_STRATEGY_LABEL[s]]) {
      const r = strategyRollup[VOD_STRATEGY_LABEL[s]]!;
      byStrategy[s] = {
        agents: r.agents,
        equity: r.equity,
        pnl: r.pnl,
        pnlPct: r.pnlPct,
        fills: r.fills,
      };
      continue;
    }
    // Fallback: synthesise from the live agents so the strategy panel
    // is never empty just because the session's manifest wasn't
    // loaded yet.
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
    llmSpend: 0,
  };
}

export type LiveStatus = "loading" | "ready" | "error";

export type VodLiveData = VodMock & {
  liveStatus: LiveStatus;
  liveError: string | null;
  /** Real equity points to plot in the chart, oldest -> newest. */
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
  /** The session id the studio is currently streaming. */
  liveSessionId: string;
};

function useLiveSessionId(): string {
  // Synthesise a session id from today's ET date so the studio has
  // something to show. Once the autonomy team exposes a
  // `/sessions/current` endpoint, swap this for that fetch.
  return useMemo(() => {
    const d = new Date();
    const date = d.toISOString().slice(0, 10);
    return `s_${date}_live`;
  }, []);
}

export function useVodLiveData(sessionId?: string): VodLiveData {
  const liveSessionId = useLiveSessionId();
  const sid = sessionId ?? liveSessionId;

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

  const feed = useEventFeed({ mutateAgents, mutatePnl });

  // Beats for the live session. The autonomy team owns the
  // /vod/{id}/beats endpoint, so the live URL is best-effort: on
  // 404 we get an error and the consumer falls back to the mock
  // beats. Once the endpoint is live this should hit cleanly.
  const { data: liveBeats, error: beatsErr } = useSWR<unknown[]>(
    sid ? `vod-beats-${sid}` : null,
    async () => {
      const r = await fetch(`/vod/${encodeURIComponent(sid)}/beats`);
      if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
      return (await r.json()) as unknown[];
    },
    { refreshInterval: REFRESH_MS * 2 },
  );

  // Strategy rollup. Lives on the manifest right now; the autonomy
  // team could expose it via /vod/{id}/manifest/strategy-rollup but
  // the manifest.json fetch isn't a backend endpoint either. We try
  // a best-effort fetch and fall back to a synthesised view.
  const { data: liveManifest } = useSWR<{ strategy_rollup?: Record<string, StrategyRollup> } | null>(
    sid ? `vod-manifest-${sid}` : null,
    async () => {
      const r = await fetch(`/vod/${encodeURIComponent(sid)}/manifest`);
      if (!r.ok) return null;
      return (await r.json()) as { strategy_rollup?: Record<string, StrategyRollup> };
    },
    { refreshInterval: REFRESH_MS * 6, errorRetryCount: 1 },
  );

  const renderTick = 0;
  const acct = feed.account ?? account ?? null;
  const lastTickIso = feed.lastTick?.ts ?? acct?.last_tick_at ?? null;

  const agents = useMemo(() => (agentRows ? makeAgents(agentRows) : []), [agentRows]);

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

  // Beats: live if the endpoint returned a list, otherwise empty
  // (we let the consumer decide to fall back to the mock).
  const beats: Beat[] = useMemo(() => {
    if (!Array.isArray(liveBeats)) return [];
    return liveBeats.map((b, i) => mapBeat(b as Record<string, unknown>, i));
  }, [liveBeats]);

  const summary = useMemo(
    () =>
      makeSummary(
        agents,
        acct,
        llmStats,
        liveFills.length,
        liveManifest?.strategy_rollup ?? null,
      ),
    [agents, acct, llmStats, liveFills.length, liveManifest],
  );

  const err = accErr || agErr || beatsErr;
  const liveStatus: LiveStatus = err
    ? "error"
    : agentRows && acct
      ? "ready"
      : "loading";
  const liveError = err ? (err as Error).message : null;

  // Empty placeholders for fields the live backend doesn't yet provide.
  const pipeline: PipelineNode[] = [];
  const selectedBeats: Set<string> = new Set(beats.map((b) => b.id));

  return {
    sessionDate: sid.slice(2, 12),
    sessionLabel: `Live session ${sid}`,
    sessionId: sid,
    episodeNumber: pnlDaily?.length ?? 0,
    agents,
    beats,
    selectedBeats,
    toggleBeat: () => {},
    totalDuration: 0,
    pipeline,
    renderProgress: 0,
    renderTick,
    summary,
    // 0.10.0 — Intern Watch + Rivalry Week surfaces. The live
    // data hook currently returns empty arrays; the future
    // /vod/{id}/extras fetch (or a direct manifest read) will
    // populate these. The surfaces fall back to a synthetic
    // head-to-head when empty so they stay useful in the
    // meantime.
    lowest_ranks: [],
    rivalries: [],
    liveStatus,
    liveError,
    equityCurve,
    liveFills,
    lastTickIso,
    liveSessionId: sid,
  };
}
