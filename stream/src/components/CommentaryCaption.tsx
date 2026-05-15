import { AnimatePresence, motion } from "framer-motion";
import type { Highlight } from "../hooks/useCommentary";

const KIND_TONE: Record<Highlight["kind"], { ring: string; bg: string; label: string }> = {
  big_fill:   { ring: "ring-amber-500/40",  bg: "bg-amber-500/10",  label: "Fill" },
  promotion:  { ring: "ring-emerald-500/40", bg: "bg-emerald-500/10", label: "Promotion" },
  demotion:   { ring: "ring-rose-500/40",    bg: "bg-rose-500/10",    label: "Demotion" },
  hot_tick:   { ring: "ring-sky-500/40",     bg: "bg-sky-500/10",     label: "Hot Tick" },
  glory:      { ring: "ring-yellow-500/40",  bg: "bg-yellow-500/10",  label: "Glory" },
  commentary: { ring: "ring-violet-500/40",  bg: "bg-violet-500/10",  label: "Commentary" },
};

export function CommentaryCaption({ highlight }: { highlight: Highlight | null }) {
  return (
    <div className="absolute right-8 bottom-8 max-w-md pointer-events-none">
      <AnimatePresence>
        {highlight && (
          <motion.div
            key={highlight.id}
            initial={{ opacity: 0, y: 16, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -10, scale: 0.95 }}
            transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
            className={`rounded-lg border border-zinc-800 ring-1 ${KIND_TONE[highlight.kind].ring} ${KIND_TONE[highlight.kind].bg} px-5 py-4 backdrop-blur-md shadow-xl`}
          >
            <div className="text-[10px] uppercase tracking-widest text-zinc-400 font-mono mb-1">
              {KIND_TONE[highlight.kind].label}
            </div>
            <div className="text-xl font-semibold leading-tight text-zinc-100">
              {highlight.text}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
