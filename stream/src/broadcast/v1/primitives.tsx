import { useNow } from "./hooks";
import { FONT_MONO } from "./tokens";

/**
 * Inline sparkline. Auto-scales to data range; renders nothing for <2 points.
 * `fillBelow` adds a translucent area fill under the line at 18% opacity.
 */
export function Sparkline({
  data,
  color = "currentColor",
  width = 80,
  height = 22,
  strokeWidth = 1.5,
  fillBelow = false,
  fillBelowOpacity = 0.18,
}: {
  data: number[];
  color?: string;
  width?: number;
  height?: number;
  strokeWidth?: number;
  fillBelow?: boolean;
  fillBelowOpacity?: number;
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
      {fill && <polygon points={fill} fill={color} opacity={fillBelowOpacity} />}
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

export function LiveDot({
  color = "#ef4444",
  label = "LIVE",
}: {
  color?: string;
  label?: string;
}) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontSize: 11,
        fontWeight: 800,
        letterSpacing: 1.4,
        color,
        fontFamily: FONT_MONO,
      }}
    >
      <span
        className="v1-pulse-dot"
        style={{ width: 8, height: 8, borderRadius: 999, background: color }}
      />
      {label}
    </span>
  );
}

/**
 * Market-status pill. The design uses a static "RTH · NYSE" placeholder; we
 * keep the same hard-coded variant for V1 and let a follow-up wire the real
 * `/market/clock` data in if needed.
 */
export function MarketBadge() {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        borderRadius: 4,
        background: "oklch(0.32 0.14 145)",
        color: "#a7f3d0",
        fontSize: 11,
        letterSpacing: 0.6,
        fontWeight: 700,
        fontFamily: FONT_MONO,
      }}
    >
      <span
        style={{
          width: 6,
          height: 6,
          borderRadius: 999,
          background: "#34d399",
          boxShadow: "0 0 8px #34d399",
        }}
      />
      RTH · NYSE
    </span>
  );
}

export function ETClock() {
  const now = useNow(500);
  const s = now.toLocaleTimeString("en-US", {
    hour12: false,
    timeZone: "America/New_York",
  });
  return <span>{s}</span>;
}
