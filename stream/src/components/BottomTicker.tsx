import { useMemo } from "react";
import type { FillEvent, PromotionEvent } from "../hooks/useStreamData";
import type { AgentRow } from "../shared/api";

const RANK_LABEL: Record<string, string> = {
  intern: "Intern",
  junior: "Junior",
  senior: "Senior",
  principal: "Principal",
};

function nameForAgent(agents: AgentRow[], id: number): string {
  return agents.find((a) => a.id === id)?.name ?? `#${id}`;
}

type TickerItem = { key: string; tone: "fill" | "promo" | "demo"; text: string };

export function BottomTicker({
  agents,
  fills,
  promotions,
  speedPxPerSec,
}: {
  agents: AgentRow[];
  fills: FillEvent[];
  promotions: PromotionEvent[];
  speedPxPerSec: number;
}) {
  const items: TickerItem[] = useMemo(() => {
    const out: TickerItem[] = [];
    for (const f of fills) {
      const sym = f.payload.symbol;
      const name = nameForAgent(agents, f.payload.agent_id);
      const side = f.payload.side.toUpperCase();
      out.push({
        key: `f-${f.ts}-${f.payload.agent_id}-${sym}`,
        tone: "fill",
        text: `${name} ${side} ${f.payload.qty} ${sym} @ $${f.payload.price.toFixed(2)}`,
      });
    }
    for (const p of promotions) {
      out.push({
        key: `p-${p.ts}-${p.payload.agent_id}`,
        tone: p.type === "promotion" ? "promo" : "demo",
        text:
          p.type === "promotion"
            ? `${p.payload.agent_name} promoted to ${RANK_LABEL[p.payload.to_rank] ?? p.payload.to_rank}`
            : `${p.payload.agent_name} demoted to ${RANK_LABEL[p.payload.to_rank] ?? p.payload.to_rank}`,
      });
    }
    if (out.length === 0) {
      out.push({ key: "idle-0", tone: "fill", text: "TradeFarm idle — waiting for the next tick." });
    }
    return out;
  }, [fills, promotions, agents]);

  // Duplicate items so the marquee animation can wrap seamlessly (-50%).
  const doubled = useMemo(() => [...items, ...items], [items]);

  // Approximate scroll distance: each item ~ 220px wide. Speed in px/s -> duration.
  const approxWidthPx = items.length * 220;
  const durationSec = Math.max(20, approxWidthPx / Math.max(20, speedPxPerSec));

  return (
    <div className="h-[100px] flex items-center bg-zinc-950/95 border-t border-zinc-800 overflow-hidden relative">
      <div
        className="flex items-center gap-10 whitespace-nowrap will-change-transform"
        style={{ animation: `tf-crawl ${durationSec}s linear infinite` }}
      >
        {doubled.map((it, i) => (
          <span key={`${it.key}-${i}`} className="flex items-center gap-3 px-4">
            <Glyph tone={it.tone} />
            <span className="text-2xl font-semibold tracking-tight">
              <Tone tone={it.tone}>{it.text}</Tone>
            </span>
            <span className="text-zinc-700 text-2xl">·</span>
          </span>
        ))}
      </div>
    </div>
  );
}

function Glyph({ tone }: { tone: "fill" | "promo" | "demo" }) {
  if (tone === "promo")
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-emerald-500/15 text-(--color-profit) text-base">
        ▲
      </span>
    );
  if (tone === "demo")
    return (
      <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-rose-500/15 text-(--color-loss) text-base">
        ▼
      </span>
    );
  return (
    <span className="inline-flex h-7 w-7 items-center justify-center rounded-full bg-zinc-700/40 text-zinc-300 text-base">
      ●
    </span>
  );
}

function Tone({ tone, children }: { tone: "fill" | "promo" | "demo"; children: React.ReactNode }) {
  if (tone === "promo") return <span className="text-(--color-profit)">{children}</span>;
  if (tone === "demo") return <span className="text-(--color-loss)">{children}</span>;
  return <span className="text-zinc-100">{children}</span>;
}
