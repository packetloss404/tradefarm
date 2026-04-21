import type { AgentRow } from "../api";

const biasTone: Record<string, string> = {
  long: "text-(--color-profit)",
  up: "text-(--color-profit)",
  short: "text-(--color-loss)",
  down: "text-(--color-loss)",
  flat: "text-(--color-wait)",
};

function pctLabel(n: number, denom: number): string {
  if (!denom) return "";
  return `${Math.round((n / denom) * 100)}%`;
}

export function BrainPanel({
  agents,
  notesThisTick,
  outcomesThisTick,
}: {
  agents: AgentRow[];
  notesThisTick?: number;
  outcomesThisTick?: number;
}) {
  const lstmAgents = agents.filter((a) => a.last_lstm);
  const llmAgents = agents.filter((a) => a.last_decision);

  const lstmBias = { down: 0, flat: 0, up: 0 };
  const lstmConfidences: number[] = [];
  for (const a of lstmAgents) {
    const d = a.last_lstm!.direction;
    if (d in lstmBias) lstmBias[d as keyof typeof lstmBias]++;
    lstmConfidences.push(a.last_lstm!.confidence);
  }
  const avgConf =
    lstmConfidences.length ? lstmConfidences.reduce((s, x) => s + x, 0) / lstmConfidences.length : 0;

  const llmStance = { trade: 0, wait: 0 };
  const llmBias = { long: 0, flat: 0, short: 0 };
  for (const a of llmAgents) {
    const d = a.last_decision!;
    llmStance[d.stance]++;
    if (d.bias in llmBias) llmBias[d.bias as keyof typeof llmBias]++;
  }

  const topDecisions = llmAgents
    .filter((a) => a.last_decision!.stance === "trade")
    .sort((x, y) => y.last_decision!.size_pct - x.last_decision!.size_pct)
    .slice(0, 6);

  return (
    <div className="grid grid-cols-12 gap-4">
      {/* Phase 1 (Agent Academy): Notes/tick counter */}
      <div className="col-span-12 -mb-2 flex items-baseline gap-4 text-[10px] uppercase tracking-wider text-zinc-500">
        <span>
          notes/tick{" "}
          <span className="font-mono text-zinc-300 tabular-nums">
            {notesThisTick ?? 0}
          </span>
        </span>
        <span>
          outcomes/tick{" "}
          <span className="font-mono text-zinc-300 tabular-nums">
            {outcomesThisTick ?? 0}
          </span>
        </span>
      </div>

      <div className="col-span-3 space-y-3">
        <div className="text-xs uppercase tracking-wider text-zinc-400">LSTM Bias</div>
        <div className="font-mono text-sm space-y-1">
          {(["up", "flat", "down"] as const).map((b) => (
            <div key={b} className="flex justify-between">
              <span className={biasTone[b]}>{b.toUpperCase()}</span>
              <span className="text-zinc-300">
                {lstmBias[b]} <span className="text-zinc-500 text-xs">{pctLabel(lstmBias[b], lstmAgents.length)}</span>
              </span>
            </div>
          ))}
        </div>
        <div className="text-[10px] text-zinc-500">avg confidence {avgConf.toFixed(2)} · n={lstmAgents.length}</div>
      </div>

      <div className="col-span-3 space-y-3">
        <div className="text-xs uppercase tracking-wider text-zinc-400">LLM Stance</div>
        <div className="font-mono text-sm space-y-1">
          <div className="flex justify-between">
            <span className="text-amber-400">TRADE</span>
            <span className="text-zinc-300">
              {llmStance.trade} <span className="text-zinc-500 text-xs">{pctLabel(llmStance.trade, llmAgents.length)}</span>
            </span>
          </div>
          <div className="flex justify-between">
            <span className="text-zinc-400">WAIT</span>
            <span className="text-zinc-300">
              {llmStance.wait} <span className="text-zinc-500 text-xs">{pctLabel(llmStance.wait, llmAgents.length)}</span>
            </span>
          </div>
        </div>
        <div className="text-[10px] text-zinc-500">
          bias: <span className={biasTone.long}>L {llmBias.long}</span>{" "}
          <span className={biasTone.flat}>F {llmBias.flat}</span>{" "}
          <span className={biasTone.short}>S {llmBias.short}</span> · n={llmAgents.length}
        </div>
      </div>

      <div className="col-span-6">
        <div className="mb-2 text-xs uppercase tracking-wider text-zinc-400">Top LLM Trade Calls</div>
        {topDecisions.length === 0 ? (
          <div className="text-xs text-zinc-500 italic">all agents on the sidelines this tick</div>
        ) : (
          <ul className="space-y-1.5 text-xs">
            {topDecisions.map((a) => {
              const d = a.last_decision!;
              const sym = Object.keys(a.positions)[0] ?? (a.strategy === "lstm_llm_v1" ? "—" : "—");
              return (
                <li key={a.id} className="flex items-baseline gap-2 font-mono">
                  <span className="w-16 text-zinc-500">{a.name}</span>
                  <span className="w-12 text-zinc-300">{sym}</span>
                  <span className={`w-12 ${biasTone[d.predictive] || ""}`}>{d.predictive.toUpperCase()}</span>
                  <span className="w-14 text-zinc-300">{(d.size_pct * 100).toFixed(1)}%</span>
                  <span className="flex-1 truncate text-zinc-400" title={d.reason}>{d.reason}</span>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
