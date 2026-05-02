import { useMemo } from "react";
import type { AgentRow, Rank } from "../shared/api";
import type { StreamSnapshot } from "../hooks/useStreamData";

const RANK_COLOR: Record<Rank | "unranked", string> = {
  intern: "text-zinc-400",
  junior: "text-sky-400",
  senior: "text-amber-400",
  principal: "text-emerald-400",
  unranked: "text-zinc-600",
};

function fmtSign(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

/**
 * Full ranked list of every agent, laid out in 4 columns × 25 rows. Each
 * row shows position, agent name, strategy chip, total PnL, and a mini
 * bar normalized against the day's largest absolute PnL.
 */
export function LeaderboardScene({ snapshot }: { snapshot: StreamSnapshot }) {
  const ranked = useMemo(() => {
    return [...snapshot.agents]
      .map((a) => ({ a, total: a.realized_pnl + a.unrealized_pnl }))
      .sort((x, y) => y.total - x.total);
  }, [snapshot.agents]);

  const maxAbs = useMemo(
    () => ranked.reduce((m, r) => Math.max(m, Math.abs(r.total)), 1),
    [ranked],
  );

  const cols = useMemo(() => {
    const out: { a: AgentRow; total: number }[][] = [[], [], [], []];
    ranked.forEach((row, i) => out[i % 4]?.push(row));
    return out;
  }, [ranked]);

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden">
      <header className="flex items-baseline justify-between mb-5">
        <h2 className="text-3xl font-bold tracking-tight">
          Leader<span className="text-(--color-profit)">board</span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          {ranked.length} agents · live ranking
        </span>
      </header>
      <div className="grid grid-cols-4 gap-x-6">
        {cols.map((col, ci) => (
          <div key={ci} className="space-y-1">
            {col.map(({ a, total }, ri) => {
              const pos = ci + ri * 4 + 1;
              const widthPct = Math.min(100, (Math.abs(total) / maxAbs) * 100);
              const sign = total >= 0;
              return (
                <div
                  key={a.id}
                  className="flex items-center gap-2 px-2 py-1 rounded text-[13px] hover:bg-zinc-900/40"
                >
                  <span className="w-7 text-right text-zinc-500 tabular-nums font-mono text-[11px]">
                    {pos}.
                  </span>
                  <span
                    className={`text-[10px] uppercase font-mono ${RANK_COLOR[a.rank ?? "unranked"]}`}
                  >
                    {a.rank ? a.rank.slice(0, 3) : "—"}
                  </span>
                  <span className="font-medium truncate flex-1">{a.name}</span>
                  <div className="relative w-16 h-2 bg-zinc-900 rounded">
                    <div
                      className={`absolute inset-y-0 ${sign ? "left-0 bg-(--color-profit)" : "left-0 bg-(--color-loss)"}`}
                      style={{ width: `${widthPct}%` }}
                    />
                  </div>
                  <span
                    className={`w-16 text-right tabular-nums font-mono font-semibold ${sign ? "text-(--color-profit)" : "text-(--color-loss)"}`}
                  >
                    {fmtSign(total, 0)}
                  </span>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}
