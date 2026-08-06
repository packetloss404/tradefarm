// Today page — home. Hero stats, optional cost rail, live equity
// chart, 25×4 agent pixel grid, episode preview, optional pipeline
// strip, recent fills, moments-so-far rail. Live data flows through
// where /api/account, /api/agents, /api/llm/stats, and /ws fills are
// reachable; mocks fill in the rest.

import { useMemo } from "react";
import { useTheme } from "./ThemeContext";
import { MicroBar } from "./Shell";
import {
  BEAT_KIND_META,
  SYMBOLS,
  VOD_STRATEGY_SHORT,
  seededRngStr,
} from "../vod/data";
import { fmtMoney, fmtPct } from "../vod/widgets";
import { DecisionFeedSidebar } from "../components/DecisionFeedSidebar";
import type { VodSessionLive } from "../vod/useVodSessionLive";
import type { DashTweaks } from "./useDashTweaks";

// --- Hero strip --------------------------------------------------------

function HeroStrip({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const equity = vod.summary.totalEquity;
  const sinceOpen = equity - vod.summary.allocated;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
      <HeroCard
        label="POOL EQUITY"
        value={"$" + equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}
        sub={`${sinceOpen >= 0 ? "+" : ""}${sinceOpen.toFixed(0)} since open`}
        color={sinceOpen >= 0 ? T.ok : T.err}
        accent
      />
      <HeroCard
        label="DAY P&L"
        value={fmtPct(vod.summary.pnlPct)}
        sub={vod.summary.totalPnl >= 0 ? "best since Apr 24" : "drawdown in progress"}
        color={vod.summary.pnlPct >= 0 ? T.ok : T.err}
      />
      <HeroCard
        label="FILLS / DECISIONS"
        value={`${vod.summary.fillCount} / ${vod.summary.decisionCount.toLocaleString()}`}
        sub={
          vod.summary.decisionCount > 0
            ? `${((vod.summary.fillCount / vod.summary.decisionCount) * 100).toFixed(1)}% fill rate`
            : "no decisions yet"
        }
      />
      <HeroCard
        label="LLM SPEND TODAY"
        value={`$${vod.summary.llmSpend.toFixed(2)}`}
        sub={`of $13.10 daily cap (${((vod.summary.llmSpend / 13.1) * 100).toFixed(0)}%)`}
      />
    </div>
  );
}

function HeroCard({
  label,
  value,
  sub,
  color,
  accent,
}: {
  label: string;
  value: string;
  sub: string;
  color?: string;
  accent?: boolean;
}) {
  const { T } = useTheme();
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${accent ? T.borderHi : T.border}`,
        borderRadius: 8,
        padding: 18,
        position: "relative",
      }}
    >
      {accent && (
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 18,
            bottom: 18,
            width: 3,
            background: T.accent,
            borderRadius: 2,
          }}
        />
      )}
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.8,
          color: T.text3,
          marginBottom: 8,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 28,
          fontWeight: 600,
          color: color || T.text,
          letterSpacing: -0.5,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: T.text2,
          marginTop: 6,
        }}
      >
        {sub}
      </div>
    </div>
  );
}

// --- Cost rail ---------------------------------------------------------

function CostRail({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const burn = (vod.summary.llmSpend / 13.1) * 100;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: "12px 18px",
        display: "flex",
        alignItems: "center",
        gap: 24,
      }}
    >
      <div>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          API SPEND TODAY
        </div>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 18, fontWeight: 600, color: T.text }}>
          ${vod.summary.llmSpend.toFixed(2)}{" "}
          <span style={{ color: T.text3, fontSize: 12 }}>/ $13.10</span>
        </div>
      </div>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 6 }}>
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            color: T.text2,
          }}
        >
          <span>{burn.toFixed(0)}% of daily cap · projected to close at $4.30</span>
          <span style={{ color: T.text3 }}>
            {vod.summary.llmCalls} calls · {vod.summary.llmSkipped} skipped by gate (
            {vod.summary.llmCalls + vod.summary.llmSkipped > 0
              ? Math.round((vod.summary.llmSkipped / (vod.summary.llmCalls + vod.summary.llmSkipped)) * 100)
              : 0}
            %)
          </span>
        </div>
        <MicroBar pct={burn / 100} color={burn < 60 ? T.ok : burn < 90 ? T.warn : T.err} />
      </div>
      <div style={{ display: "flex", gap: 14 }}>
        <CostMicro label="anthropic" value={`$${(vod.summary.llmSpend * 0.94).toFixed(2)}`} />
        <CostMicro label="eodhd" value="$0.65" />
        <CostMicro label="elevenlabs" value="$1.42 est" />
      </div>
    </div>
  );
}

function CostMicro({ label, value }: { label: string; value: string }) {
  const { T } = useTheme();
  return (
    <div>
      <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, color: T.text3 }}>{label}</div>
      <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, fontWeight: 600, color: T.text }}>
        {value}
      </div>
    </div>
  );
}

// --- Live equity chart -------------------------------------------------

function LiveEquityChart({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const W = 800;
  const H = 180;
  // Prefer the real /pnl/daily-driven curve when present; otherwise fall
  // back to a seeded synthetic so the surface never collapses to a line.
  const mockPoints = useMemo(() => {
    const arr: number[] = [];
    const r = seededRngStr("today-equity");
    let v = 0;
    for (let i = 0; i < 280; i++) {
      v += (r() - 0.46) * 4 + Math.sin(i / 32) * 0.6;
      arr.push(v);
    }
    return arr;
  }, []);
  const useLive = vod.equityCurve.length >= 2;
  const points = useLive ? vod.equityCurve : mockPoints;
  const progress = useLive ? 1 : 0.62;
  const visible = useLive ? points : points.slice(0, Math.max(2, Math.floor(points.length * progress)));
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const pts = visible.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p - min) / span) * (H - 12) - 6;
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const lastPt = pts[pts.length - 1];
  const lastX = lastPt ? lastPt[0] : 0;
  const lastY = lastPt ? lastPt[1] : H;
  const fill = `0,${H} ${line} ${lastX.toFixed(1)},${H}`;
  const equity = useLive ? points[points.length - 1] ?? vod.summary.totalEquity : vod.summary.totalEquity;
  const opening = useLive ? points[0] ?? vod.summary.allocated : vod.summary.allocated;
  const pnlAbs = equity - opening;
  const pnlPct = opening === 0 ? 0 : (pnlAbs / opening) * 100;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            POOL EQUITY · LIVE
          </div>
          <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginTop: 4 }}>
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 22, fontWeight: 600, color: T.text }}>
              ${equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}
            </span>
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 14,
                fontWeight: 600,
                color: pnlAbs >= 0 ? T.ok : T.err,
              }}
            >
              {pnlPct >= 0 ? "+" : "−"}
              {Math.abs(pnlPct).toFixed(2)}%
            </span>
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2 }}>
              {fmtMoney(pnlAbs, { signed: true, dp: 0 })} today
            </span>
          </div>
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {["1D", "1W", "1M", "ALL"].map((p) => (
            <button
              key={p}
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 10,
                fontWeight: 600,
                padding: "4px 10px",
                borderRadius: 3,
                cursor: "pointer",
                background: p === "1D" ? T.panel3 : "transparent",
                border: `1px solid ${p === "1D" ? T.borderHi : T.border}`,
                color: p === "1D" ? T.text : T.text2,
              }}
            >
              {p}
            </button>
          ))}
        </div>
      </div>
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ display: "block", height: H }}
      >
        <defs>
          <linearGradient id="today-eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.ok} stopOpacity="0.3" />
            <stop offset="100%" stopColor={T.ok} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((g) => (
          <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke={T.border} strokeDasharray="2 4" />
        ))}
        {pts.length > 1 && (
          <>
            <polygon points={fill} fill="url(#today-eq-fill)" />
            <polyline
              points={line}
              fill="none"
              stroke={T.ok}
              strokeWidth="2"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
            <circle cx={lastX} cy={lastY} r="4" fill={T.ok} />
            <circle
              cx={lastX}
              cy={lastY}
              r="9"
              fill="none"
              stroke={T.ok}
              strokeOpacity="0.4"
              className="vod-pulse-dot"
            />
          </>
        )}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: T.text3,
        }}
      >
        <span>09:30</span>
        <span>11:00</span>
        <span>12:30</span>
        <span>14:00</span>
        <span style={{ color: T.text }}>now</span>
        <span style={{ opacity: 0.4 }}>16:00</span>
      </div>
    </div>
  );
}

// --- Agent pixel grid --------------------------------------------------

function AgentPixelGrid({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const profit = vod.agents.filter((a) => a.pnl > 8).length;
  const loss = vod.agents.filter((a) => a.pnl < -8).length;
  const flat = vod.agents.filter((a) => Math.abs(a.pnl) <= 8).length;
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
          marginBottom: 12,
        }}
      >
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          ROSTER · 100 AGENTS
        </div>
        <div
          style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2, display: "flex", gap: 12 }}
        >
          <Tag color={T.ok} label={`${profit} profit`} />
          <Tag color={T.err} label={`${loss} loss`} />
          <Tag color={T.text3} label={`${flat} flat`} />
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(25, 1fr)", gap: 3 }}>
        {vod.agents.map((a) => (
          <div
            key={a.id}
            title={`${a.display} · ${VOD_STRATEGY_SHORT[a.strategy]} · ${fmtMoney(a.pnl, {
              signed: true,
              dp: 0,
            })}`}
            style={{
              width: "100%",
              aspectRatio: "1",
              borderRadius: 2,
              background: a.pnl > 8 ? T.ok : a.pnl < -8 ? T.err : T.text3,
              opacity: Math.min(1, 0.35 + Math.abs(a.pnl) / 60),
              cursor: "pointer",
            }}
          />
        ))}
      </div>
      <div style={{ marginTop: 10, fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text3 }}>
        opacity = |P&L| · 25 cols × 4 rows · click for detail
      </div>
    </div>
  );
}

function Tag({ color, label }: { color: string; label: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <span style={{ width: 6, height: 6, background: color, borderRadius: 1 }} />
      {label}
    </span>
  );
}

// --- Pipeline strip ----------------------------------------------------

function PipelineStrip({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const pipeline = vod.pipeline;
  if (pipeline.length === 0) {
    return (
      <div
        style={{
          background: T.panel,
          border: `1px solid ${T.border}`,
          borderRadius: 8,
          padding: 18,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: T.text3,
          lineHeight: 1.5,
        }}
      >
        TONIGHT'S RENDER · pipeline starts at 16:00 ET close. Subsystems will appear here once the
        session runner emits a manifest and the beat detector runs.
      </div>
    );
  }
  const done = pipeline.filter((p) => p.status === "done").length;
  const running = pipeline.filter((p) => p.status === "running").length;
  const queued = pipeline.filter((p) => p.status === "queued").length;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 14 }}>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          TONIGHT'S RENDER · EP {String(vod.episodeNumber).padStart(3, "0")}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2 }}>
          {done} done · {running} running · {queued} queued
        </span>
        {running > 0 && (
          <span
            className="vod-pulse-dot"
            style={{
              width: 8,
              height: 8,
              borderRadius: 999,
              background: T.accent,
              marginLeft: 12,
              boxShadow: `0 0 8px ${T.accent}`,
            }}
          />
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(10, 1fr)", gap: 8 }}>
        {pipeline.map((node, i) => {
          const isRunning = node.status === "running";
          const isDone = node.status === "done";
          const color = isDone ? T.ok : isRunning ? T.accent : T.text3;
          const progress = isDone ? 1 : isRunning ? vod.renderProgress : 0;
          return (
            <div
              key={node.id}
              style={{
                background: isRunning ? T.panel2 : "transparent",
                border: `1px solid ${isRunning ? T.borderHi : T.border}`,
                borderRadius: 4,
                padding: "10px 10px 8px",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}>
                <span
                  className={isRunning ? "vod-pulse-dot" : undefined}
                  style={{
                    width: 6,
                    height: 6,
                    borderRadius: 999,
                    background: color,
                    boxShadow: isRunning ? `0 0 6px ${color}` : "none",
                  }}
                />
                <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, color: T.text3 }}>
                  {String(i + 1).padStart(2, "0")}
                </span>
              </div>
              <div
                style={{
                  fontFamily: '"Helvetica Neue"',
                  fontSize: 11,
                  fontWeight: 600,
                  color: T.text,
                  marginBottom: 6,
                  height: 28,
                  overflow: "hidden",
                }}
              >
                {node.label}
              </div>
              <MicroBar pct={progress} color={isDone ? T.ok : T.accent} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Episode preview ---------------------------------------------------

function EpisodePreviewCard({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div>
          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            TONIGHT'S EPISODE
          </div>
          <div
            style={{
              fontFamily: '"Helvetica Neue"',
              fontSize: 16,
              fontWeight: 600,
              color: T.text,
              marginTop: 4,
            }}
          >
            EP {String(vod.episodeNumber).padStart(3, "0")} · {vod.sessionDate.slice(5)}
          </div>
        </div>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1,
            padding: "3px 8px",
            borderRadius: 3,
            background: `${T.accent}22`,
            color: T.accent,
          }}
        >
          RENDERING
        </span>
      </div>
      <div
        style={{
          aspectRatio: "16/9",
          borderRadius: 6,
          border: `1px solid ${T.border}`,
          position: "relative",
          overflow: "hidden",
          background: `linear-gradient(135deg, oklch(0.2 0.05 200) 0%, ${T.bg} 100%)`,
        }}
      >
        <svg
          viewBox="0 0 320 180"
          preserveAspectRatio="xMidYMid slice"
          style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
        >
          {Array.from({ length: 6 }).map((_, i) => (
            <g key={i} transform={`translate(${60 + i * 30}, ${110 - i * 10})`}>
              <polygon
                points="0,0 26,15 0,30 -26,15"
                fill="none"
                stroke={T.accent}
                strokeOpacity="0.25"
                strokeWidth="1"
              />
            </g>
          ))}
          <polyline
            points="20,130 50,124 80,128 110,115 140,108 170,112 200,98 230,86 260,90 290,72"
            fill="none"
            stroke={T.ok}
            strokeWidth="2"
            strokeLinejoin="round"
          />
        </svg>
        <div
          style={{
            position: "absolute",
            inset: 16,
            display: "flex",
            flexDirection: "column",
            justifyContent: "flex-end",
          }}
        >
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9,
              letterSpacing: 2,
              color: T.accent,
              marginBottom: 4,
            }}
          >
            TODAY ON TRADEFARM · EP {String(vod.episodeNumber).padStart(3, "0")}
          </div>
          <div
            style={{
              fontFamily: '"Helvetica Neue"',
              fontSize: 20,
              fontWeight: 800,
              color: "#fff",
              lineHeight: 1.1,
              letterSpacing: -0.5,
            }}
          >
            Mei takes #1
            <br />
            after 47 days
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12, padding: "8px 0" }}>
        <MiniStat label="ETA" value="14m" />
        <MiniStat
          label="DURATION"
          value={`${Math.floor(vod.totalDuration / 60)}:${String(vod.totalDuration % 60).padStart(2, "0")}`}
        />
        <MiniStat label="BEATS" value={`${vod.selectedBeats.size} / ${vod.beats.length}`} />
      </div>
      <a
        href="#vod-studio/beats"
        style={{
          display: "block",
          textAlign: "center",
          textDecoration: "none",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: 0.5,
          padding: "10px 12px",
          borderRadius: 4,
          background: T.accent,
          color: "#1a1408",
        }}
      >
        ▸ open beat picker
      </a>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  const { T } = useTheme();
  return (
    <div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.4,
          color: T.text3,
          marginBottom: 3,
        }}
      >
        {label}
      </div>
      <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 15, fontWeight: 600, color: T.text }}>
        {value}
      </div>
    </div>
  );
}

// --- Recent fills ------------------------------------------------------

function RecentFills({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const useLive = vod.liveFills.length > 0;
  const mockFills = useMemo(() => {
    if (useLive) return [];
    return Array.from({ length: 12 }).map((_, i) => {
      const r = seededRngStr("today-fill_" + i);
      const a = vod.agents[Math.floor(r() * vod.agents.length)];
      return {
        id: `m-${i}`,
        t: `14:${String(21 - i).padStart(2, "0")}`,
        symbol: SYMBOLS[Math.floor(r() * SYMBOLS.length)] ?? "AAPL",
        side: (r() > 0.5 ? "BUY" : "SELL") as "BUY" | "SELL",
        qty: Math.floor(1 + r() * 9),
        price: (50 + r() * 850).toFixed(2),
        agent: a,
        pnl: (r() - 0.45) * 80,
      };
    });
  }, [vod.agents, useLive]);
  const fills = useLive
    ? vod.liveFills.slice(0, 12).map((f) => ({
        id: f.id,
        t: f.t,
        symbol: f.symbol,
        side: f.side,
        qty: f.qty,
        price: f.price.toFixed(2),
        agent: f.agent,
        pnl: 0,
      }))
    : mockFills;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          {useLive ? "RECENT FILLS · LIVE WS" : "RECENT FILLS"}
        </span>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2 }}>
          last {fills.length}
        </span>
      </div>
      {fills.length === 0 && (
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            color: T.text3,
            padding: "4px 0",
            lineHeight: 1.5,
          }}
        >
          no fills since the WebSocket opened — refreshes on every fill event.
        </div>
      )}
      <div style={{ display: "flex", flexDirection: "column" }}>
        {fills.map((f, i) => (
          <div
            key={f.id}
            style={{
              display: "grid",
              gridTemplateColumns: "46px 38px 1fr auto",
              gap: 10,
              alignItems: "center",
              padding: "7px 0",
              borderBottom: i < fills.length - 1 ? `1px solid ${T.border}` : "none",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 11,
            }}
          >
            <span style={{ color: T.text3 }}>{f.t}</span>
            <span style={{ color: f.side === "BUY" ? T.ok : T.err, fontWeight: 700 }}>{f.side}</span>
            <span style={{ color: T.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              <span style={{ fontWeight: 600 }}>{f.symbol}</span>
              <span style={{ color: T.text3 }}> · </span>
              <span style={{ color: T.text2 }}>
                {f.qty}×{f.price}
              </span>
              <span style={{ color: T.text3 }}> · </span>
              <span style={{ color: T.text2 }}>{f.agent?.display ?? "—"}</span>
            </span>
            {useLive ? (
              <span style={{ color: T.text3, fontSize: 10 }}>—</span>
            ) : (
              <span style={{ color: f.pnl > 0 ? T.ok : T.err, fontWeight: 600 }}>
                {fmtMoney(f.pnl, { signed: true, dp: 0 })}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Moments today -----------------------------------------------------

function MomentsToday({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  const scored = vod.beats.slice(0, 8);
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          MOMENTS · DETECTED SO FAR
        </span>
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text2 }}>
          {scored.length} of ~13
        </span>
      </div>
      {scored.length === 0 && (
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            color: T.text3,
            padding: "4px 0",
            lineHeight: 1.5,
          }}
        >
          beat detector hasn't run yet — fires against the day's manifest after close.
        </div>
      )}
      {scored.map((b) => {
        const meta = BEAT_KIND_META[b.kind];
        return (
          <div
            key={b.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 10,
              padding: "7px 0",
              borderBottom: `1px solid ${T.border}`,
            }}
          >
            <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 10, color: T.text3, width: 36 }}>
              {b.t}
            </span>
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 9,
                letterSpacing: 1.2,
                fontWeight: 700,
                color: meta.accent,
                width: 84,
              }}
            >
              {meta.label}
            </span>
            <span
              style={{
                fontFamily: '"Helvetica Neue"',
                fontSize: 12,
                color: T.text,
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {b.headline}
            </span>
            <div style={{ width: 40 }}>
              <MicroBar pct={b.score} color={meta.accent} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- Page banner: live/loading/error -----------------------------------

function LiveBanner({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  if (vod.liveStatus === "error") {
    return (
      <div
        style={{
          background: `${T.err}18`,
          border: `1px solid ${T.err}`,
          borderRadius: 6,
          padding: "10px 14px",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: T.err,
        }}
      >
        backend unreachable — {vod.liveError ?? "unknown error"} · displaying last cached values
        and seeded mocks
      </div>
    );
  }
  if (vod.liveStatus === "loading") {
    return (
      <div
        style={{
          background: T.panel,
          border: `1px solid ${T.border}`,
          borderRadius: 6,
          padding: "10px 14px",
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 11,
          color: T.text3,
        }}
      >
        waiting on first /api/account and /api/agents responses…
      </div>
    );
  }
  return null;
}

// --- Top-level Today page ---------------------------------------------

export function TodayPage({ vod, tweaks }: { vod: VodSessionLive; tweaks: DashTweaks }) {
  return (
    <div style={{ padding: 24, display: "flex", flexDirection: "column", gap: 16 }}>
      <LiveBanner vod={vod} />
      <HeroStrip vod={vod} />
      {tweaks.showCostRail && <CostRail vod={vod} />}
      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr", gap: 16 }}>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <LiveEquityChart vod={vod} />
          <AgentPixelGrid vod={vod} />
        </div>
        <EpisodePreviewCard vod={vod} />
      </div>
      {tweaks.showPipelinePanel && <PipelineStrip vod={vod} />}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <RecentFills vod={vod} />
        <MomentsToday vod={vod} />
      </div>
      {/* 0.19.0 — persistent LLM-decision feed. Sits at the bottom
          of the Today page so the operator can scroll back through
          the last ~50 per-agent decisions without leaving the page.
          Owns its own SWR + WS subscription, no parent plumbing. */}
      <DecisionFeedSidebar />
    </div>
  );
}
