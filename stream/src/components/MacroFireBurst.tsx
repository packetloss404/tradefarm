import { AnimatePresence, motion } from "framer-motion";

export type MacroFireEvent = {
  id: string;
  label: string;
  color?: "profit" | "loss" | "neutral";
  subtitle?: string;
};

const RING_BY_COLOR: Record<NonNullable<MacroFireEvent["color"]>, string> = {
  profit: "ring-(--color-profit) text-(--color-profit)",
  loss: "ring-(--color-loss) text-(--color-loss)",
  neutral: "ring-zinc-100 text-zinc-100",
};

const FLASH_BY_COLOR: Record<NonNullable<MacroFireEvent["color"]>, string> = {
  profit:
    "bg-[radial-gradient(circle_at_center,_color-mix(in_oklab,_var(--color-profit)_55%,_transparent)_0%,_transparent_60%)]",
  loss: "bg-[radial-gradient(circle_at_center,_color-mix(in_oklab,_var(--color-loss)_55%,_transparent)_0%,_transparent_60%)]",
  neutral:
    "bg-[radial-gradient(circle_at_center,_color-mix(in_oklab,_white_45%,_transparent)_0%,_transparent_60%)]",
};

/**
 * Full-bleed director-moment burst. Replaces any in-flight burst when re-keyed
 * (parent owns the slot and re-keys via a fresh `id`/`firedAt`).
 */
export function MacroFireBurst({ event }: { event: MacroFireEvent | null }) {
  const colorKey = event?.color ?? "neutral";
  return (
    <div className="absolute inset-0 pointer-events-none z-30">
      <AnimatePresence>
        {event && (
          <motion.div
            key={event.id}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
            className="absolute inset-0"
          >
            <motion.div
              initial={{ opacity: 0.0, scale: 0.6 }}
              animate={{ opacity: [0, 0.9, 0], scale: [0.6, 1.4, 1.6] }}
              transition={{ duration: 0.9, ease: [0.16, 1, 0.3, 1] }}
              className={`absolute inset-0 ${FLASH_BY_COLOR[colorKey]}`}
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.85 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 1.04, transition: { duration: 0.5 } }}
              transition={{ duration: 0.25, ease: [0.22, 1, 0.36, 1] }}
              className="absolute inset-0 flex items-center justify-center"
            >
              <div
                className={`rounded-3xl bg-zinc-950/60 backdrop-blur-md px-16 py-10 ring-4 ${RING_BY_COLOR[colorKey]} shadow-[0_0_120px_rgba(0,0,0,0.6)]`}
              >
                <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-400 font-mono text-center">
                  Macro
                </div>
                <div className="mt-2 text-6xl font-extrabold tracking-tight text-center drop-shadow-[0_4px_24px_rgba(0,0,0,0.5)]">
                  {event.label}
                </div>
                {event.subtitle && (
                  <div className="mt-3 text-xl font-medium tracking-tight text-center text-zinc-200 drop-shadow-[0_2px_12px_rgba(0,0,0,0.5)]">
                    {event.subtitle}
                  </div>
                )}
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

// TODO: wire a "blip"/"swoosh" via streamAudio once StreamAudio exposes a generic cue method.
