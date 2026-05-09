import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRow, PromotionEventPayload, Rank } from "../api";

/* ------------------------------------------------------------------ *
 * Agent World — isometric diorama.
 *
 * Coordinate system: tiles live in a (wx, wy) world grid with wz=1 on
 * top. `iso(wx, wy, wz)` projects to screen space using classic 2:1
 * isometric projection — each tile is a chunky cube with top + south +
 * east faces. Agents are upright sprites placed at tile positions
 * within their current zone; they "walk" to a new island via a
 * CSS-transitioned transform when their zone changes.
 * ------------------------------------------------------------------ */

type ZoneId = "village" | "training" | "forest" | "gate" | "battle" | "glory";

// Iso tile dimensions in screen units.
const TW = 36;   // full diamond width
const TH = 18;   // full diamond depth
const TZ = 14;   // cube extrusion height

const iso = (wx: number, wy: number, wz = 1) => ({
  x: (wx - wy) * (TW / 2),
  y: (wx + wy) * (TH / 2) - wz * TZ,
});

/** Rectangle of tile coords with the 4 outer corners trimmed for an organic
 *  island silhouette. */
function blob(x0: number, y0: number, w: number, h: number): [number, number][] {
  const out: [number, number][] = [];
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      const corner =
        (x === 0 && y === 0) ||
        (x === w - 1 && y === 0) ||
        (x === 0 && y === h - 1) ||
        (x === w - 1 && y === h - 1);
      if (corner) continue;
      out.push([x0 + x, y0 + y]);
    }
  }
  return out;
}

type Deco = { wx: number; wy: number; glyph: string; size?: number };

type Island = {
  id: ZoneId;
  label: string;
  tiles: [number, number][];
  grass: string;
  grassAlt: string;
  sideLight: string;
  sideDark: string;
  border: string;
  decos: Deco[];
};

const ISLANDS: Island[] = [
  {
    id: "village",
    label: "Village",
    tiles: blob(1, 1, 5, 4),
    grass: "#16a34a", grassAlt: "#15803d",
    sideLight: "#854d0e", sideDark: "#713f12",
    border: "#4ade80",
    decos: [
      { wx: 2, wy: 1, glyph: "🏠", size: 14 },
      { wx: 4, wy: 2, glyph: "🏡", size: 13 },
      { wx: 3, wy: 3, glyph: "🌳", size: 12 },
    ],
  },
  {
    id: "training",
    label: "Training Camp",
    tiles: blob(8, 1, 5, 4),
    grass: "#ca8a04", grassAlt: "#a16207",
    sideLight: "#78350f", sideDark: "#451a03",
    border: "#fbbf24",
    decos: [
      { wx: 9, wy: 1, glyph: "🎯", size: 14 },
      { wx: 11, wy: 3, glyph: "⛺", size: 13 },
    ],
  },
  {
    id: "forest",
    label: "Prediction Forest",
    tiles: blob(15, 1, 5, 4),
    grass: "#15803d", grassAlt: "#14532d",
    sideLight: "#713f12", sideDark: "#451a03",
    border: "#22c55e",
    decos: [
      { wx: 15, wy: 2, glyph: "🌲", size: 13 },
      { wx: 16, wy: 1, glyph: "🌲", size: 12 },
      { wx: 17, wy: 3, glyph: "🌲", size: 14 },
      { wx: 18, wy: 2, glyph: "🌳", size: 12 },
      { wx: 16, wy: 3, glyph: "🍄", size: 10 },
    ],
  },
  {
    id: "gate",
    label: "Entry Gate",
    tiles: blob(2, 7, 4, 3),
    grass: "#0891b2", grassAlt: "#0e7490",
    sideLight: "#334155", sideDark: "#1e293b",
    border: "#38bdf8",
    decos: [
      { wx: 3, wy: 7, glyph: "🚪", size: 14 },
      { wx: 4, wy: 8, glyph: "🛎️", size: 12 },
    ],
  },
  {
    id: "battle",
    label: "Battlefield",
    tiles: blob(8, 7, 5, 3),
    grass: "#991b1b", grassAlt: "#7f1d1d",
    sideLight: "#3a1313", sideDark: "#1e0606",
    border: "#f87171",
    decos: [
      { wx: 9, wy: 7, glyph: "⚔️", size: 14 },
      { wx: 11, wy: 8, glyph: "🛡️", size: 13 },
      { wx: 10, wy: 7, glyph: "🔥", size: 12 },
    ],
  },
  {
    id: "glory",
    label: "Wall of Glory",
    tiles: blob(15, 7, 4, 3),
    grass: "#ca8a04", grassAlt: "#a16207",
    sideLight: "#713f12", sideDark: "#422006",
    border: "#fbbf24",
    decos: [
      { wx: 16, wy: 7, glyph: "🏆", size: 14 },
      { wx: 17, wy: 8, glyph: "👑", size: 13 },
    ],
  },
];

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

/** Deterministic per-agent spot on an island. Same agent always sits in
 *  roughly the same sub-tile offset so positions feel stable between ticks.
 *  Multiple agents on the same tile get small jitters so they don't overlap. */
function agentSpot(agentId: number, island: Island): { x: number; y: number } {
  if (island.tiles.length === 0) return { x: 0, y: 0 };
  const tileIdx = (agentId * 2654435761) % island.tiles.length;
  const [wx, wy] = island.tiles[Math.abs(tileIdx) % island.tiles.length]!;
  const base = iso(wx + 0.5, wy + 0.5);
  const seat = Math.floor(agentId / island.tiles.length) % 4;
  const jitter = [
    { x: 0,  y: -3 },
    { x: -6, y: 2 },
    { x: 6,  y: 2 },
    { x: 0,  y: 6 },
  ][seat]!;
  return { x: base.x + jitter.x, y: base.y + jitter.y };
}

/** Top-most tile center for sign-post anchor. */
function signAnchor(island: Island): { x: number; y: number } {
  const centers = island.tiles.map(([wx, wy]) => iso(wx + 0.5, wy + 0.5));
  return centers.reduce((a, b) => (b.y < a.y ? b : a));
}

/* ------------------------------------------------------------------ *
 * Sprite symbols — same rank-differentiated figures as v2 but re-tuned
 * to read clearly at iso scale. Origin at feet.
 * ------------------------------------------------------------------ */
const RANK = {
  intern:    { body: "#52525b", skin: "#e4e4e7", accent: "#a1a1aa", hat: "#f59e0b" },
  junior:    { body: "#0284c7", skin: "#e0f2fe", accent: "#38bdf8", hat: "#0369a1" },
  senior:    { body: "#047857", skin: "#d1fae5", accent: "#34d399", hat: "#065f46" },
  principal: { body: "#b45309", skin: "#fef3c7", accent: "#fbbf24", hat: "#78350f" },
} as const satisfies Record<Rank, { body: string; skin: string; accent: string; hat: string }>;

function SpriteDefs() {
  return (
    <defs>
      <ellipse id="sprite-shadow" cx="0" cy="1.5" rx="5" ry="1.4" fill="rgba(0,0,0,0.55)" />

      <symbol id="sprite-intern" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.6" y="-8" width="5.2" height="7" rx="1" fill={RANK.intern.body} />
        <rect x="-3.5" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.skin} />
        <rect x="2.6" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.skin} />
        <circle cx="0" cy="-10.5" r="2.5" fill={RANK.intern.skin} />
        <path d="M -3 -11.3 Q 0 -13.8 3 -11.3 L 3 -10.2 L -3 -10.2 Z" fill={RANK.intern.hat} />
        <rect x="-3.1" y="-10.4" width="6.2" height="0.7" fill={RANK.intern.hat} />
      </symbol>

      <symbol id="sprite-junior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-2.7" y="-8.5" width="5.4" height="7.5" rx="1.2" fill={RANK.junior.body} />
        <rect x="-3.6" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.skin} />
        <rect x="2.7" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.skin} />
        <path d="M -0.6 -8.5 L 0.6 -8.5 L 0.3 -5 L -0.3 -5 Z" fill={RANK.junior.accent} />
        <circle cx="0" cy="-11" r="2.5" fill={RANK.junior.skin} />
        <path d="M -2.8 -12.3 L 2.8 -12.3 L 2.5 -13.5 L -2.5 -13.5 Z" fill={RANK.junior.hat} />
        <path d="M -2.5 -13.5 L 2.5 -13.5 L 0 -14.8 Z" fill={RANK.junior.hat} />
      </symbol>

      <symbol id="sprite-senior" overflow="visible">
        <use href="#sprite-shadow" />
        <rect x="-3" y="-9" width="6" height="8" rx="1.3" fill={RANK.senior.body} />
        <rect x="-3.9" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.skin} />
        <rect x="3" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.skin} />
        <rect x="-0.5" y="-9" width="1" height="4" fill={RANK.senior.accent} />
        <circle cx="0" cy="-11.6" r="2.7" fill={RANK.senior.skin} />
        <rect x="-2.6" y="-12.3" width="5.2" height="0.5" fill="#0f172a" opacity="0.7" />
        <path d="M -2.6 -13.4 Q 0 -15 2.6 -13.4 L 2.6 -12.3 L -2.6 -12.3 Z" fill={RANK.senior.hat} />
      </symbol>

      <symbol id="sprite-principal" overflow="visible">
        <use href="#sprite-shadow" />
        <path d="M -3.6 -1 L -2.9 -9.5 L 2.9 -9.5 L 3.6 -1 Z" fill={RANK.principal.body} />
        <rect x="-3.9" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.principal.skin} />
        <rect x="3" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.principal.skin} />
        <path d="M -0.7 -9.5 L 0.7 -9.5 L 0.6 -4 L 0 -5 L -0.6 -4 Z" fill={RANK.principal.skin} />
        <circle cx="0" cy="-12" r="2.8" fill={RANK.principal.skin} />
        <path d="M -3.3 -14.5 L -2 -17.5 L -0.7 -14.8 L 0 -18 L 0.7 -14.8 L 2 -17.5 L 3.3 -14.5 Z"
              fill={RANK.principal.accent} stroke={RANK.principal.hat} strokeWidth="0.4" />
        <circle cx="-2" cy="-15.8" r="0.5" fill="#dc2626" />
        <circle cx="0" cy="-16.5" r="0.5" fill="#dc2626" />
        <circle cx="2" cy="-15.8" r="0.5" fill="#dc2626" />
      </symbol>
    </defs>
  );
}

/* ------------------------------------------------------------------ *
 * Signpost — wooden stake + plank with island label.
 * ------------------------------------------------------------------ */
function Signpost({ island }: { island: Island }) {
  const anchor = signAnchor(island);
  const cx = anchor.x;
  const cy = anchor.y - 14;
  const textW = island.label.length * 5.5 + 14;
  return (
    <g style={{ pointerEvents: "none" }}>
      {/* stake */}
      <rect x={cx - 0.9} y={cy - 2} width={1.8} height={22} fill="#713f12" />
      <rect x={cx - 1.2} y={cy + 18} width={2.4} height={2.4} rx={0.4} fill="#713f12" />
      {/* plank shadow */}
      <rect x={cx - textW / 2 + 1.5} y={cy - 10 + 1.5} width={textW} height={12} rx={3} fill="rgba(0,0,0,0.45)" />
      {/* plank */}
      <rect x={cx - textW / 2} y={cy - 10} width={textW} height={12} rx={3}
            fill="#854d0e" stroke="#78350f" strokeWidth={0.8} />
      <rect x={cx - textW / 2 + 1} y={cy - 9} width={textW - 2} height={3} rx={2}
            fill="#a16207" opacity={0.8} />
      <text x={cx} y={cy - 1}
            fontSize={7} fontWeight={700} letterSpacing={0.4}
            fontFamily="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
            textAnchor="middle" fill="#fef3c7">
        {island.label}
      </text>
    </g>
  );
}

/* ------------------------------------------------------------------ *
 * Bridge — simple plank strip between two island centers.
 * ------------------------------------------------------------------ */
function Bridge({ from, to }: { from: [number, number]; to: [number, number] }) {
  const a = iso(from[0], from[1]);
  const b = iso(to[0], to[1]);
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ang = (Math.atan2(dy, dx) * 180) / Math.PI;
  return (
    <g transform={`translate(${a.x} ${a.y}) rotate(${ang})`} style={{ pointerEvents: "none" }}>
      <rect x="0" y="-3" width={len} height="6" fill="#78350f" />
      <rect x="0" y="-3" width={len} height="1" fill="#a16207" />
      {Array.from({ length: Math.max(2, Math.floor(len / 6)) }, (_, i) => (
        <rect key={i} x={i * 6 + 1} y="-3" width="0.8" height="6" fill="#451a03" />
      ))}
    </g>
  );
}

/* Bridges to draw — picked by eye so the map reads as a connected world. */
const BRIDGES: { from: [number, number]; to: [number, number] }[] = [
  { from: [6, 2.5], to: [8, 2.5] },      // village → training
  { from: [13, 2.5], to: [15, 2.5] },    // training → forest
  { from: [3.5, 5], to: [3.5, 7] },      // village → gate
  { from: [10.5, 5], to: [10.5, 7] },    // training → battle
  { from: [17.5, 5], to: [16.5, 7] },    // forest → glory
  { from: [6, 8.5], to: [8, 8.5] },      // gate → battle
  { from: [13, 8.5], to: [15, 8.5] },    // battle → glory
];

/* ------------------------------------------------------------------ *
 * Main component
 * ------------------------------------------------------------------ */

const HALO_MS = 1500;
const FLOW_MS = 2400;

type Transition = { from: ZoneId; to: ZoneId; expiresAt: number };

export function AgentWorld({
  agents,
  onSelect,
  promotionEvents,
  fit = "natural",
}: {
  agents: AgentRow[];
  onSelect?: (a: AgentRow) => void;
  promotionEvents?: { type: "promotion" | "demotion"; ts: string; payload: PromotionEventPayload }[];
  // "natural" (default) renders at width-driven height (legacy behavior).
  // "contain" makes the outer div a flex column filling its parent: SVG takes
  // remaining space and fits its viewBox to that box (preserveAspectRatio
  // default = xMidYMid meet), legend pinned at natural height below. Used by
  // the dashboard's snap-fit live viewport so the diorama scales down rather
  // than clipping when the section is shorter than its width-driven height.
  fit?: "natural" | "contain";
}) {
  const islandById = useMemo(() => {
    const m = new Map<ZoneId, Island>();
    for (const i of ISLANDS) m.set(i.id, i);
    return m;
  }, []);

  // Agent spots in iso coords (target; CSS transition interpolates the path).
  const spots = useMemo(() => {
    const m = new Map<number, { x: number; y: number; zone: ZoneId }>();
    for (const a of agents) {
      const zoneId = zoneFor(a);
      const island = islandById.get(zoneId)!;
      const sp = agentSpot(a.id, island);
      m.set(a.id, { ...sp, zone: zoneId });
    }
    return m;
  }, [agents, islandById]);

  const zoneCounts = useMemo(() => {
    const c: Record<ZoneId, number> = { village: 0, training: 0, forest: 0, gate: 0, battle: 0, glory: 0 };
    for (const a of agents) c[zoneFor(a)]++;
    return c;
  }, [agents]);

  // Flow arc accounting
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

  // Promotion halos
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

  // Tile draw order (painter's algorithm: far to near by wx + wy)
  const tilesDraw = useMemo(() => {
    const arr: { wx: number; wy: number; island: Island }[] = [];
    for (const island of ISLANDS) for (const [wx, wy] of island.tiles) arr.push({ wx, wy, island });
    arr.sort((a, b) => a.wx + a.wy - (b.wx + b.wy));
    return arr;
  }, []);

  // Agents sorted by target y (far first, near last) so near sprites overlap far.
  const agentsSorted = useMemo(
    () => [...agents].sort((a, b) => (spots.get(a.id)?.y ?? 0) - (spots.get(b.id)?.y ?? 0)),
    [agents, spots],
  );

  // Viewbox — computed from tile extents; shift so minX is at 0.
  const bounds = useMemo(() => {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const island of ISLANDS) {
      for (const [wx, wy] of island.tiles) {
        for (const [dx, dy] of [[0,0],[1,0],[0,1],[1,1]]) {
          const p = iso(wx + dx!, wy + dy!, 1);
          if (p.x < minX) minX = p.x;
          if (p.y < minY) minY = p.y;
          if (p.x > maxX) maxX = p.x;
          if (p.y > maxY) maxY = p.y;
          const pb = iso(wx + dx!, wy + dy!, 0);
          if (pb.y > maxY) maxY = pb.y;
        }
      }
    }
    return { minX, minY, maxX, maxY };
  }, []);

  const padX = 40;
  const padTop = 60;    // room for signposts
  const padBot = 24;
  const viewX = bounds.minX - padX;
  const viewY = bounds.minY - padTop;
  const viewW = (bounds.maxX - bounds.minX) + padX * 2;
  const viewH = (bounds.maxY - bounds.minY) + padTop + padBot;

  const outerCls = fit === "contain"
    ? "relative w-full h-full flex flex-col min-h-0"
    : "relative w-full";
  const svgCls = fit === "contain"
    ? "flex-1 min-h-0 w-full h-full block"
    : "w-full h-auto block";

  return (
    <div className={outerCls}>
      <svg viewBox={`${viewX} ${viewY} ${viewW} ${viewH}`} className={svgCls}>
        <SpriteDefs />

        {/* subtle vignette backdrop */}
        <defs>
          <radialGradient id="scene-bg" cx="50%" cy="40%" r="70%">
            <stop offset="0%" stopColor="rgba(24,24,27,0)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0.35)" />
          </radialGradient>
        </defs>
        <rect x={viewX} y={viewY} width={viewW} height={viewH} fill="url(#scene-bg)" />

        {/* Bridges drawn behind tiles */}
        {BRIDGES.map((b, i) => <Bridge key={i} from={b.from} to={b.to} />)}

        {/* Tiles — painter's order */}
        {tilesDraw.map(({ wx, wy, island }) => {
          const top = iso(wx, wy);
          const topE = iso(wx + 1, wy);
          const topS = iso(wx, wy + 1);
          const topSE = iso(wx + 1, wy + 1);
          const botSE = iso(wx + 1, wy + 1, 0);
          const botS = iso(wx, wy + 1, 0);
          const botE = iso(wx + 1, wy, 0);
          const alt = (wx + wy) % 2 === 0;
          return (
            <g key={`${island.id}-${wx}-${wy}`}>
              <polygon
                points={`${topE.x},${topE.y} ${topSE.x},${topSE.y} ${botSE.x},${botSE.y} ${botE.x},${botE.y}`}
                fill={island.sideDark}
              />
              <polygon
                points={`${topS.x},${topS.y} ${topSE.x},${topSE.y} ${botSE.x},${botSE.y} ${botS.x},${botS.y}`}
                fill={island.sideLight}
              />
              <polygon
                points={`${top.x},${top.y} ${topE.x},${topE.y} ${topSE.x},${topSE.y} ${topS.x},${topS.y}`}
                fill={alt ? island.grass : island.grassAlt}
                stroke="rgba(0,0,0,0.18)"
                strokeWidth={0.3}
              />
            </g>
          );
        })}

        {/* Decorations (scene flavor) */}
        {ISLANDS.flatMap((island) =>
          island.decos.map((d, i) => {
            const p = iso(d.wx + 0.5, d.wy + 0.5);
            return (
              <text
                key={`${island.id}-deco-${i}`}
                x={p.x}
                y={p.y - 2}
                fontSize={d.size ?? 12}
                textAnchor="middle"
                style={{ pointerEvents: "none" }}
              >
                {d.glyph}
              </text>
            );
          }),
        )}

        {/* Sign posts — one per island, counts rendered as a little tag beneath */}
        {ISLANDS.map((island) => {
          const a = signAnchor(island);
          return (
            <g key={`sign-${island.id}`}>
              <Signpost island={island} />
              <g transform={`translate(${a.x} ${a.y - 32})`} style={{ pointerEvents: "none" }}>
                <rect x={-10} y={-6} width={20} height={11} rx={5}
                      fill="rgba(9,9,11,0.88)" stroke={island.border} strokeOpacity={0.7} strokeWidth={0.6} />
                <text x={0} y={1.5} textAnchor="middle" fontSize={7}
                      fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                      fontWeight={600} fill={island.border}>
                  {zoneCounts[island.id]}
                </text>
              </g>
            </g>
          );
        })}

        {/* Flow arcs for recent migrations */}
        {flowBuckets.map((b, i) => {
          const from = islandById.get(b.from)!;
          const to = islandById.get(b.to)!;
          const a = signAnchor(from);
          const c = signAnchor(to);
          const mx = (a.x + c.x) / 2;
          const my = Math.min(a.y, c.y) - 40;
          const d = `M ${a.x} ${a.y - 10} Q ${mx} ${my} ${c.x} ${c.y - 10}`;
          const strokeW = Math.min(1.2 + b.count * 0.5, 3);
          const opacity = Math.max(0.2, Math.min(0.6, 0.25 + b.count * 0.08));
          return (
            <g key={i} style={{ pointerEvents: "none" }}>
              <path d={d} fill="none" stroke={to.border} strokeOpacity={opacity}
                    strokeWidth={strokeW} strokeLinecap="round" strokeDasharray="3 5">
                <animate attributeName="stroke-dashoffset" from="0" to="-16" dur="1s" repeatCount="indefinite" />
              </path>
            </g>
          );
        })}

        {/* Agents (painter-sorted by target y). Smooth CSS transition animates
            the walk between islands when the zone assignment changes. */}
        {agentsSorted.map((a) => {
          const pos = spots.get(a.id);
          if (!pos) return null;
          const rank: Rank = ((a.rank as Rank) || "intern");
          const hasPosition = Object.values(a.positions).some((p) => p.qty !== 0);
          const halo = halos.get(a.id);
          const haloColor = halo?.kind === "promotion" ? "#34d399" : halo?.kind === "demotion" ? "#f87171" : null;
          const title = [
            a.name,
            `${a.strategy} · ${rank}`,
            Object.keys(a.positions)[0] ? `holds ${Object.keys(a.positions)[0]}` : "",
            a.last_decision ? `llm ${a.last_decision.stance}` : "",
          ].filter(Boolean).join(" · ");
          const delay = `${-((a.id * 113) % 2500) / 1000}s`;

          return (
            <g
              key={a.id}
              transform={`translate(${pos.x}, ${pos.y})`}
              style={{
                transition: "transform 1400ms cubic-bezier(0.22, 1, 0.36, 1)",
                cursor: "pointer",
              }}
              onClick={() => onSelect?.(a)}
            >
              {haloColor && (
                <circle r={9} fill="none" stroke={haloColor} strokeOpacity={0.75} strokeWidth={1.3}>
                  <animate attributeName="r" from={5} to={13} dur="1.2s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" from={0.8} to={0} dur="1.2s" repeatCount="indefinite" />
                </circle>
              )}
              {hasPosition && (
                <circle r={7} fill="none" stroke="#fbbf24" strokeOpacity={0.8} strokeWidth={0.9} />
              )}
              <g style={{
                animation: `tf-bob 2.5s ease-in-out infinite`,
                animationDelay: delay,
                transformBox: "fill-box",
                transformOrigin: "center bottom",
              }}>
                <use href={`#sprite-${rank}`} />
              </g>
              <title>{title}</title>
            </g>
          );
        })}
      </svg>

      <style>{`
        @keyframes tf-bob {
          0%, 100% { transform: translateY(0); }
          50%      { transform: translateY(-1.2px); }
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
        <span className="ml-3">watch agents walk between islands as their state changes</span>
        <span className="ml-auto text-zinc-600">click a sprite for detail</span>
      </div>
    </div>
  );
}
