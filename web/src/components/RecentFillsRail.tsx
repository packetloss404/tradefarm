import { LiveBadge, Panel } from "./Panel";
import type { LiveEvent } from "../hooks/useLiveEvents";

type FillEvent = Extract<LiveEvent, { type: "fill" }>;

function ageLabel(iso: string): string {
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.round(sec / 60)}m`;
  return `${Math.round(sec / 3600)}h`;
}

function fmtPrice(n: number): string {
  return n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function fmtNotional(n: number): string {
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  return `$${n.toFixed(0)}`;
}

export function RecentFillsRail({ fills }: { fills: FillEvent[] }) {
  return (
    <Panel
      title="Live Fills"
      badge={<LiveBadge />}
      right={<span className="text-[10px] text-zinc-500 font-mono">{fills.length} recent</span>}
      className="flex flex-col h-full"
    >
      {fills.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-xs text-zinc-600 font-mono">
          no fills yet
        </div>
      ) : (
        <ul className="flex-1 overflow-y-auto divide-y divide-zinc-800/70 -mr-2 pr-2">
          {fills.map((ev, i) => {
            const p = ev.payload;
            const buy = p.side === "buy";
            const tone = buy ? "text-(--color-profit)" : "text-(--color-loss)";
            const sideLabel = buy ? "BUY" : "SELL";
            const notional = Math.abs(p.qty * p.price);
            return (
              <li
                key={`${ev.ts}-${p.agent_id}-${p.symbol}-${i}`}
                className="grid grid-cols-[auto_1fr_auto] items-center gap-2 py-2 text-xs"
              >
                <span className="font-mono text-[10px] text-zinc-500 tabular-nums w-8">
                  {ageLabel(ev.ts)}
                </span>
                <div className="min-w-0">
                  <div className="flex items-baseline gap-1.5">
                    <span className={`font-bold tabular-nums ${tone}`}>{sideLabel}</span>
                    <span className="font-semibold text-zinc-100">{p.symbol}</span>
                    <span className="font-mono text-[10px] text-zinc-500">
                      a{p.agent_id}
                    </span>
                  </div>
                  <div className="font-mono text-[10px] text-zinc-500 tabular-nums">
                    {p.qty} @ ${fmtPrice(p.price)}
                  </div>
                </div>
                <span className="font-mono text-[11px] tabular-nums text-zinc-300">
                  {fmtNotional(notional)}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
