import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import Dashboard from "./dash/Dashboard";
import VodStudio from "./vod/VodStudio";
import { LiveProvider } from "./contexts/LiveContext";
import "./index.css";

// Three top-level surfaces:
//   #vod-studio/*  →  VodStudio   (post-production multi-tab app)
//   #legacy        →  App         (the original single-page dashboard, kept
//                                  as a safety net while the new dashboard
//                                  bakes in)
//   anything else  →  Dashboard   (the new multi-page dashboard — Today,
//                                  Episodes, Research, Admin)
function pickRoot() {
  const h = window.location.hash;
  if (h.startsWith("#vod-studio")) return "studio" as const;
  if (h === "#legacy") return "legacy" as const;
  return "dashboard" as const;
}

const initial = pickRoot();

async function render() {
  let node: React.ReactNode;
  if (initial === "studio") node = <VodStudio />;
  else if (initial === "legacy") {
    // Lazy-load so the legacy bundle doesn't ride along with the new
    // dashboard on every cold load.
    const { default: App } = await import("./App");
    node = <App />;
  } else node = <Dashboard />;
  // LiveProvider wraps every root so the legacy dashboard's multiple
  // /ws consumers (useEventFeed + useStreamState × 2) collapse onto one
  // shared socket. The provider opens the socket lazily — only when at
  // least one useLiveEvents consumer mounts — so the new dashboard and
  // VOD Studio, which use useVodSessionLive (their own /ws), don't pay
  // for an idle connection.
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <LiveProvider>{node}</LiveProvider>
    </StrictMode>,
  );
}

void render();

// Crossing a root boundary requires a full reload — each root owns its
// own state, mounts a different shell, and there's no shared layout to
// preserve. Within a root the hash is handled by the root's own router.
window.addEventListener("hashchange", () => {
  if (pickRoot() !== initial) window.location.reload();
});
