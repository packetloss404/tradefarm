// Top-level dashboard shell. Owns theme provider, hash routing, the
// shared live-data hook, and the tweaks panel.

import { useEffect, useMemo, useState } from "react";
import { DENSITY, TOKENS } from "./tokens";
import { ThemeProvider } from "./ThemeContext";
import { DashNav, TweaksButton, TweaksPanel } from "./Shell";
import { useHashRoute } from "./useHashRoute";
import { useDashTweaks } from "./useDashTweaks";
import { useVodSessionLive } from "../vod/useVodSessionLive";
import { TodayPage } from "./Today";
import { EpisodesPage } from "./Episodes";
import { ResearchPage } from "./Research";
import { AdminPage } from "./Admin";
import { AgentPage } from "./Agent";

// One-time amber-CRT scanline overlay. Conditional on body[data-theme]
// so the dark / light themes don't pay for it.
if (typeof document !== "undefined" && !document.getElementById("dash-style")) {
  const s = document.createElement("style");
  s.id = "dash-style";
  s.textContent = `
    body[data-dash-theme="amber-crt"]::before {
      content: ""; position: fixed; inset: 0; pointer-events: none;
      background: repeating-linear-gradient(0deg, rgba(255,179,71,0.06) 0 1px, transparent 1px 3px);
      z-index: 1000;
    }
  `;
  document.head.appendChild(s);
}

export default function Dashboard() {
  // Live data backs the whole dashboard — Today reads it densely, the
  // other pages read summary stats off the same VodSessionLive shape.
  const vod = useVodSessionLive();
  const [route, go] = useHashRoute("today");
  const [tweaks, setTweak] = useDashTweaks();
  const [tweaksOpen, setTweaksOpen] = useState(false);

  // Push the theme onto <body> so the scanline ::before can switch on
  // it, and so the page background paints behind the React tree even
  // when the viewport is taller than the content.
  useEffect(() => {
    const prevTheme = document.body.getAttribute("data-dash-theme");
    document.body.setAttribute("data-dash-theme", tweaks.theme);
    const prevBg = document.body.style.background;
    document.body.style.background = TOKENS[tweaks.theme].bg;
    return () => {
      if (prevTheme) document.body.setAttribute("data-dash-theme", prevTheme);
      else document.body.removeAttribute("data-dash-theme");
      document.body.style.background = prevBg;
    };
  }, [tweaks.theme]);

  const ctxValue = useMemo(
    () => ({ T: TOKENS[tweaks.theme], D: DENSITY[tweaks.density] }),
    [tweaks.theme, tweaks.density],
  );

  const page = (() => {
    switch (route.route) {
      case "episodes":
        return <EpisodesPage />;
      case "research":
        return <ResearchPage vod={vod} />;
      case "admin":
        return <AdminPage />;
      case "agent":
        return <AgentPage />;
      case "today":
      default:
        return <TodayPage vod={vod} tweaks={tweaks} />;
    }
  })();

  return (
    <ThemeProvider value={ctxValue}>
      <div
        style={{
          minHeight: "100vh",
          background: ctxValue.T.bg,
          color: ctxValue.T.text,
          fontFamily: '"Helvetica Neue", Helvetica, Arial, sans-serif',
        }}
      >
        <DashNav vod={vod} route={route} go={go as never} />
        <div style={{ maxWidth: 1600, margin: "0 auto" }}>{page}</div>
        <TweaksButton onClick={() => setTweaksOpen((o) => !o)} />
        <TweaksPanel
          tweaks={tweaks}
          setTweak={setTweak}
          open={tweaksOpen}
          onClose={() => setTweaksOpen(false)}
        />
      </div>
    </ThemeProvider>
  );
}
