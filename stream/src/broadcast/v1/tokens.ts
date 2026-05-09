// Design tokens for the V1 sports-broadcast layout. These match the
// `design_handoff_v1_broadcast` README's Design Tokens section verbatim;
// keep them in lockstep if the design ever revs.

export const V1 = {
  // Surfaces
  BG: "#08090d",
  PANEL: "#10131a",
  PANEL_HI: "#171b25",
  LINE: "#22262f",
  AMBER: "#fbbf24",

  // Text
  TEXT: "#fafafa",
  TEXT_DIM: "#d4d4d8",
  TEXT_MUTED: "#9ca3af",
  TEXT_HINT: "#71717a",
  TEXT_FAINT: "#52525b",

  // P&L
  PROFIT: "#10b981",
  PROFIT_HI: "#34d399",
  LOSS: "#f43f5e",
  LOSS_HI: "#fb7185",
} as const;

// Strategy hue mapping. The design uses oklch(0.72 0.18 H) for a perceptually
// even palette across momentum / lstm / llm. The dim variant is used as the
// origin of the race-lane progress gradient.
export const STRATEGY_HUE = {
  momentum: 24,
  lstm: 200,
  llm: 280,
} as const;

export type StrategyKey = keyof typeof STRATEGY_HUE;

export const stratColor = (s: StrategyKey): string => `oklch(0.72 0.18 ${STRATEGY_HUE[s]})`;
export const stratColorDim = (s: StrategyKey): string => `oklch(0.5 0.12 ${STRATEGY_HUE[s]})`;

export const STRATEGY_LABEL: Record<StrategyKey, string> = {
  momentum: "MOM",
  lstm: "LSTM",
  llm: "LSTM+LLM",
};

export const RANK_LABEL = {
  intern: "IN",
  junior: "JR",
  senior: "SR",
  principal: "PR",
} as const;

export const FONT_MONO = "'JetBrains Mono', monospace";
export const FONT_BODY = "'Helvetica Neue', Helvetica, Arial, sans-serif";

export const pnlColor = (n: number, neutral: string = V1.TEXT_MUTED): string =>
  n > 1 ? V1.PROFIT : n < -1 ? V1.LOSS : neutral;

export const fmtPct = (n: number, dp = 2): string =>
  (n >= 0 ? "+" : "−") + Math.abs(n).toFixed(dp) + "%";

export const fmtMoneyAbs = (n: number, dp = 0): string =>
  "$" +
  Math.abs(n).toLocaleString("en-US", {
    maximumFractionDigits: dp,
    minimumFractionDigits: dp,
  });

export const fmtSignedMoney = (n: number, dp = 0): string =>
  (n >= 0 ? "+" : "−") + fmtMoneyAbs(n, dp);
