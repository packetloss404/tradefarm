import useSWR from "swr";
import { api, type LlmStats } from "../api";
import { Panel } from "./Panel";
import { StatCard } from "./StatCard";

// README pegs default-config Claude spend at ~$3/day across 33 LSTM+LLM agents on
// Haiku 4.5 with the cost gate active. 0.0006 USD/call is a conservative point
// estimate for a small JSON overlay response and should be retuned once the
// scheduler logs real per-call token counts.
const COST_PER_CALL_USD = 0.0006;
const DAILY_CAP_USD = 5.0;

function barTone(ratio: number): string {
  if (ratio >= 0.8) return "bg-(--color-loss)";
  if (ratio >= 0.5) return "bg-amber-400";
  return "bg-(--color-profit)";
}

export function ApiSpendWidget() {
  const { data, error } = useSWR<LlmStats>("llm-stats", api.llmStats, {
    refreshInterval: 10_000,
  });

  if (error) {
    return (
      <Panel title="API Spend">
        <div className="text-xs text-(--color-loss)">llm/stats unreachable</div>
      </Panel>
    );
  }

  if (!data) {
    return (
      <Panel title="API Spend">
        <div className="text-xs text-zinc-500">loading…</div>
      </Panel>
    );
  }

  const estSpend = data.called * COST_PER_CALL_USD;
  const ratio = Math.min(estSpend / DAILY_CAP_USD, 1);
  const skipPct = data.skip_rate * 100;

  // LLM_SKIPS.called is a since-boot module counter, not a per-day counter,
  // so the labels here are honest about that scope. Wire a real daily reset
  // (e.g., orchestrator midnight task) before relabeling to "today".
  return (
    <Panel title="API Spend">
      <div className="space-y-3">
        <div className="grid grid-cols-3 gap-3">
          <StatCard label="Calls" value={data.called} />
          <StatCard
            label="Skip Rate"
            value={`${skipPct.toFixed(0)}%`}
            sub={`thr ${data.threshold.toFixed(2)}`}
            tone="wait"
          />
          <StatCard
            label="Est. Since Boot"
            value={`$${estSpend.toFixed(2)}`}
            sub={`cap $${DAILY_CAP_USD.toFixed(2)}/day`}
          />
        </div>
        <div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className={`h-full ${barTone(ratio)} transition-all`}
              style={{ width: `${ratio * 100}%` }}
            />
          </div>
          <div className="mt-1 flex justify-between text-[10px] font-mono tabular-nums text-zinc-500">
            <span>{(ratio * 100).toFixed(1)}% of $5/day cap (since boot)</span>
            <span>
              {data.called} called · {data.skipped_low_confidence} skipped
            </span>
          </div>
        </div>
      </div>
    </Panel>
  );
}
