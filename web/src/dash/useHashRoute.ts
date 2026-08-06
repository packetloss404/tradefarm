// Hash router for the dashboard. Strips the leading `#` and returns
// the raw route id (and, for nested routes like `#agent/123`, the
// trailing path segment as a string param). `go(state)` pushes via
// `window.location.hash`. Recognises the four dashboard pages plus a
// deep-linkable `#agent/<id>` route that the AgentPage component uses
// to deep-link a single-agent view.

import { useCallback, useEffect, useState } from "react";

export type DashRoute = "today" | "episodes" | "research" | "admin" | "agent";

const SIMPLE_VALID: DashRoute[] = ["today", "episodes", "research", "admin"];

export type DashRouteState =
  | { route: "today"; param: null }
  | { route: "episodes"; param: null }
  | { route: "research"; param: null }
  | { route: "admin"; param: null }
  | { route: "agent"; param: string };

function read(defaultId: DashRoute = "today"): DashRouteState {
  const raw = (window.location.hash || `#${defaultId}`).slice(1);
  if ((SIMPLE_VALID as readonly string[]).includes(raw)) {
    return { route: raw as Exclude<DashRoute, "agent">, param: null };
  }
  // Nested: agent/<id>
  const parts = raw.split("/");
  if (parts.length === 2 && parts[0] === "agent" && /^\d+$/.test(parts[1]!)) {
    return { route: "agent", param: parts[1]! };
  }
  // Unknown hash -> fall through to the default.
  return {
    route: defaultId as Exclude<DashRoute, "agent">,
    param: null,
  };
}

export function useHashRoute(
  defaultId: DashRoute = "today",
): [DashRouteState, (state: DashRouteState) => void] {
  const [state, setState] = useState<DashRouteState>(() => read(defaultId));
  useEffect(() => {
    const onChange = () => setState(read(defaultId));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, [defaultId]);
  const go = useCallback((next: DashRouteState) => {
    window.location.hash =
      next.param === null ? `#${next.route}` : `#${next.route}/${next.param}`;
  }, []);
  return [state, go];
}
