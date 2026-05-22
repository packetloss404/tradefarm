import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import {
  sortBroadcastMomentsByPriority,
  type BroadcastMoment,
} from "../hooks/useBroadcastMoments";
import { replayNow } from "../shared/replayMode";

export type BroadcastMomentRailMode = "priority" | "recent";

export type BroadcastMomentRailProps = {
  moments: readonly BroadcastMoment[];
  maxVisible?: number;
  mode?: BroadcastMomentRailMode;
  title?: string;
  emptyLabel?: string;
  className?: string;
};

const DEFAULT_VISIBLE_MOMENTS = 5;

const KIND_LABEL: Record<BroadcastMoment["kind"], string> = {
  agent_pnl: "Agent PnL",
  market_move: "Market move",
  rank_change: "Rank change",
  streak: "Streak",
  day_leader: "Day leader",
  activity: "Activity",
  commentary: "Commentary",
};

const COLOR_CLASS: Record<BroadcastMoment["color"], string> = {
  profit: "border-emerald-400 text-emerald-300",
  loss: "border-rose-400 text-rose-300",
  neutral: "border-zinc-500 text-zinc-300",
};

function normalizeVisibleCount(maxVisible?: number): number {
  if (!Number.isFinite(maxVisible) || maxVisible == null) return DEFAULT_VISIBLE_MOMENTS;
  return Math.max(1, Math.floor(maxVisible));
}

function sortRecentFirst(moments: readonly BroadcastMoment[]): BroadcastMoment[] {
  return [...moments].sort((a, b) => {
    if (a.receivedAt !== b.receivedAt) return b.receivedAt - a.receivedAt;
    return b.sequence - a.sequence;
  });
}

function formatAge(receivedAt: number): string {
  const ageSec = Math.max(0, Math.floor((replayNow() - receivedAt) / 1_000));
  if (ageSec < 60) return `${ageSec}s`;
  const ageMin = Math.floor(ageSec / 60);
  if (ageMin < 60) return `${ageMin}m`;
  return `${Math.floor(ageMin / 60)}h`;
}

export function BroadcastMomentRail({
  moments,
  maxVisible,
  mode = "priority",
  title = "Broadcast OS",
  emptyLabel = "No moments",
  className = "",
}: BroadcastMomentRailProps) {
  const visible = useMemo(() => {
    const ordered =
      mode === "priority" ? sortBroadcastMomentsByPriority(moments) : sortRecentFirst(moments);
    return ordered.slice(0, normalizeVisibleCount(maxVisible));
  }, [maxVisible, mode, moments]);

  return (
    <aside
      aria-label={title}
      className={`pointer-events-none select-none w-[320px] rounded-md border border-zinc-800/80 bg-zinc-950/70 backdrop-blur-md overflow-hidden ${className}`}
    >
      <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-800/80">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 v1-pulse-dot" />
        <span className="text-[10px] uppercase tracking-widest font-mono text-zinc-400">
          {title}
        </span>
        <span className="ml-auto text-[10px] font-mono text-zinc-500">
          {visible.length}/{moments.length}
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="px-3 py-4 text-xs font-mono text-zinc-600">{emptyLabel}</div>
      ) : (
        <div className="divide-y divide-zinc-800/70">
          <AnimatePresence initial={false}>
            {visible.map((moment) => (
              <MomentRow key={moment.id} moment={moment} />
            ))}
          </AnimatePresence>
        </div>
      )}
    </aside>
  );
}

function MomentRow({ moment }: { moment: BroadcastMoment }) {
  const expired = moment.expiresAt != null && moment.expiresAt <= replayNow();
  const toneClass = COLOR_CLASS[moment.color];

  return (
    <motion.div
      layout
      initial={{ opacity: 0, x: 12 }}
      animate={{ opacity: expired ? 0.45 : 1, x: 0 }}
      exit={{ opacity: 0, x: 8 }}
      transition={{ duration: 0.24, ease: [0.22, 1, 0.36, 1] }}
      className={`grid grid-cols-[3rem_1fr] gap-3 px-3 py-2 border-l-2 ${toneClass}`}
    >
      <div className="font-mono text-[10px] uppercase tracking-wider text-zinc-500">
        P{moment.priority}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2 text-[10px] uppercase tracking-widest font-mono text-zinc-500">
          <span className="truncate">{KIND_LABEL[moment.kind]}</span>
          <span className="ml-auto text-zinc-600">{formatAge(moment.receivedAt)}</span>
        </div>
        <div className="truncate text-sm font-semibold text-zinc-100">{moment.title}</div>
        {moment.subtitle ? (
          <div className="truncate text-xs text-zinc-400">{moment.subtitle}</div>
        ) : null}
      </div>
    </motion.div>
  );
}
