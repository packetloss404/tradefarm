import { useEffect, useState } from "react";
import { useMarketClock } from "./useMarketClock";

export type ChapterId =
  | "pre-market"
  | "opening"
  | "mid-morning"
  | "lunch"
  | "afternoon"
  | "power-hour"
  | "closing"
  | "after-hours";

export type SceneId =
  | "hero"
  | "leaderboard"
  | "showdown"
  | "brain"
  | "decision-lab"
  | "strategy"
  | "recap";

export type Chapter = {
  id: ChapterId;
  label: string;
  sceneWeights: Record<SceneId, number>;
  cadenceSec: number;
};

const CHAPTERS: Record<ChapterId, Omit<Chapter, "id">> = {
  "pre-market": {
    label: "Pre-market mayhem",
    cadenceSec: 12,
    sceneWeights: {
      hero: 1,
      leaderboard: 3,
      showdown: 2,
      brain: 2,
      "decision-lab": 1,
      strategy: 3,
      recap: 0,
    },
  },
  opening: {
    label: "Opening drama",
    cadenceSec: 8,
    sceneWeights: {
      hero: 4,
      leaderboard: 2,
      showdown: 2,
      brain: 4,
      "decision-lab": 1,
      strategy: 1,
      recap: 0,
    },
  },
  "mid-morning": {
    label: "Mid-morning grind",
    cadenceSec: 20,
    sceneWeights: {
      hero: 2,
      leaderboard: 2,
      showdown: 2,
      brain: 2,
      "decision-lab": 3,
      strategy: 2,
      recap: 0,
    },
  },
  lunch: {
    label: "Lunchtime lull",
    cadenceSec: 30,
    sceneWeights: {
      hero: 1,
      leaderboard: 3,
      showdown: 1,
      brain: 1,
      "decision-lab": 4,
      strategy: 4,
      recap: 0,
    },
  },
  afternoon: {
    label: "Afternoon ranges",
    cadenceSec: 20,
    sceneWeights: {
      hero: 2,
      leaderboard: 2,
      showdown: 2,
      brain: 2,
      "decision-lab": 3,
      strategy: 2,
      recap: 0,
    },
  },
  "power-hour": {
    label: "Power hour",
    cadenceSec: 10,
    sceneWeights: {
      hero: 3,
      leaderboard: 1,
      showdown: 3,
      brain: 4,
      "decision-lab": 1,
      strategy: 1,
      recap: 0,
    },
  },
  closing: {
    label: "Closing bell",
    cadenceSec: 15,
    sceneWeights: {
      hero: 1,
      leaderboard: 3,
      showdown: 1,
      brain: 1,
      "decision-lab": 1,
      strategy: 1,
      recap: 4,
    },
  },
  "after-hours": {
    label: "After-hours",
    cadenceSec: 40,
    sceneWeights: {
      hero: 5,
      leaderboard: 1,
      showdown: 1,
      brain: 1,
      "decision-lab": 2,
      strategy: 1,
      recap: 2,
    },
  },
};

function getEtHourMinute(): { hour: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    hourCycle: "h23",
  }).formatToParts(new Date());
  const hourStr = parts.find((p) => p.type === "hour")?.value ?? "0";
  const minStr = parts.find((p) => p.type === "minute")?.value ?? "0";
  const hour = Number.parseInt(hourStr, 10);
  const minute = Number.parseInt(minStr, 10);
  return {
    hour: Number.isFinite(hour) ? hour : 0,
    minute: Number.isFinite(minute) ? minute : 0,
  };
}

function resolveChapterId(
  phase: "premarket" | "rth" | "afterhours" | "closed",
  hour: number,
  minute: number,
): ChapterId {
  const minutesSinceMidnight = hour * 60 + minute;
  // Pre-market: explicit phase or any time before 9:30 ET
  if (phase === "premarket" || minutesSinceMidnight < 9 * 60 + 30) {
    return "pre-market";
  }
  // After-hours / closed outside the trading day
  if (phase === "closed" || minutesSinceMidnight >= 17 * 60) {
    return "after-hours";
  }
  // RTH-aligned windows (also catches `afterhours` between 16:00 and 17:00)
  if (minutesSinceMidnight < 10 * 60 + 30) return "opening";
  if (minutesSinceMidnight < 12 * 60) return "mid-morning";
  if (minutesSinceMidnight < 13 * 60 + 30) return "lunch";
  if (minutesSinceMidnight < 15 * 60) return "afternoon";
  if (minutesSinceMidnight < 16 * 60) return "power-hour";
  return "closing";
}

export function useChapter(): Chapter {
  const { phase } = useMarketClock();
  const [now, setNow] = useState<{ hour: number; minute: number }>(() =>
    getEtHourMinute(),
  );

  // Tick once a minute so chapter boundaries (e.g. 9:30, 10:30, 12:00) fire.
  useEffect(() => {
    const t = setInterval(() => setNow(getEtHourMinute()), 30_000);
    return () => clearInterval(t);
  }, []);

  const id = resolveChapterId(phase, now.hour, now.minute);
  const def = CHAPTERS[id];
  return { id, label: def.label, sceneWeights: def.sceneWeights, cadenceSec: def.cadenceSec };
}
