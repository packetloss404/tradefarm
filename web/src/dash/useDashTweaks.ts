// Persisted tweaks panel state — theme, density, and per-page layout
// toggles. Synced to localStorage so the operator's preference survives
// reloads and split-machine deploys.

import { useEffect, useState } from "react";
import type { DensityId, ThemeId } from "./tokens";

export type DashTweaks = {
  theme: ThemeId;
  density: DensityId;
  showCostRail: boolean;
  showPipelinePanel: boolean;
};

const DEFAULT_TWEAKS: DashTweaks = {
  theme: "studio-dark",
  density: "comfortable",
  showCostRail: true,
  showPipelinePanel: true,
};

const STORAGE_KEY = "tf-dash-tweaks-v1";

function load(): DashTweaks {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_TWEAKS;
    const parsed = JSON.parse(raw) as Partial<DashTweaks>;
    return { ...DEFAULT_TWEAKS, ...parsed };
  } catch {
    return DEFAULT_TWEAKS;
  }
}

export function useDashTweaks(): [DashTweaks, <K extends keyof DashTweaks>(k: K, v: DashTweaks[K]) => void] {
  const [tweaks, setTweaks] = useState<DashTweaks>(() => load());
  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(tweaks));
    } catch {
      /* private browsing etc — non-fatal */
    }
  }, [tweaks]);
  function setTweak<K extends keyof DashTweaks>(k: K, v: DashTweaks[K]) {
    setTweaks((prev) => ({ ...prev, [k]: v }));
  }
  return [tweaks, setTweak];
}
