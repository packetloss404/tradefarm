import { useMemo, useState } from "react";
import useSWR from "swr";
import { api, type AgentRow } from "../api";

const REFRESH_MS = 3_000;

type PinRequest = {
  id: string;
  requester: string;
  agent_id: number | null;
  agent_name_query: string;
  requested_at: string;
};

const requestsFetcher = async (url: string): Promise<PinRequest[]> => {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<PinRequest[]>;
};

async function postResolve(
  id: string,
  action: "approve" | "reject",
  agentId?: number,
): Promise<void> {
  const body = agentId != null ? JSON.stringify({ agent_id: agentId }) : undefined;
  const r = await fetch(`/api/audience/pin-requests/${encodeURIComponent(id)}/${action}`, {
    method: "POST",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body,
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

function relativeAge(iso: string): string {
  const ts = Date.parse(iso);
  if (!Number.isFinite(ts)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

/**
 * Operator queue for audience-driven pin requests. The audience asks for an
 * agent via chat, the backend extracts a name/id query and emits a pending
 * request; this panel surfaces them and lets the operator approve/reject.
 *
 * When the backend couldn't resolve the agent (`agent_id === null`), an
 * inline picker lets the operator pick manually. Approval propagates the
 * pin to the stream via the existing `stream_scene` heartbeat — we don't
 * fire a separate dashboard-side scene command.
 */
export function AudienceRequestsPanel() {
  const { data: requests, mutate } = useSWR<PinRequest[]>(
    "/api/audience/pin-requests",
    requestsFetcher,
    { refreshInterval: REFRESH_MS },
  );

  const { data: agents } = useSWR<AgentRow[]>("agents", api.agents);

  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");

  const wrap = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
      await mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const list = requests ?? [];

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          Audience requests
        </div>
        <div className="font-mono text-[10px] text-zinc-500">
          {list.length === 0 ? "queue empty" : `${list.length} pending`}
        </div>
      </div>

      {list.length === 0 ? (
        <div className="rounded-sm border border-dashed border-zinc-800 bg-zinc-950/40 px-3 py-4 text-center font-mono text-[11px] text-zinc-600">
          No audience requests yet.
        </div>
      ) : (
        <ul className="space-y-2">
          {list.map((req) => (
            <RequestRow
              key={req.id}
              req={req}
              agents={agents ?? []}
              busyKey={busy}
              onApprove={(agentId) =>
                wrap(`approve:${req.id}`, () => postResolve(req.id, "approve", agentId))
              }
              onReject={() => wrap(`reject:${req.id}`, () => postResolve(req.id, "reject"))}
            />
          ))}
        </ul>
      )}

      {err && (
        <div className="font-mono text-xs text-(--color-loss)">error: {err}</div>
      )}
    </div>
  );
}

function RequestRow({
  req,
  agents,
  busyKey,
  onApprove,
  onReject,
}: {
  req: PinRequest;
  agents: AgentRow[];
  busyKey: string;
  onApprove: (agentId?: number) => void;
  onReject: () => void;
}) {
  // Local manual-pick state — only relevant when the backend couldn't resolve
  // an agent itself. We keep the picker collapsed by default to avoid filling
  // the panel with noise when every request resolved cleanly.
  const [picking, setPicking] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<number | null>(null);

  const resolved = req.agent_id != null;
  const effectiveAgentId = resolved ? req.agent_id : picked;
  const approveDisabled =
    busyKey === `approve:${req.id}` || effectiveAgentId == null;
  const rejectDisabled = busyKey === `reject:${req.id}`;

  const resolvedAgent = useMemo(() => {
    if (effectiveAgentId == null) return null;
    return agents.find((a) => a.id === effectiveAgentId) ?? null;
  }, [agents, effectiveAgentId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return agents.slice(0, 20);
    return agents
      .filter((a) => {
        if (String(a.id) === q) return true;
        if (a.name.toLowerCase().includes(q)) return true;
        if (String(a.id).includes(q)) return true;
        return false;
      })
      .slice(0, 20);
  }, [agents, query]);

  return (
    <li className="rounded-sm border border-zinc-800 bg-zinc-950/50 px-2.5 py-2">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-1.5 text-xs">
            <span className="font-semibold text-zinc-100 truncate">{req.requester}</span>
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-300 truncate">{req.agent_name_query}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5 font-mono text-[10px]">
            {resolved ? (
              <span className="px-1.5 py-px rounded-sm bg-emerald-500/15 text-(--color-profit)">
                #{req.agent_id}
                {resolvedAgent ? ` ${resolvedAgent.name}` : ""}
              </span>
            ) : picked != null ? (
              <span className="px-1.5 py-px rounded-sm bg-amber-500/15 text-amber-400">
                manual: #{picked}
                {resolvedAgent ? ` ${resolvedAgent.name}` : ""}
              </span>
            ) : (
              <span className="px-1.5 py-px rounded-sm bg-rose-500/15 text-(--color-loss)">
                unresolved
              </span>
            )}
            <span className="text-zinc-600">·</span>
            <span className="text-zinc-500">{relativeAge(req.requested_at)}</span>
          </div>
        </div>

        <div className="flex shrink-0 items-center gap-1">
          <button
            onClick={() => onApprove(effectiveAgentId ?? undefined)}
            disabled={approveDisabled}
            className="rounded-sm border border-emerald-500/40 bg-emerald-500/10 px-2 py-1 text-[11px] font-medium text-(--color-profit) transition-colors hover:bg-emerald-500/20 disabled:opacity-40"
          >
            ✓ Approve
          </button>
          <button
            onClick={onReject}
            disabled={rejectDisabled}
            className="rounded-sm border border-rose-500/40 bg-rose-500/10 px-2 py-1 text-[11px] font-medium text-(--color-loss) transition-colors hover:bg-rose-500/20 disabled:opacity-40"
          >
            ✗ Reject
          </button>
        </div>
      </div>

      {!resolved && (
        <div className="mt-2 border-t border-zinc-800 pt-2">
          {!picking ? (
            <button
              onClick={() => setPicking(true)}
              className="text-[10px] font-mono uppercase tracking-wider text-zinc-500 hover:text-zinc-300"
            >
              Pick agent manually →
            </button>
          ) : (
            <div className="space-y-1.5">
              <input
                type="text"
                placeholder="Search agents by name or id"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
                className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
              />
              <div className="max-h-32 overflow-y-auto rounded-sm border border-zinc-800 bg-zinc-950/60">
                {filtered.length === 0 ? (
                  <div className="px-2 py-2 text-center font-mono text-[10px] text-zinc-600">
                    {agents.length === 0 ? "loading…" : "no matches"}
                  </div>
                ) : (
                  <ul className="divide-y divide-zinc-800">
                    {filtered.map((a) => {
                      const active = picked === a.id;
                      return (
                        <li key={a.id}>
                          <button
                            onClick={() => setPicked(a.id)}
                            className={`flex w-full items-center gap-2 px-2 py-1 text-left text-[11px] transition-colors ${
                              active
                                ? "bg-(--color-profit)/15 text-(--color-profit)"
                                : "text-zinc-100 hover:bg-zinc-800"
                            }`}
                          >
                            <span className="w-9 font-mono text-[10px] text-zinc-500">
                              #{a.id}
                            </span>
                            <span className="flex-1 truncate">{a.name}</span>
                            <span className="hidden font-mono text-[10px] text-zinc-500 sm:inline">
                              {a.strategy}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
