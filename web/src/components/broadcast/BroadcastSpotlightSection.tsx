import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api, type AgentRow, type Rank } from "../../api";

const REFRESH_MS = 5_000;
const PIN_SCENES: { id: "hero" | "brain"; label: string }[] = [
  { id: "hero", label: "Pin to Hero" },
  { id: "brain", label: "Pin to Brain" },
];

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

function rankLabel(rank: Rank | undefined): string {
  return rank ?? "intern";
}

export function BroadcastSpotlightSection(props: {
  isOnline: boolean;
  pinAgentId: number | null;
  scene: string | null;
  layoutMode: "scenes" | "v1-broadcast" | null;
}) {
  const { isOnline, pinAgentId, scene, layoutMode } = props;
  const inert = layoutMode === "v1-broadcast";

  const { data: agents } = useSWR<AgentRow[]>("agents", api.agents, {
    refreshInterval: REFRESH_MS,
  });

  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");
  const [lastPinScene, setLastPinScene] = useState<"hero" | "brain">("hero");

  // Optimistic pin — heartbeat is the source of truth but lags 5s.
  const [pendingPin, setPendingPin] = useState<number | null | undefined>(undefined);
  useEffect(() => {
    if (pendingPin !== undefined && pinAgentId === pendingPin) {
      setPendingPin(undefined);
    }
  }, [pinAgentId, pendingPin]);
  const activePin = pendingPin !== undefined ? pendingPin : pinAgentId;

  const filtered = useMemo(() => {
    const list = agents ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return list.slice(0, 50);
    return list
      .filter((a) => {
        if (String(a.id) === q) return true;
        if (a.name.toLowerCase().includes(q)) return true;
        if (String(a.id).includes(q)) return true;
        return false;
      })
      .slice(0, 50);
  }, [agents, query]);

  const pinnedAgent = useMemo(() => {
    if (activePin == null || !agents) return null;
    return agents.find((a) => a.id === activePin) ?? null;
  }, [agents, activePin]);

  const wrap = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const onPinAgent = (agent: AgentRow) => {
    // Pin into the currently-active scene when it's pin-aware (hero/brain);
    // otherwise default to hero. Avoids surprising the operator with a scene
    // flip when they're already on Brain and click another agent.
    const target: "hero" | "brain" = scene === "brain" ? "brain" : "hero";
    setPendingPin(agent.id);
    setLastPinScene(target);
    void wrap(`pin:${agent.id}`, () =>
      postCmd("stream_scene", { scene_id: target, pin_agent_id: agent.id }),
    );
  };

  const onPinScene = (sceneId: "hero" | "brain") => {
    if (activePin == null) return;
    setLastPinScene(sceneId);
    void wrap(`pin-scene:${sceneId}`, () =>
      postCmd("stream_scene", { scene_id: sceneId, pin_agent_id: activePin }),
    );
  };

  const onClear = () => {
    setPendingPin(null);
    const sceneId = scene ?? "hero";
    void wrap("pin-clear", () =>
      postCmd("stream_scene", { scene_id: sceneId, pin_agent_id: null }),
    );
  };

  const statusLine =
    activePin == null
      ? "No pin."
      : pinnedAgent
        ? `Pinned: agent ${pinnedAgent.id} — ${pinnedAgent.name}`
        : `Pinned: agent ${activePin}`;

  return (
    <div className={`space-y-3 ${inert ? "opacity-50 pointer-events-none" : ""}`}>
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Spotlight</div>
        <div className="font-mono text-[10px] text-zinc-500">
          {statusLine}
          {pendingPin !== undefined && pendingPin !== pinAgentId && (
            <span className="ml-1 text-zinc-600">(syncing…)</span>
          )}
        </div>
      </div>

      {inert && (
        <div className="text-[10px] font-mono text-zinc-500 italic">
          stream is in V1 Broadcast — spotlight doesn&apos;t apply
        </div>
      )}

      <input
        type="text"
        placeholder="Search agents by name or id"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        disabled={!isOnline || inert}
        className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500 disabled:opacity-50"
      />

      <div className="max-h-48 overflow-y-auto rounded-sm border border-zinc-800 bg-zinc-950/50">
        {filtered.length === 0 ? (
          <div className="px-2 py-3 text-center font-mono text-[10px] text-zinc-600">
            {agents == null ? "loading…" : "no matches"}
          </div>
        ) : (
          <ul className="divide-y divide-zinc-800">
            {filtered.map((a) => {
              const active = activePin === a.id;
              const pending = busy === `pin:${a.id}`;
              return (
                <li key={a.id}>
                  <button
                    onClick={() => onPinAgent(a)}
                    disabled={!isOnline || pending}
                    className={`flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs transition-colors disabled:opacity-50 ${
                      active
                        ? "bg-(--color-profit)/15 text-(--color-profit)"
                        : "text-zinc-100 hover:bg-zinc-800"
                    }`}
                  >
                    <span className="w-10 font-mono text-[10px] text-zinc-500">
                      #{a.id}
                    </span>
                    <span className="flex-1 truncate">{a.name}</span>
                    <span className="hidden font-mono text-[10px] text-zinc-500 sm:inline">
                      {a.strategy}
                    </span>
                    <span className="w-16 text-right font-mono text-[10px] uppercase tracking-wider text-zinc-500">
                      {rankLabel(a.rank)}
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-1.5">
        {PIN_SCENES.map((s) => {
          const pending = busy === `pin-scene:${s.id}`;
          const active = lastPinScene === s.id && activePin != null;
          const disabled = !isOnline || pending || activePin == null;
          return (
            <button
              key={s.id}
              onClick={() => onPinScene(s.id)}
              disabled={disabled}
              className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                active
                  ? "border-(--color-profit) bg-(--color-profit)/15 text-(--color-profit)"
                  : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
              }`}
            >
              {s.label}
            </button>
          );
        })}
        <button
          onClick={onClear}
          disabled={!isOnline || busy === "pin-clear" || activePin == null}
          className="rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:opacity-50"
        >
          Clear pin
        </button>
      </div>

      {err && (
        <div className="font-mono text-xs text-(--color-loss)">error: {err}</div>
      )}
    </div>
  );
}
