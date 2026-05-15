import { useMemo } from "react";
import type { AgentRow } from "../shared/api";
import type { StreamSnapshot } from "../hooks/useStreamData";

function fmtSign(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

const STANCE_COLOR: Record<string, string> = {
  trade: "bg-emerald-500/20 text-emerald-300 border-emerald-500/40",
  wait: "bg-zinc-700/40 text-zinc-300 border-zinc-700",
};

const BIAS_COLOR: Record<string, string> = {
  long: "text-(--color-profit)",
  short: "text-(--color-loss)",
  flat: "text-zinc-400",
};

/**
 * Brain scene: a 3×4 grid of cards showing the most-recently-thinking
 * agents. Each card displays the LSTM probability bars + the LLM overlay's
 * stance / bias / size and the (truncated) reason text.
 *
 * When `pinAgentId` is set we force that agent into slot 0 (even if they have
 * no decision/lstm activity) and cap the rest to 11 so the grid still totals 12.
 */
export function BrainScene({
  snapshot,
  pinAgentId,
}: {
  snapshot: StreamSnapshot;
  pinAgentId: number | null;
}) {
  const cards = useMemo(() => {
    const pinned = pinAgentId != null ? snapshot.agents.find((a) => a.id === pinAgentId) ?? null : null;
    const rest = [...snapshot.agents]
      .filter((a) => (a.last_decision || a.last_lstm) && (!pinned || a.id !== pinned.id))
      .sort((x, y) => activityScore(y) - activityScore(x));
    if (pinned) return [pinned, ...rest.slice(0, 11)];
    return rest.slice(0, 12);
  }, [snapshot.agents, pinAgentId]);

  return (
    <div className="absolute inset-0 px-8 py-6 overflow-hidden">
      <header className="flex items-baseline justify-between mb-5">
        <h2 className="text-3xl font-bold tracking-tight">
          Brain <span className="text-(--color-profit)">Activity</span>
        </h2>
        <span className="text-xs text-zinc-500 font-mono uppercase tracking-widest">
          last LLM decision per agent · top 12 most active
        </span>
      </header>
      <div className="grid grid-cols-3 gap-4">
        {cards.length === 0 && (
          <div className="col-span-3 text-zinc-600 font-mono text-sm">
            No LLM activity yet — agents are waiting for the next tick.
          </div>
        )}
        {cards.map((a) => (
          <BrainCard key={a.id} agent={a} pinned={pinAgentId != null && a.id === pinAgentId} />
        ))}
      </div>
    </div>
  );
}

function activityScore(a: AgentRow): number {
  if (a.last_decision?.stance === "trade") return 3;
  if (a.last_decision) return 2;
  if (a.last_lstm) return 1;
  return 0;
}

function BrainCard({ agent, pinned = false }: { agent: AgentRow; pinned?: boolean }) {
  const d = agent.last_decision;
  const l = agent.last_lstm;
  const total = agent.realized_pnl + agent.unrealized_pnl;

  return (
    <div
      className={`relative rounded-lg p-3 flex flex-col gap-2 min-h-[155px] ${
        pinned
          ? "border border-emerald-500/60 bg-emerald-950/20 ring-2 ring-emerald-500/40 shadow-lg shadow-emerald-900/20"
          : "border border-zinc-800 bg-zinc-900/40"
      }`}
    >
      {pinned && (
        <span className="absolute -top-2 -right-2 z-10 rounded-full bg-emerald-500 px-2 py-0.5 text-[9px] font-mono font-bold uppercase tracking-widest text-zinc-950 shadow">
          Pinned
        </span>
      )}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          <span className="font-semibold truncate">{agent.name}</span>
          {agent.symbol && (
            <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-500">
              {agent.symbol}
            </span>
          )}
        </div>
        <span
          className={`tabular-nums font-mono text-xs font-semibold ${total >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}
        >
          {fmtSign(total, 0)}
        </span>
      </div>

      {l && (
        <div className="flex items-center gap-1">
          {l.probs.map((p, i) => {
            const labels = ["UP", "FLAT", "DN"];
            const colors = ["bg-emerald-500/70", "bg-zinc-500/60", "bg-rose-500/70"];
            return (
              <div key={i} className="flex-1">
                <div className="h-1.5 bg-zinc-900 rounded">
                  <div
                    className={`h-full rounded ${colors[i]}`}
                    style={{ width: `${(p * 100).toFixed(1)}%` }}
                  />
                </div>
                <div className="flex justify-between text-[9px] text-zinc-500 font-mono mt-0.5">
                  <span>{labels[i]}</span>
                  <span className="tabular-nums">{(p * 100).toFixed(0)}%</span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {d ? (
        <>
          <div className="flex items-center gap-2 text-[11px] font-mono">
            <span
              className={`px-1.5 py-0.5 rounded border ${STANCE_COLOR[d.stance] ?? STANCE_COLOR.wait}`}
            >
              {d.stance.toUpperCase()}
            </span>
            <span className={`uppercase ${BIAS_COLOR[d.bias] ?? "text-zinc-400"}`}>
              {d.bias}
            </span>
            {d.size_pct > 0 && (
              <span className="text-zinc-500">size {(d.size_pct * 100).toFixed(0)}%</span>
            )}
          </div>
          <p className="text-[12px] text-zinc-300 leading-snug line-clamp-3">
            {d.reason || "—"}
          </p>
        </>
      ) : (
        <div className="text-[11px] text-zinc-600 font-mono italic">
          waiting for LLM overlay…
        </div>
      )}
    </div>
  );
}
