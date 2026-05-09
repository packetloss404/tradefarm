import { useMemo } from "react";
import { Sparkline } from "./primitives";
import { FONT_MONO, V1, fmtPct, stratColor } from "./tokens";
import type { V1Agent } from "./adapter";

/**
 * "THE FARM" — 8×8 mini-card grid (top 64 by |P&L|). Each card has a
 * strategy-color left rail, agent id + name, and a tiny sparkline + P&L%.
 */
export function AgentFarm({ agents }: { agents: V1Agent[] }) {
  const grid = useMemo(
    () => [...agents].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl)).slice(0, 64),
    [agents],
  );
  return (
    <div style={{ flex: 1, padding: 16, overflow: "hidden" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: 2 }}>
          THE FARM <span style={{ color: V1.TEXT_HINT, fontWeight: 600 }}>· 64 ACTIVE</span>
        </div>
        <div
          style={{
            display: "flex",
            gap: 12,
            fontSize: 10,
            fontFamily: FONT_MONO,
            color: V1.TEXT_MUTED,
          }}
        >
          <LegendChip color={stratColor("momentum")} label="MOM" />
          <LegendChip color={stratColor("lstm")} label="LSTM" />
          <LegendChip color={stratColor("llm")} label="LSTM+LLM" />
        </div>
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(8, 1fr)",
          gridAutoRows: "46px",
          gap: 4,
        }}
      >
        {grid.map((a) => (
          <MiniCard key={a.id} agent={a} />
        ))}
      </div>
    </div>
  );
}

function LegendChip({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
      <span style={{ letterSpacing: 1.5 }}>{label}</span>
    </span>
  );
}

function MiniCard({ agent }: { agent: V1Agent }) {
  const pnlColr = agent.pnl >= 0 ? V1.PROFIT : V1.LOSS;
  return (
    <div
      style={{
        background: V1.PANEL_HI,
        borderLeft: `3px solid ${stratColor(agent.strategy)}`,
        borderRadius: 2,
        padding: "4px 6px",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        overflow: "hidden",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
        <span
          style={{
            fontSize: 9,
            fontWeight: 800,
            fontFamily: FONT_MONO,
            color: V1.TEXT_MUTED,
            minWidth: 18,
          }}
        >
          #{agent.id.toString().padStart(3, "0")}
        </span>
        <span
          style={{
            fontSize: 9,
            color: V1.TEXT_DIM,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {agent.name}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <Sparkline
          data={agent.sparkline.slice(-12)}
          color={pnlColr}
          width={50}
          height={14}
          strokeWidth={1}
        />
        <span
          style={{
            fontSize: 10,
            fontWeight: 800,
            color: pnlColr,
            fontFamily: FONT_MONO,
          }}
        >
          {fmtPct(agent.pnlPct, 1)}
        </span>
      </div>
    </div>
  );
}
