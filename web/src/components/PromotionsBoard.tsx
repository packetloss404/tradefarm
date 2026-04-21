import useSWR from "swr";
import { api, type Promotion, type Rank } from "../api";

const POLL_MS = 10_000;

const RANK_ORDER: readonly Rank[] = ["intern", "junior", "senior", "principal"];
const RANK_TONE: Record<Rank, string> = {
  intern: "text-zinc-400",
  junior: "text-sky-400",
  senior: "text-(--color-profit)",
  principal: "text-amber-400",
};

function formatRelTime(iso: string | null): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const sec = Math.max(0, Math.round((Date.now() - t) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  return `${Math.round(sec / 86400)}d ago`;
}

function isPromotion(p: Promotion): boolean {
  const from = RANK_ORDER.indexOf(p.from_rank);
  const to = RANK_ORDER.indexOf(p.to_rank);
  if (from < 0 || to < 0) return true; // assume promotion if unparseable
  return to > from;
}

function TriggerStat({ reason }: { reason: string }) {
  const short = reason.length > 64 ? `${reason.slice(0, 61)}…` : reason;
  return <span className="truncate font-mono text-[11px] text-zinc-500">{short}</span>;
}

function RankTag({ rank }: { rank: Rank }) {
  return (
    <span className={`font-mono text-[11px] font-semibold ${RANK_TONE[rank] ?? "text-zinc-400"}`}>
      {rank}
    </span>
  );
}

export function PromotionsBoard() {
  const { data, error, isLoading } = useSWR<Promotion[]>(
    "academy-promotions",
    () => api.promotions(24, 100),
    { refreshInterval: POLL_MS },
  );

  if (error) {
    return (
      <div className="text-xs text-(--color-loss)">
        Failed to load promotions: {(error as Error).message}
      </div>
    );
  }
  if (isLoading && !data) {
    return <div className="text-xs text-zinc-500">Loading…</div>;
  }
  if (!data || data.length === 0) {
    return (
      <div className="text-xs italic text-zinc-500">no rank changes in the last 24h.</div>
    );
  }

  return (
    <ul className="divide-y divide-zinc-800">
      {data.map((p) => {
        const promo = isPromotion(p);
        const arrow = promo ? "→" : "→";
        const tone = promo ? "border-(--color-profit)/30" : "border-(--color-loss)/30";
        const label = promo ? "PROMOTE" : "DEMOTE";
        const labelTone = promo
          ? "text-(--color-profit) bg-(--color-profit)/10"
          : "text-(--color-loss) bg-(--color-loss)/10";
        return (
          <li
            key={p.id}
            className={`flex items-center gap-3 border-l-2 py-2 pl-2 ${tone}`}
          >
            <span className={`rounded px-1.5 py-0.5 font-mono text-[9px] font-bold ${labelTone}`}>
              {label}
            </span>
            <span className="min-w-[110px] truncate text-xs font-semibold text-zinc-200">
              {p.agent_name ?? `agent-${p.agent_id.toString().padStart(3, "0")}`}
            </span>
            <span className="flex items-center gap-1 text-[11px]">
              <RankTag rank={p.from_rank} />
              <span className="text-zinc-600">{arrow}</span>
              <RankTag rank={p.to_rank} />
            </span>
            <TriggerStat reason={p.reason} />
            <span className="ml-auto whitespace-nowrap text-[10px] text-zinc-500">
              {formatRelTime(p.at)}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
