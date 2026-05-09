import { useEffect, useRef, useState } from "react";
import type { AgentRow } from "../api";

type AggregatedPosition = {
  symbol: string;
  totalQty: number;
  avgEntry: number;
  mark: number;
  unrealized: number;
};

const MAX_POINTS = 20;

function aggregate(agents: AgentRow[]): AggregatedPosition[] {
  type Accum = { qty: number; notional: number; mark: number; unrealized: number };
  const map = new Map<string, Accum>();
  for (const a of agents) {
    for (const sym in a.positions) {
      const p = a.positions[sym];
      if (!p || p.qty === 0) continue;
      const acc = map.get(sym) ?? { qty: 0, notional: 0, mark: 0, unrealized: 0 };
      acc.qty += p.qty;
      acc.notional += p.qty * p.avg_price;
      acc.mark = p.mark;
      acc.unrealized += p.qty * (p.mark - p.avg_price);
      map.set(sym, acc);
    }
  }
  const out: AggregatedPosition[] = [];
  for (const [symbol, acc] of map) {
    if (acc.qty === 0) continue;
    out.push({
      symbol,
      totalQty: acc.qty,
      avgEntry: acc.notional / acc.qty,
      mark: acc.mark,
      unrealized: acc.unrealized,
    });
  }
  out.sort((a, b) => Math.abs(b.unrealized) - Math.abs(a.unrealized));
  return out;
}

function Sparkline({ points, positive }: { points: number[]; positive: boolean }) {
  const w = 80;
  const h = 22;
  if (points.length < 2) {
    return (
      <svg width={w} height={h} className="block">
        <line
          x1={0}
          y1={h / 2}
          x2={w}
          y2={h / 2}
          stroke="rgb(82 82 91)"
          strokeWidth={1}
          strokeDasharray="2 2"
        />
      </svg>
    );
  }
  let min = Infinity;
  let max = -Infinity;
  for (const v of points) {
    if (v < min) min = v;
    if (v > max) max = v;
  }
  const range = max - min || 1;
  const stepX = w / (points.length - 1);
  const coords = points
    .map((v, i) => {
      const x = i * stepX;
      const y = h - ((v - min) / range) * h;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const stroke = positive ? "var(--color-profit)" : "var(--color-loss)";
  return (
    <svg width={w} height={h} className="block">
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth={1.25}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={coords}
      />
    </svg>
  );
}

export function PositionsSparklineStrip({ agents }: { agents: AgentRow[] }) {
  const positions = aggregate(agents);
  const bufferRef = useRef<Map<string, number[]>>(new Map());
  const [, force] = useState(0);

  useEffect(() => {
    const buf = bufferRef.current;
    let changed = false;
    const seen = new Set<string>();
    for (const p of positions) {
      seen.add(p.symbol);
      const arr = buf.get(p.symbol) ?? [];
      const last = arr.length > 0 ? arr[arr.length - 1] : undefined;
      if (last === undefined || last !== p.mark) {
        arr.push(p.mark);
        if (arr.length > MAX_POINTS) arr.splice(0, arr.length - MAX_POINTS);
        buf.set(p.symbol, arr);
        changed = true;
      }
    }
    for (const k of Array.from(buf.keys())) {
      if (!seen.has(k)) {
        buf.delete(k);
        changed = true;
      }
    }
    if (changed) force((n) => n + 1);
    // Effect intentionally keys off `agents` identity (a fresh array on every
    // SWR poll). `positions` is derived during render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents]);

  if (positions.length === 0) {
    return (
      <div className="text-[11px] font-mono text-zinc-500 py-1">No open positions.</div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <div className="flex gap-2 min-w-min">
        {positions.map((p) => {
          const positive = p.unrealized >= 0;
          const points = bufferRef.current.get(p.symbol) ?? [p.mark];
          return (
            <div
              key={p.symbol}
              className="shrink-0 rounded-md border border-zinc-800 bg-zinc-950/40 px-3 py-2 min-w-[150px]"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-xs font-bold tracking-wide">{p.symbol}</span>
                <span className="font-mono text-[10px] tabular-nums text-zinc-300">
                  ${p.mark.toFixed(2)}
                </span>
              </div>
              <div className="mt-1 flex items-end justify-between gap-2">
                <div className="flex flex-col font-mono text-[10px] leading-tight text-zinc-500">
                  <span>
                    qty <span className="text-zinc-300 tabular-nums">{p.totalQty.toFixed(2)}</span>
                  </span>
                  <span
                    className={`tabular-nums ${
                      positive ? "text-(--color-profit)" : "text-(--color-loss)"
                    }`}
                  >
                    {positive ? "+" : ""}
                    {p.unrealized.toFixed(2)}
                  </span>
                </div>
                <Sparkline points={points} positive={positive} />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
