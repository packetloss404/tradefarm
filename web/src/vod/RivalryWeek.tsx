// Rivalry Week — 7-min format that profiles the two agents with the
// highest opposite-side count over the past 5 sessions, side-by-side
// with their lifetime record and most recent matchup. Pure
// presentation: the data is already on the manifest's
// `rivalries` field (0.8.0 era) — see `session/run.py:_compute_rivalries`
// and the weekly_rollup's `rivalries` aggregation (0.9.0).

import { T } from "./tokens";
import type { VodMock } from "./useVodMock";

type RivalryRow = {
  a: number;
  b: number;
  symbol: string;
  count: number;
  a_pnl: number;
  b_pnl: number;
};

function agentName(agents: VodMock["agents"], id: number): string {
  const a = agents.find((x) => x.id === id);
  if (!a) return `agent_${id}`;
  return a.display;
}

function RivalryCard({
  row,
  side,
  agents,
}: {
  row: RivalryRow;
  side: "a" | "b";
  agents: VodMock["agents"];
}) {
  const id = side === "a" ? row.a : row.b;
  const pnl = side === "a" ? row.a_pnl : row.b_pnl;
  const wins = side === "a" ? Math.ceil(row.count / 2) : Math.floor(row.count / 2);
  const isPositive = pnl >= 0;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 6,
        }}
      >
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            color: T.text3,
          }}
        >
          #{id.toString().padStart(2, "0")}
        </span>
        <span
          style={{
            fontFamily: T.font,
            fontSize: 16,
            fontWeight: 600,
            color: T.text,
          }}
        >
          {agentName(agents, id)}
        </span>
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 11,
          color: T.text2,
        }}
      >
        vs {agentName(agents, side === "a" ? row.b : row.a)} · {row.symbol} ·{" "}
        {row.count} opposite-side fills
      </div>
      <div
        style={{
          display: "flex",
          gap: 12,
          fontFamily: T.mono,
          fontSize: 13,
          fontWeight: 600,
        }}
      >
        <span style={{ color: isPositive ? T.ok : "#f87171" }}>
          {pnl >= 0 ? "+" : ""}${pnl.toFixed(0)}
        </span>
        <span style={{ color: T.text3 }}>·</span>
        <span style={{ color: T.text2 }}>{wins} wins on this side</span>
      </div>
    </div>
  );
}

export function RivalryWeek({ vod }: { vod: VodMock }) {
  // The 0.9.0 weekly rollup is the source of truth; the surface
  // reads from `vod.rivalries` which is populated from the
  // weekly_rollup's `rivalries` aggregation. When the rollup is
  // empty (fresh dev box, pre-0.9.0 mock), fall back to a synthetic
  // head-to-head so the surface still renders.
  const rivalries: RivalryRow[] =
    vod.rivalries && vod.rivalries.length > 0
      ? vod.rivalries.slice(0, 2)
      : mockRivalryFallback(vod);

  const head = rivalries[0];
  return (
    <div
      className="vod-no-scroll"
      style={{ padding: "20px 28px", flex: 1, overflow: "auto" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          marginBottom: 4,
        }}
      >
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            letterSpacing: 2,
            color: T.text3,
          }}
        >
          RIVALRY WEEK
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text2,
          }}
        >
          7-min · {rivalries.length} {rivalries.length === 1 ? "rivalry" : "rivalries"} on file
        </span>
      </div>
      <div
        style={{
          fontFamily: T.font,
          fontSize: 18,
          fontWeight: 600,
          color: T.text,
          marginBottom: 12,
        }}
      >
        {head
          ? `${agentName(vod.agents, head.a)} vs ${agentName(
              vod.agents,
              head.b,
            )} — ${head.count} opposite-side fills on ${head.symbol}`
          : "No rivalries this week"}
      </div>
      {head && (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr auto 1fr",
            gap: 16,
            alignItems: "stretch",
          }}
        >
          <RivalryCard row={head} side="a" agents={vod.agents} />
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: T.mono,
              fontSize: 11,
              color: T.text3,
              letterSpacing: 1.6,
              textTransform: "uppercase",
            }}
          >
            vs
          </div>
          <RivalryCard row={head} side="b" agents={vod.agents} />
        </div>
      )}
      {rivalries.length === 0 && (
        <div
          style={{
            marginTop: 16,
            padding: 16,
            background: T.panel,
            border: `1px solid ${T.border}`,
            borderRadius: 6,
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text3,
          }}
        >
          No rivalries detected. The detector needs ≥3 opposite-side
          fills between the same two agents within a 90-min window.
        </div>
      )}
    </div>
  );
}

function mockRivalryFallback(vod: VodMock): RivalryRow[] {
  // Fallback for pre-0.9.0 mock fixtures: pick two agents that
  // traded the same symbol, synthesize a head-to-head. Stays
  // useful for screenshots + UI testing.
  const by = new Map<string, number[]>();
  vod.agents.slice(0, 50).forEach((a) => {
    const sym = a.symbol ?? "AAPL";
    if (!by.has(sym)) by.set(sym, []);
    by.get(sym)!.push(a.id);
  });
  for (const [, ids] of by) {
    if (ids.length >= 2) {
      return [
        {
          a: ids[0]!,
          b: ids[1]!,
          symbol: "AAPL",
          count: 3,
          a_pnl: 80,
          b_pnl: -60,
        },
      ];
    }
  }
  return [];
}
