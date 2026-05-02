import { useMemo } from "react";
import type { AgentRow } from "../shared/api";
import type { FillEvent } from "../hooks/useStreamData";

function fmtSign(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

/** Left-rail vertical stack of giant stat blocks: top performers, recent fills,
 *  and biggest single fill. Numbers are sized for 1080p readability. */
export function StatPillar({
  agents,
  fills,
}: {
  agents: AgentRow[];
  fills: FillEvent[];
}) {
  const top5 = useMemo(() => {
    return [...agents]
      .map((a) => ({ a, total: a.realized_pnl + a.unrealized_pnl }))
      .sort((x, y) => y.total - x.total)
      .slice(0, 5);
  }, [agents]);

  const biggestFill = useMemo(() => {
    if (fills.length === 0) return null;
    return [...fills].sort(
      (a, b) =>
        Math.abs(b.payload.qty * b.payload.price) - Math.abs(a.payload.qty * a.payload.price),
    )[0]!;
  }, [fills]);

  const totalRealized = useMemo(
    () => agents.reduce((acc, a) => acc + a.realized_pnl, 0),
    [agents],
  );
  const totalUnrealized = useMemo(
    () => agents.reduce((acc, a) => acc + a.unrealized_pnl, 0),
    [agents],
  );

  return (
    <div className="h-full w-full p-5 flex flex-col gap-4 bg-zinc-950/70 border-r border-zinc-800">
      <Block title="Top 5 Agents">
        {top5.length === 0 && <span className="text-zinc-600 text-sm font-mono">—</span>}
        {top5.map(({ a, total }, i) => (
          <div key={a.id} className="flex items-center justify-between text-sm">
            <span className="flex items-center gap-2">
              <span className="text-zinc-500 tabular-nums w-5">{i + 1}.</span>
              <span className="font-medium truncate max-w-[150px]">{a.name}</span>
            </span>
            <span
              className={`tabular-nums font-mono font-semibold ${total >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}
            >
              {fmtSign(total)}
            </span>
          </div>
        ))}
      </Block>

      <Block title="Pool PnL">
        <div className="flex items-baseline justify-between">
          <span className="text-xs text-zinc-500 uppercase tracking-wider">Realized</span>
          <span
            className={`text-2xl font-semibold tabular-nums ${totalRealized >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}
          >
            {fmtSign(totalRealized, 0)}
          </span>
        </div>
        <div className="flex items-baseline justify-between mt-1">
          <span className="text-xs text-zinc-500 uppercase tracking-wider">Unrealized</span>
          <span
            className={`text-2xl font-semibold tabular-nums ${totalUnrealized >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}
          >
            {fmtSign(totalUnrealized, 0)}
          </span>
        </div>
      </Block>

      <Block title="Biggest Fill">
        {biggestFill ? (
          <div className="flex flex-col">
            <span className="text-xs text-zinc-500 uppercase tracking-wider">
              {biggestFill.payload.side.toUpperCase()} {biggestFill.payload.symbol}
            </span>
            <span className="text-3xl font-bold tabular-nums mt-1">
              {biggestFill.payload.qty}
            </span>
            <span className="text-base text-zinc-400 tabular-nums">
              @ ${biggestFill.payload.price.toFixed(2)}
            </span>
          </div>
        ) : (
          <span className="text-zinc-600 text-sm font-mono">—</span>
        )}
      </Block>

      <Block title="Roster">
        <div className="grid grid-cols-2 gap-y-1 text-sm">
          <span className="text-zinc-500">Total</span>
          <span className="tabular-nums text-right">{agents.length}</span>
          <span className="text-zinc-500">Holding</span>
          <span className="tabular-nums text-right">
            {agents.filter((a) => Object.values(a.positions).some((p) => p.qty !== 0)).length}
          </span>
          <span className="text-zinc-500">Principal</span>
          <span className="tabular-nums text-right">
            {agents.filter((a) => a.rank === "principal").length}
          </span>
          <span className="text-zinc-500">Senior</span>
          <span className="tabular-nums text-right">
            {agents.filter((a) => a.rank === "senior").length}
          </span>
        </div>
      </Block>
    </div>
  );
}

function Block({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
      <div className="text-[10px] uppercase tracking-widest text-zinc-500 mb-2 font-mono">
        {title}
      </div>
      {children}
    </div>
  );
}
