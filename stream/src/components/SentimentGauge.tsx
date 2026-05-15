import { motion } from "framer-motion";
import type { AudienceSentimentState } from "../hooks/useStreamCommands";

// Minimum sample size before we show the gauge. A single vote can swing the
// score to ±1 which is meaningless and visually distracting on stream.
const MIN_SAMPLES = 3;

/**
 * Bottom-right horizontal sentiment gauge driven by audience chat. The bar
 * grows from the center marker — left side fills `--color-loss` for negative
 * scores, right side fills `--color-profit` for positive. Hidden until we
 * have at least `MIN_SAMPLES` total votes so an early single-vote skew
 * doesn't put a misleading full-red bar on-screen.
 *
 * Score is clamped [-1, 1] by `useStreamCommands` so a bad payload can't
 * push the bar past its track.
 */
export function SentimentGauge({ sentiment }: { sentiment: AudienceSentimentState | null }) {
  if (!sentiment) return null;
  const total = sentiment.up + sentiment.down;
  if (total < MIN_SAMPLES) return null;

  const score = sentiment.score;
  const negative = score < 0;
  // The bar takes up to ~50% of the track on either side of the center.
  const widthPct = Math.min(1, Math.abs(score)) * 50;

  return (
    <div className="absolute bottom-3 right-3 z-20 w-[200px] pointer-events-none select-none">
      <div className="rounded-md bg-zinc-950/70 backdrop-blur-sm border border-zinc-800/80 px-2.5 py-1.5 shadow-lg">
        <div className="flex items-baseline justify-between mb-1">
          <span className="text-[9px] font-mono uppercase tracking-[0.18em] text-zinc-400">
            Audience
          </span>
          <span
            className={`text-[9px] font-mono tabular-nums ${
              score > 0.05
                ? "text-(--color-profit)"
                : score < -0.05
                  ? "text-(--color-loss)"
                  : "text-zinc-500"
            }`}
          >
            {score > 0 ? "+" : ""}
            {score.toFixed(2)}
          </span>
        </div>

        <div className="relative h-2.5 rounded-sm bg-zinc-900/80 overflow-hidden">
          {/* Center marker */}
          <span className="absolute left-1/2 top-0 bottom-0 w-px bg-zinc-700/80" />

          {/* Left (negative) bar — anchored at center, grows leftward. */}
          {negative && (
            <motion.span
              key="neg"
              initial={false}
              animate={{ width: `${widthPct}%` }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="absolute top-0 bottom-0 right-1/2 bg-(--color-loss) rounded-l-sm"
            />
          )}

          {/* Right (positive) bar — anchored at center, grows rightward. */}
          {!negative && (
            <motion.span
              key="pos"
              initial={false}
              animate={{ width: `${widthPct}%` }}
              transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
              className="absolute top-0 bottom-0 left-1/2 bg-(--color-profit) rounded-r-sm"
            />
          )}
        </div>

        <div className="mt-1 flex items-center justify-between font-mono text-[9px] tabular-nums">
          <span className="text-(--color-loss)">−{sentiment.down}</span>
          <span className="text-zinc-600">{total} votes</span>
          <span className="text-(--color-profit)">+{sentiment.up}</span>
        </div>
      </div>
    </div>
  );
}
