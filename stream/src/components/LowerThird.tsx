import { AnimatePresence, motion } from "framer-motion";
import type { BannerState } from "../hooks/useStreamCommands";

/**
 * 1080p-friendly lower-third overlay. Renders nothing when ``banner`` is
 * null; otherwise fades in a left-accent-barred title + subtitle 96px above
 * the bottom edge of its parent. Mount inside the SceneRotator's body
 * region (the same container that hosts AnimatePresence for scene swaps).
 */
export function LowerThird({ banner }: { banner: BannerState | null }) {
  return (
    <div className="absolute inset-0 pointer-events-none">
      <AnimatePresence>
        {banner && (
          <motion.div
            key={`${banner.shown_at}-${banner.title}`}
            initial={{ opacity: 0, y: 24 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 24 }}
            transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
            className="absolute bottom-24 left-0 right-0 flex justify-center"
          >
            <div className="flex items-stretch gap-4 rounded-md bg-zinc-950/80 backdrop-blur-md border border-zinc-800/80 shadow-2xl px-5 py-4 max-w-[80%]">
              <span className="w-1.5 self-stretch rounded-full bg-(--color-profit)" />
              <div className="leading-tight">
                <div className="text-3xl font-bold text-zinc-50 tracking-tight">
                  {banner.title}
                </div>
                {banner.subtitle && (
                  <div className="text-base text-zinc-400 mt-1 font-mono">
                    {banner.subtitle}
                  </div>
                )}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
