import { useEffect, useState } from "react";
import type { AgentRow, Rank } from "../api";
import type { LiveEvent } from "../hooks/useLiveEvents";

const dotClass: Record<AgentRow["status"], string> = {
  profit: "bg-(--color-profit)",
  loss: "bg-(--color-loss)",
  waiting: "bg-(--color-wait)",
  trading: "bg-amber-400",
};

// Phase 2: rank pip tone. Tailwind class patterns match PROJECT_PLAN.md's
// Rank table — they must stay in sync with AgentRankSection / RankDistBadge.
const pipTone: Record<Rank, string> = {
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

// Phase 4 — emerald (promote) / rose (demote) halo that lingers for HALO_MS.
const HALO_MS = 1_500;

type HaloKind = "promote" | "demote";
type HaloEntry = { kind: HaloKind; expiresAt: number };

type PromotionEvent = Extract<LiveEvent, { type: "promotion" | "demotion" }>;

export function AgentGrid({
  agents,
  onSelect,
  promotionEvents = [],
}: {
  agents: AgentRow[];
  onSelect?: (a: AgentRow) => void;
  /** Phase 4 — sliding window of the last N promotion/demotion events. */
  promotionEvents?: PromotionEvent[];
}) {
  const [halos, setHalos] = useState<Map<number, HaloEntry>>(new Map());

  // Register new halos as promotion events arrive. We key off event.ts so
  // re-renders with the same slice don't re-trigger. Expired entries get
  // cleared by the timer effect below.
  useEffect(() => {
    if (promotionEvents.length === 0) return;
    const now = Date.now();
    setHalos((prev) => {
      const next = new Map(prev);
      for (const ev of promotionEvents) {
        const t = new Date(ev.ts).getTime();
        if (Number.isNaN(t) || now - t > HALO_MS) continue;
        next.set(ev.payload.agent_id, {
          kind: ev.type === "promotion" ? "promote" : "demote",
          expiresAt: t + HALO_MS,
        });
      }
      return next;
    });
  }, [promotionEvents]);

  // Sweep expired entries every 250ms so the halo genuinely fades out.
  useEffect(() => {
    if (halos.size === 0) return;
    const interval = setInterval(() => {
      setHalos((prev) => {
        const now = Date.now();
        const next = new Map<number, HaloEntry>();
        let changed = false;
        for (const [id, entry] of prev.entries()) {
          if (entry.expiresAt > now) {
            next.set(id, entry);
          } else {
            changed = true;
          }
        }
        return changed ? next : prev;
      });
    }, 250);
    return () => clearInterval(interval);
  }, [halos.size]);

  return (
    <div className="grid grid-cols-10 gap-1.5">
      {agents.map((a) => {
        const symbols = Object.keys(a.positions);
        const sym = symbols[0];
        const pos = sym ? a.positions[sym]! : null;
        const rank: Rank = a.rank ?? "intern";
        const halo = halos.get(a.id);
        const haloClass =
          halo?.kind === "promote"
            ? "ring-4 ring-(--color-profit)/40 ring-offset-0"
            : halo?.kind === "demote"
              ? "ring-4 ring-(--color-loss)/40 ring-offset-0"
              : "";
        const tooltip = [
          a.name,
          a.strategy,
          `rank=${RANK_LABEL[rank]}`,
          `cash=$${a.cash.toFixed(2)} equity=$${a.equity.toFixed(2)}`,
          pos ? `holds ${pos.qty} ${sym} avg=${pos.avg_price.toFixed(2)} mark=${pos.mark.toFixed(2)}` : "",
          a.realized_pnl ? `realized $${a.realized_pnl.toFixed(2)}` : "",
          a.unrealized_pnl ? `unrealized $${a.unrealized_pnl.toFixed(2)}` : "",
        ].filter(Boolean).join("\n");
        return (
          <button
            key={a.id}
            type="button"
            title={tooltip}
            onClick={() => onSelect?.(a)}
            className={`relative flex h-10 flex-col items-center justify-center gap-0.5 rounded border border-zinc-800 bg-zinc-900/40 hover:border-zinc-500 hover:bg-zinc-800/60 cursor-pointer focus:outline-none focus:ring-1 focus:ring-emerald-500 transition-shadow ${haloClass}`}
          >
            {/* Rank pip — absolute top-right so it coexists with the status dot
                below. Never shares space with the status dot; never overrides
                its color. */}
            <span
              className={`absolute top-0.5 right-1 text-[8px] font-mono font-bold leading-none ${pipTone[rank]}`}
              aria-label={`rank ${rank}`}
            >
              {rank[0]!.toUpperCase()}
            </span>
            <span className={`size-1.5 rounded-full ${dotClass[a.status]}`} />
            <span className="text-[9px] font-mono text-zinc-500">{a.id.toString().padStart(3, "0")}</span>
          </button>
        );
      })}
    </div>
  );
}
