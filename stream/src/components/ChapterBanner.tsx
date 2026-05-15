import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";

const DWELL_MS = 4_000;

export function ChapterBanner({ label }: { label: string }) {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    setVisible(true);
    const t = setTimeout(() => setVisible(false), DWELL_MS);
    return () => clearTimeout(t);
  }, [label]);

  return (
    <div className="absolute inset-x-0 top-20 flex justify-center pointer-events-none">
      <AnimatePresence>
        {visible && (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: -16, scale: 0.96 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -12, scale: 0.98 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="rounded-md bg-zinc-950/85 backdrop-blur-md border border-emerald-500/40 shadow-2xl px-6 py-3 flex items-center gap-3"
          >
            <span className="h-2 w-2 rounded-full bg-(--color-profit) animate-pulse" />
            <div className="leading-tight">
              <div className="text-[10px] uppercase tracking-widest text-zinc-400 font-mono">
                Now entering
              </div>
              <div className="text-2xl font-bold text-zinc-50 tracking-tight">
                {label}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
