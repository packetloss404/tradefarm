import { useMemo } from "react";
import type { AgentRow } from "../shared/api";
import type { FillEvent, StreamSnapshot } from "../hooks/useStreamData";

const STRATEGY_PRETTY: Record<string, string> = {
  momentum_sma20: "Momentum (SMA20)",
  lstm_v1: "LSTM v1",
  lstm_llm_v1: "LSTM + LLM v1",
};

type StrategyRow = {
  name: string;
  count: number;
  total: number;
};

type Recap = {
  totalPnl: number;
  totalPnlPct: number;
  best: { agent: AgentRow; total: number } | null;
  worst: { agent: AgentRow; total: number } | null;
  biggestFill: { fill: FillEvent; notional: number } | null;
  strategies: StrategyRow[];
  fillCount: number;
  promotionCount: number;
  agentCount: number;
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

function fmtPct(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}%`;
}

function totalOf(a: AgentRow): number {
  return a.realized_pnl + a.unrealized_pnl;
}

function computeRecap(snapshot: StreamSnapshot): Recap {
  let best: { agent: AgentRow; total: number } | null = null;
  let worst: { agent: AgentRow; total: number } | null = null;
  let totalPnl = 0;

  const stratMap = new Map<string, StrategyRow>();
  for (const a of snapshot.agents) {
    const t = totalOf(a);
    totalPnl += t;
    if (best === null || t > best.total) best = { agent: a, total: t };
    if (worst === null || t < worst.total) worst = { agent: a, total: t };

    const cur = stratMap.get(a.strategy) ?? {
      name: a.strategy,
      count: 0,
      total: 0,
    };
    cur.count += 1;
    cur.total += t;
    stratMap.set(a.strategy, cur);
  }

  let biggest: { fill: FillEvent; notional: number } | null = null;
  for (const f of snapshot.fills) {
    const notional = Math.abs(f.payload.qty * f.payload.price);
    if (biggest === null || notional > biggest.notional) {
      biggest = { fill: f, notional };
    }
  }

  const allocated = snapshot.agents.length * 1000;
  const totalPnlPct = allocated > 0 ? (totalPnl / allocated) * 100 : 0;

  return {
    totalPnl,
    totalPnlPct,
    best,
    worst,
    biggestFill: biggest,
    strategies: Array.from(stratMap.values()).sort((x, y) => y.total - x.total),
    fillCount: snapshot.fills.length,
    promotionCount: snapshot.promotions.length,
    agentCount: snapshot.agents.length,
  };
}

/**
 * End-of-day recap shown by the rotator after 16:00 ET. Big total PnL
 * hero number, three highlight cards (top mover / biggest fill / bottom
 * mover), and a strategy-ranked P&L table.
 */
export function RecapScene({ snapshot }: { snapshot: StreamSnapshot }) {
  const recap = useMemo(() => computeRecap(snapshot), [snapshot]);
  const sign = recap.totalPnl >= 0;
  const maxStratAbs = useMemo(
    () => recap.strategies.reduce((m, s) => Math.max(m, Math.abs(s.total)), 1),
    [recap.strategies],
  );

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden flex flex-col">
      <header className="flex items-baseline justify-between mb-5">
        <h2 className="text-3xl font-bold tracking-tight">
          Day <span className="text-(--color-profit)">Recap</span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          session closed · 16:00 ET · {recap.agentCount} agents · {recap.fillCount} live fills
        </span>
      </header>

      <section
        className={`relative rounded-xl border ${
          sign ? "border-emerald-500/30" : "border-rose-500/30"
        } bg-gradient-to-br from-zinc-900/70 to-zinc-950 px-8 py-7 mb-5`}
      >
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[720px] h-[260px] rounded-full bg-emerald-500/5 blur-3xl pointer-events-none" />
        <div className="relative flex items-center justify-between">
          <div>
            <div className="text-[11px] uppercase tracking-[0.3em] text-zinc-500 font-mono">
              Total Day P&amp;L
            </div>
            <div
              className={`text-[112px] leading-none font-bold tabular-nums mt-2 ${
                sign ? "text-(--color-profit)" : "text-(--color-loss)"
              }`}
            >
              {fmtSign(recap.totalPnl)}
              <span className="text-4xl text-zinc-500 ml-3 font-mono">USD</span>
            </div>
          </div>
          <div className="flex flex-col items-end gap-3">
            <div
              className={`text-5xl font-bold tabular-nums ${
                sign ? "text-(--color-profit)" : "text-(--color-loss)"
              }`}
            >
              {fmtPct(recap.totalPnlPct)}
            </div>
            <div className="flex gap-3 text-[11px] font-mono uppercase tracking-wider text-zinc-500">
              <span>{recap.promotionCount} promotions</span>
              <span>·</span>
              <span>{recap.fillCount} fills</span>
            </div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-3 gap-4 mb-5">
        <MoverCard
          label="Top Mover"
          tone="profit"
          mover={recap.best}
        />
        <BiggestFillCard fill={recap.biggestFill} />
        <MoverCard
          label="Bottom Mover"
          tone="loss"
          mover={recap.worst}
        />
      </section>

      <section className="rounded-lg border border-zinc-800 bg-zinc-900/40 px-5 py-4 flex-1 min-h-0">
        <div className="flex items-baseline justify-between mb-3">
          <h3 className="text-sm font-semibold uppercase tracking-widest text-zinc-300">
            Strategy Ranking
          </h3>
          <span className="text-[10px] font-mono uppercase tracking-widest text-zinc-600">
            day P&amp;L by strategy family
          </span>
        </div>

        <div className="space-y-2">
          {recap.strategies.length === 0 && (
            <div className="text-zinc-600 font-mono text-sm">
              No agent snapshots yet.
            </div>
          )}
          {recap.strategies.map((s, i) => {
            const widthPct = Math.min(
              100,
              (Math.abs(s.total) / maxStratAbs) * 100,
            );
            const ssign = s.total >= 0;
            return (
              <div
                key={s.name}
                className="flex items-center gap-3 px-2 py-1.5 rounded"
              >
                <span className="w-7 text-zinc-500 tabular-nums font-mono text-xs">
                  #{i + 1}
                </span>
                <div className="w-[220px] truncate text-base font-semibold">
                  {STRATEGY_PRETTY[s.name] ?? s.name}
                </div>
                <span className="text-[11px] font-mono text-zinc-500 w-20">
                  {s.count} agents
                </span>
                <div className="relative flex-1 h-3 bg-zinc-950 rounded overflow-hidden">
                  <div
                    className={`absolute inset-y-0 left-0 ${
                      ssign ? "bg-(--color-profit)" : "bg-(--color-loss)"
                    }`}
                    style={{ width: `${widthPct}%` }}
                  />
                </div>
                <span
                  className={`w-32 text-right text-2xl font-bold tabular-nums ${
                    ssign ? "text-(--color-profit)" : "text-(--color-loss)"
                  }`}
                >
                  {fmtSign(s.total)}
                </span>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

function MoverCard({
  label,
  tone,
  mover,
}: {
  label: string;
  tone: "profit" | "loss";
  mover: { agent: AgentRow; total: number } | null;
}) {
  const accent = tone === "profit" ? "text-(--color-profit)" : "text-(--color-loss)";
  const border =
    tone === "profit" ? "border-emerald-500/30" : "border-rose-500/30";

  if (!mover) {
    return (
      <div className={`rounded-lg border ${border} bg-zinc-900/40 p-5 min-h-[155px] flex flex-col`}>
        <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 font-mono">
          {label}
        </span>
        <span className="text-zinc-600 font-mono text-sm mt-4">no data</span>
      </div>
    );
  }

  const a = mover.agent;
  const ssign = mover.total >= 0;
  return (
    <div className={`rounded-lg border ${border} bg-zinc-900/40 p-5 min-h-[155px] flex flex-col`}>
      <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 font-mono">
        {label}
      </span>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="text-2xl font-bold truncate">{a.name}</span>
        {a.symbol && (
          <span className="text-[11px] font-mono uppercase text-zinc-500">
            {a.symbol}
          </span>
        )}
      </div>
      <span className="text-[11px] font-mono uppercase tracking-wider text-zinc-500">
        {STRATEGY_PRETTY[a.strategy] ?? a.strategy} · {a.rank ?? "unranked"}
      </span>
      <span
        className={`mt-auto pt-3 text-5xl font-bold tabular-nums ${
          ssign ? "text-(--color-profit)" : "text-(--color-loss)"
        }`}
      >
        {fmtSign(mover.total)}
        <span className={`text-base ml-1 font-mono ${accent}`}>USD</span>
      </span>
    </div>
  );
}

function BiggestFillCard({
  fill,
}: {
  fill: { fill: FillEvent; notional: number } | null;
}) {
  if (!fill) {
    return (
      <div className="rounded-lg border border-emerald-500/20 bg-zinc-900/40 p-5 min-h-[155px] flex flex-col">
        <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 font-mono">
          Biggest Fill
        </span>
        <span className="text-zinc-600 font-mono text-sm mt-4">no live fills yet</span>
      </div>
    );
  }

  const p = fill.fill.payload;
  const isBuy = p.side === "buy";
  return (
    <div className="rounded-lg border border-emerald-500/20 bg-zinc-900/40 p-5 min-h-[155px] flex flex-col">
      <span className="text-[10px] uppercase tracking-[0.25em] text-zinc-500 font-mono">
        Biggest Fill
      </span>
      <div className="flex items-baseline gap-2 mt-2">
        <span className="text-2xl font-bold">{p.symbol}</span>
        <span
          className={`text-[11px] font-mono uppercase px-1.5 py-0.5 rounded border ${
            isBuy
              ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10"
              : "border-rose-500/40 text-rose-300 bg-rose-500/10"
          }`}
        >
          {p.side}
        </span>
      </div>
      <span className="text-[11px] font-mono uppercase tracking-wider text-zinc-500">
        agent #{p.agent_id} · {p.qty} @ ${fmtUsd(p.price, 2)}
      </span>
      <span className="mt-auto pt-3 text-5xl font-bold tabular-nums text-zinc-100">
        ${fmtUsd(fill.notional)}
        <span className="text-base ml-1 font-mono text-zinc-500">notional</span>
      </span>
    </div>
  );
}
