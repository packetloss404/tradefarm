import { useMemo } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { AgentDecision } from "../hooks/useStreamCommands";

const STRATEGY_BADGE: Record<string, string> = {
  momentum_sma20: "bg-amber-500/15 text-amber-300 border-amber-500/40",
  lstm_v1: "bg-sky-500/15 text-sky-300 border-sky-500/40",
  lstm_llm_v1: "bg-fuchsia-500/15 text-fuchsia-300 border-fuchsia-500/40",
};

const STRATEGY_SHORT: Record<string, string> = {
  momentum_sma20: "MOM",
  lstm_v1: "LSTM",
  lstm_llm_v1: "LSTM+LLM",
};

const LSTM_ENTRY_THRESH = 0.4;

/**
 * Decision Lab — a scrolling ticker of the most-recent agent decisions.
 *
 * Renders the 12 newest unique-agent rows from the most-recent
 * ``agent_decisions_batch``. WAIT verdicts are intentionally surfaced so a
 * flat day still has visible activity on the broadcast. Aggregate counts
 * (trading / waiting / below LSTM threshold) live in the right rail.
 */
export function DecisionLabScene({
  decisions,
}: {
  decisions: AgentDecision[];
}) {
  // Deduplicate by agent id, newest-first. The wire payload is already
  // single-tick so duplicates shouldn't appear, but be defensive.
  const rows = useMemo<AgentDecision[]>(() => {
    const seen = new Set<number>();
    const out: AgentDecision[] = [];
    for (const d of decisions) {
      if (seen.has(d.agent_id)) continue;
      seen.add(d.agent_id);
      out.push(d);
      if (out.length >= 12) break;
    }
    return out;
  }, [decisions]);

  // Aggregate stats — computed over the *full* batch, not just the visible
  // 12, so the right-rail card reflects "what the whole farm is thinking".
  const stats = useMemo(() => {
    let trading = 0;
    let waiting = 0;
    let belowThresh = 0;
    let withLstm = 0;
    for (const d of decisions) {
      if (d.verdict === "trade") trading += 1;
      else waiting += 1;
      if (d.lstm_max_prob != null) {
        withLstm += 1;
        if (d.lstm_max_prob < LSTM_ENTRY_THRESH) belowThresh += 1;
      }
    }
    return { trading, waiting, belowThresh, withLstm, total: decisions.length };
  }, [decisions]);

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden flex flex-col gap-4">
      <header className="flex items-baseline justify-between">
        <h2 className="text-3xl font-bold tracking-tight">
          DECISION <span className="text-(--color-profit)">LAB</span>
          <span className="ml-3 text-sm font-mono text-zinc-500 uppercase tracking-widest">
            live agent thinking
          </span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          most-recent tick · {decisions.length} agents
        </span>
      </header>

      <div className="flex-1 grid grid-cols-[1fr_280px] gap-5 min-h-0">
        {/* Left rail: scrolling decision feed */}
        <div className="relative overflow-hidden">
          {rows.length === 0 && (
            <div className="text-zinc-600 font-mono text-sm">
              Waiting for the first tick…
            </div>
          )}
          <AnimatePresence initial={false}>
            <div className="flex flex-col gap-1.5">
              {rows.map((d) => (
                <DecisionRow key={`${d.agent_id}-${d.at}`} d={d} />
              ))}
            </div>
          </AnimatePresence>
        </div>

        {/* Right rail: aggregate stats */}
        <StatsCard
          trading={stats.trading}
          waiting={stats.waiting}
          belowThresh={stats.belowThresh}
          withLstm={stats.withLstm}
          total={stats.total}
        />
      </div>
    </div>
  );
}

function DecisionRow({ d }: { d: AgentDecision }) {
  const stratClass = STRATEGY_BADGE[d.strategy] ?? "bg-zinc-700/40 text-zinc-300 border-zinc-700";
  const stratShort = STRATEGY_SHORT[d.strategy] ?? d.strategy;
  const isTrade = d.verdict === "trade";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: -12 }}
      animate={{ opacity: 1, x: 0 }}
      exit={{ opacity: 0, x: 12 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="grid grid-cols-[160px_140px_72px_1fr] gap-3 items-center rounded-md border border-zinc-800 bg-zinc-900/40 px-3 py-2"
    >
      {/* Agent identity */}
      <div className="flex items-center gap-2 min-w-0">
        <span className="font-semibold text-sm truncate">{d.agent_name}</span>
        {d.symbol && (
          <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
            {d.symbol}
          </span>
        )}
      </div>

      {/* LSTM probability bars (or placeholder when momentum-only) */}
      <LstmBars probs={d.lstm_probs} />

      {/* Strategy badge + verdict pill stacked */}
      <div className="flex flex-col gap-1 items-start">
        <span
          className={`px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider rounded border ${stratClass}`}
        >
          {stratShort}
        </span>
        <span
          className={`px-1.5 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider rounded border ${
            isTrade
              ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
              : "bg-zinc-700/40 text-zinc-400 border-zinc-700"
          }`}
        >
          {isTrade ? "TRADE" : "WAIT"}
        </span>
      </div>

      {/* Reason — small mono, single line clipped with ellipsis */}
      <p className="text-[11px] font-mono text-zinc-400 truncate">{d.reason}</p>
    </motion.div>
  );
}

function LstmBars({ probs }: { probs: [number, number, number] | null }) {
  // Backend regression could ship a 2- or 4-element array without TypeScript
  // catching it (types are erased). Refuse to render rather than produce a
  // broken bar layout.
  if (probs == null || probs.length !== 3) {
    return (
      <span className="text-[10px] font-mono italic text-zinc-600">— no lstm —</span>
    );
  }
  // probs is [down, flat, up] on the wire; render UP / FLAT / DOWN labels
  // bottom-to-top isn't worth the complexity here — keep it left-to-right
  // matching the source order so audience eyes can map "left bar = down".
  const labels: [string, string, string] = ["DN", "FLAT", "UP"];
  const colors: [string, string, string] = [
    "bg-rose-500/80",
    "bg-zinc-500/70",
    "bg-emerald-500/80",
  ];
  return (
    <div className="flex items-center gap-1">
      {probs.map((p, i) => (
        <div key={i} className="flex-1 min-w-0">
          <div className="h-1.5 bg-zinc-900 rounded">
            <div
              className={`h-full rounded ${colors[i]}`}
              style={{ width: `${Math.max(0, Math.min(1, p)) * 100}%` }}
            />
          </div>
          <div className="flex justify-between text-[8px] text-zinc-500 font-mono mt-0.5">
            <span>{labels[i]}</span>
            <span className="tabular-nums">{(p * 100).toFixed(0)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function StatsCard({
  trading,
  waiting,
  belowThresh,
  withLstm,
  total,
}: {
  trading: number;
  waiting: number;
  belowThresh: number;
  withLstm: number;
  total: number;
}) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-4 flex flex-col gap-3 h-full">
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
        This tick
      </div>
      <StatRow
        label="trading"
        value={trading}
        total={total}
        tone="profit"
      />
      <StatRow
        label="waiting"
        value={waiting}
        total={total}
        tone="neutral"
      />
      <div className="border-t border-zinc-800 my-1" />
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
        LSTM gate
      </div>
      <StatRow
        label={`below ${LSTM_ENTRY_THRESH.toFixed(2)}`}
        value={belowThresh}
        total={withLstm}
        tone="loss"
      />
      <div className="mt-auto text-[10px] font-mono text-zinc-600 leading-snug">
        Agents wait when LSTM max-prob is below {LSTM_ENTRY_THRESH.toFixed(2)}.
        On flat days, this is most of them — and that&apos;s by design.
      </div>
    </div>
  );
}

function StatRow({
  label,
  value,
  total,
  tone,
}: {
  label: string;
  value: number;
  total: number;
  tone: "profit" | "loss" | "neutral";
}) {
  const pct = total > 0 ? (value / total) * 100 : 0;
  const toneClass =
    tone === "profit"
      ? "text-(--color-profit)"
      : tone === "loss"
        ? "text-(--color-loss)"
        : "text-zinc-300";
  const barClass =
    tone === "profit"
      ? "bg-emerald-500/70"
      : tone === "loss"
        ? "bg-rose-500/70"
        : "bg-zinc-500/60";

  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-mono uppercase tracking-wide text-zinc-400">
          {label}
        </span>
        <span className={`text-lg font-bold tabular-nums ${toneClass}`}>
          {value}
        </span>
      </div>
      <div className="h-1.5 bg-zinc-900 rounded">
        <div
          className={`h-full rounded ${barClass}`}
          style={{ width: `${Math.max(0, Math.min(100, pct)).toFixed(1)}%` }}
        />
      </div>
    </div>
  );
}
