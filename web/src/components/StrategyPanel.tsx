import useSWR from "swr";

const REFRESH_MS = 10_000;

export type StrategySummaryRow = {
  strategy: string;
  agent_count: number;
  realized_pnl_total: number;
  unrealized_pnl_total: number;
  equity_total: number;
  trades_today: number;
  win_rate: number;
  best_agent_name: string;
  worst_agent_name: string;
};

export type StrategyTimeseriesPoint = {
  date: string;
  strategy: string;
  equity_total: number;
};

const STRATEGIES = ["momentum_sma20", "lstm_v1", "lstm_llm_v1"] as const;
type StrategyKey = (typeof STRATEGIES)[number];

const STRATEGY_COLOR: Record<StrategyKey, string> = {
  momentum_sma20: "#fbbf24", // amber-400
  lstm_v1: "#38bdf8", // sky-400
  lstm_llm_v1: "#34d399", // emerald-400
};

const fetcher = async <T,>(url: string): Promise<T> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
};

function emptyRow(strategy: string): StrategySummaryRow {
  return {
    strategy,
    agent_count: 0,
    realized_pnl_total: 0,
    unrealized_pnl_total: 0,
    equity_total: 0,
    trades_today: 0,
    win_rate: 0,
    best_agent_name: "—",
    worst_agent_name: "—",
  };
}

function tone(n: number): string {
  if (n > 0) return "text-(--color-profit)";
  if (n < 0) return "text-(--color-loss)";
  return "text-zinc-300";
}

function MiniChart({ series }: { series: StrategyTimeseriesPoint[] }) {
  const W = 600;
  const H = 80;
  const PAD_X = 4;
  const PAD_Y = 6;
  const byDate = Array.from(new Set(series.map((p) => p.date))).sort();
  if (byDate.length < 2) {
    return <div className="h-20 flex items-center text-[10px] text-zinc-500 italic">not enough history yet</div>;
  }
  const xIdx = new Map(byDate.map((d, i) => [d, i]));
  const vals = series.map((p) => p.equity_total).filter((v) => Number.isFinite(v));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const xFor = (d: string) => PAD_X + ((xIdx.get(d) ?? 0) / (byDate.length - 1)) * (W - 2 * PAD_X);
  const yFor = (v: number) => H - PAD_Y - ((v - min) / span) * (H - 2 * PAD_Y);

  const paths: { k: StrategyKey; d: string }[] = [];
  for (const k of STRATEGIES) {
    const pts = series
      .filter((p) => p.strategy === k)
      .sort((a, b) => a.date.localeCompare(b.date));
    if (pts.length < 2) continue;
    const d = pts.map((p, i) => `${i === 0 ? "M" : "L"}${xFor(p.date).toFixed(2)},${yFor(p.equity_total).toFixed(2)}`).join(" ");
    paths.push({ k, d });
  }

  const firstDate = byDate[0]!;
  const lastDate = byDate[byDate.length - 1]!;

  return (
    <div className="space-y-1">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="h-20 w-full">
        {paths.map(({ k, d }) => (
          <path key={k} d={d} fill="none" stroke={STRATEGY_COLOR[k]} strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
        ))}
      </svg>
      <div className="flex justify-between text-[10px] font-mono text-zinc-500">
        <span>{firstDate}</span>
        <div className="flex gap-3">
          {STRATEGIES.map((k) => (
            <span key={k} className="inline-flex items-center gap-1">
              <span className="inline-block size-1.5 rounded-full" style={{ backgroundColor: STRATEGY_COLOR[k] }} />
              {k}
            </span>
          ))}
        </div>
        <span>{lastDate}</span>
      </div>
    </div>
  );
}

function StrategyCard({ row }: { row: StrategySummaryRow }) {
  const totalPnl = row.realized_pnl_total + row.unrealized_pnl_total;
  const winsPct = Math.round(row.win_rate * 100);
  const sign = totalPnl >= 0 ? "+" : "";
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3 space-y-2">
      <div className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">{row.strategy}</div>
      <div className={`text-2xl font-mono font-semibold tabular-nums ${tone(totalPnl)}`}>
        {sign}{totalPnl.toFixed(2)}
      </div>
      <div className="text-[11px] text-zinc-400 font-mono">
        {row.agent_count} agents · {row.trades_today} trades today · {winsPct}% wins
      </div>
      <div className="text-[10px] text-zinc-500 font-mono truncate" title={`best ${row.best_agent_name} · worst ${row.worst_agent_name}`}>
        best <span className="text-(--color-profit)">{row.best_agent_name}</span> · worst <span className="text-(--color-loss)">{row.worst_agent_name}</span>
      </div>
    </div>
  );
}

export function StrategyPanel() {
  const { data: summary, error: sumErr } = useSWR<StrategySummaryRow[]>(
    "strategy-summary",
    () => fetcher<StrategySummaryRow[]>("/api/pnl/by-strategy"),
    { refreshInterval: REFRESH_MS },
  );
  const { data: series, error: tsErr } = useSWR<StrategyTimeseriesPoint[]>(
    "strategy-timeseries",
    () => fetcher<StrategyTimeseriesPoint[]>("/api/pnl/by-strategy/timeseries?days=7"),
    { refreshInterval: REFRESH_MS },
  );

  const err = sumErr || tsErr;
  if (err) {
    return (
      <div className="rounded-md border border-rose-900/50 bg-rose-950/20 p-3 text-xs text-(--color-loss) font-mono">
        strategy data unavailable: {(err as Error).message}
      </div>
    );
  }

  if (!summary || !series) {
    return <div className="text-xs text-zinc-500 italic">loading strategies…</div>;
  }

  if (summary.length === 0 && series.length === 0) {
    return <div className="text-xs text-zinc-500 italic">No strategy data yet — run a tick.</div>;
  }

  const byKey = new Map(summary.map((r) => [r.strategy, r]));
  const rows = STRATEGIES.map((k) => byKey.get(k) ?? emptyRow(k));

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-3">
        {rows.map((r) => <StrategyCard key={r.strategy} row={r} />)}
      </div>
      <MiniChart series={series} />
    </div>
  );
}
