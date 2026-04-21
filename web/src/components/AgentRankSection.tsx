import useSWR from "swr";
import { api, type AgentAcademy, type Rank } from "../api";

const RANK_TONE: Record<Rank, string> = {
  intern: "text-zinc-400",
  junior: "text-sky-400",
  senior: "text-(--color-profit)",
  principal: "text-amber-400",
};

const RANK_LABEL: Record<Rank, string> = {
  intern: "Intern",
  junior: "Junior",
  senior: "Senior",
  principal: "Principal",
};

const RANK_ONE_LINER: Record<Rank, string> = {
  intern: "just hired; small size caps while we see what you can do",
  junior: "proven a few wins; trusted with a bit more rope",
  senior: "consistent edge across enough trades to matter",
  principal: "top of the floor; biggest cap and first retrieval pick",
};

const RANK_ORDER: Rank[] = ["intern", "junior", "senior", "principal"];

/**
 * Rank section for the Agent detail modal. Shows current rank, multiplier,
 * progression bar toward the next rank, and a plain-English gap description
 * ("needs N more trades, win-rate ≥ p%, Sharpe ≥ s over Nw").
 *
 * Lazy-loads via SWR so modal first-paint is never blocked.
 */
export function AgentRankSection({ agentId }: { agentId: number }) {
  const { data, error } = useSWR<AgentAcademy>(
    `agent-academy-${agentId}`,
    () => api.agentAcademy(agentId),
    { refreshInterval: 10_000 },
  );

  return (
    <section className="rounded-md border border-zinc-800 bg-zinc-950/50 p-3">
      <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-400">Rank</div>
      {error ? (
        <div className="text-xs italic text-zinc-500">could not load rank</div>
      ) : !data ? (
        <div className="text-xs text-zinc-500">loading…</div>
      ) : (
        <RankBody data={data} />
      )}
    </section>
  );
}

function RankBody({ data }: { data: AgentAcademy }) {
  const tone = RANK_TONE[data.rank];
  const progress = progressToNext(data);
  const gapText = gapCopy(data);

  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3 font-mono">
        <span className={`text-lg font-bold ${tone}`} title={RANK_ONE_LINER[data.rank]}>
          {RANK_LABEL[data.rank]}
        </span>
        <span className="text-[10px] uppercase tracking-wider text-zinc-500">
          size cap {(data.effective_cap_pct * 100).toFixed(1)}% · mult {data.multiplier.toFixed(2)}x
        </span>
      </div>

      <div className="grid grid-cols-4 gap-3 text-xs font-mono">
        <KV label="Trades" value={String(data.stats.n_closed_trades)} />
        <KV
          label="Win rate"
          value={`${(data.stats.win_rate * 100).toFixed(1)}%`}
        />
        <KV label="Sharpe" value={data.stats.sharpe.toFixed(2)} />
        <KV label="Weeks" value={data.stats.weeks_active.toFixed(1)} />
      </div>

      {data.next_rank ? (
        <div>
          <div className="mb-1 flex items-baseline justify-between text-[11px] font-mono">
            <span className="text-zinc-400">
              progress to <span className={RANK_TONE[data.next_rank]}>{RANK_LABEL[data.next_rank]}</span>
            </span>
            <span className="tabular-nums text-zinc-500">{(progress * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
            <div
              className={`h-full ${progressBarTone(data.next_rank)}`}
              style={{ width: `${Math.min(100, Math.max(0, progress * 100))}%` }}
              title={gapText}
            />
          </div>
          <div className="mt-1 text-[11px] italic text-zinc-500" title={gapText}>
            {gapText}
          </div>
        </div>
      ) : (
        <div className="text-[11px] italic text-zinc-500">top of the floor — no higher rank</div>
      )}

      <div className="flex items-center gap-1 border-t border-zinc-800 pt-2">
        {RANK_ORDER.map((r) => {
          const active = r === data.rank;
          return (
            <span
              key={r}
              title={RANK_ONE_LINER[r]}
              className={`rounded px-1.5 py-0.5 text-[10px] font-mono uppercase ${
                active
                  ? `border border-zinc-600 bg-zinc-900 ${RANK_TONE[r]}`
                  : `border border-transparent ${RANK_TONE[r]} opacity-60`
              }`}
            >
              {r[0]!.toUpperCase()}·{RANK_LABEL[r]}
            </span>
          );
        })}
      </div>
    </div>
  );
}

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div className="tabular-nums text-zinc-100">{value}</div>
    </div>
  );
}

function progressBarTone(next: Rank): string {
  if (next === "junior") return "bg-sky-400";
  if (next === "senior") return "bg-(--color-profit)";
  if (next === "principal") return "bg-amber-400";
  return "bg-zinc-500";
}

function progressToNext(data: AgentAcademy): number {
  // Derive a simple "ratio of remaining need" → progress. Prefer trades as
  // the primary axis (present for every non-principal gap); when trades are
  // satisfied, the bar is full and the secondary gate (win-rate / Sharpe /
  // weeks) shows up in the gap text below the bar.
  const gaps = data.gaps;
  if (gaps.trades_needed !== undefined) {
    const target =
      data.next_rank === "junior"
        ? gaps.trades_needed + data.stats.n_closed_trades || 1
        : data.next_rank === "senior"
          ? gaps.trades_needed + data.stats.n_closed_trades || 1
          : gaps.trades_needed + data.stats.n_closed_trades || 1;
    return target > 0 ? Math.min(1, data.stats.n_closed_trades / target) : 0;
  }
  return 0;
}

function gapCopy(data: AgentAcademy): string {
  const g = data.gaps;
  const parts: string[] = [];
  if (g.trades_needed && g.trades_needed > 0) {
    parts.push(`${g.trades_needed} more trade${g.trades_needed === 1 ? "" : "s"}`);
  }
  if (g.win_rate_target !== undefined && data.stats.win_rate < g.win_rate_target) {
    parts.push(`win-rate ≥ ${(g.win_rate_target * 100).toFixed(0)}%`);
  }
  if (g.sharpe_target !== undefined && data.stats.sharpe < g.sharpe_target) {
    parts.push(`Sharpe ≥ ${g.sharpe_target.toFixed(1)}`);
  }
  if (g.weeks_needed !== undefined && g.weeks_needed > 0) {
    parts.push(`${g.weeks_needed.toFixed(1)}w more tenure`);
  }
  if (!parts.length) return "ready for promotion";
  return `needs ${parts.join(", ")}`;
}
