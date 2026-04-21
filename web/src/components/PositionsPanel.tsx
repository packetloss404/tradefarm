import type { AgentRow } from "../api";

type Side = "long" | "short";

function aggregate(agents: AgentRow[], side: Side) {
  const wantPositive = side === "long";
  let agentCount = 0;
  let totalNotional = 0;
  let weightedEntry = 0;
  let totalQty = 0;
  for (const a of agents) {
    let touched = false;
    for (const sym in a.positions) {
      const p = a.positions[sym]!;
      if ((wantPositive && p.qty > 0) || (!wantPositive && p.qty < 0)) {
        touched = true;
        const q = Math.abs(p.qty);
        totalNotional += q * p.avg_price;
        weightedEntry += q * p.avg_price;
        totalQty += q;
      }
    }
    if (touched) agentCount++;
  }
  return {
    agentCount,
    totalNotional,
    avgEntry: totalQty ? weightedEntry / totalQty : 0,
    totalQty,
  };
}

export function PositionsPanel({ agents }: { agents: AgentRow[] }) {
  const long = aggregate(agents, "long");
  const short = aggregate(agents, "short");
  const openCount = long.agentCount + short.agentCount;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <span className="text-xs uppercase tracking-wider text-zinc-400">Overview of Open Positions</span>
        <span className="text-2xl font-mono font-semibold tabular-nums">{openCount}</span>
      </div>

      <div className="rounded-md border border-emerald-900/50 bg-emerald-950/20 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-bold text-(--color-profit)">LONG</span>
          <span className="font-mono text-zinc-400">{long.agentCount} POS</span>
        </div>
        <div className="grid grid-cols-2 gap-y-1.5 text-xs">
          <span className="text-zinc-500">POS SIZE</span>
          <span className="text-right font-mono text-(--color-profit)">${long.totalNotional.toFixed(0)}</span>
          <span className="text-zinc-500">ENTRY AVG</span>
          <span className="text-right font-mono">${long.avgEntry.toFixed(2)}</span>
          <span className="text-zinc-500">AI COUNT</span>
          <span className="text-right font-mono">{long.agentCount}</span>
          <span className="text-zinc-500">SHARES</span>
          <span className="text-right font-mono">{long.totalQty.toFixed(2)}</span>
        </div>
      </div>

      <div className="rounded-md border border-rose-900/50 bg-rose-950/20 p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <span className="font-bold text-(--color-loss)">SHORT</span>
          <span className="font-mono text-zinc-400">{short.agentCount} POS</span>
        </div>
        <div className="grid grid-cols-2 gap-y-1.5 text-xs">
          <span className="text-zinc-500">POS SIZE</span>
          <span className="text-right font-mono text-(--color-loss)">${short.totalNotional.toFixed(0)}</span>
          <span className="text-zinc-500">ENTRY AVG</span>
          <span className="text-right font-mono">${short.avgEntry.toFixed(2)}</span>
          <span className="text-zinc-500">AI COUNT</span>
          <span className="text-right font-mono">{short.agentCount}</span>
          <span className="text-zinc-500">SHARES</span>
          <span className="text-right font-mono">{short.totalQty.toFixed(2)}</span>
        </div>
      </div>
    </div>
  );
}
