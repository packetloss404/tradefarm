import { motion, AnimatePresence } from "framer-motion";
import { AgentWorldXL } from "../components/AgentWorldXL";
import { StatPillar } from "../components/StatPillar";
import { useMarketClock } from "../hooks/useMarketClock";
import type { StreamSnapshot } from "../hooks/useStreamData";

function fmtSign(n: number, frac = 0): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

/**
 * Hero body: stat pillar + Agent World diorama. Wrapped by SceneRotator
 * which provides the persistent top/bottom tickers and the toast/caption
 * overlays that should appear on every scene.
 *
 * When `pinAgentId` is set the diorama still renders the full world (no
 * highlight prop available on AgentWorldXL), but a top-right "PINNED" badge
 * surfaces the operator's chosen agent like a lower-third.
 */
export function HeroBody({
  snapshot,
  pinAgentId,
}: {
  snapshot: StreamSnapshot;
  pinAgentId: number | null;
}) {
  const { phase } = useMarketClock();
  const allocated = snapshot.agents.length * 1000;
  const equity = snapshot.account?.total_equity ?? allocated;
  const pnlPct = allocated > 0 ? ((equity - allocated) / allocated) * 100 : 0;

  const pinned =
    pinAgentId != null ? snapshot.agents.find((a) => a.id === pinAgentId) ?? null : null;
  const pinnedTotal = pinned ? pinned.realized_pnl + pinned.unrealized_pnl : 0;

  return (
    <div className="absolute inset-0 flex">
      <aside className="w-[320px] shrink-0">
        <StatPillar agents={snapshot.agents} fills={snapshot.fills} />
      </aside>
      <main className="relative flex-1 overflow-hidden">
        <AgentWorldXL
          agents={snapshot.agents}
          promotionEvents={snapshot.promotions}
          marketPhase={phase}
          todayPnlPct={pnlPct}
        />
        <AnimatePresence>
          {pinned && (
            <motion.div
              key={`pin-${pinned.id}`}
              initial={{ opacity: 0, y: -8, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.96 }}
              transition={{ duration: 0.35, ease: "easeOut" }}
              className="absolute top-4 right-4 z-20 rounded-lg border border-emerald-500/60 bg-zinc-950/85 backdrop-blur px-4 py-2.5 shadow-lg shadow-emerald-900/30"
            >
              <div className="flex items-center gap-2 text-[10px] font-mono uppercase tracking-[0.18em] text-emerald-400">
                <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
                Pinned
              </div>
              <div className="mt-1 flex items-baseline gap-3">
                <span className="text-lg font-bold tracking-tight text-zinc-100">
                  {pinned.name}
                </span>
                {pinned.rank && (
                  <span className="text-[10px] font-mono uppercase tracking-wider text-zinc-400">
                    {pinned.rank}
                  </span>
                )}
              </div>
              <div className="mt-1 flex items-baseline gap-3 text-xs font-mono">
                {pinned.symbol && (
                  <span className="text-zinc-500 uppercase tracking-wider">
                    {pinned.symbol}
                  </span>
                )}
                <span
                  className={`tabular-nums font-semibold ${
                    pinnedTotal >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"
                  }`}
                >
                  {fmtSign(pinnedTotal)}
                </span>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </main>
    </div>
  );
}
