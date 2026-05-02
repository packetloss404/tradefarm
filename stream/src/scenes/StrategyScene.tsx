import { useMemo } from "react";
import type { AgentRow } from "../shared/api";
import type { StreamSnapshot } from "../hooks/useStreamData";

type StrategyAgg = {
  name: string;
  count: number;
  equity: number;
  realized: number;
  unrealized: number;
  total: number;
  profit: number;
  loss: number;
  waiting: number;
};

const PRETTY: Record<string, string> = {
  momentum_sma20: "Momentum (SMA20)",
  lstm_v1: "LSTM v1",
  lstm_llm_v1: "LSTM + LLM v1",
};

function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtSign(n: number, frac = 0): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

function aggregate(agents: AgentRow[]): StrategyAgg[] {
  const map = new Map<string, StrategyAgg>();
  for (const a of agents) {
    const cur = map.get(a.strategy) ?? {
      name: a.strategy,
      count: 0,
      equity: 0,
      realized: 0,
      unrealized: 0,
      total: 0,
      profit: 0,
      loss: 0,
      waiting: 0,
    };
    cur.count += 1;
    cur.equity += a.equity;
    cur.realized += a.realized_pnl;
    cur.unrealized += a.unrealized_pnl;
    cur.total += a.realized_pnl + a.unrealized_pnl;
    if (a.status === "profit") cur.profit += 1;
    else if (a.status === "loss") cur.loss += 1;
    else if (a.status === "waiting") cur.waiting += 1;
    map.set(a.strategy, cur);
  }
  return Array.from(map.values()).sort((a, b) => b.total - a.total);
}

/**
 * Strategy scene: side-by-side comparison of every strategy family. Big
 * PnL bar, agent count, and a profit/loss/wait breakdown row.
 */
export function StrategyScene({ snapshot }: { snapshot: StreamSnapshot }) {
  const groups = useMemo(() => aggregate(snapshot.agents), [snapshot.agents]);
  const maxAbs = useMemo(
    () => groups.reduce((m, g) => Math.max(m, Math.abs(g.total)), 1),
    [groups],
  );

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden">
      <header className="flex items-baseline justify-between mb-6">
        <h2 className="text-3xl font-bold tracking-tight">
          Strategy <span className="text-(--color-profit)">Attribution</span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          live aggregation by strategy family
        </span>
      </header>

      <div className="space-y-5">
        {groups.length === 0 && (
          <div className="text-zinc-600 font-mono text-sm">
            No agent snapshots yet.
          </div>
        )}
        {groups.map((g) => {
          const widthPct = Math.min(100, (Math.abs(g.total) / maxAbs) * 100);
          const sign = g.total >= 0;
          return (
            <div
              key={g.name}
              className="rounded-lg border border-zinc-800 bg-zinc-900/40 p-5"
            >
              <div className="flex items-baseline justify-between mb-3">
                <div>
                  <div className="text-xl font-semibold">
                    {PRETTY[g.name] ?? g.name}
                  </div>
                  <div className="text-xs text-zinc-500 font-mono mt-0.5">
                    {g.count} agents · ${fmtUsd(g.equity)} equity
                  </div>
                </div>
                <div
                  className={`text-3xl font-bold tabular-nums ${sign ? "text-(--color-profit)" : "text-(--color-loss)"}`}
                >
                  {fmtSign(g.total)} USD
                </div>
              </div>

              <div className="relative h-3 bg-zinc-950 rounded overflow-hidden">
                <div
                  className={`absolute inset-y-0 left-0 ${sign ? "bg-(--color-profit)" : "bg-(--color-loss)"}`}
                  style={{ width: `${widthPct}%` }}
                />
              </div>

              <div className="grid grid-cols-5 gap-3 mt-3 text-xs font-mono">
                <Mini label="Realized" value={fmtSign(g.realized)} sign={g.realized >= 0} />
                <Mini
                  label="Unrealized"
                  value={fmtSign(g.unrealized)}
                  sign={g.unrealized >= 0}
                />
                <PillCount label="Profit" value={g.profit} tone="profit" />
                <PillCount label="Loss" value={g.loss} tone="loss" />
                <PillCount label="Wait" value={g.waiting} tone="wait" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Mini({
  label,
  value,
  sign,
}: {
  label: string;
  value: string;
  sign: boolean;
}) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
      <span
        className={`text-base tabular-nums font-semibold ${sign ? "text-(--color-profit)" : "text-(--color-loss)"}`}
      >
        {value}
      </span>
    </div>
  );
}

function PillCount({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "profit" | "loss" | "wait";
}) {
  const cls =
    tone === "profit"
      ? "text-(--color-profit)"
      : tone === "loss"
        ? "text-(--color-loss)"
        : "text-(--color-wait)";
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
      <span className={`text-base tabular-nums font-semibold ${cls}`}>{value}</span>
    </div>
  );
}
