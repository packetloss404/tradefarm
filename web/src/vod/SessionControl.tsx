// Session control room — "let the simulation run" view. REC indicator,
// live pool equity chart, 100-agent roster grid, manifest counters,
// beat-detector moments-so-far rail, fills feed.

import { useEffect, useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { T } from "./tokens";
import {
  BEAT_KIND_META,
  SYMBOLS,
  VOD_STRATEGY_SHORT,
  seededRngStr,
  type Agent,
} from "./mockData";
import { ETClock, fmtMoney, fmtInt } from "./widgets";
import type { VodMock } from "./useVodMock";

// SessionControl reads either mock data or the live-data superset; the
// extras are all optional so the mock path stays untouched.
type LiveExtras = {
  liveStatus?: "loading" | "ready" | "error";
  liveError?: string | null;
  equityCurve?: number[];
  liveFills?: {
    id: string;
    t: string;
    side: "BUY" | "SELL";
    symbol: string;
    qty: number;
    price: number;
    agent: Agent | undefined;
  }[];
  lastTickIso?: string | null;
};

export type SessionData = VodMock & LiveExtras;

// Coming-soon affordance for the session controls. Pause / abort imply
// DESTRUCTIVE actions but have no backend wiring yet, so they render
// dimmed + non-interactive to keep an operator from trusting them.
const COMING_SOON_TITLE = "Coming soon — session control not wired yet";

function scBtn(color?: string, disabled = false): CSSProperties {
  return {
    fontFamily: T.mono,
    fontSize: 11,
    letterSpacing: 0.4,
    fontWeight: 600,
    padding: "7px 12px",
    border: `1px solid ${color || T.border}`,
    background: "transparent",
    color: color || T.text,
    borderRadius: 4,
    cursor: disabled ? "not-allowed" : "pointer",
    opacity: disabled ? 0.45 : 1,
  };
}

function Stat3({
  label,
  value,
  color,
  mono,
}: {
  label: string;
  value: ReactNode;
  color?: string;
  mono?: boolean;
}) {
  return (
    <div style={{ minWidth: 92 }}>
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.4, color: T.text3, marginBottom: 3 }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? T.mono : T.font,
          fontSize: 14,
          color: color || T.text,
          fontWeight: 600,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function formatElapsed(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function formatTickAge(iso: string | null | undefined): string {
  if (!iso) return "no ticks yet";
  const ageSec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (ageSec < 60) return `last tick ${ageSec}s ago`;
  if (ageSec < 3600) return `last tick ${Math.round(ageSec / 60)}m ago`;
  return `last tick ${Math.round(ageSec / 3600)}h ago`;
}

function SessionHeader({
  vod,
  sessionRunning,
  elapsed,
  live,
}: {
  vod: SessionData;
  sessionRunning: boolean;
  elapsed: number;
  live: boolean;
}) {
  // 1s tick so the "last tick Xs ago" stat keeps counting up between
  // backend ticks. Cheap — the rest of the header is already animating.
  const [, force] = useState(0);
  useEffect(() => {
    if (!live) return;
    const id = window.setInterval(() => force((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [live]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "14px 24px",
        borderBottom: `1px solid ${T.border}`,
        background: T.panel,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <span
          className="vod-pulse-dot"
          style={{
            width: 10,
            height: 10,
            borderRadius: 999,
            background: T.rec,
            boxShadow: `0 0 10px ${T.rec}`,
          }}
        />
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: 1.4,
            color: T.rec,
          }}
        >
          REC · SESSION
        </span>
      </div>
      <div style={{ width: 1, height: 22, background: T.border }} />
      <div>
        <div style={{ fontFamily: T.font, fontSize: 14, fontWeight: 600, color: T.text }}>
          Session control
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text2 }}>
          {vod.sessionId} · {live ? formatTickAge(vod.lastTickIso) : `started 09:30:04 ET · ${sessionRunning ? "running" : "paused"}`}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <Stat3
        label="session time"
        value={live ? <ETClock /> : formatElapsed(elapsed)}
        mono
      />
      <Stat3 label="market time" value={<ETClock />} mono />
      <Stat3
        label={live ? "fills today" : "tick"}
        value={live ? fmtInt(vod.summary.fillCount) : "3,840 / 23,400"}
        mono
      />
      <Stat3
        label={live ? "llm calls" : "speed"}
        value={live ? fmtInt(vod.summary.llmCalls) : "38× realtime"}
        mono
      />
      <div style={{ width: 1, height: 22, background: T.border }} />
      <button disabled title={COMING_SOON_TITLE} style={scBtn(undefined, true)}>
        ⏸ pause
      </button>
      <button
        disabled
        title={COMING_SOON_TITLE}
        style={{ ...scBtn(T.err, true), color: T.err, borderColor: T.err }}
      >
        ■ abort
      </button>
    </div>
  );
}

function LiveEquityHeadline({ total, curve }: { total: number; curve: number[] }) {
  const start = curve[0] ?? total;
  const pct = start === 0 ? 0 : ((total - start) / start) * 100;
  const pnl = total - start;
  const tone = pnl >= 0 ? T.ok : T.err;
  return (
    <div
      style={{
        fontFamily: T.mono,
        fontSize: 26,
        fontWeight: 700,
        color: T.text,
        marginTop: 2,
        fontFeatureSettings: '"tnum"',
      }}
    >
      ${total.toLocaleString("en-US", { maximumFractionDigits: 0 })}{" "}
      <span style={{ color: tone, fontSize: 16 }}>
        {pnl >= 0 ? "+" : "−"}
        {Math.abs(pct).toFixed(2)}%
      </span>
    </div>
  );
}

function LiveEquityFooter({ curve }: { curve: number[] }) {
  if (curve.length < 2) {
    return <span style={{ fontStyle: "italic" }}>warming up…</span>;
  }
  const open = curve[0] ?? 0;
  const high = Math.max(...curve);
  const low = Math.min(...curve);
  const fmt = (n: number) => "$" + n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  return (
    <>
      <span>open {fmt(open)}</span>
      <span>·</span>
      <span>high {fmt(high)}</span>
      <span>·</span>
      <span>low {fmt(low)}</span>
    </>
  );
}

function EquityChart({
  progress,
  liveCurve,
  liveTotal,
}: {
  progress: number;
  liveCurve?: number[];
  liveTotal?: number;
}) {
  const W = 760;
  const H = 220;
  const mockPoints = useMemo(() => {
    const arr: number[] = [];
    const r = seededRngStr("equity");
    let v = 0;
    for (let i = 0; i < 240; i++) {
      v += (r() - 0.48) * 4 + Math.sin(i / 32) * 0.6;
      arr.push(v);
    }
    return arr;
  }, []);
  // Use live curve when present and non-trivial; otherwise fall back to
  // the seeded mock so the chart never collapses to a flat line.
  const useLive = liveCurve != null && liveCurve.length >= 2;
  const points = useLive ? liveCurve : mockPoints;
  const visibleCount = useLive ? points.length : Math.floor(points.length * progress);
  const visible = points.slice(0, Math.max(2, visibleCount));
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
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        position: "relative",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div>
          <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            POOL EQUITY · LIVE
          </div>
          {useLive ? (
            <LiveEquityHeadline total={liveTotal ?? 0} curve={liveCurve ?? []} />
          ) : (
            <div
              style={{
                fontFamily: T.mono,
                fontSize: 26,
                fontWeight: 700,
                color: T.text,
                marginTop: 2,
              }}
            >
              $101,840 <span style={{ color: T.ok, fontSize: 16 }}>+1.84%</span>
            </div>
          )}
        </div>
        <div style={{ display: "flex", gap: 12, fontFamily: T.mono, fontSize: 11, color: T.text2 }}>
          {useLive ? (
            <LiveEquityFooter curve={liveCurve ?? []} />
          ) : (
            <>
              <span>open $100,000</span>
              <span>·</span>
              <span>high $101,840</span>
              <span>·</span>
              <span>low $99,460</span>
            </>
          )}
        </div>
      </div>
      <svg
        width="100%"
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ display: "block", height: H }}
      >
        <defs>
          <linearGradient id="vod-eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.ok} stopOpacity="0.35" />
            <stop offset="100%" stopColor={T.ok} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((g) => (
          <line
            key={g}
            x1="0"
            x2={W}
            y1={H * g}
            y2={H * g}
            stroke={T.border}
            strokeDasharray="2 4"
          />
        ))}
        {pts.length > 1 && (
          <>
            <polygon points={fill} fill="url(#vod-eq-fill)" />
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
        {[0.077, 0.231, 0.385, 0.538, 0.692, 0.846, 1].map((p, i) => (
          <line
            key={i}
            x1={p * W}
            x2={p * W}
            y1={H - 4}
            y2={H}
            stroke={T.text3}
            strokeWidth="1"
          />
        ))}
      </svg>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text3,
          marginTop: 4,
        }}
      >
        {["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"].map((t) => (
          <span key={t}>{t}</span>
        ))}
      </div>
    </div>
  );
}

function AgentDot({ a }: { a: Agent }) {
  const c = a.pnl > 8 ? T.ok : a.pnl < -8 ? T.err : T.text3;
  return (
    <div
      title={`${a.display} · ${VOD_STRATEGY_SHORT[a.strategy]} · ${fmtMoney(a.pnl, {
        signed: true,
        dp: 0,
      })}`}
      style={{
        width: "100%",
        aspectRatio: "1",
        borderRadius: 3,
        background: c,
        opacity: Math.min(1, 0.4 + Math.abs(a.pnl) / 60),
        cursor: "pointer",
      }}
    />
  );
}

function AgentRoster({ vod }: { vod: SessionData }) {
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          ROSTER · 100 AGENTS
        </div>
        <div
          style={{ fontFamily: T.mono, fontSize: 10, color: T.text2, display: "flex", gap: 12 }}
        >
          <span>
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                background: T.ok,
                marginRight: 5,
                borderRadius: 1,
              }}
            />
            profit {vod.agents.filter((a) => a.pnl > 8).length}
          </span>
          <span>
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                background: T.err,
                marginRight: 5,
                borderRadius: 1,
              }}
            />
            loss {vod.agents.filter((a) => a.pnl < -8).length}
          </span>
          <span>
            <span
              style={{
                display: "inline-block",
                width: 6,
                height: 6,
                background: T.text3,
                marginRight: 5,
                borderRadius: 1,
              }}
            />
            flat {vod.agents.filter((a) => Math.abs(a.pnl) <= 8).length}
          </span>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(20, 1fr)", gap: 4 }}>
        {vod.agents.map((a) => (
          <AgentDot key={a.id} a={a} />
        ))}
      </div>
    </div>
  );
}

function MomentRail({ vod, live }: { vod: SessionData; live: boolean }) {
  const scored = vod.beats.slice(0, 8);
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 10,
        }}
      >
        <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          MOMENTS · DETECTED SO FAR
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text2 }}>
          {live
            ? `${scored.length} so far · beat detector lands post-close`
            : `${scored.length} of ~13 expected · beat detector runs at close`}
        </div>
      </div>
      <div
        className="vod-no-scroll"
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 6,
          overflow: "auto",
          flex: 1,
          minHeight: 0,
        }}
      >
        {live && scored.length === 0 && (
          <div
            style={{
              fontFamily: T.mono,
              fontSize: 11,
              color: T.text3,
              padding: "12px 4px",
              lineHeight: 1.5,
            }}
          >
            no beats detected yet — moment scoring runs against the day's
            manifest after the close, then the picker tab fills in.
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
                gap: 12,
                padding: "8px 10px",
                background: T.bg,
                border: `1px solid ${T.border}`,
                borderRadius: 4,
              }}
            >
              <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3, width: 40 }}>
                {b.t}
              </span>
              <span
                style={{
                  fontFamily: T.mono,
                  fontSize: 9,
                  letterSpacing: 1.4,
                  color: meta.accent,
                  fontWeight: 700,
                  width: 84,
                }}
              >
                {meta.label}
              </span>
              <span
                style={{
                  fontFamily: T.font,
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
              <div
                style={{
                  width: 60,
                  height: 4,
                  background: T.panel2,
                  borderRadius: 2,
                  overflow: "hidden",
                }}
              >
                <div
                  style={{
                    width: `${b.score * 100}%`,
                    height: "100%",
                    background: meta.accent,
                  }}
                />
              </div>
              <span
                style={{
                  fontFamily: T.mono,
                  fontSize: 10,
                  color: T.text2,
                  width: 28,
                  textAlign: "right",
                }}
              >
                {(b.score * 100).toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function LiveFillsFeed({ vod }: { vod: SessionData }) {
  const useLive = vod.liveFills != null;
  const mockFills = useMemo(() => {
    if (useLive) return [];
    return Array.from({ length: 18 }).map((_, i) => {
      const r = seededRngStr("fill_" + i);
      const agentIdx = Math.floor(r() * vod.agents.length);
      const a = vod.agents[agentIdx] ?? vod.agents[0]!;
      const symIdx = Math.floor(r() * SYMBOLS.length);
      return {
        id: `mock-${i}`,
        t: `${String(9 + Math.floor((i * 21) / 60)).padStart(2, "0")}:${String((i * 21) % 60).padStart(2, "0")}`,
        symbol: SYMBOLS[symIdx] ?? "AAPL",
        side: (r() > 0.5 ? "BUY" : "SELL") as "BUY" | "SELL",
        qty: Math.floor(1 + r() * 9),
        price: (50 + r() * 850).toFixed(2),
        agent: a,
      };
    });
  }, [vod.agents, useLive]);
  const liveFills = (vod.liveFills ?? []).map((f) => ({
    ...f,
    price: f.price.toFixed(2),
  }));
  const fills = useLive ? liveFills : mockFills;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 10,
        height: "100%",
      }}
    >
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
        {useLive ? `FILLS · LIVE WS · LAST ${fills.length}` : "FILLS · LAST 18"}
      </div>
      <div
        className="vod-no-scroll"
        style={{ overflow: "auto", flex: 1, fontFamily: T.mono, fontSize: 11 }}
      >
        {useLive && fills.length === 0 && (
          <div style={{ color: T.text3, padding: "8px 0", lineHeight: 1.5 }}>
            no fills since the WebSocket opened — fires here on every fill event.
          </div>
        )}
        {fills.map((f) => (
          <div
            key={f.id}
            style={{
              display: "grid",
              gridTemplateColumns: "52px 44px 54px 70px 1fr",
              gap: 8,
              padding: "5px 0",
              borderBottom: `1px solid ${T.border}`,
              color: T.text2,
            }}
          >
            <span style={{ color: T.text3 }}>{f.t}</span>
            <span style={{ color: f.side === "BUY" ? T.ok : T.err, fontWeight: 700 }}>{f.side}</span>
            <span style={{ color: T.text }}>{f.symbol}</span>
            <span style={{ color: T.text, fontFeatureSettings: '"tnum"' }}>
              {f.qty}×{f.price}
            </span>
            <span
              style={{
                color: T.text2,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {f.agent?.display ?? "—"}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function ManifestPanel({
  vod,
  progress,
  live,
}: {
  vod: SessionData;
  progress: number;
  live: boolean;
}) {
  const counters = live
    ? [
        { label: "decisions", value: fmtInt(vod.summary.decisionCount), max: "since restart" },
        {
          label: "fills (ws buffer)",
          value: fmtInt(vod.summary.fillCount),
          max: "last 20 pushed",
        },
        { label: "LLM calls", value: fmtInt(vod.summary.llmCalls), max: "since restart" },
        {
          label: "LLM skipped",
          value: fmtInt(vod.summary.llmSkipped),
          max: "below conf threshold",
        },
        { label: "pool equity", value: fmtInt(vod.summary.totalEquity), max: "live" },
      ]
    : [
        { label: "ticks", value: Math.floor(23400 * progress).toLocaleString(), max: "23,400" },
        {
          label: "decisions",
          value: Math.floor(4812 * progress).toLocaleString(),
          max: "4,812 est",
        },
        { label: "fills", value: String(Math.floor(312 * progress)), max: "312 est" },
        { label: "LLM calls", value: String(Math.floor(1067 * progress)), max: "~$2.84" },
        {
          label: "manifest",
          value: `${Math.floor(184 * progress)} KB`,
          max: "184 KB at close",
        },
      ];
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 16,
        display: "flex",
        flexDirection: "column",
        gap: 12,
      }}
    >
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
        {live ? "LIVE COUNTERS · BACKEND" : "MANIFEST · BUILDING"}
      </div>
      {counters.map((c) => (
        <div key={c.label}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              fontFamily: T.mono,
              fontSize: 10,
              marginBottom: 4,
            }}
          >
            <span style={{ color: T.text2 }}>{c.label}</span>
            <span style={{ color: T.text3 }}>{c.max}</span>
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 16, color: T.text, fontWeight: 600 }}>
            {c.value}
          </div>
        </div>
      ))}
      <div
        style={{
          paddingTop: 6,
          borderTop: `1px solid ${T.border}`,
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text3,
        }}
      >
        writing → out/sessions/{vod.sessionId}/
      </div>
    </div>
  );
}

export function SessionControl({ vod }: { vod: SessionData }) {
  const [elapsed, setElapsed] = useState(6240);
  useEffect(() => {
    const id = window.setInterval(() => setElapsed((t) => t + 1), 1000);
    return () => window.clearInterval(id);
  }, []);
  const progress = 0.55;
  const live = vod.liveStatus != null;
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: T.bg,
        color: T.text,
        fontFamily: T.font,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <SessionHeader vod={vod} sessionRunning={true} elapsed={elapsed} live={live} />
      {vod.liveStatus === "error" && (
        <div
          style={{
            padding: "8px 24px",
            background: `${T.err}18`,
            borderBottom: `1px solid ${T.err}`,
            fontFamily: T.mono,
            fontSize: 11,
            color: T.err,
          }}
        >
          backend unreachable — {vod.liveError ?? "unknown error"} · falling back to last cached
          values
        </div>
      )}
      {vod.liveStatus === "loading" && (
        <div
          style={{
            padding: "8px 24px",
            background: T.panel,
            borderBottom: `1px solid ${T.border}`,
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text3,
          }}
        >
          waiting on first /agents and /account responses…
        </div>
      )}
      <div
        style={{
          flex: 1,
          minHeight: 0,
          padding: 16,
          display: "grid",
          gridTemplateColumns: "1.6fr 1fr",
          gridTemplateRows: "auto 1fr",
          gap: 14,
        }}
      >
        <EquityChart
          progress={progress}
          liveCurve={live ? vod.equityCurve : undefined}
          liveTotal={live ? vod.summary.totalEquity : undefined}
        />
        <ManifestPanel vod={vod} progress={progress} live={live} />
        <div style={{ display: "flex", flexDirection: "column", gap: 14, minHeight: 0 }}>
          <AgentRoster vod={vod} />
          <MomentRail vod={vod} live={live} />
        </div>
        <LiveFillsFeed vod={vod} />
      </div>
    </div>
  );
}
