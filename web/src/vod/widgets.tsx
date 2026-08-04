// Small primitives shared across all four VOD surfaces. Formatters,
// pulse/cursor keyframes, sparkline, score circle, status dot, progress
// bar, ET clock. Mirrors the prototype's shared.jsx + the small helpers
// scattered across the four artboard files.

import { useEffect, useState } from "react";
import { T } from "./tokens";
import { VOD_STRATEGY_HUE } from "./data";
import type { Strategy } from "./types";

// One-time keyframe injection — the prototype attaches @keyframes
// pulse-dot and cursor-blink via inline <style>. We need them anywhere
// the VOD surfaces mount, so do it imperatively the first time anything
// from this module is imported.
if (typeof document !== "undefined" && !document.getElementById("vod-keyframes")) {
  const s = document.createElement("style");
  s.id = "vod-keyframes";
  s.textContent = `
    @keyframes vod-pulse-dot {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(0.5); opacity: 0.4; }
    }
    .vod-pulse-dot { animation: vod-pulse-dot 1.2s ease-in-out infinite; transform-origin: center; }
    @keyframes vod-cursor-blink { 0%, 49% { opacity: 1; } 50%, 100% { opacity: 0; } }
    .vod-cursor-blink { animation: vod-cursor-blink 1s step-end infinite; }
    /* Hide scrollbars inside the studio (the surfaces scroll plenty
       internally; the chrome reads cleaner without). */
    .vod-no-scroll::-webkit-scrollbar { display: none; }
    .vod-no-scroll { scrollbar-width: none; }
  `;
  document.head.appendChild(s);
}

type FmtMoneyOpts = { compact?: boolean; signed?: boolean; dp?: number };
export function fmtMoney(n: number, opts: FmtMoneyOpts = {}): string {
  const sign = n >= 0 ? "+" : "−";
  const abs = Math.abs(n);
  if (opts.compact && abs >= 1_000_000) {
    return (n >= 0 ? "+" : "−") + "$" + (abs / 1_000_000).toFixed(2) + "M";
  }
  if (opts.compact && abs >= 1000) {
    return (n >= 0 ? "+" : "−") + "$" + (abs / 1000).toFixed(2) + "k";
  }
  const v =
    "$" +
    abs.toLocaleString("en-US", {
      maximumFractionDigits: opts.dp ?? 2,
      minimumFractionDigits: opts.dp ?? 2,
    });
  return opts.signed ? sign + v : v;
}

export function fmtPct(n: number, dp = 2): string {
  return (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(dp) + "%";
}

export function fmtInt(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

export function stratColor(s: Strategy): string {
  return `oklch(0.72 0.18 ${VOD_STRATEGY_HUE[s]})`;
}

export function Sparkline({
  data,
  color = "currentColor",
  width = 80,
  height = 22,
  strokeWidth = 1.5,
  fillBelow = false,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  strokeWidth?: number;
  fillBelow?: boolean;
}) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return [x, y] as const;
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const fill = fillBelow ? `0,${height} ${line} ${width},${height}` : null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {fill && <polygon points={fill} fill={color} opacity="0.18" />}
      <polyline
        points={line}
        fill="none"
        stroke={color}
        strokeWidth={strokeWidth}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

export function ETClock({ intervalMs = 500 }: { intervalMs?: number }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), intervalMs);
    return () => window.clearInterval(id);
  }, [intervalMs]);
  return (
    <span>
      {now.toLocaleTimeString("en-US", { hour12: false, timeZone: "America/New_York" })}
    </span>
  );
}

export function ScoreCircle({ score }: { score: number }) {
  const r = 11;
  const c = 2 * Math.PI * r;
  const stroke = score > 0.7 ? T.accent : score > 0.5 ? T.accent2 : T.text3;
  return (
    <div style={{ position: "relative", width: 26, height: 26 }}>
      <svg width="26" height="26" viewBox="0 0 26 26">
        <circle cx="13" cy="13" r={r} fill="none" stroke={T.panel3} strokeWidth="2" />
        <circle
          cx="13"
          cy="13"
          r={r}
          fill="none"
          stroke={stroke}
          strokeWidth="2"
          strokeDasharray={`${c * score} ${c}`}
          transform="rotate(-90 13 13)"
          strokeLinecap="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontFamily: T.mono,
          fontSize: 9,
          color: T.text,
          fontWeight: 700,
        }}
      >
        {(score * 100).toFixed(0)}
      </div>
    </div>
  );
}

export function StatusDot({
  status,
}: {
  status: "done" | "running" | "queued" | "failed";
}) {
  const color =
    status === "done"
      ? T.ok
      : status === "running"
      ? T.accent
      : status === "failed"
      ? T.err
      : T.text3;
  return (
    <span
      className={status === "running" ? "vod-pulse-dot" : undefined}
      style={{
        display: "inline-block",
        width: 8,
        height: 8,
        borderRadius: 999,
        background: color,
        boxShadow: status === "running" ? `0 0 8px ${color}` : "none",
        flexShrink: 0,
      }}
    />
  );
}

export function ProgressBar({
  progress,
  color = T.accent,
  height = 4,
}: {
  progress: number;
  color?: string;
  height?: number;
}) {
  return (
    <div style={{ height, background: T.panel2, borderRadius: 2, overflow: "hidden" }}>
      <div
        style={{
          width: `${Math.max(0, Math.min(1, progress)) * 100}%`,
          height: "100%",
          background: color,
          transition: "width 200ms ease",
        }}
      />
    </div>
  );
}

export function SubLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontFamily: T.mono,
        fontSize: 9,
        letterSpacing: 1.8,
        color: T.text3,
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}
