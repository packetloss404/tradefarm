import type { AgentRow } from "../api";

const dotClass: Record<AgentRow["status"], string> = {
  profit: "bg-(--color-profit)",
  loss: "bg-(--color-loss)",
  waiting: "bg-(--color-wait)",
  trading: "bg-amber-400",
};

export function AgentGrid({ agents, onSelect }: { agents: AgentRow[]; onSelect?: (a: AgentRow) => void }) {
  return (
    <div className="grid grid-cols-10 gap-1.5">
      {agents.map((a) => {
        const symbols = Object.keys(a.positions);
        const sym = symbols[0];
        const pos = sym ? a.positions[sym]! : null;
        const tooltip = [
          a.name,
          a.strategy,
          `cash=$${a.cash.toFixed(2)} equity=$${a.equity.toFixed(2)}`,
          pos ? `holds ${pos.qty} ${sym} avg=${pos.avg_price.toFixed(2)} mark=${pos.mark.toFixed(2)}` : "",
          a.realized_pnl ? `realized $${a.realized_pnl.toFixed(2)}` : "",
          a.unrealized_pnl ? `unrealized $${a.unrealized_pnl.toFixed(2)}` : "",
        ].filter(Boolean).join("\n");
        return (
          <button
            key={a.id}
            type="button"
            title={tooltip}
            onClick={() => onSelect?.(a)}
            className="flex h-10 flex-col items-center justify-center gap-0.5 rounded border border-zinc-800 bg-zinc-900/40 hover:border-zinc-500 hover:bg-zinc-800/60 cursor-pointer focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            <span className={`size-1.5 rounded-full ${dotClass[a.status]}`} />
            <span className="text-[9px] font-mono text-zinc-500">{a.id.toString().padStart(3, "0")}</span>
          </button>
        );
      })}
    </div>
  );
}
