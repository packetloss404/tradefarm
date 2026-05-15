import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import type { PredictionState } from "../hooks/useStreamCommands";

// Backend retires revealed predictions after a grace window — we just render
// whatever is in the map and let server-side state ageing handle eviction.
const MAX_OPTIONS_RENDERED = 3;

type Row = { option: string; votes: number; pct: number };

function buildRows(p: PredictionState): { rows: Row[]; total: number } {
  // We display top-N by vote count rather than the spec's `options` order so
  // the widget is useful for runaway favorites. When tallies are all zero,
  // fall back to spec order so the question still renders nicely on entry.
  const total = Object.values(p.tally).reduce((s, n) => s + n, 0);
  const tallied = (p.options.length > 0 ? p.options : Object.keys(p.tally)).map((option) => ({
    option,
    votes: p.tally[option] ?? 0,
  }));
  tallied.sort((a, b) => b.votes - a.votes || a.option.localeCompare(b.option));
  const top = tallied.slice(0, MAX_OPTIONS_RENDERED);
  const rows: Row[] = top.map((r) => ({
    option: r.option,
    votes: r.votes,
    pct: total > 0 ? (r.votes / total) * 100 : 0,
  }));
  return { rows, total };
}

/**
 * Stacked predictions overlay. Sits in the bottom-left of the scene body just
 * above the chat strip. Renders all currently-tracked predictions whose state
 * we haven't yet retired — when a prediction reveals, it stays on-screen for
 * a short grace window so the audience sees the result before it leaves.
 */
export function PredictionsWidget({
  predictions,
}: {
  predictions: Record<string, PredictionState>;
}) {
  const visible = useMemo(() => {
    const list = Object.values(predictions);
    // Sort: open first, then locked, then revealed (most recently revealed
    // surfaces last so the eye lands on it). Within a status, alphabetic by
    // id for stability — the backend never reuses ids so this is fine.
    const order: Record<PredictionState["status"], number> = {
      open: 0,
      locked: 1,
      revealed: 2,
    };
    return list
      .slice()
      .sort((a, b) => order[a.status] - order[b.status] || a.id.localeCompare(b.id));
  }, [predictions]);

  if (visible.length === 0) return null;

  return (
    <div className="absolute left-3 bottom-[330px] z-[21] w-[320px] pointer-events-none select-none space-y-2">
      <AnimatePresence initial={false}>
        {visible.map((p) => (
          <PredictionRow key={p.id} prediction={p} />
        ))}
      </AnimatePresence>
    </div>
  );
}

function PredictionRow({ prediction }: { prediction: PredictionState }) {
  const { rows, total } = buildRows(prediction);
  const isOpen = prediction.status === "open";
  const isLocked = prediction.status === "locked";
  const isRevealed = prediction.status === "revealed";

  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 8, scale: 0.98 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: -8, scale: 0.98 }}
      transition={{ duration: 0.3, ease: [0.22, 1, 0.36, 1] }}
      className="rounded-md bg-zinc-950/85 backdrop-blur-md border border-zinc-800/80 shadow-2xl px-3 py-2"
    >
      <div className="flex items-start justify-between gap-2 mb-2">
        <span className="text-[11px] font-semibold text-zinc-100 leading-snug">
          {prediction.question}
        </span>
        <StatusPill status={prediction.status} />
      </div>

      <div className="space-y-1.5">
        {rows.map((r) => {
          const isWinner = isRevealed && prediction.winningOption === r.option;
          return (
            <PredictionBar
              key={r.option}
              option={r.option}
              votes={r.votes}
              pct={r.pct}
              frozen={isLocked || isRevealed}
              winner={isWinner}
            />
          );
        })}
      </div>

      <div className="mt-1.5 flex items-center justify-between font-mono text-[9px] text-zinc-500 tabular-nums">
        <span>
          {isOpen
            ? "vote in chat"
            : isLocked
              ? "voting closed"
              : prediction.winningOption
                ? `winner: ${prediction.winningOption}`
                : "revealed"}
        </span>
        <span>{total} votes</span>
      </div>

    </motion.div>
  );
}

function StatusPill({ status }: { status: PredictionState["status"] }) {
  if (status === "open") {
    return (
      <span className="shrink-0 flex items-center gap-1 px-1.5 py-px rounded-sm bg-rose-500/15 text-rose-400 text-[9px] font-mono uppercase tracking-wider">
        <motion.span
          aria-hidden
          animate={{ opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 1.4, repeat: Infinity, ease: "easeInOut" }}
          className="h-1 w-1 rounded-full bg-rose-500"
        />
        LIVE
      </span>
    );
  }
  if (status === "locked") {
    return (
      <span className="shrink-0 flex items-center gap-1 px-1.5 py-px rounded-sm bg-zinc-800/80 text-zinc-400 text-[9px] font-mono uppercase tracking-wider">
        <LockIcon /> LOCKED
      </span>
    );
  }
  return (
    <span className="shrink-0 flex items-center gap-1 px-1.5 py-px rounded-sm bg-emerald-500/15 text-(--color-profit) text-[9px] font-mono uppercase tracking-wider">
      <span aria-hidden>✓</span> REVEALED
    </span>
  );
}

function LockIcon() {
  return (
    <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="currentColor" aria-hidden>
      <path d="M3 5V3.5a3 3 0 1 1 6 0V5h.5A1.5 1.5 0 0 1 11 6.5v3A1.5 1.5 0 0 1 9.5 11h-7A1.5 1.5 0 0 1 1 9.5v-3A1.5 1.5 0 0 1 2.5 5H3Zm1.25 0h3.5V3.5a1.75 1.75 0 0 0-3.5 0V5Z" />
    </svg>
  );
}

function PredictionBar({
  option,
  votes,
  pct,
  frozen,
  winner,
}: {
  option: string;
  votes: number;
  pct: number;
  frozen: boolean;
  winner: boolean;
}) {
  return (
    <div className="relative">
      <div className="flex items-center justify-between mb-0.5 font-mono text-[10px] tabular-nums">
        <span
          className={`truncate pr-2 ${
            winner
              ? "text-(--color-profit) font-semibold"
              : frozen
                ? "text-zinc-300"
                : "text-zinc-200"
          }`}
        >
          {option}
        </span>
        <span className="text-zinc-500">
          {Math.round(pct)}% <span className="text-zinc-600">· {votes}</span>
        </span>
      </div>
      <div className="relative h-2 rounded-sm bg-zinc-900 overflow-hidden">
        <motion.div
          // Re-key on `frozen` so the bar freezes at its final width when the
          // status flips to locked/revealed and doesn't keep animating from
          // late tally events.
          key={frozen ? "frozen" : "live"}
          initial={{ width: 0 }}
          animate={{ width: `${pct}%` }}
          transition={{ duration: frozen ? 0 : 0.5, ease: [0.22, 1, 0.36, 1] }}
          className={`absolute inset-y-0 left-0 rounded-sm ${
            winner ? "bg-(--color-profit)" : frozen ? "bg-zinc-500" : "bg-emerald-500/60"
          }`}
        />
        {winner && (
          <motion.div
            aria-hidden
            initial={{ opacity: 0 }}
            animate={{ opacity: [0.6, 0, 0.6] }}
            transition={{ duration: 1.6, repeat: Infinity, ease: "easeInOut" }}
            className="absolute inset-y-0 left-0 rounded-sm bg-(--color-profit)/40"
            style={{ width: `${pct}%` }}
          />
        )}
      </div>
    </div>
  );
}
