import { useEffect } from "react";
import useSWR from "swr";
import { api, type AgentRow, type AgentTrade } from "../api";
import { AgentJournalSection } from "./AgentJournalSection";

const DIR_TONE: Record<string, string> = {
  up: "text-(--color-profit)",
  long: "text-(--color-profit)",
  down: "text-(--color-loss)",
  short: "text-(--color-loss)",
  flat: "text-(--color-wait)",
};

function fmt(n: number | undefined, digits = 2): string {
  if (n === undefined || n === null) return "—";
  return n.toFixed(digits);
}

function rel(iso: string | null): string {
  if (!iso) return "—";
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

export function AgentDetailModal({ agent, onClose }: { agent: AgentRow; onClose: () => void }) {
  const { data: trades } = useSWR<AgentTrade[]>(
    `agent-trades-${agent.id}`,
    () => api.agentTrades(agent.id, 20),
    { refreshInterval: 5_000 },
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const totalPnl = agent.realized_pnl + agent.unrealized_pnl;
  const pos = Object.entries(agent.positions)[0];
  const lstm = agent.last_lstm;
  const dec = agent.last_decision;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="w-[640px] max-w-[92vw] max-h-[88vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
          <div>
            <div className="font-mono text-lg font-semibold">{agent.name}</div>
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">
              {agent.strategy} · status {agent.status}
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
            aria-label="close"
          >
            esc
          </button>
        </header>

        <div className="space-y-4 p-5">
          {/* P&L row */}
          <div className="grid grid-cols-4 gap-3">
            <KV label="Equity" value={`$${fmt(agent.equity)}`} />
            <KV label="Cash" value={`$${fmt(agent.cash)}`} />
            <KV
              label="Realized"
              value={`${agent.realized_pnl >= 0 ? "+" : ""}${fmt(agent.realized_pnl, 4)}`}
              tone={agent.realized_pnl >= 0 ? "profit" : "loss"}
            />
            <KV
              label="Unrealized"
              value={`${agent.unrealized_pnl >= 0 ? "+" : ""}${fmt(agent.unrealized_pnl, 4)}`}
              tone={agent.unrealized_pnl >= 0 ? "profit" : "loss"}
            />
          </div>
          <div className="rounded-md border border-zinc-800 bg-zinc-950 p-3 text-sm">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Total P&L vs $1,000 start</div>
            <div className={`font-mono text-xl font-semibold tabular-nums ${totalPnl >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}>
              {totalPnl >= 0 ? "+" : ""}${fmt(totalPnl, 4)}
              <span className="ml-2 text-xs text-zinc-500">
                ({((totalPnl / 1000) * 100).toFixed(3)}%)
              </span>
            </div>
          </div>

          {/* Position */}
          <Section label="Position">
            {pos ? (
              (() => {
                const [sym, p] = pos;
                const upl = p.qty * (p.mark - p.avg_price);
                return (
                  <div className="grid grid-cols-5 gap-3 text-xs font-mono">
                    <KV label="Symbol" value={sym} />
                    <KV label="Qty" value={fmt(p.qty, 4)} />
                    <KV label="Avg" value={`$${fmt(p.avg_price)}`} />
                    <KV label="Mark" value={`$${fmt(p.mark)}`} />
                    <KV
                      label="MTM P&L"
                      value={`${upl >= 0 ? "+" : ""}${fmt(upl, 4)}`}
                      tone={upl >= 0 ? "profit" : "loss"}
                    />
                  </div>
                );
              })()
            ) : (
              <div className="text-xs italic text-zinc-500">no open position</div>
            )}
          </Section>

          {/* LSTM */}
          {lstm && (
            <Section label="LSTM">
              <div className="flex items-baseline gap-4 text-xs font-mono">
                <span className={DIR_TONE[lstm.direction] ?? ""}>bias {lstm.direction.toUpperCase()}</span>
                <span className="text-zinc-400">
                  probs down/flat/up ={" "}
                  <span className="tabular-nums">
                    {lstm.probs.map((p) => p.toFixed(2)).join(" / ")}
                  </span>
                </span>
                <span className="text-zinc-400">conf {lstm.confidence.toFixed(2)}</span>
              </div>
            </Section>
          )}

          {/* LLM decision */}
          {dec && (
            <Section label="LLM Decision">
              <div className="space-y-2 text-xs">
                <div className="flex items-baseline gap-4 font-mono">
                  <span className={DIR_TONE[dec.bias] ?? ""}>BIAS {dec.bias.toUpperCase()}</span>
                  <span className={DIR_TONE[dec.predictive] ?? ""}>PRED {dec.predictive.toUpperCase()}</span>
                  <span className={dec.stance === "trade" ? "text-amber-400" : "text-zinc-400"}>
                    STANCE {dec.stance.toUpperCase()}
                  </span>
                  <span className="text-zinc-400">size {(dec.size_pct * 100).toFixed(1)}%</span>
                </div>
                <div className="rounded border border-zinc-800 bg-zinc-950 px-3 py-2 text-zinc-300">
                  “{dec.reason}”
                </div>
              </div>
            </Section>
          )}

          {/* Trades */}
          <Section label={`Recent Trades${trades ? ` (${trades.length})` : ""}`}>
            {!trades ? (
              <div className="text-xs text-zinc-500">loading…</div>
            ) : trades.length === 0 ? (
              <div className="text-xs italic text-zinc-500">no trades yet</div>
            ) : (
              <ul className="divide-y divide-zinc-800 text-xs font-mono">
                {trades.map((t) => (
                  <li key={t.id} className="flex items-baseline justify-between gap-3 py-1.5">
                    <span className={t.side === "buy" ? "text-(--color-profit) w-10" : "text-(--color-loss) w-10"}>
                      {t.side.toUpperCase()}
                    </span>
                    <span className="w-12 text-zinc-300">{t.symbol}</span>
                    <span className="w-20 text-right tabular-nums text-zinc-300">{fmt(t.qty, 4)}</span>
                    <span className="w-20 text-right tabular-nums text-zinc-300">${fmt(t.price)}</span>
                    <span className="w-20 text-right text-zinc-500">{rel(t.executed_at)}</span>
                    <span className="flex-1 truncate text-zinc-500" title={t.reason}>{t.reason}</span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          {/* Journal (Phase 1 — Agent Academy) */}
          <AgentJournalSection agentId={agent.id} />
        </div>
      </div>
    </div>
  );
}

function KV({ label, value, tone }: { label: string; value: string; tone?: "profit" | "loss" }) {
  const toneClass = tone === "profit" ? "text-(--color-profit)" : tone === "loss" ? "text-(--color-loss)" : "text-zinc-100";
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${toneClass}`}>{value}</div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-400">{label}</div>
      {children}
    </section>
  );
}
