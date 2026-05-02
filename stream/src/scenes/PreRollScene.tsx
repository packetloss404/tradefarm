import { useEffect } from "react";
import { motion } from "framer-motion";
import type { StreamSnapshot } from "../hooks/useStreamData";

function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

/**
 * Splash card shown for `durationSec` seconds when the broadcast app boots,
 * then fades into the rotator. Length is configurable via the Admin
 * overlay; setting it to 0 skips the pre-roll entirely.
 */
export function PreRollScene({
  snapshot,
  durationSec,
  onComplete,
}: {
  snapshot: StreamSnapshot;
  durationSec: number;
  onComplete: () => void;
}) {
  useEffect(() => {
    const ms = Math.max(500, durationSec * 1000);
    const t = setTimeout(onComplete, ms);
    return () => clearTimeout(t);
  }, [durationSec, onComplete]);

  const today = new Date();
  const dateStr = today.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  const dayN = Math.max(1, snapshot.pnlDaily.length);
  const equity = snapshot.account?.total_equity ?? 0;
  const yesterdayClose =
    snapshot.pnlDaily.length >= 2
      ? snapshot.pnlDaily[snapshot.pnlDaily.length - 2]?.equity ?? null
      : null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute inset-0 flex flex-col items-center justify-center bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 text-zinc-100 overflow-hidden"
    >
      {/* Subtle radial glow behind the wordmark */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1200px] h-[1200px] rounded-full bg-emerald-500/10 blur-3xl" />
      </div>

      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.1 }}
        className="relative z-10 flex flex-col items-center"
      >
        <img src="/favicon.svg" alt="" className="h-24 w-24 mb-4 opacity-90" />
        <h1 className="text-[148px] font-bold tracking-tight leading-none">
          Trade<span className="text-(--color-profit)">Farm</span>
        </h1>
        <h2 className="text-3xl text-zinc-400 mt-3 font-mono">
          Day {dayN} · {dateStr}
        </h2>

        <div className="grid grid-cols-3 gap-16 mt-16">
          <Stat label="Agents" value={snapshot.agents.length.toString()} />
          <Stat label="Equity" value={`$${fmtUsd(equity)}`} />
          <Stat
            label="Yesterday's Close"
            value={yesterdayClose != null ? `$${fmtUsd(yesterdayClose)}` : "—"}
          />
        </div>

        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 0.6 }}
          transition={{ duration: 1.2, delay: 0.6 }}
          className="mt-20 text-zinc-500 font-mono uppercase tracking-[0.3em] text-sm"
        >
          Live broadcast starting…
        </motion.div>
      </motion.div>

      {/* Bottom progress bar — drains over the duration */}
      <motion.div
        initial={{ width: "100%" }}
        animate={{ width: 0 }}
        transition={{ duration: durationSec, ease: "linear" }}
        className="absolute bottom-0 left-0 h-1 bg-emerald-500/60"
      />
    </motion.div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col items-center gap-2">
      <span className="text-[11px] uppercase tracking-[0.25em] text-zinc-500 font-mono">
        {label}
      </span>
      <span className="text-5xl font-semibold tabular-nums">{value}</span>
    </div>
  );
}
