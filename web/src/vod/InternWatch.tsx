// Intern Watch — 12-min Friday format that profiles the 5
// lowest-ranked `intern` agents at session start, with a per-intern
// trade count + promotion/demotion status.
//
// The data comes from the manifest's `lowest_ranks` field (0.9.0
// era) — a list of 5 cast rows captured before the run started.
// The mock data path uses the same shape; the live path hits
// /vod/{session_id}/extras via useVodLiveData.

import { T } from "./tokens";
import type { VodMock } from "./useVodMock";

type InternCastRow = {
  agent_id: number;
  name: string;
  rank: string;
  rank_index: number;
  strategy: string;
  starting_capital: number;
};

function internName(row: InternCastRow): string {
  const [a = "", b = ""] = row.name.split("_");
  if (!a) return row.name;
  const cap = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : "");
  return b ? `${cap(a)} ${cap(b)}` : cap(a);
}

function InternCard({ row }: { row: InternCastRow }) {
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 14,
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
          marginBottom: 2,
        }}
      >
        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>
          #{row.agent_id.toString().padStart(2, "0")}
        </span>
        <span
          style={{
            fontFamily: T.font,
            fontSize: 14,
            fontWeight: 600,
            color: T.text,
          }}
        >
          {internName(row)}
        </span>
        <span style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 9,
            color: T.text3,
            letterSpacing: 1.2,
            textTransform: "uppercase",
          }}
        >
          {row.strategy}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          fontFamily: T.mono,
          fontSize: 11,
          color: T.text2,
        }}
      >
        <span>${row.starting_capital.toLocaleString()}</span>
        <span style={{ color: T.text3 }}>starting</span>
        <span style={{ color: T.text3 }}>·</span>
        <span style={{ color: T.accent }}>cast</span>
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text3,
          letterSpacing: 1.2,
          textTransform: "uppercase",
        }}
      >
        rank · {row.rank} (idx {row.rank_index})
      </div>
    </div>
  );
}

export function InternWatch({ vod }: { vod: VodMock }) {
  // The VodMock carries a `lowest_ranks` list (added in 0.10.0); when
  // it's empty the surface falls back to picking the 5 lowest-cash
  // agents from the existing agents list so the studio stays useful
  // against pre-0.9.0 mock fixtures.
  const cast: InternCastRow[] =
    vod.lowest_ranks && vod.lowest_ranks.length > 0
      ? vod.lowest_ranks
      : vodFallback(vod);

  const totalRuntime = cast.length * 24 + 12; // 24s per intern + 12s open
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
          INTERN WATCH
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text2,
          }}
        >
          12-min Friday · cast of {cast.length} · est. runtime {totalRuntime}s
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
        The 5 lowest-ranked interns at session start
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(5, 1fr)",
          gap: 12,
        }}
      >
        {cast.map((row) => (
          <InternCard key={row.agent_id} row={row} />
        ))}
      </div>
      {cast.length === 0 && (
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
          No intern cast in the manifest — run a session to populate
          <code style={{ color: T.text2 }}> lowest_ranks</code>.
        </div>
      )}
    </div>
  );
}

function vodFallback(vod: VodMock): InternCastRow[] {
  // Fallback: pull the 5 lowest-cash agents from the existing agents
  // list so the surface still renders against a pre-0.9.0 mock. The
  // cast row is synthesized from the agent's name + strategy + cash
  // — the in-memory studio mock is self-consistent.
  const sorted = [...vod.agents]
    .filter((a) => (a.cash ?? 1000) <= 1100)
    .sort((a, b) => (a.cash ?? 1000) - (b.cash ?? 1000))
    .slice(0, 5);
  return sorted.map((a) => ({
    agent_id: a.id,
    name: a.name,
    rank: "intern",
    rank_index: 0,
    strategy: a.strategy,
    starting_capital: 1000,
  }));
}
