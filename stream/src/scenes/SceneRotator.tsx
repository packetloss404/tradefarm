import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { TopTicker } from "../components/TopTicker";
import { BottomTicker } from "../components/BottomTicker";
import { CommentaryCaption } from "../components/CommentaryCaption";
import { PromotionToast } from "../components/PromotionToast";
import { useCommentary } from "../hooks/useCommentary";
import type { StreamSnapshot } from "../hooks/useStreamData";
import { HeroBody } from "./HeroBody";
import { LeaderboardScene } from "./LeaderboardScene";
import { BrainScene } from "./BrainScene";
import { StrategyScene } from "./StrategyScene";

const ORDER = ["hero", "leaderboard", "brain", "strategy"] as const;
type SceneId = (typeof ORDER)[number];

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
}: {
  snapshot: StreamSnapshot;
  rotationSec: number;
  paused: boolean;
  commentaryEnabled: boolean;
  tickerSpeedPxPerSec: number;
}) {
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (rotationSec <= 0 || paused) return;
    const t = setInterval(() => {
      setIdx((i) => (i + 1) % ORDER.length);
    }, rotationSec * 1000);
    return () => clearInterval(t);
  }, [rotationSec, paused]);

  const id: SceneId = rotationSec <= 0 ? "hero" : (ORDER[idx] ?? "hero");

  const commentary = useCommentary({
    agents: snapshot.agents,
    fills: snapshot.fills,
    promotions: snapshot.promotions,
    enabled: commentaryEnabled,
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
            {id === "hero" && <HeroBody snapshot={snapshot} />}
            {id === "leaderboard" && <LeaderboardScene snapshot={snapshot} />}
            {id === "brain" && <BrainScene snapshot={snapshot} />}
            {id === "strategy" && <StrategyScene snapshot={snapshot} />}
          </motion.div>
        </AnimatePresence>

        <PromotionToast promotions={snapshot.promotions} />
        <CommentaryCaption highlight={commentary.current} />

        {snapshot.error && (
          <div className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 rounded-md bg-rose-500/20 border border-rose-500/50 px-6 py-4 text-(--color-loss) font-mono">
            Backend unreachable: {snapshot.error}
          </div>
        )}

        {/* Scene indicator dots — bottom-right of the body area */}
        <div className="absolute bottom-3 right-4 flex items-center gap-1.5 z-10">
          {ORDER.map((s) => (
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
