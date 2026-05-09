import { AgentWorldXL } from "../components/AgentWorldXL";
import { StatPillar } from "../components/StatPillar";
import { useMarketClock } from "../hooks/useMarketClock";
import type { StreamSnapshot } from "../hooks/useStreamData";

/**
 * Hero body: stat pillar + Agent World diorama. Wrapped by SceneRotator
 * which provides the persistent top/bottom tickers and the toast/caption
 * overlays that should appear on every scene.
 */
export function HeroBody({ snapshot }: { snapshot: StreamSnapshot }) {
  const { phase } = useMarketClock();
  const allocated = snapshot.agents.length * 1000;
  const equity = snapshot.account?.total_equity ?? allocated;
  const pnlPct = allocated > 0 ? ((equity - allocated) / allocated) * 100 : 0;

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
      </main>
    </div>
  );
}
