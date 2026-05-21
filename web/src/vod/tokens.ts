// Shared design tokens for the VOD Studio surfaces — ported from the
// prototype's BP/VP/SC/EP objects (which were nearly identical). One
// source of truth so all four artboards stay visually coherent.

export const T = {
  bg: "#0c0d10",
  panel: "#13141a",
  panel2: "#191a22",
  panel3: "#1f2129",
  border: "#23252e",
  borderHi: "#363946",
  text: "#e7e8ec",
  text2: "#9094a0",
  text3: "#5e636f",
  accent: "#d4a02e",
  accent2: "#86c5ff",
  ok: "#34d399",
  warn: "#fbbf24",
  err: "#fb7185",
  rec: "#ef4444",
  yt: "#ff0033",
  font: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: "JetBrains Mono, ui-monospace, monospace",
} as const;

export type ThemeColor = keyof typeof T;
