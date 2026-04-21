import useSWR from "swr";
import { api, type AcademyOverview, type Rank } from "../api";

const RANK_TONE: Record<Rank, string> = {
  intern: "text-zinc-400",
  junior: "text-sky-400",
  senior: "text-(--color-profit)",
  principal: "text-amber-400",
};

const RANK_ORDER: Rank[] = ["intern", "junior", "senior", "principal"];

/**
 * Header strip showing the live rank distribution across all agents, e.g.
 * "I·42 J·31 S·20 P·7". Sits next to the `ws:` status indicator in App.tsx.
 */
export function RankDistBadge() {
  const { data } = useSWR<AcademyOverview>("academy-overview", api.academyOverview, {
    refreshInterval: 10_000,
  });
  if (!data) {
    return <span className="font-mono text-zinc-700">rank·…</span>;
  }
  return (
    <span
      className="flex items-center gap-1 font-mono"
      title={RANK_ORDER.map(
        (r) => `${r}: ${data.distribution[r] ?? 0} (${(data.ranks.find((x) => x.rank === r)?.multiplier ?? 1).toFixed(2)}x)`,
      ).join(" · ")}
    >
      {RANK_ORDER.map((r) => {
        const count = data.distribution[r] ?? 0;
        return (
          <span key={r} className={`tabular-nums ${RANK_TONE[r]}`}>
            {r[0]!.toUpperCase()}·{count}
          </span>
        );
      })}
    </span>
  );
}
