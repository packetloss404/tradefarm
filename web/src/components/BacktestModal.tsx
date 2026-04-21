import { useEffect, useRef, useState } from "react";
import { api, type BacktestJob, type BacktestResult } from "../api";

type SortKey = "symbol" | "sharpe" | "total_return_pct" | "cagr_pct" | "max_drawdown_pct" | "win_rate" | "n_trades";

const HEADERS: { key: SortKey; label: string; num: boolean }[] = [
  { key: "symbol", label: "Symbol", num: false },
  { key: "sharpe", label: "Sharpe", num: true },
  { key: "total_return_pct", label: "Total %", num: true },
  { key: "cagr_pct", label: "CAGR %", num: true },
  { key: "max_drawdown_pct", label: "Max DD %", num: true },
  { key: "win_rate", label: "Win %", num: true },
  { key: "n_trades", label: "Trades", num: true },
];


export function BacktestModal({ onClose }: { onClose: () => void }) {
  const [symbolInput, setSymbolInput] = useState("");
  const [job, setJob] = useState<BacktestJob | null>(null);
  const [err, setErr] = useState<string>("");
  const [sortKey, setSortKey] = useState<SortKey>("sharpe");
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const pollRef = useRef<number | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
    };
  }, [onClose]);

  const start = async (allUniverse: boolean) => {
    setErr("");
    setJob(null);
    try {
      const syms = allUniverse
        ? null
        : symbolInput.split(/[,\s]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
      const r = await api.backtestRun(syms);
      // Seed the local state so the UI shows "0 / total" immediately.
      setJob({
        job_id: r.job_id,
        status: "running",
        total: r.total,
        done: 0,
        current: null,
        results: [],
        started_at: new Date().toISOString(),
        finished_at: null,
      });
      // Poll until done.
      if (pollRef.current !== null) window.clearInterval(pollRef.current);
      pollRef.current = window.setInterval(async () => {
        try {
          const s = await api.backtestStatus(r.job_id);
          setJob(s);
          if (s.status === "done" && pollRef.current !== null) {
            window.clearInterval(pollRef.current);
            pollRef.current = null;
          }
        } catch (e) {
          setErr((e as Error).message);
        }
      }, 1500);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const cancel = async () => {
    if (!job) return;
    if (pollRef.current !== null) {
      window.clearInterval(pollRef.current);
      pollRef.current = null;
    }
    await api.backtestCancel(job.job_id);
    setJob(null);
  };

  const results = job?.results ?? [];
  const ok = results.filter((r): r is Required<BacktestResult> => !("error" in r) || !r.error);
  const skipped = results.filter((r) => r.error);

  const sorted = [...ok].sort((a, b) => {
    const av = a[sortKey];
    const bv = b[sortKey];
    if (typeof av === "number" && typeof bv === "number") return (av - bv) * sortDir;
    return String(av).localeCompare(String(bv)) * sortDir;
  });

  const clickHeader = (k: SortKey) => {
    if (k === sortKey) setSortDir((d) => (d === 1 ? -1 : 1) as 1 | -1);
    else {
      setSortKey(k);
      setSortDir(k === "symbol" ? 1 : -1);
    }
  };

  const progressPct = job && job.total ? Math.round((job.done / job.total) * 100) : 0;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[900px] max-w-[95vw] max-h-[90vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
          <div>
            <div className="text-lg font-semibold">Backtest Launcher</div>
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">
              walk-forward on ~2y of EOD bars · LstmAgent rule (max_prob ≥ 0.40)
            </div>
          </div>
          <button onClick={onClose} className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700">esc</button>
        </header>

        <div className="space-y-4 p-5">
          {/* Launch form */}
          <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4">
            <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-400">Launch</div>
            <div className="flex items-center gap-2">
              <input
                type="text"
                value={symbolInput}
                onChange={(e) => setSymbolInput(e.target.value)}
                placeholder="SPY, QQQ, NVDA  (space- or comma-separated)"
                disabled={job?.status === "running"}
                className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-1.5 font-mono text-xs text-zinc-100 disabled:opacity-50"
              />
              <button
                onClick={() => start(false)}
                disabled={!symbolInput.trim() || job?.status === "running"}
                className="rounded border border-emerald-600 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40"
              >
                Run symbols
              </button>
              <button
                onClick={() => start(true)}
                disabled={job?.status === "running"}
                className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-semibold text-zinc-100 hover:bg-zinc-700 disabled:opacity-40"
              >
                Run universe
              </button>
            </div>
            {err && <div className="mt-2 text-xs text-(--color-loss)">{err}</div>}
          </div>

          {/* Progress */}
          {job && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4">
              <div className="mb-2 flex items-center justify-between">
                <div className="text-[10px] uppercase tracking-wider text-zinc-400">
                  {job.status === "running" ? "Running" : "Complete"} · job {job.job_id}
                </div>
                {job.status === "running" && (
                  <button onClick={cancel} className="text-[11px] text-zinc-500 underline hover:text-zinc-300">cancel</button>
                )}
              </div>
              <div className="h-2 w-full overflow-hidden rounded bg-zinc-800">
                <div
                  className={`h-full transition-all ${job.status === "done" ? "bg-(--color-profit)" : "bg-emerald-500"}`}
                  style={{ width: `${progressPct}%` }}
                />
              </div>
              <div className="mt-2 flex items-baseline justify-between text-[11px]">
                <span className="font-mono text-zinc-500">
                  {job.done} / {job.total}
                  {job.current && ` · current: ${job.current}`}
                </span>
                <span className="font-mono text-zinc-500">{progressPct}%</span>
              </div>
            </div>
          )}

          {/* Results table */}
          {ok.length > 0 && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4">
              <div className="mb-2 flex items-baseline justify-between">
                <div className="text-[10px] uppercase tracking-wider text-zinc-400">Results ({ok.length})</div>
                <div className="text-[11px] text-zinc-500">
                  avg sharpe {avg(ok.map((r) => r.sharpe)).toFixed(2)} · avg total {avg(ok.map((r) => r.total_return_pct)).toFixed(1)}%
                </div>
              </div>
              <table className="w-full text-xs font-mono tabular-nums">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wider text-zinc-500">
                    {HEADERS.map((h) => (
                      <th
                        key={h.key}
                        onClick={() => clickHeader(h.key)}
                        className={`cursor-pointer select-none py-1.5 pr-2 hover:text-zinc-300 ${h.num ? "text-right" : ""}`}
                      >
                        {h.label}
                        {sortKey === h.key && <span className="ml-1 text-emerald-400">{sortDir === 1 ? "▲" : "▼"}</span>}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((r) => (
                    <tr key={r.symbol} className="border-t border-zinc-800/60">
                      <td className="py-1 pr-2 text-zinc-300">{r.symbol}</td>
                      <td className={`py-1 pr-2 text-right ${tone(r.sharpe, 0)}`}>{r.sharpe.toFixed(2)}</td>
                      <td className={`py-1 pr-2 text-right ${tone(r.total_return_pct, 0)}`}>{r.total_return_pct.toFixed(1)}</td>
                      <td className={`py-1 pr-2 text-right ${tone(r.cagr_pct, 0)}`}>{r.cagr_pct.toFixed(1)}</td>
                      <td className="py-1 pr-2 text-right text-(--color-loss)">{r.max_drawdown_pct.toFixed(1)}</td>
                      <td className="py-1 pr-2 text-right text-zinc-300">{(r.win_rate * 100).toFixed(0)}%</td>
                      <td className="py-1 pr-2 text-right text-zinc-300">{r.n_trades}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {skipped.length > 0 && (
            <div className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4">
              <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-400">Skipped ({skipped.length})</div>
              <ul className="space-y-1 text-xs font-mono text-zinc-500">
                {skipped.map((r) => (
                  <li key={r.symbol}>{r.symbol}: <span className="text-(--color-loss)">{r.error}</span></li>
                ))}
              </ul>
            </div>
          )}

          {!job && (
            <div className="rounded-md border border-dashed border-zinc-800 p-6 text-center text-xs text-zinc-500">
              Kick off a backtest above. Single symbols return in ~2s; the 40-ticker universe takes ~60s.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function avg(xs: number[]): number {
  return xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : 0;
}

function tone(v: number, threshold = 0): string {
  if (v > threshold) return "text-(--color-profit)";
  if (v < threshold) return "text-(--color-loss)";
  return "text-zinc-300";
}
