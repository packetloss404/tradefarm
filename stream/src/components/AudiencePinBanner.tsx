import { AnimatePresence, motion } from "framer-motion";
import { useMemo } from "react";
import type { AudiencePinResolvedState } from "../hooks/useStreamCommands";
import type { AgentRow } from "../shared/api";

/**
 * Brief top-center overlay that fires when the operator approves an audience
 * pin request. Rejected resolutions are ignored — the audience only ever
 * sees the *result* of an approval, never a "rejected" message.
 *
 * The slot is auto-cleared after 4s by `useStreamCommands` so this component
 * just renders whatever the parent gives it; AnimatePresence handles the
 * in/out crossfade against React's mount/unmount.
 */
export function AudiencePinBanner({
  resolved,
  agents,
}: {
  resolved: AudiencePinResolvedState | null;
  agents: AgentRow[];
}) {
  const visible = resolved && resolved.status === "approved";

  // Look up the pinned agent's display name. If the agentId is null (the
  // operator approved but the backend couldn't resolve a target — should be
  // rare, mostly a race where the agent disappeared) we fall back to a
  // generic label rather than rendering "#null".
  const name = useMemo(() => {
    if (!resolved || resolved.agentId == null) return "an agent";
    const a = agents.find((row) => row.id === resolved.agentId);
    return a?.name ?? `Agent #${resolved.agentId}`;
  }, [resolved, agents]);

  return (
    <div className="absolute inset-x-0 top-6 z-25 flex justify-center pointer-events-none">
      <AnimatePresence>
        {visible && (
          <motion.div
            key={resolved.id}
            initial={{ opacity: 0, y: -16, scale: 0.94 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: -12, scale: 0.96 }}
            transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
            className="rounded-md bg-zinc-950/85 backdrop-blur-md border border-emerald-500/40 shadow-2xl px-6 py-3 flex items-center gap-3"
          >
            <span className="h-2 w-2 rounded-full bg-(--color-profit) animate-pulse" />
            <div className="leading-tight">
              <div className="text-[10px] uppercase tracking-widest text-zinc-400 font-mono">
                Audience pinned
              </div>
              <div className="text-2xl font-bold text-zinc-50 tracking-tight">
                {name}
              </div>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
