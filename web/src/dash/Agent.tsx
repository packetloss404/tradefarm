// 0.29.0 — per-agent routed page.
//
// Renders the existing AgentDetailModal in a full-page layout
// (the modal was promoted to a routed page so the URL is
// deep-linkable: #agent/123). The page is responsible for:
//   - looking up the agent row by id from the live agents list,
//   - rendering a header (back link, agent identity),
//   - mounting the modal in "full-page" mode (no overlay, no
//     close-on-click-outside — the back link is the only close
//     affordance, matching the AdminPage's #admin pattern).
//
// Unknown / not-yet-loaded agent id -> a friendly loading state
// that re-renders on every 1s tick so the page never gets stuck
// behind a stale `agents` array.

import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, type AgentRow } from "../api";
import { AgentDetailModal } from "../components/AgentDetailModal";
import { useHashRoute, type DashRouteState } from "./useHashRoute";

const POLL_MS = 1_000;

export function AgentPage() {
  const [route, go] = useHashRoute("today");
  const agentId = route.route === "agent" ? Number(route.param) : null;

  const { data: agents } = useSWR<AgentRow[]>("agents", api.agents, {
    refreshInterval: POLL_MS,
  });
  // Keep a per-id last-seen snapshot so a transient re-render
  // (e.g. an agents refetch that briefly returns 0 rows) doesn't
  // blank the page.
  const [lastSeen, setLastSeen] = useState<AgentRow | null>(null);
  useEffect(() => {
    if (agentId === null || !agents) return;
    const found = agents.find((a) => a.id === agentId);
    if (found) setLastSeen(found);
  }, [agentId, agents]);

  const back = () => go({ route: "today", param: null } as DashRouteState);

  if (agentId === null) {
    // Should never happen — the router only routes to AgentPage
    // when the route is 'agent'. Defensive: render a back link.
    return (
      <div style={{ padding: 24 }}>
        <a href="#today" className="text-emerald-400 underline">back</a>
      </div>
    );
  }

  if (!lastSeen) {
    return (
      <div style={{ padding: 24, color: "#a1a1aa" }}>
        <button
          onClick={back}
          className="mb-3 rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
        >
          ← back
        </button>
        <div className="text-sm">loading agent #{agentId}…</div>
      </div>
    );
  }

  return (
    <div style={{ padding: 24, maxWidth: 1200, margin: "0 auto" }}>
      <header className="mb-4 flex items-center justify-between border-b border-zinc-800 pb-3">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-zinc-500">
            agent profile
          </div>
          <h1 className="text-xl font-semibold text-zinc-100">
            {lastSeen.name}{" "}
            <span className="text-xs text-zinc-500">#{lastSeen.id}</span>
          </h1>
        </div>
        <button
          onClick={back}
          className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
        >
          ← back to dashboard
        </button>
      </header>
      <AgentDetailModal agent={lastSeen} onClose={back} />
    </div>
  );
}
