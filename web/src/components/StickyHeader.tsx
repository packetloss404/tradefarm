import type { AccountSummary } from "../api";
import { MarketClockBadge } from "./MarketClockBadge";
import { OnAirBadge } from "./OnAirBadge";
import { RankDistBadge } from "./RankDistBadge";
import { StatCard } from "./StatCard";
import { TickCountdownRing } from "./TickCountdownRing";

type Props = {
  account: AccountSummary;
  agentCount: number;
  wsStatus: "open" | "connecting" | "closed";
  lastTickIso: string | null;
  onManualTick: () => void;
  onOpenAdmin: () => void;
  ticking: boolean;
  lastTick: string;
};

function formatTickAt(iso: string | null): string {
  if (iso === null) return "never";
  const t = new Date(iso);
  const sec = Math.max(0, Math.round((Date.now() - t.getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

export function StickyHeader({
  account,
  agentCount,
  wsStatus,
  lastTickIso,
  onManualTick,
  onOpenAdmin,
  ticking,
  lastTick,
}: Props) {
  const totalAllocated = agentCount * 1000;
  const todayPnl = account.total_equity - totalAllocated;
  const todayPct = totalAllocated > 0 ? (todayPnl / totalAllocated) * 100 : 0;

  return (
    <header className="sticky top-0 z-30 -mx-4 -mt-4 mb-0 border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-md">
      <div className="flex h-[72px] items-center gap-4 px-4">
        <h1 className="flex shrink-0 items-center gap-2 text-lg font-semibold">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          Trade<span className="text-(--color-profit)">Farm</span>
          <span className="text-sm font-normal text-zinc-500">— US equities, paper</span>
        </h1>

        <div className="flex flex-1 items-end justify-center gap-6">
          <StatCard
            label="Today PnL"
            value={`${todayPnl >= 0 ? "+" : ""}${todayPnl.toFixed(2)}`}
            sub={`${todayPct >= 0 ? "+" : ""}${todayPct.toFixed(3)}%`}
            tone={todayPnl >= 0 ? "profit" : "loss"}
            big
          />
          <StatCard label="Equity" value={`$${account.total_equity.toFixed(0)}`} />
          <div className="flex items-end gap-3 border-l border-zinc-800 pl-4">
            <StatCard label="Profit" value={account.profit_ai} tone="profit" />
            <StatCard label="Loss" value={account.loss_ai} tone="loss" />
            <StatCard label="Wait" value={account.waiting_ai} tone="wait" />
          </div>
          <div className="flex items-end gap-3 border-l border-zinc-800 pl-4">
            <StatCard
              label="Realized"
              value={`${account.realized_pnl >= 0 ? "+" : ""}${account.realized_pnl.toFixed(2)}`}
              tone={account.realized_pnl >= 0 ? "profit" : "loss"}
            />
            <StatCard
              label="Unrealized"
              value={`${account.unrealized_pnl >= 0 ? "+" : ""}${account.unrealized_pnl.toFixed(2)}`}
              tone={account.unrealized_pnl >= 0 ? "profit" : "loss"}
            />
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-3 text-xs text-zinc-500">
          <TickCountdownRing lastTickIso={lastTickIso} />
          <MarketClockBadge />
          <OnAirBadge />
          <span className="font-mono">last tick: {formatTickAt(lastTickIso)}</span>
          <span
            className={`font-mono ${wsStatus === "open" ? "text-emerald-500" : "text-zinc-600"}`}
            title="WebSocket status"
          >
            ws:{wsStatus}
          </span>
          <RankDistBadge />
          {lastTick && <span className="font-mono">· {lastTick}</span>}
          <button
            onClick={onManualTick}
            disabled={ticking}
            className="rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
          >
            {ticking ? "ticking…" : "Manual Tick"}
          </button>
          <button
            onClick={onOpenAdmin}
            className="rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700"
          >
            Admin
          </button>
        </div>
      </div>
    </header>
  );
}
