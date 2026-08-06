// 0.19.0 — persistent LLM-decision feed sidebar.
//
// Renders the last N ``DecisionEntry`` rows from the backend's
// ``RecentDecisionsLedger`` (200-entry ring buffer, served via
// ``GET /api/decisions/recent``). Two refresh paths:
//
// 1. SWR polling at 5s on the HTTP endpoint — covers the "what was
//    the LLM thinking 5 min ago" case where the user has been on
//    another tab.
// 2. WebSocket subscription to the ``agent_decisions_batch`` event
//    — covers the "I'm watching the dashboard" case where freshly
//    arriving decisions should prepend without waiting for the next
//    poll tick.
//
// We dedup on ``tick_id`` so a WS event that overlaps with the next
// poll doesn't double-insert the same row. The cap of 50 displayed
// rows matches the server's default ``limit`` so a re-fetch with
// the same query string is a no-op for the visible state.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import { api, type DecisionEntry } from "../api";
import { useLiveEvents, type LiveEvent, type LiveEventHandler } from "../hooks/useLiveEvents";
import { Panel } from "./Panel";

const VERDICT_TONE: Record<DecisionEntry["verdict"], string> = {
  trade: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  wait: "bg-zinc-700/40 text-zinc-300 border-zinc-700",
};

const BIAS_TONE: Record<string, string> = {
  long: "text-(--color-profit)",
  short: "text-(--color-loss)",
  flat: "text-zinc-400",
};

function fmtAge(iso: string, now: number): string {
  const sec = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}

function fmtStrategy(strategy: string): string {
  // The strategy names in the wire payload are full
  // ("lstm_llm_v1", "momentum_sma20"); for the sidebar we want a
  // short tag. Keep it conservative — anything we don't recognize
  // falls through to a 4-char abbreviation.
  if (strategy === "lstm_llm_v1") return "LSTM+LLM";
  if (strategy === "lstm_v1") return "LSTM";
  if (strategy.startsWith("momentum")) return "MOM";
  if (strategy === "mean_reversion_bb") return "BB";
  if (strategy === "rsi2") return "RSI";
  if (strategy === "donchian_breakout") return "DON";
  if (strategy === "pairs_zscore") return "PAIR";
  return strategy.slice(0, 4).toUpperCase();
}

const DISPLAY_CAP = 50;

export function DecisionFeedSidebar() {
  const [now, setNow] = useState(() => Date.now());
  const [onlyLlm, setOnlyLlm] = useState(false);
  // Local optimistic list — initialized from the SWR fetch, then
  // extended live by the WS subscription. We hold the entries here
  // rather than only on the server so the WS update is a no-round-
  // trip render.
  const [entries, setEntries] = useState<DecisionEntry[]>([]);
  const [totalInLedger, setTotalInLedger] = useState(0);
  const lastTickIdRef = useRef<string | null>(null);

  // Tick the age label every 5s. Lower cadence than RecentFills
  // (1s) because decision entries are at most one per tick (~30s
  // for the orchestrator's default interval) and operators care
  // about the ballpark "this was a few minutes ago" rather than
  // the second-precise age.
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(id);
  }, []);

  const swr = useSWR(
    onlyLlm ? ["decisions-recent", { onlyLlm: true }] : "decisions-recent",
    () => api.decisionsRecent({ limit: DISPLAY_CAP, onlyLlm }),
    {
      refreshInterval: 5000,
      revalidateOnFocus: true,
      keepPreviousData: true,
    },
  );

  // Reconcile the SWR response into our local state. We do this in
  // an effect (not by setting state from render) so a stale render
  // path can't overwrite a fresh WS-merged list.
  useEffect(() => {
    if (!swr.data) return;
    setEntries(swr.data.entries);
    setTotalInLedger(swr.data.total_in_ledger);
  }, [swr.data]);

  // Live updates from the WS bus. Dedupe on tick_id so a race with
  // the next SWR poll can't insert the same row twice.
  const onLiveEvent: LiveEventHandler = useCallback(
    (ev: LiveEvent) => {
      if (ev.type !== "agent_decisions_batch") return;
      const { decisions, tick_id } = ev.payload;
      if (!Array.isArray(decisions) || decisions.length === 0) return;
      if (lastTickIdRef.current === tick_id) return;
      lastTickIdRef.current = tick_id;
      setEntries((prev) => {
        const filtered = onlyLlm
          ? decisions.filter((d) => d.llm_bias || d.llm_stance)
          : decisions;
        // Newest first: prepend filtered, dedup by tick_id+agent_id.
        const seen = new Set(prev.map((e) => `${e.tick_id}:${e.agent_id}`));
        const next = [...prev];
        for (const d of filtered) {
          const key = `${d.tick_id}:${d.agent_id}`;
          if (seen.has(key)) continue;
          seen.add(key);
          next.unshift(d);
        }
        return next.slice(0, DISPLAY_CAP);
      });
      setTotalInLedger((n) => n + filteredCount(decisions, onlyLlm));
    },
    [onlyLlm],
  );
  useLiveEvents(onLiveEvent);

  const visible = useMemo(() => entries.slice(0, DISPLAY_CAP), [entries]);

  return (
    <Panel
      title="Decision Feed"
      right={
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-zinc-500">
            <input
              type="checkbox"
              checked={onlyLlm}
              onChange={(e) => setOnlyLlm(e.target.checked)}
              className="size-3 accent-emerald-500"
            />
            LLM only
          </label>
          <span className="text-[10px] font-mono text-zinc-500">
            {totalInLedger} in ring
          </span>
        </div>
      }
    >
      {swr.isLoading && entries.length === 0 ? (
        <div className="text-xs text-zinc-500 italic">loading…</div>
      ) : visible.length === 0 ? (
        <div className="text-xs text-zinc-500 italic">
          {onlyLlm
            ? "no LLM decisions in the recent ring"
            : "no decisions yet — waiting for the next tick"}
        </div>
      ) : (
        <ul className="space-y-1.5 max-h-[420px] overflow-y-auto pr-1">
          {visible.map((e) => (
            <DecisionRow key={`${e.tick_id}:${e.agent_id}`} entry={e} now={now} />
          ))}
        </ul>
      )}
    </Panel>
  );
}

function filteredCount(decisions: DecisionEntry[], onlyLlm: boolean): number {
  if (!onlyLlm) return decisions.length;
  return decisions.filter((d) => d.llm_bias || d.llm_stance).length;
}

function DecisionRow({ entry: e, now }: { entry: DecisionEntry; now: number }) {
  return (
    <li className="flex items-baseline gap-2 text-xs font-mono">
      <span className="w-16 shrink-0 text-zinc-500" title={e.at}>
        {fmtAge(e.at, now)}
      </span>
      <span className="w-14 shrink-0 truncate text-zinc-400" title={e.agent_name}>
        {e.agent_name}
      </span>
      <span className="w-10 shrink-0 text-zinc-500">{e.symbol ?? "—"}</span>
      <span className="w-12 shrink-0 text-zinc-500">{fmtStrategy(e.strategy)}</span>
      <span
        className={`w-14 shrink-0 rounded-sm border px-1 py-0.5 text-center text-[10px] font-bold ${VERDICT_TONE[e.verdict]}`}
      >
        {e.verdict.toUpperCase()}
      </span>
      {e.llm_stance && e.llm_bias ? (
        <span className={`w-10 shrink-0 ${BIAS_TONE[e.llm_bias] ?? ""}`} title={`llm ${e.llm_stance}`}>
          {e.llm_bias.toUpperCase().slice(0, 1)}
        </span>
      ) : (
        <span className="w-10 shrink-0" />
      )}
      <span className="flex-1 truncate text-zinc-300" title={e.reason}>
        {e.reason}
      </span>
    </li>
  );
}
