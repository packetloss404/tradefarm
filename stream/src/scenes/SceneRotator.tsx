import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { TopTicker } from "../components/TopTicker";
import { BottomTicker } from "../components/BottomTicker";
import { CommentaryCaption } from "../components/CommentaryCaption";
import { PromotionToast } from "../components/PromotionToast";
import { LowerThird } from "../components/LowerThird";
import { MacroFireBurst } from "../components/MacroFireBurst";
import { ChapterBanner } from "../components/ChapterBanner";
import { useCommentary } from "../hooks/useCommentary";
import { useMarketClock } from "../hooks/useMarketClock";
import { useChapter } from "../hooks/useChapter";
import type { StreamSnapshot } from "../hooks/useStreamData";
import type { BannerState, CommentaryState, MacroFireState } from "../hooks/useStreamCommands";
import { HeroBody } from "./HeroBody";
import { LeaderboardScene } from "./LeaderboardScene";
import { BrainScene } from "./BrainScene";
import { StrategyScene } from "./StrategyScene";
import { RecapScene } from "./RecapScene";
import { ShowdownScene } from "./ShowdownScene";

const ORDER = ["hero", "leaderboard", "showdown", "brain", "strategy", "recap"] as const;
type SceneId = (typeof ORDER)[number];

function pickWeighted(
  pool: readonly SceneId[],
  weights: Record<SceneId, number>,
  exclude: SceneId | null,
): SceneId | null {
  const candidates = pool.filter((s) => s !== exclude && (weights[s] ?? 0) > 0);
  // Fall back to the unfiltered pool if exclusion left nothing weight-eligible
  // (e.g. a chapter that only weights a single scene).
  const effective = candidates.length > 0 ? candidates : pool.filter((s) => (weights[s] ?? 0) > 0);
  if (effective.length === 0) return null;
  const total = effective.reduce((a, s) => a + (weights[s] ?? 0), 0);
  if (total <= 0) return effective[0] ?? null;
  let r = Math.random() * total;
  for (const s of effective) {
    r -= weights[s] ?? 0;
    if (r <= 0) return s;
  }
  return effective[effective.length - 1] ?? null;
}

/**
 * Top-level scene rotator. The TopTicker / BottomTicker / promotion toast
 * / commentary caption are persistent across all scenes; only the middle
 * panel crossfades. If `rotationSec` <= 0 the rotator pins on Hero.
 *
 * `paused` is set true when the Admin overlay is open so a viewer can read
 * settings without losing their place.
 */
export function SceneRotator({
  snapshot,
  rotationSec,
  paused,
  commentaryEnabled,
  tickerSpeedPxPerSec,
  forceSceneId,
  banner,
  macroFire,
  pinAgentId,
  commentary,
}: {
  snapshot: StreamSnapshot;
  rotationSec: number;
  paused: boolean;
  commentaryEnabled: boolean;
  tickerSpeedPxPerSec: number;
  forceSceneId?: string | null;
  banner?: BannerState | null;
  macroFire?: MacroFireState | null;
  pinAgentId: number | null;
  commentary?: CommentaryState | null;
}) {
  const { phase } = useMarketClock();
  const chapter = useChapter();

  // Recap is only eligible after 16:00 ET on a closed/afterhours session.
  // Double-check the wall-clock ET hour because phase === "closed" also
  // fires before the open on weekends/holidays.
  const recapEligible = useMemo(() => {
    if (phase !== "afterhours" && phase !== "closed") return false;
    // hourCycle: "h23" → 0..23 (avoids the h24 quirk where midnight returns "24"
    // on some Chromium releases, which would incorrectly satisfy hour >= 16).
    const etHourStr = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      hour: "2-digit",
      hour12: false,
      hourCycle: "h23",
    }).format(new Date());
    const etHour = Number.parseInt(etHourStr, 10);
    return Number.isFinite(etHour) && etHour >= 16 && etHour < 24;
  }, [phase]);

  const cycle = useMemo<readonly SceneId[]>(
    () => (recapEligible ? ORDER : ORDER.filter((s) => s !== "recap")),
    [recapEligible],
  );

  // Effective cadence: operator override (rotationSec > 0) wins; otherwise
  // the current chapter dictates pace.
  const effectiveCadenceSec = rotationSec > 0 ? rotationSec : chapter.cadenceSec;

  const [currentScene, setCurrentScene] = useState<SceneId>("hero");
  const sceneRef = useRef<SceneId>(currentScene);
  sceneRef.current = currentScene;

  useEffect(() => {
    if (effectiveCadenceSec <= 0 || paused || forceSceneId) return;
    const t = setInterval(() => {
      const next = pickWeighted(cycle, chapter.sceneWeights, sceneRef.current);
      if (next) setCurrentScene(next);
    }, effectiveCadenceSec * 1000);
    return () => clearInterval(t);
  }, [effectiveCadenceSec, paused, forceSceneId, cycle, chapter.sceneWeights]);

  // If the current scene drops out of the cycle (e.g. recap when no longer
  // eligible), snap to a chapter-weighted alternative.
  useEffect(() => {
    if (!cycle.includes(currentScene)) {
      const next = pickWeighted(cycle, chapter.sceneWeights, null);
      if (next) setCurrentScene(next);
    }
  }, [cycle, chapter.sceneWeights, currentScene]);

  const id: SceneId =
    forceSceneId && (ORDER as readonly string[]).includes(forceSceneId)
      ? (forceSceneId as SceneId)
      : effectiveCadenceSec <= 0
        ? "hero"
        : currentScene;

  const commentaryFeed = useCommentary({
    agents: snapshot.agents,
    fills: snapshot.fills,
    promotions: snapshot.promotions,
    enabled: commentaryEnabled,
    commentary: commentary ?? null,
  });

  return (
    <div className="h-full w-full flex flex-col bg-zinc-950 text-zinc-100">
      <TopTicker
        account={snapshot.account}
        agentCount={snapshot.agents.length}
        wsStatus={snapshot.status}
      />

      <div className="flex-1 relative overflow-hidden">
        <AnimatePresence mode="wait">
          <motion.div
            key={id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.5 }}
            className="absolute inset-0"
          >
            {id === "hero" && <HeroBody snapshot={snapshot} pinAgentId={pinAgentId} />}
            {id === "leaderboard" && <LeaderboardScene snapshot={snapshot} />}
            {id === "showdown" && <ShowdownScene snapshot={snapshot} />}
            {id === "brain" && <BrainScene snapshot={snapshot} pinAgentId={pinAgentId} />}
            {id === "strategy" && <StrategyScene snapshot={snapshot} />}
            {id === "recap" && <RecapScene snapshot={snapshot} />}
          </motion.div>
        </AnimatePresence>

        <PromotionToast promotions={snapshot.promotions} />
        <CommentaryCaption highlight={commentaryFeed.current} />
        <LowerThird banner={banner ?? null} />
        <MacroFireBurst event={macroFire ?? null} />
        <ChapterBanner key={chapter.id} label={chapter.label} />

        {snapshot.error && (
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-md bg-rose-500/20 border border-rose-500/50 px-6 py-4 text-(--color-loss) font-mono">
            Backend unreachable: {snapshot.error}
          </div>
        )}

        {/* Scene indicator dots — bottom-right of the body area */}
        <div className="absolute bottom-3 right-4 flex items-center gap-1.5 z-10">
          {cycle.map((s) => (
            <span
              key={s}
              className={`h-1.5 rounded-full transition-all ${
                s === id ? "w-6 bg-emerald-500/80" : "w-1.5 bg-zinc-700"
              }`}
              title={s}
            />
          ))}
        </div>
      </div>

      <BottomTicker
        agents={snapshot.agents}
        fills={snapshot.fills}
        promotions={snapshot.promotions}
        speedPxPerSec={tickerSpeedPxPerSec}
      />
    </div>
  );
}
