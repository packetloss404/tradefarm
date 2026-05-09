import useSWR from "swr";
import { api, type AccountSummary, type AgentRow, type DailyPnlPoint } from "./api";
import { Panel, LiveBadge } from "./components/Panel";
import { StatCard } from "./components/StatCard";
import { AgentGrid } from "./components/AgentGrid";
import { PositionsPanel } from "./components/PositionsPanel";
import { MonthlyPnlChart } from "./components/MonthlyPnlChart";
import { BrainPanel } from "./components/BrainPanel";
import { PromotionsBoard } from "./components/PromotionsBoard";
import { StrategyPanel } from "./components/StrategyPanel";
import { OrderStatusPanel } from "./components/OrderStatusPanel";
import { AgentDetailModal } from "./components/AgentDetailModal";
import { AgentWorld } from "./components/AgentWorld";
import { AdminModal } from "./components/AdminModal";
import { BroadcastPanel } from "./components/BroadcastPanel";
import { StickyHeader } from "./components/StickyHeader";
import { TabbedPanel } from "./components/TabbedPanel";
import { WorkflowFlowchart } from "./components/WorkflowFlowchart";
import { CommandPalette } from "./components/CommandPalette";
import { useCommandPalette } from "./hooks/useCommandPalette";
import { buildCommands } from "./lib/buildCommands";
import { useEventFeed } from "./hooks/useEventFeed";
import { PositionsSparklineStrip } from "./components/PositionsSparklineStrip";
import { KeyboardMapOverlay } from "./components/KeyboardMapOverlay";
import { useKeyboardMap } from "./hooks/useKeyboardMap";
import { ApiSpendWidget } from "./components/ApiSpendWidget";
import { RecentFillsRail } from "./components/RecentFillsRail";
import {
  Group as ResizableGroup,
  Panel as ResizablePanel,
  Separator as ResizableSeparator,
  useDefaultLayout,
} from "react-resizable-panels";
import { useState } from "react";

const REFRESH_MS = 5_000;

export default function App() {
  const { data: account, error: accErr } = useSWR<AccountSummary>("account", api.account, {
    refreshInterval: REFRESH_MS,
  });
  const { data: agents, error: agErr, mutate: mutateAgents } = useSWR<AgentRow[]>("agents", api.agents, {
    refreshInterval: REFRESH_MS,
  });
  const { data: pnlDaily, mutate: mutatePnl } = useSWR<DailyPnlPoint[]>("pnl-daily", () => api.pnlDaily(30), {
    refreshInterval: REFRESH_MS * 6,
  });

  // WebSocket feed — authoritative for header KPIs once connected; SWR still
  // owns /api/agents and /api/pnl/daily and is re-validated on each tick event.
  const feed = useEventFeed({ mutateAgents, mutatePnl });

  const [ticking, setTicking] = useState(false);
  const [lastTick, setLastTick] = useState<string>("");
  const [selectedAgentId, setSelectedAgentId] = useState<number | null>(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const cmdK = useCommandPalette();
  const kbMap = useKeyboardMap({ disabled: cmdK.open });

  // Persist the AW ↔ Fills split width to localStorage. Panels need stable `id`s
  // matching the keys in the saved layout map; defaults below kick in on first load.
  const liveLayout = useDefaultLayout({
    id: "dashboard-live-split-v1",
    storage: typeof window !== "undefined" ? window.localStorage : undefined,
  });

  const handleTick = async () => {
    setTicking(true);
    try {
      const r = await api.tick();
      setLastTick(`fills=${r.fills} blocked=${r.blocked} symbols=${r.symbols}`);
      await Promise.all([mutateAgents(), mutatePnl()]);
    } catch (e) {
      setLastTick(`error: ${(e as Error).message}`);
    } finally {
      setTicking(false);
    }
  };

  const err = accErr || agErr;

  if (err) {
    return (
      <div className="flex h-full items-center justify-center text-(--color-loss)">
        Backend unreachable. Start with: <code className="ml-2 rounded bg-zinc-800 px-2 py-1 font-mono">uv run uvicorn tradefarm.api.main:app --reload</code>
      </div>
    );
  }

  if (!account || !agents) {
    return <div className="flex h-full items-center justify-center text-zinc-500">Loading…</div>;
  }

  // Prefer live WS account data; fall back to SWR until the first `account` event.
  const acct: AccountSummary = feed.account ?? account;
  const lastTickIso = feed.lastTick?.ts ?? acct.last_tick_at;

  const totalAllocated = agents.length * 1000;
  const todayPnl = acct.total_equity - totalAllocated;
  const todayPct = (todayPnl / totalAllocated) * 100;
  const monthName = new Date().toLocaleDateString("en-US", { month: "long", year: "numeric" });

  // Snap-aligned section spacing: each viewport snaps below the 72px sticky header.
  // The arbitrary [scroll-margin-top] keeps the snap target from disappearing under it.
  const sectionClass = "snap-start [scroll-margin-top:72px] min-h-[calc(100vh-200px)]";

  return (
    <>
      {/* Outer = the scroll container. Snap is owned here so the sticky header
          inside still sticks to the top of THIS viewport, not document. */}
      <div className="h-screen overflow-y-auto snap-y snap-mandatory">
        <div className="p-4">
          <StickyHeader
            account={acct}
            agentCount={agents.length}
            wsStatus={feed.status}
            lastTickIso={lastTickIso}
            onManualTick={handleTick}
            onOpenAdmin={() => setAdminOpen(true)}
            ticking={ticking}
            lastTick={lastTick}
          />

          {/* Viewport 1 — live show. Resizable horizontal split between Agent World
              and Live Fills, persisted to localStorage via useDefaultLayout. The
              defaults (75/25) mirror the previous 9/3 grid for first-load. */}
          <section className={`${sectionClass} flex flex-col`}>
            <ResizableGroup
              orientation="horizontal"
              defaultLayout={liveLayout.defaultLayout ?? { aw: 75, fills: 25 }}
              onLayoutChanged={liveLayout.onLayoutChanged}
              className="flex-1 min-h-0 mt-4"
            >
              <ResizablePanel id="aw" minSize={40}>
                <Panel
                  className="h-full flex flex-col"
                  title="Agent World"
                  badge={<LiveBadge />}
                  right={<span className="text-[10px] text-zinc-500 font-mono">live — dots migrate between zones as state changes</span>}
                >
                  <div className="flex-1 min-h-0">
                    <AgentWorld
                      agents={agents}
                      onSelect={(a) => setSelectedAgentId(a.id)}
                      promotionEvents={feed.promotionEvents}
                      fit="contain"
                    />
                  </div>
                </Panel>
              </ResizablePanel>
              <ResizableSeparator className="group relative w-3 flex items-center justify-center cursor-col-resize">
                <span className="h-12 w-1 rounded-full bg-zinc-700 group-hover:bg-zinc-500 transition-colors" />
              </ResizableSeparator>
              <ResizablePanel id="fills" minSize={15}>
                <div className="h-full">
                  <RecentFillsRail fills={feed.fills} />
                </div>
              </ResizablePanel>
            </ResizableGroup>
          </section>

          {/* Viewport 2 — controls. Constrained to 1600px so tables stay readable. */}
          <section className={`${sectionClass} mx-auto w-full max-w-[1600px] space-y-4 pt-4`}>
            <div className="grid grid-cols-12 gap-4">
              <Panel className="col-span-4" title="TradeFarm AI" badge={<LiveBadge />}>
                <div className="space-y-3">
                  <StatCard
                    label="Today PnL"
                    value={`${todayPnl >= 0 ? "+" : ""}${todayPnl.toFixed(2)} USD`}
                    sub={`${todayPct >= 0 ? "+" : ""}${todayPct.toFixed(3)}%`}
                    tone={todayPnl >= 0 ? "profit" : "loss"}
                    big
                  />
                  <div className="grid grid-cols-3 gap-3 border-t border-zinc-800 pt-3">
                    <StatCard label="Profit AI" value={acct.profit_ai} tone="profit" />
                    <StatCard label="Loss AI" value={acct.loss_ai} tone="loss" />
                    <StatCard label="Waiting" value={acct.waiting_ai} tone="wait" />
                  </div>
                  <div className="grid grid-cols-3 gap-3 border-t border-zinc-800 pt-3">
                    <StatCard label="Equity" value={`$${acct.total_equity.toFixed(0)}`} />
                    <StatCard
                      label="Realized"
                      value={`${acct.realized_pnl >= 0 ? "+" : ""}${acct.realized_pnl.toFixed(2)}`}
                      tone={acct.realized_pnl >= 0 ? "profit" : "loss"}
                    />
                    <StatCard
                      label="Unrealized"
                      value={`${acct.unrealized_pnl >= 0 ? "+" : ""}${acct.unrealized_pnl.toFixed(2)}`}
                      tone={acct.unrealized_pnl >= 0 ? "profit" : "loss"}
                    />
                  </div>
                </div>
              </Panel>

              <Panel className="col-span-4">
                <PositionsPanel agents={agents} />
              </Panel>

              <Panel className="col-span-4">
                <MonthlyPnlChart data={pnlDaily ?? []} totalUnrealized={acct.unrealized_pnl} monthName={monthName} />
              </Panel>
            </div>

            <TabbedPanel
              persistKey="lower"
              tabs={[
                {
                  id: "brain",
                  label: "Brain Activity",
                  content: (
                    <BrainPanel
                      agents={agents}
                      notesThisTick={acct.notes_this_tick}
                      outcomesThisTick={acct.outcomes_this_tick}
                    />
                  ),
                },
                { id: "promotions", label: "Promotions", content: <PromotionsBoard /> },
                { id: "strategies", label: "Strategies", content: <StrategyPanel /> },
                { id: "workflow", label: "Workflow", content: <WorkflowFlowchart /> },
                { id: "orders", label: "Orders", content: <OrderStatusPanel /> },
              ]}
            />

            <BroadcastPanel />

            <ApiSpendWidget />

            <Panel title="Open Positions" right={<span className="text-[10px] text-zinc-500 font-mono">live marks · sparklines build over time</span>}>
              <PositionsSparklineStrip agents={agents} />
            </Panel>

            <Panel
              title="Agent Grid"
              right={<span className="text-[10px] text-zinc-500 font-mono">{agents.length} agents · click for detail</span>}
            >
              <AgentGrid
                agents={agents}
                onSelect={(a) => setSelectedAgentId(a.id)}
                promotionEvents={feed.promotionEvents}
              />
            </Panel>
          </section>
        </div>
      </div>

      {/* Modals/overlays — fixed-positioned, escape the snap container. */}
      {selectedAgentId !== null && (() => {
        const a = agents.find((x) => x.id === selectedAgentId);
        return a ? <AgentDetailModal agent={a} onClose={() => setSelectedAgentId(null)} /> : null;
      })()}

      {adminOpen && <AdminModal onClose={() => setAdminOpen(false)} />}

      <CommandPalette
        open={cmdK.open}
        onClose={() => cmdK.setOpen(false)}
        commands={buildCommands({
          agents,
          onSelectAgent: setSelectedAgentId,
          onManualTick: handleTick,
          onOpenAdmin: () => setAdminOpen(true),
        })}
      />

      <KeyboardMapOverlay open={kbMap.open} onClose={() => kbMap.setOpen(false)} />
    </>
  );
}
