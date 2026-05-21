// Theme/density context — every dashboard page reads from useTheme()
// to pick up the operator's tweaks-panel preference. Defaults to dark
// + comfortable.

import { createContext, useContext, type ReactNode } from "react";
import { DENSITY, TOKENS, type Density, type Theme } from "./tokens";

type Ctx = { T: Theme; D: Density };

const defaultCtx: Ctx = { T: TOKENS["studio-dark"], D: DENSITY.comfortable };

const ThemeCtx = createContext<Ctx>(defaultCtx);

export function ThemeProvider({ value, children }: { value: Ctx; children: ReactNode }) {
  return <ThemeCtx.Provider value={value}>{children}</ThemeCtx.Provider>;
}

export function useTheme(): Ctx {
  return useContext(ThemeCtx);
}
