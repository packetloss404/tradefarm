import useSWR from "swr";
import { api, type AdminConfig, type LlmStats } from "../api";
import { Panel } from "./Panel";
import { StatCard } from "./StatCard";

// README pegs default-config Claude spend at ~$3/day across 33 LSTM+LLM agents on
// Haiku 4.5 with the cost gate active. 0.0006 USD/call is a conservative point
// estimate for a small JSON overlay response and should be retuned once the
// scheduler logs real per-call token counts.
const COST_PER_CALL_USD = 0.0006;
// 0.14.0 — the "daily cap" surfaced in the widget is now driven by
// the live admin config (`llm_daily_budget_usd`) so the operator
// can tune it from the admin form. When the field is missing on
// older backends we fall back to 0 (no cap) — the gauge then
// stays at 0% and the "of $X/day" label reads "of $0.00/day".
const FALLBACK_CAP_USD = 0;

function barTone(ratio: number): string {
  if (ratio >= 0.8) return "bg-(--color-loss)";
  if (ratio >= 0.5) return "bg-amber-400";
  return "bg-(--color-profit)";
}

export function ApiSpendWidget() {
  const { data, error } = useSWR<LlmStats>("llm-stats", api.llmStats, {
    refreshInterval: 10_000,
  });
  const { data: cfg } = useSWR<AdminConfig>("admin-config-spend", api.adminConfig, {
    refreshInterval: 30_000,
    shouldRetryOnError: false,
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
  // 0.14.0 — read the cap from the live admin config so the operator
  // can tune it from the admin form. The fallback (`FALLBACK_CAP_USD`)
  // is 0 (no cap) so older backends that don't expose the field
  // keep the gauge at 0% rather than crashing.
  const dailyCap = cfg?.llm_daily_budget_usd ?? FALLBACK_CAP_USD;
  // When the cap is 0 the gauge shows 0% (no cap → no progress to
  // measure). Operator reads "of $0.00/day" as "no cap configured".
  const ratio = dailyCap > 0 ? Math.min(estSpend / dailyCap, 1) : 0;
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
            sub={dailyCap > 0 ? `cap $${dailyCap.toFixed(2)}/day` : "no cap configured"}
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
            <span>
              {dailyCap > 0
                ? `${(ratio * 100).toFixed(1)}% of $${dailyCap.toFixed(2)}/day cap (since boot)`
                : "no daily cap configured — set one in Admin → Tuning"}
            </span>
            <span>
              {data.called} called · {data.skipped_low_confidence} skipped
            </span>
          </div>
        </div>
      </div>
    </Panel>
  );
}
