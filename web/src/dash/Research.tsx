// Research page — multi-day pool equity, leaderboard rank history,
// strategy attribution, storyline ribbon cards. The "what's the bigger
// story" view. All multi-day data is mocked — the storyline detector
// is net-new.

import { useTheme } from "./ThemeContext";
import {
  LB_HISTORY,
  POOL_HISTORY,
  STORYLINES,
  STORYLINE_KIND_META,
} from "./data";
import type { LbHistory, Storyline } from "./types";
import {
  VOD_AGENTS,
  VOD_STRATEGY_LABEL,
  VOD_STRATEGY_SHORT,
  seededRngStr,
} from "../vod/data";
import type { Agent, Strategy } from "../vod/types";
import { fmtMoney, fmtPct, stratColor } from "../vod/widgets";
import type { VodSessionLive } from "../vod/useVodSessionLive";

// The multi-day range selector is presentational only — the storyline /
// history endpoints are net-new, so the buttons render non-interactive
// to avoid implying the range can be changed live.
const COMING_SOON_TITLE = "Coming soon — multi-day range not wired yet";

function ResearchHeader() {
  const { T } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        padding: "24px 24px 18px",
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: '"Helvetica Neue"',
            fontSize: 28,
            fontWeight: 700,
            color: T.text,
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          Research
        </h1>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2, marginTop: 6 }}>
          multi-day arcs · leaderboard history · pool trajectory
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <RangeMenu />
      </div>
    </div>
  );
}

function RangeMenu() {
  const { T } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      {["7D", "14D", "30D", "90D", "ALL"].map((r) => (
        <button
          key={r}
          disabled
          title={COMING_SOON_TITLE}
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            fontWeight: 600,
            padding: "8px 12px",
            cursor: "not-allowed",
            background: r === "14D" ? T.panel3 : "transparent",
            border: "none",
            color: r === "14D" ? T.text : T.text2,
            opacity: r === "14D" ? 1 : 0.5,
          }}
        >
          {r}
        </button>
      ))}
    </div>
  );
}

function PoolHistoryChart() {
  const { T } = useTheme();
  const points = POOL_HISTORY;
  const W = 1200;
  const H = 220;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const pts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p - min) / span) * (H - 16) - 8;
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const fill = `0,${H} ${line} ${W},${H}`;
  const last = points[points.length - 1] ?? 0;
  const first = points[0] ?? 0;
  const change = first === 0 ? 0 : ((last - first) / first) * 100;
  const baselineY = H - ((100000 - min) / span) * (H - 16) - 8;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 22,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <div>
          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            POOL EQUITY · 14 SESSIONS
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 14, marginTop: 6 }}>
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 28, fontWeight: 600, color: T.text }}>
              ${last.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </span>
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 14,
                color: change > 0 ? T.ok : T.err,
                fontWeight: 600,
              }}
            >
              {fmtPct(change)} <span style={{ color: T.text2 }}>over 14d</span>
            </span>
          </div>
        </div>
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            color: T.text2,
            textAlign: "right",
          }}
        >
          <div>
            Sharpe-30d <span style={{ color: T.text, fontWeight: 600 }}>1.62</span>
          </div>
          <div>
            Max drawdown <span style={{ color: T.err, fontWeight: 600 }}>−4.2%</span>
          </div>
        </div>
      </div>
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ display: "block", height: H }}
      >
        <defs>
          <linearGradient id="pool-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.accent} stopOpacity="0.18" />
            <stop offset="100%" stopColor={T.accent} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke={T.border} strokeDasharray="2 4" />
        ))}
        <line x1="0" x2={W} y1={baselineY} y2={baselineY} stroke={T.text3} strokeDasharray="4 3" />
        <text
          x={W - 6}
          y={baselineY - 2}
          textAnchor="end"
          fontFamily="JetBrains Mono, monospace"
          fontSize="10"
          fill={T.text3}
        >
          $100k allocated
        </text>
        <polygon points={fill} fill="url(#pool-fill)" />
        <polyline
          points={line}
          fill="none"
          stroke={T.accent}
          strokeWidth="2"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {Array.from({ length: 14 }).map((_, i) => {
          const x = ((i + 1) / 14) * W - W / 28;
          return <line key={i} x1={x} x2={x} y1={H - 4} y2={H} stroke={T.text3} strokeWidth="1" />;
        })}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: T.text3,
          marginTop: 4,
        }}
      >
        <span>May 4</span>
        <span>May 7</span>
        <span>May 10</span>
        <span>May 13</span>
        <span style={{ color: T.text }}>May 19 (today)</span>
      </div>
    </div>
  );
}

function StorylineRibbon({ sl }: { sl: Storyline }) {
  const { T } = useTheme();
  const meta = STORYLINE_KIND_META[sl.kind];
  const cells = 14;
  const startCell = Math.max(0, 14 - sl.daysActive);
  return (
    <div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.4,
          color: T.text3,
          marginBottom: 6,
        }}
      >
        ACTIVITY · 14 DAYS
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${cells}, 1fr)`,
          gap: 3,
          height: 18,
        }}
      >
        {Array.from({ length: cells }).map((_, i) => {
          const active = i >= startCell;
          const isToday = i === cells - 1;
          const r = seededRngStr(`${sl.id}-${i}`);
          const intensity = active ? 0.45 + r() * 0.55 : 0;
          return (
            <div
              key={i}
              title={`day -${cells - 1 - i}`}
              style={{
                background: active ? meta.accent : T.panel2,
                opacity: active ? intensity : 0.4,
                borderRadius: 2,
                border: isToday && active ? `1px solid ${T.text}` : "none",
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

function StorylineCard({ sl }: { sl: Storyline }) {
  const { T } = useTheme();
  const meta = STORYLINE_KIND_META[sl.kind];
  const involved = sl.agents
    .map((id) => VOD_AGENTS[id])
    .filter((a): a is Agent => a !== undefined);
  const trendBadgeMap: Record<Storyline["trend"], { label: string; color: string }> = {
    escalating: { label: "escalating", color: T.err },
    hot: { label: "hot", color: T.ok },
    completed: { label: "completed", color: T.text3 },
    declining: { label: "declining", color: T.warn },
    steady: { label: "steady", color: T.text2 },
  };
  const trendBadge = trendBadgeMap[sl.trend];
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
        position: "relative",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 18,
          bottom: 18,
          width: 3,
          background: meta.accent,
          borderRadius: 2,
        }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 9,
            letterSpacing: 1.6,
            color: meta.accent,
            fontWeight: 700,
          }}
        >
          {meta.label}
        </span>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text3 }}>·</span>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2 }}>
          day {sl.daysActive} ·{" "}
          since {new Date(sl.startDate).toLocaleDateString("en-US", { month: "short", day: "numeric" })}
        </span>
        <div style={{ flex: 1 }} />
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 1,
            padding: "2px 6px",
            borderRadius: 2,
            color: trendBadge.color,
            border: `1px solid ${trendBadge.color}55`,
          }}
        >
          {trendBadge.label}
        </span>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            color: T.text,
            fontWeight: 600,
          }}
        >
          {(sl.score * 100).toFixed(0)}
        </span>
      </div>
      <div
        style={{
          fontFamily: '"Helvetica Neue"',
          fontSize: 16,
          fontWeight: 700,
          color: T.text,
          marginBottom: 4,
        }}
      >
        {sl.headline}
      </div>
      <div
        style={{
          fontFamily: '"Helvetica Neue"',
          fontSize: 12.5,
          color: T.text2,
          lineHeight: 1.5,
          marginBottom: 12,
        }}
      >
        {sl.sub}
      </div>
      <StorylineRibbon sl={sl} />
      {involved.length > 0 && (
        <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
          {involved.map((a) => (
            <div
              key={a.id}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 8,
                background: T.bg,
                padding: "6px 10px",
                borderRadius: 4,
                border: `1px solid ${T.border}`,
              }}
            >
              <div
                style={{
                  width: 22,
                  height: 22,
                  borderRadius: 3,
                  background: stratColor(a.strategy),
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 9,
                  fontWeight: 700,
                  color: "#0a0a0a",
                }}
              >
                {a.initials}
              </div>
              <span
                style={{
                  fontFamily: '"Helvetica Neue"',
                  fontSize: 12,
                  fontWeight: 600,
                  color: T.text,
                }}
              >
                {a.display}
              </span>
              {sl.standings && (
                <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2 }}>
                  · {sl.standings[a.id]}W
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: T.text3,
          marginTop: 12,
          paddingTop: 12,
          borderTop: `1px solid ${T.border}`,
        }}
      >
        next hook · <span style={{ color: T.text2 }}>{sl.nextHook}</span>
      </div>
    </div>
  );
}

function RankRow({ agent, rank, series }: { agent: Agent; rank: number; series: LbHistory["series"] }) {
  const { T } = useTheme();
  const ranks = series.map((s) => {
    const r = s.ranks.find((x) => x.id === agent.id);
    return r ? r.rank : null;
  });
  const W = 360;
  const H = 28;
  const days = ranks.length;
  const min = 0.5;
  const max = 11.5;
  const pts = ranks
    .map((r, i) => {
      if (r == null) return null;
      const x = (i / (days - 1)) * W;
      const y = ((Math.min(max, Math.max(min, r)) - min) / (max - min)) * H;
      return [x, y] as const;
    })
    .filter((p): p is readonly [number, number] => p !== null);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 12,
        padding: "8px 4px",
        borderBottom: `1px solid ${T.border}`,
      }}
    >
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text3, width: 26 }}>
        #{rank}
      </span>
      <div
        style={{
          width: 24,
          height: 24,
          borderRadius: 4,
          background: stratColor(agent.strategy),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          fontWeight: 700,
          color: "#0a0a0a",
        }}
      >
        {agent.initials}
      </div>
      <div style={{ width: 180 }}>
        <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, fontWeight: 600, color: T.text }}>
          {agent.display}
        </div>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text3 }}>
          {VOD_STRATEGY_SHORT[agent.strategy]} · {agent.rank}
        </div>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ flexShrink: 0 }}>
        <polyline points={line} fill="none" stroke={T.accent2} strokeWidth="1.5" strokeLinejoin="round" />
        {pts.map(([x, y], i) => (
          <circle
            key={i}
            cx={x}
            cy={y}
            r={i === pts.length - 1 ? 3 : 1.5}
            fill={i === pts.length - 1 ? T.text : T.accent2}
          />
        ))}
      </svg>
      <div style={{ flex: 1 }} />
      <span
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 12,
          color: agent.pnl > 0 ? T.ok : T.err,
          fontWeight: 600,
        }}
      >
        {fmtMoney(agent.pnl, { signed: true, dp: 0 })}
      </span>
    </div>
  );
}

function LeaderboardHistory() {
  const { T } = useTheme();
  const data = LB_HISTORY;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 14,
        }}
      >
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          LEADERBOARD HISTORY · TOP 10
        </span>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2 }}>
          rank evolution · 14 sessions
        </span>
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {data.agents.map((a, idx) => (
          <RankRow key={a.id} agent={a} rank={idx + 1} series={data.series} />
        ))}
      </div>
    </div>
  );
}

function StrategyAttribution({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const totals = vod.summary.byStrategy;
  const pairs = Object.entries(totals) as [Strategy, (typeof totals)[Strategy]][];
  const maxAbs = Math.max(...pairs.map(([, v]) => Math.abs(v.pnl)), 1);
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
      }}
    >
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.6,
          color: T.text3,
          marginBottom: 12,
        }}
      >
        STRATEGY ATTRIBUTION · TODAY
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {pairs.map(([k, v]) => {
          const widthPct = (Math.abs(v.pnl) / maxAbs) * 50;
          const leftPct = v.pnl >= 0 ? 50 : 50 - widthPct;
          return (
            <div key={k}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 11,
                  marginBottom: 4,
                }}
              >
                <span style={{ color: T.text }}>{VOD_STRATEGY_LABEL[k]}</span>
                <span style={{ color: v.pnl > 0 ? T.ok : T.err, fontWeight: 600 }}>
                  {fmtMoney(v.pnl, { signed: true, dp: 0 })}{" "}
                  <span style={{ color: T.text3 }}>· {fmtPct(v.pnlPct)}</span>
                </span>
              </div>
              <div
                style={{
                  height: 6,
                  background: T.panel2,
                  borderRadius: 2,
                  overflow: "hidden",
                  position: "relative",
                }}
              >
                <div
                  style={{
                    position: "absolute",
                    left: `${leftPct}%`,
                    width: `${widthPct}%`,
                    height: "100%",
                    background: stratColor(k),
                  }}
                />
                <div
                  style={{
                    position: "absolute",
                    left: "50%",
                    width: 1,
                    height: "100%",
                    background: T.text3,
                  }}
                />
              </div>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  fontFamily: "JetBrains Mono, monospace",
                  fontSize: 10,
                  color: T.text3,
                  marginTop: 4,
                }}
              >
                <span>{v.agents} agents</span>
                <span>{v.fills} fills</span>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ResearchPage({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const storylines = STORYLINES;
  return (
    <div>
      <ResearchHeader />
      <div style={{ padding: "0 24px 24px", display: "flex", flexDirection: "column", gap: 18 }}>
        <PoolHistoryChart />
        <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 18 }}>
          <LeaderboardHistory />
          <StrategyAttribution vod={vod} />
        </div>
        <div>
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9,
              letterSpacing: 1.6,
              color: T.text3,
              marginBottom: 12,
            }}
          >
            ACTIVE STORYLINES · {storylines.length}
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(420px, 1fr))",
              gap: 16,
            }}
          >
            {storylines.map((sl) => (
              <StorylineCard key={sl.id} sl={sl} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
