import useSWR from "swr";
import { api, type AgentNote } from "../api";

function rel(iso: string | null): string {
  if (!iso) return "—";
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

function kindLabel(k: string): string {
  if (k === "entry") return "ENTRY";
  if (k === "exit") return "EXIT";
  return "OBS";
}

function kindTone(k: string): string {
  if (k === "entry") return "text-(--color-profit)";
  if (k === "exit") return "text-(--color-loss)";
  return "text-zinc-400";
}

export function AgentJournalSection({ agentId }: { agentId: number }) {
  const { data: notes } = useSWR<AgentNote[]>(
    `agent-notes-${agentId}`,
    () => api.agentNotes(agentId, 20),
    { refreshInterval: 5_000 },
  );

  return (
    <section className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-400">
        Journal{notes ? ` (${notes.length})` : ""}
      </div>
      {!notes ? (
        <div className="text-xs text-zinc-500">loading…</div>
      ) : notes.length === 0 ? (
        <div className="text-xs italic text-zinc-500">no notes yet</div>
      ) : (
        <ul className="divide-y divide-zinc-800 text-xs">
          {notes.map((n) => {
            const resolved = n.outcome_closed_at !== null && n.outcome_realized_pnl !== null;
            const pnl = n.outcome_realized_pnl ?? 0;
            const pnlTone = pnl >= 0 ? "text-(--color-profit)" : "text-(--color-loss)";
            return (
              <li key={n.id} className="flex items-start gap-2 py-1.5 font-mono">
                <span className={`w-12 shrink-0 ${kindTone(n.kind)}`}>{kindLabel(n.kind)}</span>
                <span className="w-12 shrink-0 text-zinc-300">{n.symbol}</span>
                <span
                  className="flex-1 truncate text-zinc-300 hover:whitespace-normal hover:text-zinc-100"
                  title={n.content}
                  style={{
                    display: "-webkit-box",
                    WebkitLineClamp: 2,
                    WebkitBoxOrient: "vertical",
                    overflow: "hidden",
                  }}
                >
                  {n.content || <span className="italic text-zinc-500">(no body)</span>}
                </span>
                <span className="w-20 shrink-0 text-right text-zinc-500">
                  {rel(n.created_at)}
                </span>
                {resolved ? (
                  <span
                    className={`w-28 shrink-0 rounded border border-zinc-800 bg-zinc-900 px-1.5 py-0.5 text-right tabular-nums ${pnlTone}`}
                    title="realized P&L"
                  >
                    {pnl >= 0 ? "+" : ""}${pnl.toFixed(2)} realized
                  </span>
                ) : (
                  <span className="w-28 shrink-0 text-right text-zinc-600 italic">open</span>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
