// Hash router for the dashboard. Strips the leading `#` and returns the
// raw route id; `go(id)` pushes via `window.location.hash`. Recognises
// only the four dashboard pages — anything else (notably `#vod-studio`)
// is handled by main.tsx before this hook ever sees the URL.

import { useCallback, useEffect, useState } from "react";

export type DashRoute = "today" | "episodes" | "research" | "admin";

const VALID: DashRoute[] = ["today", "episodes", "research", "admin"];

function read(defaultId: DashRoute): DashRoute {
  const raw = (window.location.hash || `#${defaultId}`).slice(1);
  return (VALID as readonly string[]).includes(raw) ? (raw as DashRoute) : defaultId;
}

export function useHashRoute(defaultId: DashRoute = "today"): [DashRoute, (id: DashRoute) => void] {
  const [route, setRoute] = useState<DashRoute>(() => read(defaultId));
  useEffect(() => {
    const onChange = () => setRoute(read(defaultId));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, [defaultId]);
  const go = useCallback((id: DashRoute) => {
    window.location.hash = `#${id}`;
  }, []);
  return [route, go];
}
