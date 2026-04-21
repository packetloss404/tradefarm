import { useEffect, useMemo, useState } from "react";
import type { AgentRow, PromotionEventPayload, Rank } from "../api";

type WsPromoEvt = {
  type: "promotion" | "demotion";
  ts: string;
  payload: PromotionEventPayload;
};

const HALO_MS = 1500;

type ZoneId = "village" | "training" | "forest" | "gate" | "battle" | "glory";

type Zone = {
  id: ZoneId;
  label: string;
  col: number;
  row: number;
  border: string;
  fill: string;
};

const ZONES: readonly Zone[] = [
  { id: "village",  label: "Village",           col: 0, row: 0, border: "#10b981", fill: "rgb(6,78,59,0.35)" },
  { id: "training", label: "Training Camp",     col: 1, row: 0, border: "#f59e0b", fill: "rgb(120,53,15,0.35)" },
  { id: "forest",   label: "Prediction Forest", col: 2, row: 0, border: "#22c55e", fill: "rgb(20,83,45,0.35)" },
  { id: "gate",     label: "Entry Gate",        col: 0, row: 1, border: "#0ea5e9", fill: "rgb(12,74,110,0.35)" },
  { id: "battle",   label: "Battlefield",       col: 1, row: 1, border: "#ef4444", fill: "rgb(127,29,29,0.35)" },
  { id: "glory",    label: "Wall of Glory",     col: 2, row: 1, border: "#fbbf24", fill: "rgb(113,63,18,0.35)" },
];

const RANK_FILL: Record<Rank, string> = {
  intern:    "#a1a1aa", // zinc-400
  junior:    "#38bdf8", // sky-400
  senior:    "#34d399", // emerald-400
  principal: "#fbbf24", // amber-400
};

const VIEW_W = 1200;
const VIEW_H = 340;
const COLS = 3;
const ROWS = 2;
const GAP = 14;
const PAD = 16;
const ZONE_W = (VIEW_W - PAD * 2 - GAP * (COLS - 1)) / COLS;
const ZONE_H = (VIEW_H - PAD * 2 - GAP * (ROWS - 1)) / ROWS;
const LABEL_H = 26;

function zoneFor(a: AgentRow): ZoneId {
  const hasPosition = Object.values(a.positions).some((p) => p.qty !== 0);
  if (hasPosition) return "battle";
  const totalPnl = a.realized_pnl + a.unrealized_pnl;
  if ((a.rank === "senior" || a.rank === "principal") && totalPnl > 0) return "glory";
  if (a.last_decision?.stance === "trade") return "gate";
  if (a.strategy === "lstm_llm_v1") return "forest";
  if (a.strategy === "lstm_v1") return "training";
  return "village";
}

function zoneRect(zone: Zone) {
  return {
    x: PAD + zone.col * (ZONE_W + GAP),
    y: PAD + zone.row * (ZONE_H + GAP),
    w: ZONE_W,
    h: ZONE_H,
  };
}

type DotPos = { x: number; y: number; zone: ZoneId };

function computePositions(agents: AgentRow[]): Map<number, DotPos> {
  const byZone = new Map<ZoneId, AgentRow[]>();
  for (const a of agents) {
    const z = zoneFor(a);
    const arr = byZone.get(z) ?? [];
    arr.push(a);
    byZone.set(z, arr);
  }

  const out = new Map<number, DotPos>();
  for (const zone of ZONES) {
    const members = byZone.get(zone.id) ?? [];
    if (members.length === 0) continue;
    const rect = zoneRect(zone);
    const innerW = rect.w - 20;
    const innerH = rect.h - LABEL_H - 20;
    const cols = Math.max(1, Math.ceil(Math.sqrt(members.length * (innerW / innerH))));
    const rows = Math.ceil(members.length / cols);
    const dx = innerW / cols;
    const dy = innerH / Math.max(rows, 1);
    members.forEach((a, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      out.set(a.id, {
        zone: zone.id,
        x: rect.x + 10 + dx * (c + 0.5),
        y: rect.y + LABEL_H + 10 + dy * (r + 0.5),
      });
    });
  }
  return out;
}

const RANK_ORDER: Record<Rank, number> = { intern: 0, junior: 1, senior: 2, principal: 3 };

export function AgentWorld({
  agents,
  onSelect,
  promotionEvents,
}: {
  agents: AgentRow[];
  onSelect?: (a: AgentRow) => void;
  promotionEvents?: WsPromoEvt[];
}) {
  const positions = useMemo(() => computePositions(agents), [agents]);

  // Track recently-promoted/demoted agents for the halo pulse; mirror the
  // AgentGrid behaviour so both views react to the same WS events.
  const [halos, setHalos] = useState<Map<number, { kind: "promotion" | "demotion"; expiresAt: number }>>(
    () => new Map(),
  );

  useEffect(() => {
    if (!promotionEvents || promotionEvents.length === 0) return;
    const now = Date.now();
    setHalos((prev) => {
      const next = new Map(prev);
      for (const e of promotionEvents) {
        const evtTime = new Date(e.ts).getTime();
        if (now - evtTime > HALO_MS) continue;
        const p = e.payload;
        const kind: "promotion" | "demotion" =
          RANK_ORDER[p.to_rank as Rank] >= RANK_ORDER[p.from_rank as Rank] ? "promotion" : "demotion";
        next.set(p.agent_id, { kind, expiresAt: evtTime + HALO_MS });
      }
      return next;
    });
  }, [promotionEvents]);

  useEffect(() => {
    const t = window.setInterval(() => {
      setHalos((prev) => {
        const now = Date.now();
        let changed = false;
        const next = new Map(prev);
        for (const [id, h] of prev) {
          if (h.expiresAt <= now) { next.delete(id); changed = true; }
        }
        return changed ? next : prev;
      });
    }, 250);
    return () => window.clearInterval(t);
  }, []);
  const zoneCounts = useMemo(() => {
    const c: Record<ZoneId, number> = {
      village: 0, training: 0, forest: 0, gate: 0, battle: 0, glory: 0,
    };
    for (const a of agents) c[zoneFor(a)]++;
    return c;
  }, [agents]);

  return (
    <div className="relative w-full">
      <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full h-auto block">
        {/* Zone tiles */}
        {ZONES.map((z) => {
          const r = zoneRect(z);
          return (
            <g key={z.id}>
              {/* zone body */}
              <rect
                x={r.x}
                y={r.y}
                width={r.w}
                height={r.h}
                rx={10}
                fill={z.fill}
                stroke={z.border}
                strokeOpacity={0.5}
                strokeWidth={1}
              />
              {/* label banner */}
              <rect
                x={r.x}
                y={r.y}
                width={r.w}
                height={LABEL_H}
                rx={10}
                fill={z.border}
                fillOpacity={0.22}
              />
              <text
                x={r.x + 14}
                y={r.y + 17}
                fontSize={11}
                fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                fontWeight={600}
                letterSpacing={1}
                fill={z.border}
              >
                {z.label.toUpperCase()}
              </text>
              <text
                x={r.x + r.w - 14}
                y={r.y + 17}
                fontSize={11}
                fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                textAnchor="end"
                fill="#a1a1aa"
              >
                {zoneCounts[z.id]}
              </text>
            </g>
          );
        })}

        {/* Agent dots. Each dot is a <g transform="translate(x,y)"> with a
            CSS transition so reassignments animate smoothly between zones. */}
        {agents.map((a) => {
          const pos = positions.get(a.id);
          if (!pos) return null;
          const rank: Rank = (a.rank as Rank) || "intern";
          const hasPosition = Object.values(a.positions).some((p) => p.qty !== 0);
          const halo = halos.get(a.id);
          const haloColor = halo?.kind === "promotion" ? "#34d399" : halo?.kind === "demotion" ? "#f87171" : null;
          const symbols = Object.keys(a.positions);
          const sym = symbols[0] ?? "";
          const title = [
            a.name,
            `${a.strategy} · ${rank}`,
            sym ? `holds ${sym}` : "",
            a.last_decision ? `llm ${a.last_decision.stance}` : "",
          ].filter(Boolean).join(" · ");
          return (
            <g
              key={a.id}
              transform={`translate(${pos.x}, ${pos.y})`}
              style={{ transition: "transform 700ms cubic-bezier(0.22, 1, 0.36, 1)", cursor: "pointer" }}
              onClick={() => onSelect?.(a)}
            >
              {haloColor && (
                <circle r={9} fill="none" stroke={haloColor} strokeOpacity={0.65} strokeWidth={1.5}>
                  <animate attributeName="r" from={4} to={12} dur="1.2s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" from={0.75} to={0} dur="1.2s" repeatCount="indefinite" />
                </circle>
              )}
              <circle
                r={4}
                fill={RANK_FILL[rank]}
                stroke={hasPosition ? "#fbbf24" : "#18181b"}
                strokeWidth={hasPosition ? 1.5 : 0.75}
              />
              <title>{title}</title>
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] font-mono text-zinc-500">
        <span>ranks:</span>
        {(["intern", "junior", "senior", "principal"] as const).map((r) => (
          <span key={r} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full" style={{ background: RANK_FILL[r] }} />
            {r}
          </span>
        ))}
        <span className="ml-3 inline-flex items-center gap-1.5">
          <span className="inline-block size-2 rounded-full bg-zinc-400 ring-1 ring-amber-400" />
          holding position
        </span>
        <span className="ml-auto text-zinc-600">click a dot for detail</span>
      </div>
    </div>
  );
}
