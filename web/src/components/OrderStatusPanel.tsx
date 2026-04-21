import useSWR from "swr";
import { api, type OrderStatus } from "../api";

const pillClass: Record<OrderStatus["status"], string> = {
  filled: "bg-emerald-600/20 text-(--color-profit)",
  partially_filled: "bg-amber-600/20 text-amber-400",
  new: "bg-zinc-700/40 text-zinc-300",
  accepted: "bg-zinc-700/40 text-zinc-300",
  pending_new: "bg-zinc-700/40 text-zinc-300",
  canceled: "bg-zinc-800/60 text-zinc-500",
  rejected: "bg-rose-600/20 text-(--color-loss)",
};

const sideTone: Record<OrderStatus["side"], string> = {
  buy: "text-(--color-profit)",
  sell: "text-(--color-loss)",
};

function relTime(iso: string): string {
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

function ShimmerRows() {
  return (
    <div className="space-y-1.5">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-7 w-full animate-pulse rounded bg-zinc-800/60" />
      ))}
    </div>
  );
}

export function OrderStatusPanel() {
  const { data, error, isLoading } = useSWR<OrderStatus[]>(
    "orders",
    () => api.orders(25),
    { refreshInterval: 3_000 },
  );

  if (error) {
    return (
      <div className="rounded border border-rose-900/50 bg-rose-950/20 px-3 py-2 text-xs text-(--color-loss)">
        Failed to load orders: {(error as Error).message}
      </div>
    );
  }

  if (isLoading || !data) return <ShimmerRows />;

  if (data.length === 0) {
    return (
      <div className="rounded border border-zinc-800 bg-zinc-900/40 px-3 py-4 text-center text-xs italic text-zinc-500">
        No orders yet — switch EXECUTION_MODE=alpaca_paper and wait for a signal.
      </div>
    );
  }

  const sorted = [...data].sort(
    (a, b) => new Date(b.submitted_at).getTime() - new Date(a.submitted_at).getTime(),
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-zinc-800 text-left text-[10px] uppercase tracking-wider text-zinc-500">
            <th className="py-1.5 pr-2 font-medium">Agent</th>
            <th className="py-1.5 pr-2 font-medium">Symbol</th>
            <th className="py-1.5 pr-2 font-medium">Side</th>
            <th className="py-1.5 pr-2 text-right font-medium">Filled / Qty</th>
            <th className="py-1.5 pr-2 text-right font-medium">Avg Fill</th>
            <th className="py-1.5 pr-2 font-medium">Status</th>
            <th className="py-1.5 pr-0 text-right font-medium">Submitted</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((o) => (
            <tr key={o.broker_order_id} className="border-b border-zinc-900 last:border-0 hover:bg-zinc-900/40">
              <td className="py-1.5 pr-2 font-mono text-zinc-400">
                {o.agent_id === null ? "—" : o.agent_id.toString().padStart(3, "0")}
              </td>
              <td className="py-1.5 pr-2 font-mono text-zinc-200">{o.symbol}</td>
              <td className={`py-1.5 pr-2 font-mono uppercase ${sideTone[o.side]}`}>{o.side}</td>
              <td className="py-1.5 pr-2 text-right font-mono tabular-nums text-zinc-300">
                {o.filled_qty}/{o.qty}
              </td>
              <td className="py-1.5 pr-2 text-right font-mono tabular-nums text-zinc-300">
                {o.filled_avg_price === null ? "—" : `$${o.filled_avg_price.toFixed(2)}`}
              </td>
              <td className="py-1.5 pr-2">
                <span className={`rounded-sm px-1.5 py-0.5 text-[10px] font-bold uppercase ${pillClass[o.status]}`}>
                  {o.status.replace("_", " ")}
                </span>
              </td>
              <td className="py-1.5 pr-0 text-right font-mono text-zinc-500">{relTime(o.submitted_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
