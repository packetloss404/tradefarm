import type { AccountSummary } from "../shared/api";

function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtSign(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

function tickAge(iso: string | null): string {
  if (!iso) return "never";
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

export function TopTicker({
  account,
  agentCount,
  wsStatus,
}: {
  account: AccountSummary | null;
  agentCount: number;
  wsStatus: "connecting" | "open" | "closed";
}) {
  if (!account) {
    return (
      <div className="h-[60px] flex items-center px-8 bg-zinc-950/90 border-b border-zinc-800">
        <span className="text-zinc-500 text-sm font-mono">connecting…</span>
      </div>
    );
  }

  const totalAllocated = agentCount * 1000;
  const todayPnl = account.total_equity - totalAllocated;
  const todayPct = totalAllocated > 0 ? (todayPnl / totalAllocated) * 100 : 0;
  const tone = todayPnl >= 0 ? "text-(--color-profit)" : "text-(--color-loss)";
  const wsColor =
    wsStatus === "open" ? "text-emerald-500" : wsStatus === "connecting" ? "text-amber-500" : "text-rose-500";

  return (
    <div className="h-[60px] flex items-center justify-between px-8 bg-gradient-to-b from-zinc-950 via-zinc-950/95 to-zinc-950/80 border-b border-zinc-800">
      <div className="flex items-center gap-3">
        <img src="/favicon.svg" alt="" className="h-7 w-7" />
        <h1 className="text-xl font-semibold tracking-tight">
          Trade<span className="text-(--color-profit)">Farm</span>
        </h1>
        <span className="text-zinc-500 text-xs font-mono ml-1 mt-1">live</span>
      </div>

      <div className="flex items-center gap-8">
        <Stat label="Equity" value={`$${fmtUsd(account.total_equity)}`} />
        <Stat
          label="Today"
          value={`${fmtSign(todayPnl, 0)} USD`}
          sub={`${fmtSign(todayPct, 3)}%`}
          tone={todayPnl >= 0 ? "profit" : "loss"}
        />
        <Stat
          label="Realized"
          value={`${fmtSign(account.realized_pnl)}`}
          tone={account.realized_pnl >= 0 ? "profit" : "loss"}
        />
        <Stat
          label="Unrealized"
          value={`${fmtSign(account.unrealized_pnl)}`}
          tone={account.unrealized_pnl >= 0 ? "profit" : "loss"}
        />
        <div className="flex items-center gap-3 pl-6 border-l border-zinc-800">
          <Pill label="Profit" value={account.profit_ai} tone="profit" />
          <Pill label="Loss" value={account.loss_ai} tone="loss" />
          <Pill label="Wait" value={account.waiting_ai} tone="wait" />
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs font-mono text-zinc-500">
        <span>last tick {tickAge(account.last_tick_at)}</span>
        <span className={wsColor}>● ws:{wsStatus}</span>
      </div>

      {/* Tone hint span — keeps Tailwind from purging the dynamic class */}
      <span className={`hidden ${tone}`} />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "profit" | "loss" | "wait";
}) {
  const toneCls =
    tone === "profit" ? "text-(--color-profit)" : tone === "loss" ? "text-(--color-loss)" : "text-zinc-100";
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
      <span className={`mt-0.5 text-lg font-semibold tabular-nums ${toneCls}`}>{value}</span>
      {sub && <span className={`text-[11px] tabular-nums ${toneCls} opacity-80`}>{sub}</span>}
    </div>
  );
}

function Pill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "profit" | "loss" | "wait";
}) {
  const toneCls =
    tone === "profit"
      ? "bg-emerald-500/10 text-(--color-profit) border-emerald-500/30"
      : tone === "loss"
        ? "bg-rose-500/10 text-(--color-loss) border-rose-500/30"
        : "bg-zinc-500/10 text-(--color-wait) border-zinc-500/30";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-mono ${toneCls}`}>
      <span className="opacity-70">{label}</span>
      <span className="tabular-nums font-semibold">{value}</span>
    </span>
  );
}
