import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRow, PromotionEventPayload, Rank } from "../api";

/* ------------------------------------------------------------------ *
 * Agent World — IMMT-inspired isometric scene.
 *
 *   - Six themed zones arranged 3×2, drawn as rounded hex-ish tiles.
 *   - One <use href="#sprite-{rank}"> per agent; migrates with CSS transition.
 *   - When agents change zone we draw a faint flowing arc between the two
 *     zones (intensity = concurrent migration volume, fades over ~2.4 s).
 *   - Whole SVG is CSS-rotated (rotateX) for a 2.5D feel; labels stay inside
 *     so they tilt with the tiles (more cohesive than a floating HTML layer).
 * ------------------------------------------------------------------ */

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
  { id: "village",  label: "Village",           col: 0, row: 0, border: "#10b981", fill: "rgba(6,78,59,0.55)" },
  { id: "training", label: "Training Camp",     col: 1, row: 0, border: "#f59e0b", fill: "rgba(120,53,15,0.55)" },
  { id: "forest",   label: "Prediction Forest", col: 2, row: 0, border: "#22c55e", fill: "rgba(20,83,45,0.55)" },
  { id: "gate",     label: "Entry Gate",        col: 0, row: 1, border: "#0ea5e9", fill: "rgba(12,74,110,0.55)" },
  { id: "battle",   label: "Battlefield",       col: 1, row: 1, border: "#ef4444", fill: "rgba(127,29,29,0.55)" },
  { id: "glory",    label: "Wall of Glory",     col: 2, row: 1, border: "#fbbf24", fill: "rgba(113,63,18,0.55)" },
];

const RANK_FILL: Record<Rank, string> = {
  intern:    "#a1a1aa",
  junior:    "#38bdf8",
  senior:    "#34d399",
  principal: "#fbbf24",
};

const VIEW_W = 1200;
const VIEW_H = 360;
const COLS = 3;
const ROWS = 2;
const GAP = 16;
const PAD = 24;
const ZONE_W = (VIEW_W - PAD * 2 - GAP * (COLS - 1)) / COLS;
const ZONE_H = (VIEW_H - PAD * 2 - GAP * (ROWS - 1)) / ROWS;
const LABEL_H = 26;
const HALO_MS = 1500;
const FLOW_MS = 2400;

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

function zoneCenter(zone: Zone) {
  const r = zoneRect(zone);
  return { x: r.x + r.w / 2, y: r.y + LABEL_H + (r.h - LABEL_H) / 2 };
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
    const innerW = rect.w - 28;
    const innerH = rect.h - LABEL_H - 22;
    const cols = Math.max(1, Math.ceil(Math.sqrt(members.length * (innerW / innerH))));
    const rows = Math.ceil(members.length / cols);
    const dx = innerW / cols;
    const dy = innerH / Math.max(rows, 1);
    members.forEach((a, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      out.set(a.id, {
        zone: zone.id,
        x: rect.x + 14 + dx * (c + 0.5),
        y: rect.y + LABEL_H + 12 + dy * (r + 0.5),
      });
    });
  }
  return out;
}

/* ------------------------------------------------------------------ *
 * Rank sprites. Each <symbol> is an 18×24 glyph drawn around origin so a
 * parent <g transform="translate(x,y)"> places its feet at (x,y).
 * Keeps them readable at the size we render (~14px tall).
 * ------------------------------------------------------------------ */
function SpriteDefs() {
  return (
    <defs>
      {/* Shadow blob reused under every sprite */}
      <ellipse id="sprite-shadow" cx="0" cy="1.5" rx="4.5" ry="1.3" fill="rgba(0,0,0,0.35)" />

      {/* Intern — small figure, no hat */}
      <symbol id="sprite-intern" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.4" y="-7" width="4.8" height="6" rx="1.2" fill={RANK_FILL.intern} />
        <circle cx="0" cy="-10" r="2.3" fill={RANK_FILL.intern} />
      </symbol>

      {/* Junior — same body, small sky cap (triangle hat) */}
      <symbol id="sprite-junior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.6" y="-7.5" width="5.2" height="6.5" rx="1.3" fill={RANK_FILL.junior} />
        <circle cx="0" cy="-10.5" r="2.5" fill={RANK_FILL.junior} />
        <path d="M -2.8 -11.8 L 2.8 -11.8 L 0 -14.5 Z" fill={RANK_FILL.junior} opacity="0.8" />
      </symbol>

      {/* Senior — slightly taller, with a badge/tie */}
      <symbol id="sprite-senior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.8" y="-8.5" width="5.6" height="7.5" rx="1.4" fill={RANK_FILL.senior} />
        <rect x="-0.6" y="-7.5" width="1.2" height="3" fill="rgba(9,9,11,0.8)" />
        <circle cx="0" cy="-11.5" r="2.6" fill={RANK_FILL.senior} />
      </symbol>

      {/* Principal — crown */}
      <symbol id="sprite-principal" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-3" y="-9" width="6" height="8" rx="1.4" fill={RANK_FILL.principal} />
        <circle cx="0" cy="-12" r="2.8" fill={RANK_FILL.principal} />
        <path d="M -3.2 -14 L -2 -17 L -0.8 -14.5 L 0 -17.5 L 0.8 -14.5 L 2 -17 L 3.2 -14 Z"
              fill={RANK_FILL.principal} stroke="#78350f" strokeWidth="0.3" />
      </symbol>
    </defs>
  );
}

type Transition = { from: ZoneId; to: ZoneId; expiresAt: number };

export function AgentWorld({
  agents,
  onSelect,
  promotionEvents,
}: {
  agents: AgentRow[];
  onSelect?: (a: AgentRow) => void;
  promotionEvents?: { type: "promotion" | "demotion"; ts: string; payload: PromotionEventPayload }[];
}) {
  const positions = useMemo(() => computePositions(agents), [agents]);
  const zoneCounts = useMemo(() => {
    const c: Record<ZoneId, number> = {
      village: 0, training: 0, forest: 0, gate: 0, battle: 0, glory: 0,
    };
    for (const a of agents) c[zoneFor(a)]++;
    return c;
  }, [agents]);

  /* ---- flow paths: detect zone changes across renders ---- */
  const prevZones = useRef(new Map<number, ZoneId>());
  const [flows, setFlows] = useState<Transition[]>([]);

  useEffect(() => {
    const now = Date.now();
    const fresh: Transition[] = [];
    for (const a of agents) {
      const newZ = zoneFor(a);
      const oldZ = prevZones.current.get(a.id);
      if (oldZ && oldZ !== newZ) fresh.push({ from: oldZ, to: newZ, expiresAt: now + FLOW_MS });
      prevZones.current.set(a.id, newZ);
    }
    if (fresh.length) setFlows((prev) => [...prev.filter((t) => t.expiresAt > now), ...fresh]);
  }, [agents]);

  useEffect(() => {
    const t = window.setInterval(() => {
      setFlows((prev) => {
        const now = Date.now();
        const next = prev.filter((t) => t.expiresAt > now);
        return next.length === prev.length ? prev : next;
      });
    }, 300);
    return () => window.clearInterval(t);
  }, []);

  /* ---- halos (reuses phase-4 WS promotion events) ---- */
  const [halos, setHalos] = useState<Map<number, { kind: "promotion" | "demotion"; expiresAt: number }>>(new Map());

  useEffect(() => {
    if (!promotionEvents || promotionEvents.length === 0) return;
    const now = Date.now();
    setHalos((prev) => {
      const next = new Map(prev);
      for (const e of promotionEvents) {
        const evtTime = new Date(e.ts).getTime();
        if (now - evtTime > HALO_MS) continue;
        next.set(e.payload.agent_id, { kind: e.type, expiresAt: evtTime + HALO_MS });
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

  /* ---- render ---- */
  // Bucket flows by (from→to) pair so many simultaneous migrations draw as
  // one fatter arc instead of one-per-agent.
  const flowBuckets = useMemo(() => {
    const m = new Map<string, { from: ZoneId; to: ZoneId; count: number; latest: number }>();
    for (const t of flows) {
      const key = `${t.from}->${t.to}`;
      const b = m.get(key);
      if (b) { b.count += 1; b.latest = Math.max(b.latest, t.expiresAt); }
      else m.set(key, { from: t.from, to: t.to, count: 1, latest: t.expiresAt });
    }
    return Array.from(m.values());
  }, [flows]);

  return (
    <div
      className="relative w-full"
      style={{
        perspective: "1600px",
        perspectiveOrigin: "50% 0%",
      }}
    >
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H + 40}`}
        className="w-full h-auto block"
        style={{
          transform: "rotateX(28deg)",
          transformOrigin: "center top",
          transformStyle: "preserve-3d",
        }}
      >
        <SpriteDefs />

        {/* Zone tiles */}
        {ZONES.map((z) => {
          const r = zoneRect(z);
          return (
            <g key={z.id}>
              {/* drop shadow — small offset so tiles look like islands */}
              <rect x={r.x + 3} y={r.y + 6} width={r.w} height={r.h} rx={14} fill="rgba(0,0,0,0.45)" />
              {/* tile body */}
              <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={14}
                    fill={z.fill} stroke={z.border} strokeOpacity={0.6} strokeWidth={1.2} />
              {/* subtle top highlight */}
              <rect x={r.x + 1} y={r.y + 1} width={r.w - 2} height={6} rx={12}
                    fill="rgba(255,255,255,0.06)" />
              {/* label pill */}
              <rect x={r.x + 10} y={r.y + 6} width={Math.min(r.w - 20, z.label.length * 7 + 40)} height={LABEL_H - 8}
                    rx={9} fill="rgba(9,9,11,0.85)" stroke={z.border} strokeOpacity={0.7} strokeWidth={1} />
              <text x={r.x + 20} y={r.y + 20}
                    fontSize={11} fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                    fontWeight={600} letterSpacing={1} fill={z.border}>
                {z.label.toUpperCase()}
              </text>
              <text x={r.x + r.w - 16} y={r.y + 20}
                    fontSize={11} fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                    textAnchor="end" fill="#a1a1aa">
                {zoneCounts[z.id]}
              </text>
            </g>
          );
        })}

        {/* Flow arcs between zones for recent migrations */}
        {flowBuckets.map((b, i) => {
          const from = ZONES.find((z) => z.id === b.from)!;
          const to = ZONES.find((z) => z.id === b.to)!;
          const a = zoneCenter(from);
          const c = zoneCenter(to);
          const mx = (a.x + c.x) / 2;
          const my = (a.y + c.y) / 2 - 80; // lift control point above for a nice arc
          const d = `M ${a.x} ${a.y} Q ${mx} ${my} ${c.x} ${c.y}`;
          const strokeW = Math.min(1 + b.count * 0.5, 3.5);
          const opacity = Math.max(0.15, Math.min(0.55, 0.2 + b.count * 0.08));
          return (
            <g key={i} style={{ pointerEvents: "none" }}>
              <path d={d} fill="none" stroke={to.border} strokeOpacity={opacity}
                    strokeWidth={strokeW} strokeLinecap="round"
                    strokeDasharray="4 6">
                <animate attributeName="stroke-dashoffset" from="0" to="-20" dur="1.2s" repeatCount="indefinite" />
              </path>
              <circle cx={c.x} cy={c.y} r={4} fill={to.border} fillOpacity={opacity * 0.9} />
            </g>
          );
        })}

        {/* Agent sprites */}
        {agents.map((a) => {
          const pos = positions.get(a.id);
          if (!pos) return null;
          const rank: Rank = ((a.rank as Rank) || "intern");
          const hasPosition = Object.values(a.positions).some((p) => p.qty !== 0);
          const halo = halos.get(a.id);
          const haloColor = halo?.kind === "promotion" ? "#34d399"
                          : halo?.kind === "demotion"  ? "#f87171"
                          : null;
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
              style={{
                transition: "transform 700ms cubic-bezier(0.22, 1, 0.36, 1)",
                cursor: "pointer",
              }}
              onClick={() => onSelect?.(a)}
            >
              {haloColor && (
                <circle r={10} fill="none" stroke={haloColor} strokeOpacity={0.7} strokeWidth={1.5}>
                  <animate attributeName="r" from={5} to={14} dur="1.2s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" from={0.75} to={0} dur="1.2s" repeatCount="indefinite" />
                </circle>
              )}
              {hasPosition && (
                /* amber aura for agents currently holding a position */
                <circle r={7} fill="none" stroke="#fbbf24" strokeOpacity={0.85} strokeWidth={1} />
              )}
              <use href={`#sprite-${rank}`} />
              <title>{title}</title>
            </g>
          );
        })}
      </svg>

      {/* Legend (outside the tilt so it stays readable) */}
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
        <span className="ml-3">arcs = recent zone migrations · pulse = promotion/demotion</span>
        <span className="ml-auto text-zinc-600">click a sprite for detail</span>
      </div>
    </div>
  );
}
