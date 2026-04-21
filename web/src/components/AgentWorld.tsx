import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRow, PromotionEventPayload, Rank } from "../api";

/* ------------------------------------------------------------------ *
 * Agent World — stylized 2.5D scene.
 *
 * Design notes:
 *  - CSS 3D rotation on the whole SVG made sprites look like they were
 *    lying on the ground. Instead we keep the SVG flat and sell depth
 *    per-tile: each tile has a dark "side face" polygon below the top
 *    face, giving a raised-platform look without ruining sprite readability.
 *  - Sprites are <symbol> instances with richer silhouettes per rank.
 *    They bob on a staggered idle animation so the scene feels alive.
 *  - Zones carry an emoji watermark so empty zones read at a glance.
 *  - Flow arcs + promotion halos + state transitions unchanged from v1.
 * ------------------------------------------------------------------ */

type ZoneId = "village" | "training" | "forest" | "gate" | "battle" | "glory";

type Zone = {
  id: ZoneId;
  label: string;
  col: number;
  row: number;
  border: string;
  fillTop: string;
  fillBot: string;
  side: string;     // dark side-face color
  icon: string;     // emoji watermark
};

const ZONES: readonly Zone[] = [
  { id: "village",  label: "Village",           col: 0, row: 0, border: "#34d399", fillTop: "#064e3b", fillBot: "#022c22", side: "#032a24", icon: "🏠" },
  { id: "training", label: "Training Camp",     col: 1, row: 0, border: "#fbbf24", fillTop: "#78350f", fillBot: "#451a03", side: "#3a1301", icon: "🎯" },
  { id: "forest",   label: "Prediction Forest", col: 2, row: 0, border: "#4ade80", fillTop: "#14532d", fillBot: "#0b3b1c", side: "#082a15", icon: "🌲" },
  { id: "gate",     label: "Entry Gate",        col: 0, row: 1, border: "#38bdf8", fillTop: "#0c4a6e", fillBot: "#082f49", side: "#052238", icon: "🚪" },
  { id: "battle",   label: "Battlefield",       col: 1, row: 1, border: "#f87171", fillTop: "#7f1d1d", fillBot: "#4b0f0f", side: "#3a0a0a", icon: "⚔️" },
  { id: "glory",    label: "Wall of Glory",     col: 2, row: 1, border: "#fbbf24", fillTop: "#713f12", fillBot: "#422006", side: "#2f1604", icon: "🏆" },
];

/* Richer rank palette — primary + accent so sprites have contrast within a zone. */
const RANK = {
  intern:    { body: "#52525b", skin: "#d4d4d8", accent: "#a1a1aa" }, // warm grays
  junior:    { body: "#0ea5e9", skin: "#e0f2fe", accent: "#38bdf8" },
  senior:    { body: "#059669", skin: "#d1fae5", accent: "#34d399" },
  principal: { body: "#b45309", skin: "#fef3c7", accent: "#fbbf24" },
} as const satisfies Record<Rank, { body: string; skin: string; accent: string }>;

const VIEW_W = 1200;
const VIEW_H = 420;
const COLS = 3;
const ROWS = 2;
const GAP = 24;
const PAD = 24;
const ZONE_W = (VIEW_W - PAD * 2 - GAP * (COLS - 1)) / COLS;
const ZONE_H = (VIEW_H - PAD * 2 - GAP * (ROWS - 1)) / ROWS;
const LABEL_H = 28;
const TILE_DEPTH = 10;          // height of the side face
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
    const innerW = rect.w - 36;
    const innerH = rect.h - LABEL_H - 30;
    const cols = Math.max(1, Math.ceil(Math.sqrt(members.length * (innerW / innerH))));
    const rows = Math.ceil(members.length / cols);
    const dx = innerW / cols;
    const dy = innerH / Math.max(rows, 1);
    members.forEach((a, i) => {
      const c = i % cols;
      const r = Math.floor(i / cols);
      out.set(a.id, {
        zone: zone.id,
        x: rect.x + 18 + dx * (c + 0.5),
        y: rect.y + LABEL_H + 22 + dy * (r + 0.5),
      });
    });
  }
  return out;
}

/* ------------------------------------------------------------------ *
 * Sprite symbols — coordinate system: origin at feet, x in [-4, 4],
 * y from -18 (head) to 0 (ground). Body built from simple primitives.
 * ------------------------------------------------------------------ */
function SpriteDefs() {
  return (
    <defs>
      {/* Shared shadow */}
      <ellipse id="sprite-shadow" cx="0" cy="1.5" rx="5" ry="1.4" fill="rgba(0,0,0,0.5)" />

      {/* Intern — hard hat, simple posture, grey body */}
      <symbol id="sprite-intern" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.5" y="-8" width="5" height="7" rx="1" fill={RANK.intern.body} />
        <rect x="-3.3" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.accent} />
        <rect x="2.4" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.accent} />
        <circle cx="0" cy="-10.5" r="2.4" fill={RANK.intern.skin} />
        <path d="M -3 -11.5 Q 0 -14 3 -11.5 L 3 -10.5 L -3 -10.5 Z" fill="#f59e0b" />
        <rect x="-3.1" y="-10.7" width="6.2" height="0.9" fill="#f59e0b" />
      </symbol>

      {/* Junior — sky cap, clean suit */}
      <symbol id="sprite-junior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.6" y="-8.5" width="5.2" height="7.5" rx="1.2" fill={RANK.junior.body} />
        <rect x="-3.5" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.accent} />
        <rect x="2.6" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.accent} />
        <path d="M -0.6 -8.5 L 0.6 -8.5 L 0.3 -5 L -0.3 -5 Z" fill={RANK.junior.skin} />
        <circle cx="0" cy="-11" r="2.5" fill={RANK.junior.skin} />
        <path d="M -2.8 -12.3 L 2.8 -12.3 L 2.5 -13.5 L -2.5 -13.5 Z" fill={RANK.junior.accent} />
        <path d="M -2.5 -13.5 L 2.5 -13.5 L 0 -14.8 Z" fill={RANK.junior.accent} />
      </symbol>

      {/* Senior — suit + tie, glasses hint */}
      <symbol id="sprite-senior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.9" y="-9" width="5.8" height="8" rx="1.3" fill={RANK.senior.body} />
        <rect x="-3.7" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.accent} />
        <rect x="2.8" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.accent} />
        <path d="M -0.7 -9 L 0.7 -9 L 0.9 -4.2 L 0 -5 L -0.9 -4.2 Z" fill={RANK.senior.skin} />
        <rect x="-0.4" y="-8.6" width="0.8" height="3.4" fill="#0f172a" />
        <circle cx="0" cy="-11.6" r="2.6" fill={RANK.senior.skin} />
        <rect x="-2.4" y="-12.1" width="4.8" height="0.5" fill="#0f172a" opacity="0.7" />
        <path d="M -2.4 -13.2 Q 0 -14.8 2.4 -13.2 L 2.4 -12.2 L -2.4 -12.2 Z" fill="#1e293b" />
      </symbol>

      {/* Principal — crown + robe-ish base */}
      <symbol id="sprite-principal" overflow="visible">
        <use href="#sprite-shadow" />
        <path d="M -3.5 -1 L -2.8 -9.5 L 2.8 -9.5 L 3.5 -1 Z" fill={RANK.principal.body} />
        <path d="M -3.5 -1 L 3.5 -1 L 3 0.2 L -3 0.2 Z" fill="#78350f" />
        <rect x="-3.6" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.principal.accent} />
        <rect x="2.7" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.principal.accent} />
        <path d="M -0.8 -9.5 L 0.8 -9.5 L 0.6 -4 L 0 -5 L -0.6 -4 Z" fill={RANK.principal.skin} />
        <circle cx="0" cy="-12" r="2.7" fill={RANK.principal.skin} />
        <rect x="-2.4" y="-13.3" width="4.8" height="0.6" fill={RANK.principal.accent} opacity="0.7" />
        <path d="M -3.2 -14.5 L -2 -17.5 L -0.7 -14.8 L 0 -18 L 0.7 -14.8 L 2 -17.5 L 3.2 -14.5 Z"
              fill={RANK.principal.accent} stroke="#78350f" strokeWidth="0.4" />
        <circle cx="-2" cy="-15.8" r="0.5" fill="#dc2626" />
        <circle cx="0" cy="-16.5" r="0.5" fill="#dc2626" />
        <circle cx="2" cy="-15.8" r="0.5" fill="#dc2626" />
      </symbol>

      {/* Surface dot pattern — cheap "terrain" texture */}
      <pattern id="tile-grid" width="16" height="16" patternUnits="userSpaceOnUse">
        <circle cx="8" cy="8" r="0.8" fill="rgba(255,255,255,0.05)" />
      </pattern>
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
    const c: Record<ZoneId, number> = { village: 0, training: 0, forest: 0, gate: 0, battle: 0, glory: 0 };
    for (const a of agents) c[zoneFor(a)]++;
    return c;
  }, [agents]);

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
        for (const [id, h] of prev) if (h.expiresAt <= now) { next.delete(id); changed = true; }
        return changed ? next : prev;
      });
    }, 250);
    return () => window.clearInterval(t);
  }, []);

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
    <div className="relative w-full">
      <svg
        viewBox={`0 0 ${VIEW_W} ${VIEW_H + TILE_DEPTH + 8}`}
        className="w-full h-auto block"
        // Subtle horizontal skew gives a hint of perspective without laying sprites flat.
        style={{ transform: "skewY(-2deg)", transformOrigin: "center" }}
      >
        <SpriteDefs />

        {/* Zone tiles (bottom-up so side faces don't overlap tops) */}
        {ZONES.map((z) => {
          const r = zoneRect(z);
          return (
            <g key={z.id}>
              {/* side face — small parallelogram below the top face */}
              <path
                d={`M ${r.x} ${r.y + r.h} L ${r.x + r.w} ${r.y + r.h} L ${r.x + r.w - 4} ${r.y + r.h + TILE_DEPTH} L ${r.x + 4} ${r.y + r.h + TILE_DEPTH} Z`}
                fill={z.side}
              />
              {/* top face */}
              <defs>
                <linearGradient id={`grad-${z.id}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0" stopColor={z.fillTop} />
                  <stop offset="1" stopColor={z.fillBot} />
                </linearGradient>
              </defs>
              <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={14} fill={`url(#grad-${z.id})`} />
              <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={14} fill="url(#tile-grid)" />
              <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={14}
                    fill="none" stroke={z.border} strokeOpacity={0.5} strokeWidth={1.4} />
              {/* soft top highlight */}
              <rect x={r.x + 1} y={r.y + 1} width={r.w - 2} height={4} rx={12} fill="rgba(255,255,255,0.07)" />
              {/* zone watermark icon — large, faint, in the tile center */}
              <text
                x={r.x + r.w - 18}
                y={r.y + r.h - 12}
                fontSize={42}
                textAnchor="end"
                opacity={0.16}
                style={{ pointerEvents: "none" }}
              >
                {z.icon}
              </text>
              {/* label pill */}
              <rect x={r.x + 10} y={r.y + 6} width={z.label.length * 7 + 48} height={LABEL_H - 8}
                    rx={9} fill="rgba(9,9,11,0.88)" stroke={z.border} strokeOpacity={0.75} strokeWidth={1} />
              <text x={r.x + 20} y={r.y + 20} fontSize={11}
                    fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                    fontWeight={700} letterSpacing={1.2} fill={z.border}>
                {z.icon}  {z.label.toUpperCase()}
              </text>
              <text x={r.x + r.w - 16} y={r.y + 20} fontSize={11}
                    fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                    textAnchor="end" fill="#a1a1aa">
                {zoneCounts[z.id]}
              </text>
            </g>
          );
        })}

        {/* Flow arcs for recent migrations */}
        {flowBuckets.map((b, i) => {
          const from = ZONES.find((z) => z.id === b.from)!;
          const to = ZONES.find((z) => z.id === b.to)!;
          const a = zoneCenter(from);
          const c = zoneCenter(to);
          const mx = (a.x + c.x) / 2;
          const my = (a.y + c.y) / 2 - 90;
          const d = `M ${a.x} ${a.y} Q ${mx} ${my} ${c.x} ${c.y}`;
          const strokeW = Math.min(1.2 + b.count * 0.55, 4);
          const opacity = Math.max(0.18, Math.min(0.6, 0.24 + b.count * 0.09));
          return (
            <g key={i} style={{ pointerEvents: "none" }}>
              <path d={d} fill="none" stroke={to.border} strokeOpacity={opacity}
                    strokeWidth={strokeW} strokeLinecap="round" strokeDasharray="4 6">
                <animate attributeName="stroke-dashoffset" from="0" to="-20" dur="1.2s" repeatCount="indefinite" />
              </path>
              <circle cx={c.x} cy={c.y} r={4} fill={to.border} fillOpacity={opacity * 0.9} />
            </g>
          );
        })}

        {/* Sprites */}
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

          // Staggered idle bob — each sprite offsets by its agent id so the
          // scene breathes without being in lockstep.
          const delay = `${-((a.id * 113) % 2500) / 1000}s`;

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
                <circle r={11} fill="none" stroke={haloColor} strokeOpacity={0.75} strokeWidth={1.6}>
                  <animate attributeName="r" from={6} to={16} dur="1.2s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" from={0.8} to={0} dur="1.2s" repeatCount="indefinite" />
                </circle>
              )}
              {hasPosition && (
                <circle r={8} fill="none" stroke="#fbbf24" strokeOpacity={0.7} strokeWidth={1} />
              )}
              <g style={{ animation: `tf-bob 2.5s ease-in-out infinite`, animationDelay: delay, transformBox: "fill-box", transformOrigin: "center bottom" }}>
                <use href={`#sprite-${rank}`} />
              </g>
              <title>{title}</title>
            </g>
          );
        })}
      </svg>

      {/* Idle-bob keyframes. Kept inline so the component is self-contained. */}
      <style>{`
        @keyframes tf-bob {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-1.5px); }
        }
      `}</style>

      {/* Legend */}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] font-mono text-zinc-500">
        <span>ranks:</span>
        {(["intern", "junior", "senior", "principal"] as const).map((r) => (
          <span key={r} className="inline-flex items-center gap-1.5">
            <span className="inline-block size-2 rounded-full" style={{ background: RANK[r].accent }} />
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
