// Theme tokens + density presets for the multi-page dashboard.
// Three themes (studio-dark / studio-light / amber-crt) selectable from
// the bottom-right tweaks panel; density swaps row heights and font sizes.

export type ThemeId = "studio-dark" | "studio-light" | "amber-crt";

export type Theme = {
  bg: string;
  panel: string;
  panel2: string;
  panel3: string;
  border: string;
  borderHi: string;
  text: string;
  text2: string;
  text3: string;
  accent: string;
  accent2: string;
  ok: string;
  warn: string;
  err: string;
  rec: string;
};

export const TOKENS: Record<ThemeId, Theme> = {
  "studio-dark": {
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
  },
  "studio-light": {
    bg: "#f4f2ee",
    panel: "#ffffff",
    panel2: "#f9f7f3",
    panel3: "#f0eee8",
    border: "#dcd8d2",
    borderHi: "#c4bfb8",
    text: "#1c1d22",
    text2: "#52555e",
    text3: "#888a92",
    accent: "#a36b00",
    accent2: "#1f6fd0",
    ok: "#0d8a5b",
    warn: "#a16207",
    err: "#c5183c",
    rec: "#d4133a",
  },
  "amber-crt": {
    bg: "#0a0805",
    panel: "#14100a",
    panel2: "#1e170d",
    panel3: "#2a200f",
    border: "#3a2f1a",
    borderHi: "#5a4a28",
    text: "#fbcf7e",
    text2: "#c79a4a",
    text3: "#80622c",
    accent: "#ffb347",
    accent2: "#ff9b50",
    ok: "#a8d65c",
    warn: "#ffd166",
    err: "#ff7a59",
    rec: "#ff5848",
  },
};

export type DensityId = "compact" | "comfortable" | "cozy";

export type Density = { row: number; gap: number; pad: number; font: number };

export const DENSITY: Record<DensityId, Density> = {
  compact: { row: 32, gap: 8, pad: 12, font: 12 },
  comfortable: { row: 40, gap: 12, pad: 16, font: 13 },
  cozy: { row: 52, gap: 18, pad: 22, font: 14 },
};
