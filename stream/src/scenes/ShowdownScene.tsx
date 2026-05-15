import { useMemo } from "react";
import { motion } from "framer-motion";
import type { AgentRow, Rank } from "../shared/api";
import type { StreamSnapshot } from "../hooks/useStreamData";

const RANK_COLOR: Record<Rank | "unranked", string> = {
  intern: "text-zinc-400",
  junior: "text-sky-400",
  senior: "text-amber-400",
  principal: "text-emerald-400",
  unranked: "text-zinc-600",
};

function fmtUsd(n: number, frac = 0): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  });
}

function fmtSign(n: number, frac = 0): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toLocaleString("en-US", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  })}`;
}

function totalOf(a: AgentRow): number {
  return a.realized_pnl + a.unrealized_pnl;
}

type Matchup = {
  leader: AgentRow;
  challenger: AgentRow;
  gap: number;
};

function pickMatchup(agents: AgentRow[]): Matchup | null {
  if (agents.length < 2) return null;

  const active = agents.filter((a) => a.status !== "waiting");
  const pool = active.length >= 2 ? active : agents;

  const sorted = [...pool].sort((a, b) => b.equity - a.equity);
  const leader = sorted[0];
  if (!leader) return null;

  let challenger: AgentRow | null = null;
  let bestGap = Number.POSITIVE_INFINITY;
  for (const a of sorted) {
    if (a.id === leader.id) continue;
    const gap = Math.abs(a.equity - leader.equity);
    if (gap < bestGap) {
      bestGap = gap;
      challenger = a;
    }
  }

  if (!challenger) {
    const fallback = sorted[1];
    if (!fallback) return null;
    challenger = fallback;
    bestGap = Math.abs(fallback.equity - leader.equity);
  }

  return { leader, challenger, gap: bestGap };
}

const sideVariants = {
  hidden: (dir: "left" | "right") => ({
    opacity: 0,
    x: dir === "left" ? -60 : 60,
  }),
  visible: { opacity: 1, x: 0, transition: { duration: 0.55, ease: [0.16, 1, 0.3, 1] } },
};

const vsVariants = {
  hidden: { opacity: 0, scale: 0.4 },
  visible: {
    opacity: 1,
    scale: 1,
    transition: { delay: 0.25, duration: 0.6, type: "spring" as const, stiffness: 180 },
  },
};

const badgeVariants = {
  hidden: { opacity: 0, y: -16 },
  visible: {
    opacity: 1,
    y: 0,
    transition: { delay: 0.5, duration: 0.45, ease: [0.16, 1, 0.3, 1] },
  },
};

export function ShowdownScene({ snapshot }: { snapshot: StreamSnapshot }) {
  const matchup = useMemo(() => pickMatchup(snapshot.agents), [snapshot.agents]);

  if (!matchup) {
    return (
      <div className="absolute inset-0 flex items-center justify-center">
        <div className="text-zinc-500 font-mono text-sm uppercase tracking-widest">
          Showdown loading…
        </div>
      </div>
    );
  }

  const { leader, challenger, gap } = matchup;

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden flex flex-col">
      <header className="flex items-baseline justify-between mb-5">
        <h2 className="text-3xl font-bold tracking-tight">
          Show<span className="text-(--color-profit)">down</span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          head-to-head · gap ${fmtUsd(gap)}
        </span>
      </header>

      <div className="flex-1 relative grid grid-cols-2 gap-4">
        <ShowdownSide agent={leader} side="left" winner gap={gap} />
        <ShowdownSide agent={challenger} side="right" winner={false} gap={gap} />

        <motion.div
          variants={vsVariants}
          initial="hidden"
          animate="visible"
          className="pointer-events-none absolute inset-y-0 left-1/2 -translate-x-1/2 flex items-center justify-center"
        >
          <div className="relative flex items-center justify-center">
            <div className="absolute inset-0 -m-6 rounded-full bg-zinc-950/80 blur-2xl" />
            <span className="relative font-black text-8xl tracking-tighter bg-gradient-to-br from-zinc-100 to-zinc-500 bg-clip-text text-transparent drop-shadow-[0_0_24px_rgba(0,0,0,0.85)]">
              VS
            </span>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

function ShowdownSide({
  agent,
  side,
  winner,
  gap,
}: {
  agent: AgentRow;
  side: "left" | "right";
  winner: boolean;
  gap: number;
}) {
  const total = totalOf(agent);
  const totalPos = total >= 0;
  const tone = winner
    ? "border-emerald-500/50 bg-emerald-950/30 ring-1 ring-emerald-500/30"
    : "border-rose-500/40 bg-rose-950/20 ring-1 ring-rose-500/20";
  const edgeLabel = winner
    ? gap < 1
      ? "DEAD HEAT"
      : "LEADER"
    : gap < 1
      ? "TIED"
      : "UNDERDOG";
  const edgeTone = winner
    ? "bg-emerald-500/20 text-emerald-300 border-emerald-500/50"
    : "bg-rose-500/20 text-rose-300 border-rose-500/50";

  return (
    <motion.div
      custom={side}
      variants={sideVariants}
      initial="hidden"
      animate="visible"
      className={`relative rounded-2xl border ${tone} p-6 flex flex-col gap-4 overflow-hidden`}
    >
      {winner && (
        <motion.div
          variants={badgeVariants}
          initial="hidden"
          animate="visible"
          className="absolute -top-3 left-1/2 -translate-x-1/2 z-10"
        >
          <div className="rounded-full bg-emerald-500 px-4 py-1 text-[10px] font-mono font-bold uppercase tracking-[0.25em] text-zinc-950 shadow-lg shadow-emerald-900/40">
            ★ Leader
          </div>
        </motion.div>
      )}

      <div className={`flex items-baseline ${side === "left" ? "justify-start" : "justify-end"} gap-2`}>
        <span
          className={`text-[10px] uppercase font-mono tracking-widest ${RANK_COLOR[agent.rank ?? "unranked"]}`}
        >
          {agent.rank ?? "unranked"}
        </span>
        <span className={`px-2 py-0.5 rounded-sm border text-[10px] font-mono font-bold tracking-widest ${edgeTone}`}>
          {edgeLabel}
        </span>
      </div>

      <div className={side === "left" ? "text-left" : "text-right"}>
        <div className="text-4xl font-black tracking-tight truncate">{agent.name}</div>
        <div className="text-[11px] font-mono text-zinc-500 uppercase tracking-wider mt-1">
          {agent.strategy}
          {agent.symbol ? <span className="text-zinc-400"> · {agent.symbol}</span> : null}
        </div>
      </div>

      <div className={`flex flex-col gap-1 ${side === "left" ? "items-start" : "items-end"}`}>
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
          Equity
        </span>
        <span className="text-5xl font-black tabular-nums">
          ${fmtUsd(agent.equity)}
        </span>
      </div>

      <div className={`flex flex-col gap-1 ${side === "left" ? "items-start" : "items-end"}`}>
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
          Day P&amp;L
        </span>
        <span
          className={`text-2xl font-bold tabular-nums ${totalPos ? "text-(--color-profit)" : "text-(--color-loss)"}`}
        >
          {fmtSign(total)} USD
        </span>
      </div>

      <div className="mt-auto flex flex-col gap-1.5">
        <span className="text-[10px] uppercase tracking-widest text-zinc-500 font-mono">
          LSTM read
        </span>
        {agent.last_lstm ? (
          <div className="flex items-center gap-2">
            {agent.last_lstm.probs.map((p, i) => {
              const labels = ["UP", "FLAT", "DN"];
              const colors = ["bg-emerald-500/70", "bg-zinc-500/60", "bg-rose-500/70"];
              return (
                <div key={i} className="flex-1">
                  <div className="h-2 bg-zinc-950 rounded overflow-hidden">
                    <motion.div
                      initial={{ width: 0 }}
                      animate={{ width: `${(p * 100).toFixed(1)}%` }}
                      transition={{ duration: 0.6, delay: 0.4 + i * 0.08 }}
                      className={`h-full ${colors[i]}`}
                    />
                  </div>
                  <div className="flex justify-between text-[9px] text-zinc-500 font-mono mt-0.5">
                    <span>{labels[i]}</span>
                    <span className="tabular-nums">{(p * 100).toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-[11px] text-zinc-600 font-mono italic">no LSTM read yet</div>
        )}
      </div>
    </motion.div>
  );
}
