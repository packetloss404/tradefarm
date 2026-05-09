import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import type { StreamSnapshot } from "../../hooks/useStreamData";
import { useBroadcastViewModel } from "./adapter";
import { Scoreboard } from "./Scoreboard";
import { Leaderboard } from "./Leaderboard";
import { RaceLanes } from "./RaceLanes";
import { AgentFarm } from "./AgentFarm";
import { RightPanel } from "./RightPanel";
import { LowerThird } from "./LowerThird";
import { Ticker } from "./Ticker";
import { FONT_BODY, V1 } from "./tokens";

/**
 * V1 Broadcast — the 1920×1080 "sports broadcast" frame. The design specifies
 * a fixed-resolution overlay (meant to render edge-to-edge into OBS at exactly
 * 1920×1080). For dev work in a regular Vite/Tauri window we compute a scale
 * factor so the canvas fits the viewport without scrollbars; in OBS at the
 * intended source size the scale resolves to 1.
 */
const DESIGN_W = 1920;
const DESIGN_H = 1080;

function useFitScale(): number {
  const [scale, setScale] = useState<number>(1);
  useEffect(() => {
    const recompute = () => {
      const sx = window.innerWidth / DESIGN_W;
      const sy = window.innerHeight / DESIGN_H;
      // Math.min keeps both axes inside the viewport (letterbox if AR mismatches).
      // Cap at 1 so the design never up-scales past native — at native it stays crisp.
      setScale(Math.min(sx, sy, 1));
    };
    recompute();
    window.addEventListener("resize", recompute);
    return () => window.removeEventListener("resize", recompute);
  }, []);
  return scale;
}

export function Broadcast({ snapshot }: { snapshot: StreamSnapshot }) {
  const view = useBroadcastViewModel(snapshot);
  const scale = useFitScale();

  return (
    <motion.div
      key="v1-broadcast"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.18 }}
      style={{
        position: "absolute",
        inset: 0,
        background: "#000",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          width: DESIGN_W,
          height: DESIGN_H,
          background: V1.BG,
          color: V1.TEXT,
          fontFamily: FONT_BODY,
          WebkitFontSmoothing: "antialiased",
          MozOsxFontSmoothing: "grayscale",
          display: "flex",
          flexDirection: "column",
          position: "relative",
          overflow: "hidden",
          transform: `scale(${scale})`,
          transformOrigin: "center center",
          flexShrink: 0,
        }}
      >
        <Scoreboard account={view.account} />
        <div
          style={{
            flex: 1,
            display: "grid",
            gridTemplateColumns: "380px 1fr 360px",
            minHeight: 0,
          }}
        >
          <Leaderboard agents={view.agents} />
          <div
            style={{
              display: "flex",
              flexDirection: "column",
              minHeight: 0,
              borderLeft: `1px solid ${V1.LINE}`,
              borderRight: `1px solid ${V1.LINE}`,
            }}
          >
            <RaceLanes agents={view.agents} />
            <AgentFarm agents={view.agents} />
          </div>
          <RightPanel fills={view.fills} />
        </div>
        <LowerThird promotions={view.promotions} account={view.account} />
        <Ticker fills={view.fills} promotions={view.promotions} />
      </div>
    </motion.div>
  );
}
