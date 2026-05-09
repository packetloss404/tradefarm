import { useMemo } from "react";
import { useAnimatedNumber } from "./hooks";
import { FONT_MONO, V1, fmtPct, stratColor, stratColorDim } from "./tokens";
import type { V1Agent } from "./adapter";

/**
 * 6-lane horse-race style P&L chart. Each lane's progress is the agent's
 * P&L mapped onto the percentile of the full agent set, then smoothed with
 * useAnimatedNumber (600ms cubic-out).
 */
export function RaceLanes({ agents }: { agents: V1Agent[] }) {
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 6), [agents]);
  const { lo, range } = useMemo(() => {
    if (agents.length === 0) return { lo: 0, range: 1 };
    let mn = Infinity;
    let mx = -Infinity;
    for (const a of agents) {
      if (a.pnl < mn) mn = a.pnl;
      if (a.pnl > mx) mx = a.pnl;
    }
    return { lo: mn, range: Math.max(1, mx - mn) };
  }, [agents]);

  return (
    <div style={{ background: V1.PANEL, padding: 16, borderBottom: `1px solid ${V1.LINE}` }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 2 }}>
          RACE TO ALPHA <span style={{ color: V1.AMBER, fontSize: 12 }}>· LIVE</span>
        </div>
        <div
          style={{
            fontSize: 10,
            color: V1.TEXT_HINT,
            letterSpacing: 1.5,
            fontFamily: FONT_MONO,
          }}
        >
          POSITION · 24h P&L NORMALIZED
        </div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {top.map((a, i) => {
          const t = (a.pnl - lo) / range;
          return <Lane key={a.id} agent={a} progress={t} laneNo={i + 1} />;
        })}
      </div>
    </div>
  );
}

function Lane({
  agent,
  progress,
  laneNo,
}: {
  agent: V1Agent;
  progress: number;
  laneNo: number;
}) {
  const pnlColr = agent.pnl >= 0 ? V1.PROFIT : V1.LOSS;
  const t = useAnimatedNumber(progress, 600);
  const pctW = Math.max(2, t * 100);
  return (
    <div
      style={{
        position: "relative",
        height: 36,
        background:
          "repeating-linear-gradient(90deg, transparent 0 36px, rgba(255,255,255,0.025) 36px 38px)",
        borderRadius: 4,
        border: `1px solid ${V1.LINE}`,
        overflow: "hidden",
      }}
    >
      {/* progress fill */}
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 0,
          bottom: 0,
          width: `${pctW}%`,
          background: `linear-gradient(90deg, ${stratColorDim(agent.strategy)} 0%, ${stratColor(agent.strategy)} 100%)`,
          opacity: 0.45,
        }}
      />
      {/* finish-line stripe */}
      <div
        style={{
          position: "absolute",
          right: 8,
          top: 0,
          bottom: 0,
          width: 12,
          background: "repeating-linear-gradient(0deg, #fff 0 6px, #000 6px 12px)",
          opacity: 0.7,
        }}
      />
      {/* horse marker */}
      <div
        style={{
          position: "absolute",
          left: `calc(${t * 100}% - 18px)`,
          top: 4,
          bottom: 4,
          width: 32,
          borderRadius: 4,
          background: stratColor(agent.strategy),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 900,
          color: "#000",
          fontFamily: FONT_MONO,
          boxShadow: `0 0 10px ${stratColor(agent.strategy)}`,
          transition: "left 0.3s ease-out",
        }}
      >
        {agent.initials}
      </div>
      {/* L# */}
      <div
        style={{
          position: "absolute",
          left: 8,
          top: 0,
          bottom: 0,
          display: "flex",
          alignItems: "center",
          fontSize: 11,
          fontWeight: 700,
          color: "#fff",
          letterSpacing: 1.5,
          fontFamily: FONT_MONO,
          textShadow: "0 0 4px #000",
        }}
      >
        L{laneNo}
      </div>
      {/* right-side labels */}
      <div
        style={{
          position: "absolute",
          right: 28,
          top: 0,
          bottom: 0,
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: 11,
          fontWeight: 700,
          color: pnlColr,
          fontFamily: FONT_MONO,
          textShadow: "0 0 6px rgba(0,0,0,0.8)",
        }}
      >
        <span style={{ color: "#e5e7eb" }}>{agent.name}</span>
        <span>{fmtPct(agent.pnlPct, 1)}</span>
      </div>
    </div>
  );
}
