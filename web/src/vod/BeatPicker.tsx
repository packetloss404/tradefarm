// Beat picker — the keystone VOD studio surface. Operator reviews the
// auto-detected dramatic moments of the trading day, toggles them
// in/out of the master reel, and edits per-beat captions before render.
//
// Layout: header · (preview + detail) · timeline strip · beat-list rail.

import { useState, type CSSProperties } from "react";
import { T } from "./tokens";
import {
  BEAT_KIND_META,
  VOD_AGENTS,
  VOD_STRATEGY_LABEL,
  VOD_STRATEGY_SHORT,
  seededRngStr,
  type Beat,
  type BeatMeta,
} from "./mockData";
import { fmtMoney, ScoreCircle, stratColor, SubLabel } from "./widgets";
import type { VodMock } from "./useVodMock";

// Render / re-detect / regenerate-caption have no backend wiring yet,
// so they render dimmed + non-interactive to keep an operator from
// trusting them.
const COMING_SOON_TITLE = "Coming soon — render pipeline not wired yet";

// --- Preview pane --------------------------------------------------------

function SceneVignette({ beat }: { beat: Beat }) {
  const meta = BEAT_KIND_META[beat.kind];
  if (beat.scene === "leaderboard") {
    return <LeaderboardSceneCue highlight={beat.agents[0]} />;
  }
  if (beat.scene === "brain" || beat.scene === "decision-lab") {
    return <BrainSceneCue meta={meta} />;
  }
  if (beat.scene === "showdown") {
    return <ShowdownSceneCue beat={beat} />;
  }
  if (beat.scene === "recap") {
    return <RecapSceneCue />;
  }
  return <HeroSceneCue beat={beat} meta={meta} />;
}

function HeroSceneCue({ beat, meta }: { beat: Beat; meta: BeatMeta }) {
  const r = seededRngStr(beat.id);
  return (
    <svg
      viewBox="0 0 600 320"
      preserveAspectRatio="xMidYMid slice"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", opacity: 0.55 }}
    >
      <defs>
        <linearGradient id={`hero-${beat.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={meta.accent} stopOpacity="0.5" />
          <stop offset="100%" stopColor={meta.accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {Array.from({ length: 8 }).map((_, i) => (
        <g key={i} transform={`translate(${100 + i * 50}, ${220 - i * 14})`}>
          <polygon
            points="0,0 48,28 0,56 -48,28"
            fill="none"
            stroke={meta.accent}
            strokeOpacity="0.18"
            strokeWidth="1"
          />
        </g>
      ))}
      {Array.from({ length: 14 }).map((_, i) => {
        const x = r() * 600;
        const y = 80 + r() * 200;
        const sz = 6 + r() * 8;
        return (
          <rect
            key={i}
            x={x}
            y={y}
            width={sz}
            height={sz}
            fill={meta.accent}
            opacity={0.4 + r() * 0.5}
          />
        );
      })}
      <rect x="0" y="200" width="600" height="120" fill={`url(#hero-${beat.id})`} />
    </svg>
  );
}

function LeaderboardSceneCue({ highlight }: { highlight: number | undefined }) {
  const top = [...VOD_AGENTS].sort((a, b) => b.pnl - a.pnl).slice(0, 8);
  return (
    <div
      style={{
        position: "absolute",
        inset: 24,
        display: "flex",
        flexDirection: "column",
        gap: 6,
        opacity: 0.85,
      }}
    >
      {top.map((a, i) => {
        const isHi = highlight != null && a.id === highlight;
        return (
          <div
            key={a.id}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 12,
              background: isHi ? "oklch(0.3 0.12 50 / 0.6)" : "rgba(255,255,255,0.04)",
              border: `1px solid ${isHi ? T.accent : "rgba(255,255,255,0.08)"}`,
              padding: "6px 12px",
              borderRadius: 4,
            }}
          >
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text3, width: 24 }}>
              #{i + 1}
            </span>
            <span
              style={{
                width: 24,
                height: 24,
                borderRadius: 4,
                background: stratColor(a.strategy),
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                fontFamily: T.mono,
                fontSize: 10,
                fontWeight: 700,
                color: "#0a0a0a",
              }}
            >
              {a.initials}
            </span>
            <span style={{ fontFamily: T.font, fontSize: 13, color: "#fff", flex: 1 }}>
              {a.display}
            </span>
            <span
              style={{
                fontFamily: T.mono,
                fontSize: 13,
                color: a.pnl > 0 ? T.ok : T.err,
                fontWeight: 600,
              }}
            >
              {fmtMoney(a.pnl, { signed: true, dp: 0 })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BrainSceneCue({ meta }: { meta: BeatMeta }) {
  const probs = [
    { d: "up", pct: 71 },
    { d: "flat", pct: 18 },
    { d: "down", pct: 11 },
  ] as const;
  return (
    <div style={{ position: "absolute", inset: 32, display: "flex", gap: 18 }}>
      <div style={{ flex: 1, background: "rgba(0,0,0,0.4)", borderRadius: 6, padding: 16 }}>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3, marginBottom: 8 }}>
          LSTM probs
        </div>
        {probs.map((p, i) => (
          <div
            key={p.d}
            style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}
          >
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text2, width: 36 }}>
              {p.d}
            </span>
            <div
              style={{
                flex: 1,
                height: 10,
                background: "#0008",
                borderRadius: 2,
                overflow: "hidden",
              }}
            >
              <div
                style={{
                  width: `${p.pct}%`,
                  height: "100%",
                  background: i === 0 ? meta.accent : `${meta.accent}55`,
                }}
              />
            </div>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text }}>
              {(p.pct / 100).toFixed(2)}
            </span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, background: "rgba(0,0,0,0.4)", borderRadius: 6, padding: 16 }}>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3, marginBottom: 8 }}>
          LLM overlay · claude-haiku-4-5
        </div>
        <div style={{ fontFamily: T.font, fontSize: 12, color: "#cdd1da", lineHeight: 1.6 }}>
          "Strong upside conviction. 19/19 features point up, sector flow positive, no
          earnings risk in window. Sizing 95%."
        </div>
        <div style={{ marginTop: 12, fontFamily: T.mono, fontSize: 11, color: T.accent }}>
          stance: trade · bias: long · size_pct: 0.95
        </div>
      </div>
    </div>
  );
}

function ShowdownSceneCue({ beat }: { beat: Beat }) {
  const a = beat.agents[0] != null ? VOD_AGENTS[beat.agents[0]] : undefined;
  const b = beat.agents[1] != null ? VOD_AGENTS[beat.agents[1]] : undefined;
  if (!a || !b) return null;
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      <ShowdownAvatar agent={a} />
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 48,
          fontWeight: 800,
          color: T.err,
          padding: "0 36px",
          opacity: 0.7,
        }}
      >
        VS
      </div>
      <ShowdownAvatar agent={b} />
    </div>
  );
}

function ShowdownAvatar({ agent }: { agent: NonNullable<(typeof VOD_AGENTS)[number]> }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
      <div
        style={{
          width: 80,
          height: 80,
          borderRadius: 12,
          background: stratColor(agent.strategy),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: T.mono,
          fontSize: 28,
          fontWeight: 700,
          color: "#0a0a0a",
        }}
      >
        {agent.initials}
      </div>
      <div style={{ fontFamily: T.font, fontSize: 14, color: "#fff", fontWeight: 600 }}>
        {agent.display}
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 11, color: T.text2 }}>
        {VOD_STRATEGY_SHORT[agent.strategy]} · {agent.rank}
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 14,
          color: agent.pnl > 0 ? T.ok : T.err,
          fontWeight: 600,
        }}
      >
        {fmtMoney(agent.pnl, { signed: true })}
      </div>
    </div>
  );
}

function RecapSceneCue() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        flexDirection: "column",
        gap: 6,
      }}
    >
      <div style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: 3, color: T.accent }}>
        POOL P&L · DAY
      </div>
      <div
        style={{
          fontFamily: T.font,
          fontSize: 88,
          fontWeight: 800,
          color: T.ok,
          letterSpacing: -3,
        }}
      >
        +1.84%
      </div>
      <div style={{ fontFamily: T.mono, fontSize: 13, color: T.text2 }}>
        +$1,840 · best since Apr 24
      </div>
    </div>
  );
}

function PreviewPane({ beat }: { beat: Beat }) {
  const meta = BEAT_KIND_META[beat.kind];
  return (
    <div
      style={{
        background: "#000",
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        flex: 1,
        position: "relative",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          flex: 1,
          position: "relative",
          background: `radial-gradient(ellipse at 30% 20%, oklch(0.28 0.08 ${meta.hue}) 0%, #0a0a0d 70%)`,
        }}
      >
        <SceneVignette beat={beat} />
        <div
          style={{
            position: "absolute",
            inset: 0,
            padding: 22,
            display: "flex",
            flexDirection: "column",
            justifyContent: "flex-end",
            pointerEvents: "none",
          }}
        >
          <div
            style={{
              display: "inline-block",
              fontFamily: T.mono,
              fontSize: 10,
              letterSpacing: 1.8,
              color: meta.accent,
              padding: "4px 8px",
              background: `oklch(0.2 0.05 ${meta.hue} / 0.85)`,
              border: `1px solid ${meta.accent}40`,
              borderRadius: 3,
              alignSelf: "flex-start",
              marginBottom: 8,
            }}
          >
            {meta.label} · {beat.scene}
          </div>
          <div
            style={{
              fontFamily: T.font,
              fontSize: 26,
              fontWeight: 700,
              color: "#fff",
              letterSpacing: -0.3,
              marginBottom: 4,
              textShadow: "0 2px 8px rgba(0,0,0,0.8)",
            }}
          >
            {beat.headline}
          </div>
          <div
            style={{
              fontFamily: T.mono,
              fontSize: 13,
              color: "#cdd1da",
              textShadow: "0 2px 6px rgba(0,0,0,0.8)",
            }}
          >
            {beat.sub}
          </div>
        </div>
        <div
          style={{
            position: "absolute",
            top: 16,
            left: 16,
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontFamily: T.mono,
            fontSize: 11,
            color: "#fff8",
          }}
        >
          <span
            className="vod-pulse-dot"
            style={{ width: 8, height: 8, borderRadius: 999, background: T.err }}
          />
          REPLAY · {beat.t} ET
        </div>
        <div
          style={{
            position: "absolute",
            top: 16,
            right: 16,
            fontFamily: T.mono,
            fontSize: 11,
            color: "#fff8",
          }}
        >
          {beat.duration}.0s · 1920×1080 · 30fps
        </div>
      </div>
      <div
        style={{
          padding: "10px 14px",
          display: "flex",
          alignItems: "center",
          gap: 12,
          borderTop: `1px solid ${T.border}`,
          background: T.panel2,
        }}
      >
        <span style={{ fontFamily: T.mono, fontSize: 14, color: T.text }}>▸</span>
        <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text2, width: 80 }}>
          00:12 / {String(beat.duration).padStart(2, "0")}:00
        </span>
        <div
          style={{
            flex: 1,
            height: 4,
            background: T.panel3,
            borderRadius: 2,
            overflow: "hidden",
            position: "relative",
          }}
        >
          <div style={{ position: "absolute", inset: 0, width: "24%", background: T.accent }} />
        </div>
        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>volume −18 dB</span>
      </div>
    </div>
  );
}

// --- Timeline strip ------------------------------------------------------

const TOTAL_MS = 23400;

function BeatLane({
  label,
  beats,
  currentId,
  setCurrentId,
  selected,
}: {
  label: string;
  beats: Beat[];
  currentId: string;
  setCurrentId: (id: string) => void;
  selected: boolean;
}) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: 1.6,
          color: T.text3,
          width: 70,
          flexShrink: 0,
          textAlign: "right",
        }}
      >
        {label}
      </span>
      <div
        style={{
          flex: 1,
          height: selected ? 64 : 36,
          position: "relative",
          background: selected ? T.panel2 : "transparent",
          borderRadius: 4,
          border: selected ? `1px solid ${T.border}` : "none",
        }}
      >
        {beats.map((b) => {
          const left = (b.tMs / TOTAL_MS) * 100;
          const width = (((b.duration / 60) * 1000) / TOTAL_MS) * 100;
          const meta = BEAT_KIND_META[b.kind];
          const isCurrent = b.id === currentId;
          const barHeight = (selected ? 52 : 26) * Math.max(0.35, b.score);
          return (
            <div
              key={b.id}
              onClick={() => setCurrentId(b.id)}
              title={`${b.t} · ${b.headline}`}
              style={{
                position: "absolute",
                left: `${left}%`,
                width: `max(${Math.max(2.4, width)}%, 18px)`,
                bottom: 6,
                height: barHeight,
                background: selected ? meta.accent : `${meta.accent}40`,
                border: isCurrent
                  ? `2px solid ${T.text}`
                  : selected
                  ? "none"
                  : `1px dashed ${meta.accent}80`,
                borderRadius: 2,
                cursor: "pointer",
                opacity: selected ? 1 : 0.5,
              }}
            />
          );
        })}
      </div>
    </div>
  );
}

function TimelineStrip({
  vod,
  currentId,
  setCurrentId,
}: {
  vod: VodMock;
  currentId: string;
  setCurrentId: (id: string) => void;
}) {
  const ticks = ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "15:30", "16:00"];
  const beats = vod.beats;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: "14px 16px 8px",
        display: "flex",
        flexDirection: "column",
        gap: 6,
        position: "relative",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.8, color: T.text3 }}>
          session timeline · 09:30 → 16:00 ET
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>
          {beats.length} beats detected · {vod.selectedBeats.size} selected
        </div>
      </div>
      <div style={{ position: "relative", height: 18, marginTop: 4 }}>
        {ticks.map((t, i, arr) => {
          const x = (i / (arr.length - 1)) * 100;
          return (
            <div
              key={t}
              style={{
                position: "absolute",
                left: `${x}%`,
                top: 0,
                transform: "translateX(-50%)",
                fontFamily: T.mono,
                fontSize: 10,
                color: T.text3,
              }}
            >
              {t}
            </div>
          );
        })}
        <div
          style={{
            position: "absolute",
            left: 0,
            right: 0,
            top: 16,
            height: 1,
            background: T.border,
          }}
        />
      </div>
      <BeatLane
        label="MASTER"
        beats={beats.filter((b) => vod.selectedBeats.has(b.id))}
        currentId={currentId}
        setCurrentId={setCurrentId}
        selected
      />
      <BeatLane
        label="REJECTED"
        beats={beats.filter((b) => !vod.selectedBeats.has(b.id))}
        currentId={currentId}
        setCurrentId={setCurrentId}
        selected={false}
      />
    </div>
  );
}

// --- Beat list rail ------------------------------------------------------

function BeatChip({
  beat,
  index,
  vod,
  isCurrent,
  onSelect,
}: {
  beat: Beat;
  index: number;
  vod: VodMock;
  isCurrent: boolean;
  onSelect: () => void;
}) {
  const meta = BEAT_KIND_META[beat.kind];
  const selected = vod.selectedBeats.has(beat.id);
  return (
    <div
      onClick={onSelect}
      style={{
        flex: "0 0 224px",
        background: isCurrent ? T.panel3 : T.panel,
        border: `1px solid ${isCurrent ? T.borderHi : T.border}`,
        borderRadius: 6,
        padding: 12,
        cursor: "pointer",
        opacity: selected ? 1 : 0.55,
        position: "relative",
        transition: "background 120ms",
      }}
    >
      <div
        style={{
          position: "absolute",
          left: 0,
          top: 12,
          bottom: 12,
          width: 2,
          borderRadius: 2,
          background: meta.accent,
        }}
      />
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3, letterSpacing: 1 }}>
          #{String(index).padStart(2, "0")}
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: 1.6,
            color: meta.accent,
            fontWeight: 700,
          }}
        >
          {meta.label}
        </span>
        <div style={{ flex: 1 }} />
        <ScoreCircle score={beat.score} />
      </div>
      <div
        style={{
          fontFamily: T.font,
          fontSize: 12,
          fontWeight: 600,
          color: T.text,
          marginBottom: 6,
          lineHeight: 1.3,
          height: 32,
          overflow: "hidden",
          textOverflow: "ellipsis",
          display: "-webkit-box",
          WebkitLineClamp: 2,
          WebkitBoxOrient: "vertical",
        }}
      >
        {beat.headline}
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text2,
        }}
      >
        <span>{beat.t}</span>
        <span>·</span>
        <span>{beat.duration}s</span>
        <span>·</span>
        <span>{beat.scene}</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={(e) => {
            e.stopPropagation();
            vod.toggleBeat(beat.id);
          }}
          style={{
            fontFamily: T.mono,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: 0.8,
            padding: "2px 6px",
            borderRadius: 3,
            border: `1px solid ${selected ? T.ok : T.text3}`,
            background: "transparent",
            color: selected ? T.ok : T.text3,
            cursor: "pointer",
          }}
        >
          {selected ? "IN" : "OUT"}
        </button>
      </div>
    </div>
  );
}

function BeatListRail({
  vod,
  currentId,
  setCurrentId,
}: {
  vod: VodMock;
  currentId: string;
  setCurrentId: (id: string) => void;
}) {
  return (
    <div
      className="vod-no-scroll"
      style={{ display: "flex", gap: 10, overflowX: "auto", padding: "2px 2px 6px" }}
    >
      {vod.beats.map((b, i) => (
        <BeatChip
          key={b.id}
          beat={b}
          index={i + 1}
          vod={vod}
          isCurrent={b.id === currentId}
          onSelect={() => setCurrentId(b.id)}
        />
      ))}
    </div>
  );
}

// --- Detail card ---------------------------------------------------------

function btnBP(color?: string): CSSProperties {
  return {
    fontFamily: T.mono,
    fontSize: 10,
    letterSpacing: 0.8,
    fontWeight: 700,
    padding: "8px 12px",
    borderRadius: 4,
    border: `1px solid ${color || T.border}`,
    background: color === T.ok ? `${T.ok}18` : "transparent",
    color: color || T.text2,
    cursor: "pointer",
    flex: 1,
  };
}

// Layered onto btnBP() for not-yet-wired actions.
const DISABLED_STYLE: CSSProperties = { cursor: "not-allowed", opacity: 0.45 };

function BeatDetailCard({ vod, beat }: { vod: VodMock; beat: Beat }) {
  const meta = BEAT_KIND_META[beat.kind];
  const involved = beat.agents
    .map((id) => VOD_AGENTS[id])
    .filter((a): a is NonNullable<typeof a> => a !== undefined);
  return (
    <div
      className="vod-no-scroll"
      style={{
        width: 360,
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 18,
        display: "flex",
        flexDirection: "column",
        gap: 14,
        overflow: "auto",
      }}
    >
      <div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <span
            style={{
              fontFamily: T.mono,
              fontSize: 10,
              letterSpacing: 1.6,
              color: meta.accent,
              fontWeight: 700,
            }}
          >
            {meta.label}
          </span>
          <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>
            · {beat.t} ET · {beat.duration}s
          </span>
          <div style={{ flex: 1 }} />
          <ScoreCircle score={beat.score} />
        </div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 16,
            fontWeight: 700,
            color: T.text,
            lineHeight: 1.35,
          }}
        >
          {beat.headline}
        </div>
      </div>

      <div>
        <SubLabel>caption · editing coming soon</SubLabel>
        <div
          title={COMING_SOON_TITLE}
          aria-disabled
          style={{
            fontFamily: T.font,
            fontSize: 13,
            color: T.text2,
            lineHeight: 1.5,
            background: T.bg,
            border: `1px solid ${T.border}`,
            borderRadius: 4,
            padding: "8px 10px",
            minHeight: 56,
            outline: "none",
            cursor: "not-allowed",
            opacity: 0.6,
          }}
        >
          {beat.sub}
        </div>
      </div>

      <div>
        <SubLabel>scene · render hint</SubLabel>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <code
            style={{
              fontFamily: T.mono,
              fontSize: 11,
              color: T.text,
              background: T.bg,
              padding: "4px 8px",
              borderRadius: 3,
              border: `1px solid ${T.border}`,
            }}
          >
            scene={beat.scene}
          </code>
          <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text3 }}>
            ?replay={vod.sessionId}&at={beat.t}
          </span>
        </div>
      </div>

      {involved.length > 0 && (
        <div>
          <SubLabel>personalities</SubLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            {involved.map((a) => (
              <div
                key={a.id}
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  background: T.bg,
                  padding: "8px 10px",
                  borderRadius: 4,
                  border: `1px solid ${T.border}`,
                }}
              >
                <div
                  style={{
                    width: 28,
                    height: 28,
                    borderRadius: 4,
                    background: stratColor(a.strategy),
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    fontFamily: T.mono,
                    fontSize: 11,
                    fontWeight: 700,
                    color: "#0a0a0a",
                  }}
                >
                  {a.initials}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{ fontFamily: T.font, fontSize: 12, fontWeight: 600, color: T.text }}
                  >
                    {a.display}
                  </div>
                  <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>
                    {VOD_STRATEGY_LABEL[a.strategy]} · {a.rank} · {a.trades}/{a.wins} W
                  </div>
                </div>
                <div
                  style={{
                    fontFamily: T.mono,
                    fontSize: 12,
                    fontWeight: 600,
                    color: a.pnl > 0 ? T.ok : T.err,
                  }}
                >
                  {fmtMoney(a.pnl, { signed: true, dp: 0 })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <SubLabel>event refs · manifest pointers</SubLabel>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {beat.refs.map((r) => (
            <code
              key={r}
              style={{
                fontFamily: T.mono,
                fontSize: 10,
                color: T.text2,
                background: T.bg,
                padding: "3px 6px",
                borderRadius: 3,
                border: `1px solid ${T.border}`,
              }}
            >
              {r}
            </code>
          ))}
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: "auto" }}>
        <button
          onClick={() => vod.toggleBeat(beat.id)}
          style={btnBP(vod.selectedBeats.has(beat.id) ? T.ok : T.text3)}
        >
          {vod.selectedBeats.has(beat.id) ? "✓ included" : "+ include"}
        </button>
        <button disabled title={COMING_SOON_TITLE} style={{ ...btnBP(), ...DISABLED_STYLE }}>
          ↻ regenerate caption
        </button>
      </div>
    </div>
  );
}

// --- Header --------------------------------------------------------------

function Pill({
  label,
  value,
  accent,
  subtle,
}: {
  label: string;
  value: string;
  accent?: string;
  subtle?: boolean;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
      <span style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
        {label}
      </span>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: 14,
          color: subtle ? T.text2 : accent || T.text,
          fontWeight: 600,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </span>
    </div>
  );
}

function BeatHeader({ vod }: { vod: VodMock }) {
  const dur = vod.totalDuration;
  const mins = Math.floor(dur / 60);
  const secs = dur % 60;
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "16px 24px",
        borderBottom: `1px solid ${T.border}`,
        background: T.panel,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 2, color: T.text3 }}>
          EP
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 22,
            fontWeight: 700,
            color: T.text,
            letterSpacing: -0.5,
          }}
        >
          {String(vod.episodeNumber).padStart(3, "0")}
        </span>
      </div>
      <div style={{ width: 1, height: 24, background: T.border }} />
      <div>
        <div style={{ fontFamily: T.font, fontSize: 14, fontWeight: 600, color: T.text }}>
          Beat picker
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text2 }}>{vod.sessionLabel}</div>
      </div>
      <div style={{ flex: 1 }} />
      <Pill label="reel length" value={`${mins}:${String(secs).padStart(2, "0")}`} accent={T.accent} />
      <Pill label="beats in master" value={`${vod.selectedBeats.size} / ${vod.beats.length}`} />
      <Pill label="target" value="08:00–12:00" subtle />
      <div style={{ width: 1, height: 24, background: T.border }} />
      <button
        disabled
        title={COMING_SOON_TITLE}
        style={{ ...btnBP(), flex: "none", ...DISABLED_STYLE }}
      >
        ↻ re-detect
      </button>
      <button
        disabled
        title={COMING_SOON_TITLE}
        style={{
          ...btnBP(T.accent),
          background: T.accent,
          color: "#1a1408",
          flex: "none",
          ...DISABLED_STYLE,
        }}
      >
        ▸ render selected
      </button>
    </div>
  );
}

// --- Top level -----------------------------------------------------------

export function BeatPicker({ vod }: { vod: VodMock }) {
  const fallbackBeat = vod.beats[0];
  if (!fallbackBeat) return null;
  const initial = vod.beats.find((b) => vod.selectedBeats.has(b.id))?.id ?? fallbackBeat.id;
  const [currentId, setCurrentId] = useState(initial);
  const current = vod.beats.find((b) => b.id === currentId) ?? fallbackBeat;
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
      <BeatHeader vod={vod} />
      <div style={{ flex: 1, display: "flex", minHeight: 0, gap: 14, padding: 14 }}>
        <div
          style={{
            flex: 1,
            display: "flex",
            flexDirection: "column",
            gap: 14,
            minWidth: 0,
          }}
        >
          <div style={{ flex: 1, minHeight: 0, display: "flex" }}>
            <PreviewPane beat={current} />
          </div>
          <TimelineStrip vod={vod} currentId={currentId} setCurrentId={setCurrentId} />
          <BeatListRail vod={vod} currentId={currentId} setCurrentId={setCurrentId} />
        </div>
        <BeatDetailCard vod={vod} beat={current} />
      </div>
    </div>
  );
}
