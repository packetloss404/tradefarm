import { useMemo } from "react";
import { Sparkline } from "./primitives";
import {
  FONT_MONO,
  RANK_LABEL,
  STRATEGY_LABEL,
  V1,
  fmtPct,
  stratColor,
} from "./tokens";
import type { V1Agent } from "./adapter";

/**
 * Left column — the top 12 agents by P&L. Rows 1–3 get an amber gradient
 * highlight; row 1's rank glyph is brand amber.
 */
export function Leaderboard({ agents }: { agents: V1Agent[] }) {
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 12), [agents]);
  return (
    <div
      style={{
        background: V1.PANEL,
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "12px 16px",
          borderBottom: `1px solid ${V1.LINE}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.6 }}>TOP 12 · ALPHA</div>
        <span
          style={{
            fontSize: 9,
            padding: "2px 6px",
            background: V1.AMBER,
            color: "#000",
            fontWeight: 800,
            letterSpacing: 1,
            borderRadius: 2,
            fontFamily: FONT_MONO,
          }}
        >
          LEADERS
        </span>
      </div>
      <div style={{ flex: 1, overflow: "hidden" }}>
        {top.map((a, i) => (
          <LeaderRow key={a.id} agent={a} rank={i + 1} />
        ))}
      </div>
    </div>
  );
}

function LeaderRow({ agent, rank }: { agent: V1Agent; rank: number }) {
  const pnlColr = agent.pnl >= 0 ? V1.PROFIT : V1.LOSS;
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "24px 1fr 80px 56px",
        alignItems: "center",
        gap: 8,
        padding: "8px 12px",
        borderBottom: `1px solid ${V1.LINE}`,
        background:
          rank <= 3
            ? "linear-gradient(90deg, rgba(251,191,36,0.08), transparent)"
            : "transparent",
      }}
    >
      <div
        style={{
          fontSize: 14,
          fontWeight: 800,
          fontFamily: FONT_MONO,
          color: rank === 1 ? V1.AMBER : rank <= 3 ? "#fde68a" : V1.TEXT_MUTED,
          textAlign: "center",
        }}
      >
        {rank}
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <div
            style={{
              width: 18,
              height: 18,
              borderRadius: 3,
              background: stratColor(agent.strategy),
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontSize: 9,
              fontWeight: 800,
              color: "#000",
              fontFamily: FONT_MONO,
            }}
          >
            {agent.initials}
          </div>
          <div
            style={{
              fontSize: 12,
              fontWeight: 600,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {agent.name}
          </div>
        </div>
        <div
          style={{
            fontSize: 9,
            color: V1.TEXT_HINT,
            letterSpacing: 1,
            marginTop: 1,
            fontFamily: FONT_MONO,
          }}
        >
          {STRATEGY_LABEL[agent.strategy]} · {RANK_LABEL[agent.rank]}
          {agent.symbol ? ` · ${agent.symbol}` : ""}
        </div>
      </div>
      <Sparkline
        data={agent.sparkline.slice(-20)}
        color={pnlColr}
        width={70}
        height={22}
        strokeWidth={1.5}
        fillBelow
      />
      <div
        style={{
          fontSize: 13,
          fontWeight: 800,
          color: pnlColr,
          textAlign: "right",
          fontFamily: FONT_MONO,
        }}
      >
        {fmtPct(agent.pnlPct, 1)}
      </div>
    </div>
  );
}
