import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useState } from "react";
import type { PromotionEvent } from "../hooks/useStreamData";

const RANK_LABEL: Record<string, string> = {
  intern: "Intern",
  junior: "Junior",
  senior: "Senior",
  principal: "Principal",
};

const TOAST_DWELL_MS = 4_000;

type Visible = { ev: PromotionEvent; expiresAt: number };

/** Top-center confetti-ish toast that briefly celebrates rank changes. */
export function PromotionToast({ promotions }: { promotions: PromotionEvent[] }) {
  const [visible, setVisible] = useState<Visible | null>(null);
  const [seen] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    if (promotions.length === 0) return;
    const head = promotions[0]!;
    const key = `${head.ts}-${head.payload.agent_id}-${head.payload.to_rank}`;
    if (seen.has(key)) return;
    seen.add(key);
    setVisible({ ev: head, expiresAt: Date.now() + TOAST_DWELL_MS });
  }, [promotions, seen]);

  useEffect(() => {
    if (!visible) return;
    const t = setTimeout(() => setVisible(null), TOAST_DWELL_MS);
    return () => clearTimeout(t);
  }, [visible]);

  return (
    <div className="absolute left-1/2 -translate-x-1/2 top-6 pointer-events-none">
      <AnimatePresence>
        {visible && (
          <motion.div
            key={visible.ev.ts}
            initial={{ opacity: 0, y: -20, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -20, scale: 0.95 }}
            transition={{ duration: 0.5, ease: [0.22, 1, 0.36, 1] }}
            className={`rounded-full px-7 py-3 shadow-2xl backdrop-blur-md border-2 ${
              visible.ev.type === "promotion"
                ? "bg-emerald-500/20 border-emerald-500/50 text-(--color-profit)"
                : "bg-rose-500/20 border-rose-500/50 text-(--color-loss)"
            }`}
          >
            <div className="flex items-center gap-3">
              <span className="text-2xl">
                {visible.ev.type === "promotion" ? "▲" : "▼"}
              </span>
              <div className="leading-tight">
                <div className="text-[10px] uppercase tracking-widest opacity-80 font-mono">
                  {visible.ev.type === "promotion" ? "Promoted" : "Demoted"}
                </div>
                <div className="text-2xl font-bold">
                  {visible.ev.payload.agent_name} → {RANK_LABEL[visible.ev.payload.to_rank] ?? visible.ev.payload.to_rank}
                </div>
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
