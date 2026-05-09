import { useEffect, useMemo, useRef, useState } from "react";
import type { AgentRow, MarketPhase, PromotionEventPayload, Rank } from "../shared/api";

/* ------------------------------------------------------------------ *
 * AgentWorldXL — streaming-tuned isometric diorama.
 *
 * Ported from web/src/components/AgentWorld.tsx with:
 *   - 2x tile dimensions (TW/TH/TZ) so sprites read at 1080p stream scale
 *   - longer walk transitions (1400ms -> 2400ms) for visible motion on stream
 *   - subtle continuous camera drift via a sin/cos translate on the SVG
 *     viewBox so the scene feels alive even when state is idle
 *   - a parallax sky/clouds layer behind the islands
 *   - no click handlers (broadcast-only)
 * ------------------------------------------------------------------ */

type ZoneId = "village" | "training" | "forest" | "gate" | "battle" | "glory";

const TW = 72;
const TH = 36;
const TZ = 28;

const iso = (wx: number, wy: number, wz = 1) => ({
  x: (wx - wy) * (TW / 2),
  y: (wx + wy) * (TH / 2) - wz * TZ,
});

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
      { wx: 2, wy: 1, glyph: "🏠", size: 28 },
      { wx: 4, wy: 2, glyph: "🏡", size: 26 },
      { wx: 3, wy: 3, glyph: "🌳", size: 24 },
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
      { wx: 9, wy: 1, glyph: "🎯", size: 28 },
      { wx: 11, wy: 3, glyph: "⛺", size: 26 },
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
      { wx: 15, wy: 2, glyph: "🌲", size: 26 },
      { wx: 16, wy: 1, glyph: "🌲", size: 24 },
      { wx: 17, wy: 3, glyph: "🌲", size: 28 },
      { wx: 18, wy: 2, glyph: "🌳", size: 24 },
      { wx: 16, wy: 3, glyph: "🍄", size: 20 },
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
      { wx: 3, wy: 7, glyph: "🚪", size: 28 },
      { wx: 4, wy: 8, glyph: "🛎️", size: 24 },
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
      { wx: 9, wy: 7, glyph: "⚔️", size: 28 },
      { wx: 11, wy: 8, glyph: "🛡️", size: 26 },
      { wx: 10, wy: 7, glyph: "🔥", size: 24 },
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
      { wx: 16, wy: 7, glyph: "🏆", size: 28 },
      { wx: 17, wy: 8, glyph: "👑", size: 26 },
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

function agentSpot(agentId: number, island: Island): { x: number; y: number } {
  if (island.tiles.length === 0) return { x: 0, y: 0 };
  const tileIdx = (agentId * 2654435761) % island.tiles.length;
  const [wx, wy] = island.tiles[Math.abs(tileIdx) % island.tiles.length]!;
  const base = iso(wx + 0.5, wy + 0.5);
  const seat = Math.floor(agentId / island.tiles.length) % 4;
  const jitter = [
    { x: 0,   y: -6 },
    { x: -12, y: 4 },
    { x: 12,  y: 4 },
    { x: 0,   y: 12 },
  ][seat]!;
  return { x: base.x + jitter.x, y: base.y + jitter.y };
}

function signAnchor(island: Island): { x: number; y: number } {
  const centers = island.tiles.map(([wx, wy]) => iso(wx + 0.5, wy + 0.5));
  return centers.reduce((a, b) => (b.y < a.y ? b : a));
}

const RANK = {
  intern:    { body: "#52525b", skin: "#e4e4e7", accent: "#a1a1aa", hat: "#f59e0b" },
  junior:    { body: "#0284c7", skin: "#e0f2fe", accent: "#38bdf8", hat: "#0369a1" },
  senior:    { body: "#047857", skin: "#d1fae5", accent: "#34d399", hat: "#065f46" },
  principal: { body: "#b45309", skin: "#fef3c7", accent: "#fbbf24", hat: "#78350f" },
} as const satisfies Record<Rank, { body: string; skin: string; accent: string; hat: string }>;

// Sprite scale multiplier vs the dashboard symbol set.
const SPRITE_SCALE = 2.4;

function SpriteDefs() {
  return (
    <defs>
      <ellipse id="sprite-shadow-xl" cx="0" cy="1.5" rx="5" ry="1.4" fill="rgba(0,0,0,0.6)" />

      <symbol id="sprite-intern-xl" overflow="visible">
        <use href="#sprite-shadow-xl" />
        <rect x="-2.6" y="-8" width="5.2" height="7" rx="1" fill={RANK.intern.body} />
        <rect x="-3.5" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.skin} />
        <rect x="2.6" y="-5" width="0.9" height="3.5" rx="0.3" fill={RANK.intern.skin} />
        <circle cx="0" cy="-10.5" r="2.5" fill={RANK.intern.skin} />
        <path d="M -3 -11.3 Q 0 -13.8 3 -11.3 L 3 -10.2 L -3 -10.2 Z" fill={RANK.intern.hat} />
        <rect x="-3.1" y="-10.4" width="6.2" height="0.7" fill={RANK.intern.hat} />
      </symbol>

      <symbol id="sprite-junior-xl" overflow="visible">
        <use href="#sprite-shadow-xl" />
        <rect x="-2.7" y="-8.5" width="5.4" height="7.5" rx="1.2" fill={RANK.junior.body} />
        <rect x="-3.6" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.skin} />
        <rect x="2.7" y="-5.3" width="0.9" height="3.7" rx="0.3" fill={RANK.junior.skin} />
        <path d="M -0.6 -8.5 L 0.6 -8.5 L 0.3 -5 L -0.3 -5 Z" fill={RANK.junior.accent} />
        <circle cx="0" cy="-11" r="2.5" fill={RANK.junior.skin} />
        <path d="M -2.8 -12.3 L 2.8 -12.3 L 2.5 -13.5 L -2.5 -13.5 Z" fill={RANK.junior.hat} />
        <path d="M -2.5 -13.5 L 2.5 -13.5 L 0 -14.8 Z" fill={RANK.junior.hat} />
      </symbol>

      <symbol id="sprite-senior-xl" overflow="visible">
        <use href="#sprite-shadow-xl" />
        <rect x="-3" y="-9" width="6" height="8" rx="1.3" fill={RANK.senior.body} />
        <rect x="-3.9" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.skin} />
        <rect x="3" y="-5.8" width="0.9" height="3.9" rx="0.3" fill={RANK.senior.skin} />
        <rect x="-0.5" y="-9" width="1" height="4" fill={RANK.senior.accent} />
        <circle cx="0" cy="-11.6" r="2.7" fill={RANK.senior.skin} />
        <rect x="-2.6" y="-12.3" width="5.2" height="0.5" fill="#0f172a" opacity="0.7" />
        <path d="M -2.6 -13.4 Q 0 -15 2.6 -13.4 L 2.6 -12.3 L -2.6 -12.3 Z" fill={RANK.senior.hat} />
      </symbol>

      <symbol id="sprite-principal-xl" overflow="visible">
        <use href="#sprite-shadow-xl" />
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

function Signpost({ island }: { island: Island }) {
  const anchor = signAnchor(island);
  const cx = anchor.x;
  const cy = anchor.y - 28;
  const textW = island.label.length * 11 + 28;
  return (
    <g style={{ pointerEvents: "none" }}>
      <rect x={cx - 1.8} y={cy - 4} width={3.6} height={44} fill="#713f12" />
      <rect x={cx - 2.4} y={cy + 36} width={4.8} height={4.8} rx={0.8} fill="#713f12" />
      <rect x={cx - textW / 2 + 3} y={cy - 20 + 3} width={textW} height={24} rx={6} fill="rgba(0,0,0,0.45)" />
      <rect x={cx - textW / 2} y={cy - 20} width={textW} height={24} rx={6}
            fill="#854d0e" stroke="#78350f" strokeWidth={1.6} />
      <rect x={cx - textW / 2 + 2} y={cy - 18} width={textW - 4} height={6} rx={4}
            fill="#a16207" opacity={0.8} />
      <text x={cx} y={cy - 2}
            fontSize={14} fontWeight={700} letterSpacing={0.8}
            fontFamily="ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif"
            textAnchor="middle" fill="#fef3c7">
        {island.label}
      </text>
    </g>
  );
}

function Bridge({ from, to }: { from: [number, number]; to: [number, number] }) {
  const a = iso(from[0], from[1]);
  const b = iso(to[0], to[1]);
  const dx = b.x - a.x, dy = b.y - a.y;
  const len = Math.sqrt(dx * dx + dy * dy);
  const ang = (Math.atan2(dy, dx) * 180) / Math.PI;
  return (
    <g transform={`translate(${a.x} ${a.y}) rotate(${ang})`} style={{ pointerEvents: "none" }}>
      <rect x="0" y="-6" width={len} height="12" fill="#78350f" />
      <rect x="0" y="-6" width={len} height="2" fill="#a16207" />
      {Array.from({ length: Math.max(3, Math.floor(len / 12)) }, (_, i) => (
        <rect key={i} x={i * 12 + 2} y="-6" width="1.6" height="12" fill="#451a03" />
      ))}
    </g>
  );
}

const BRIDGES: { from: [number, number]; to: [number, number] }[] = [
  { from: [6, 2.5], to: [8, 2.5] },
  { from: [13, 2.5], to: [15, 2.5] },
  { from: [3.5, 5], to: [3.5, 7] },
  { from: [10.5, 5], to: [10.5, 7] },
  { from: [17.5, 5], to: [16.5, 7] },
  { from: [6, 8.5], to: [8, 8.5] },
  { from: [13, 8.5], to: [15, 8.5] },
];

const HALO_MS = 2_400;
const FLOW_MS = 4_000;
const WALK_MS = 2_400;

type Transition = { from: ZoneId; to: ZoneId; expiresAt: number };

type WeatherKind = "none" | "rain" | "sun" | "snow" | "fog";

const SKY_BY_PHASE: Record<MarketPhase, { top: string; bottom: string }> = {
  premarket:  { top: "#0c1322", bottom: "#1e293b" },
  rth:        { top: "#0ea5e9", bottom: "#7dd3fc" },
  afterhours: { top: "#1e1b4b", bottom: "#c2410c" },
  closed:     { top: "#020617", bottom: "#1e293b" },
};

function pickWeather(phase: MarketPhase, pnlPct: number): WeatherKind {
  if (phase === "closed") return "snow";
  if (phase === "premarket") return "fog";
  if (pnlPct <= -1) return "rain";
  if (pnlPct >= 1) return "sun";
  return "none";
}

// Deterministic pseudo-random so star/particle positions are stable across
// re-renders without needing refs everywhere.
function seeded(i: number, salt = 1): number {
  const x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

export function AgentWorldXL({
  agents,
  promotionEvents,
  marketPhase = "rth",
  todayPnlPct = 0,
}: {
  agents: AgentRow[];
  promotionEvents?: { type: "promotion" | "demotion"; ts: string; payload: PromotionEventPayload }[];
  marketPhase?: MarketPhase;
  todayPnlPct?: number;
}) {
  const islandById = useMemo(() => {
    const m = new Map<ZoneId, Island>();
    for (const i of ISLANDS) m.set(i.id, i);
    return m;
  }, []);

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

  // Migration flow tracking
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
    }, 400);
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
    }, 300);
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

  const tilesDraw = useMemo(() => {
    const arr: { wx: number; wy: number; island: Island }[] = [];
    for (const island of ISLANDS) for (const [wx, wy] of island.tiles) arr.push({ wx, wy, island });
    arr.sort((a, b) => a.wx + a.wy - (b.wx + b.wy));
    return arr;
  }, []);

  const agentsSorted = useMemo(
    () => [...agents].sort((a, b) => (spots.get(a.id)?.y ?? 0) - (spots.get(b.id)?.y ?? 0)),
    [agents, spots],
  );

  // Continuous camera drift — sin/cos translate of the SVG viewBox so the
  // diorama gently floats. Computed every animation frame.
  const [cameraTick, setCameraTick] = useState(0);
  useEffect(() => {
    let raf: number;
    const loop = () => {
      setCameraTick((t) => (t + 1) % 100_000);
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, []);
  const camPhase = (performance.now() / 1000) * 0.18;
  const camDx = Math.sin(camPhase) * 16;
  const camDy = Math.cos(camPhase * 0.7) * 8;
  void cameraTick;

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

  const weather: WeatherKind = pickWeather(marketPhase, todayPnlPct);

  const padX = 80;
  const padTop = 140;
  const padBot = 60;
  const viewX = bounds.minX - padX + camDx;
  const viewY = bounds.minY - padTop + camDy;
  const viewW = (bounds.maxX - bounds.minX) + padX * 2;
  const viewH = (bounds.maxY - bounds.minY) + padTop + padBot;

  return (
    <div className="relative w-full h-full">
      <svg
        viewBox={`${viewX} ${viewY} ${viewW} ${viewH}`}
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full block"
      >
        <SpriteDefs />

        <defs>
          <radialGradient id="scene-bg-xl" cx="50%" cy="40%" r="80%">
            <stop offset="0%" stopColor="rgba(30,41,59,0.0)" />
            <stop offset="60%" stopColor="rgba(15,23,42,0.4)" />
            <stop offset="100%" stopColor="rgba(0,0,0,0.85)" />
          </radialGradient>
          <linearGradient id="sky-xl" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SKY_BY_PHASE[marketPhase].top}>
              <animate attributeName="stop-color"
                values={`${SKY_BY_PHASE[marketPhase].top};${SKY_BY_PHASE[marketPhase].top}`}
                dur="60s" />
            </stop>
            <stop offset="100%" stopColor={SKY_BY_PHASE[marketPhase].bottom}>
              <animate attributeName="stop-color"
                values={`${SKY_BY_PHASE[marketPhase].bottom};${SKY_BY_PHASE[marketPhase].bottom}`}
                dur="60s" />
            </stop>
          </linearGradient>
          <radialGradient id="sun-rays-xl" cx="50%" cy="0%" r="80%">
            <stop offset="0%" stopColor="#fde68a" stopOpacity="0.55" />
            <stop offset="40%" stopColor="#fbbf24" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#f59e0b" stopOpacity="0" />
          </radialGradient>
        </defs>

        <rect x={viewX} y={viewY} width={viewW} height={viewH} fill="url(#sky-xl)" />

        {/* Twinkling stars — only when market is dark (premarket/afterhours/closed) */}
        {marketPhase !== "rth" && Array.from({ length: 36 }, (_, i) => {
          const sx = viewX + seeded(i, 1) * viewW;
          const sy = viewY + seeded(i, 2) * (viewH * 0.45);
          const r = 0.6 + seeded(i, 3) * 1.4;
          const dur = 1.8 + seeded(i, 4) * 2.6;
          const delay = seeded(i, 5) * dur;
          return (
            <circle key={`star-${i}`} cx={sx} cy={sy} r={r} fill="#fef9c3">
              <animate attributeName="opacity"
                values="0.15;0.95;0.15"
                dur={`${dur}s`} begin={`-${delay}s`}
                repeatCount="indefinite" />
            </circle>
          );
        })}

        {/* Drifting clouds (parallax) */}
        {[
          { x: 0, y: -120, r: 60, op: 0.10, speed: 0.04, phase: 0 },
          { x: 220, y: -80, r: 80, op: 0.08, speed: 0.025, phase: 1.4 },
          { x: 480, y: -150, r: 50, op: 0.12, speed: 0.06, phase: 2.6 },
          { x: 700, y: -100, r: 90, op: 0.07, speed: 0.03, phase: 3.7 },
        ].map((c, i) => {
          const dx = Math.sin(camPhase * c.speed + c.phase) * 40;
          return (
            <ellipse key={i}
              cx={bounds.minX + c.x + dx}
              cy={bounds.minY + c.y}
              rx={c.r} ry={c.r * 0.45}
              fill="#e2e8f0" opacity={c.op} />
          );
        })}

        <rect x={viewX} y={viewY} width={viewW} height={viewH} fill="url(#scene-bg-xl)" />

        {/* Weather layer — particles tied to portfolio PnL and market phase. */}
        {weather === "rain" && Array.from({ length: 70 }, (_, i) => {
          const rx = viewX + seeded(i, 11) * viewW;
          const ry = viewY + seeded(i, 12) * viewH;
          const dur = 0.7 + seeded(i, 13) * 0.5;
          const delay = seeded(i, 14) * dur;
          return (
            <line key={`rain-${i}`}
              x1={rx} y1={ry} x2={rx - 4} y2={ry + 14}
              stroke="#7dd3fc" strokeOpacity={0.55} strokeWidth={1}>
              <animate attributeName="y1" values={`${ry};${ry + viewH}`}
                dur={`${dur}s`} begin={`-${delay}s`} repeatCount="indefinite" />
              <animate attributeName="y2" values={`${ry + 14};${ry + viewH + 14}`}
                dur={`${dur}s`} begin={`-${delay}s`} repeatCount="indefinite" />
            </line>
          );
        })}

        {weather === "sun" && (
          <>
            <rect x={viewX} y={viewY} width={viewW} height={viewH * 0.7}
              fill="url(#sun-rays-xl)" style={{ pointerEvents: "none" }}>
              <animate attributeName="opacity" values="0.7;1;0.7" dur="6s" repeatCount="indefinite" />
            </rect>
            {Array.from({ length: 14 }, (_, i) => {
              const cx = viewX + viewW * 0.5;
              const cy = viewY + 20;
              const len = viewH * 0.8;
              const baseAngle = -90 + (i / 14) * 180;
              return (
                <g key={`ray-${i}`} transform={`translate(${cx} ${cy})`} opacity={0.18}>
                  <rect x={-1.2} y={0} width={2.4} height={len}
                    fill="#fde68a"
                    transform={`rotate(${baseAngle})`}>
                    <animateTransform attributeName="transform" type="rotate"
                      from={`${baseAngle} 0 0`} to={`${baseAngle + 360} 0 0`}
                      dur="60s" repeatCount="indefinite" />
                  </rect>
                </g>
              );
            })}
          </>
        )}

        {weather === "snow" && Array.from({ length: 60 }, (_, i) => {
          const sx = viewX + seeded(i, 21) * viewW;
          const sy = viewY + seeded(i, 22) * viewH;
          const r = 1 + seeded(i, 23) * 1.6;
          const dur = 5 + seeded(i, 24) * 4;
          const delay = seeded(i, 25) * dur;
          const drift = (seeded(i, 26) - 0.5) * 30;
          return (
            <circle key={`snow-${i}`} cx={sx} cy={sy} r={r}
              fill="#f8fafc" opacity={0.78}>
              <animate attributeName="cy" values={`${sy};${sy + viewH}`}
                dur={`${dur}s`} begin={`-${delay}s`} repeatCount="indefinite" />
              <animate attributeName="cx" values={`${sx};${sx + drift};${sx}`}
                dur={`${dur}s`} begin={`-${delay}s`} repeatCount="indefinite" />
            </circle>
          );
        })}

        {weather === "fog" && (
          <rect x={viewX} y={viewY + viewH * 0.55} width={viewW} height={viewH * 0.45}
            fill="#cbd5e1" opacity={0.18} style={{ pointerEvents: "none" }}>
            <animate attributeName="opacity" values="0.10;0.22;0.10" dur="9s" repeatCount="indefinite" />
          </rect>
        )}

        {BRIDGES.map((b, i) => <Bridge key={i} from={b.from} to={b.to} />)}

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
                strokeWidth={0.6}
              />
            </g>
          );
        })}

        {ISLANDS.flatMap((island) =>
          island.decos.map((d, i) => {
            const p = iso(d.wx + 0.5, d.wy + 0.5);
            return (
              <text
                key={`${island.id}-deco-${i}`}
                x={p.x}
                y={p.y - 4}
                fontSize={d.size ?? 24}
                textAnchor="middle"
                style={{ pointerEvents: "none" }}
              >
                {d.glyph}
              </text>
            );
          }),
        )}

        {ISLANDS.map((island) => {
          const a = signAnchor(island);
          return (
            <g key={`sign-${island.id}`}>
              <Signpost island={island} />
              <g transform={`translate(${a.x} ${a.y - 64})`} style={{ pointerEvents: "none" }}>
                <rect x={-22} y={-12} width={44} height={22} rx={11}
                      fill="rgba(9,9,11,0.92)" stroke={island.border} strokeOpacity={0.85} strokeWidth={1.4} />
                <text x={0} y={3} textAnchor="middle" fontSize={14}
                      fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                      fontWeight={700} fill={island.border}>
                  {zoneCounts[island.id]}
                </text>
              </g>
            </g>
          );
        })}

        {flowBuckets.map((b, i) => {
          const from = islandById.get(b.from)!;
          const to = islandById.get(b.to)!;
          const a = signAnchor(from);
          const c = signAnchor(to);
          const mx = (a.x + c.x) / 2;
          const my = Math.min(a.y, c.y) - 80;
          const d = `M ${a.x} ${a.y - 20} Q ${mx} ${my} ${c.x} ${c.y - 20}`;
          const strokeW = Math.min(2.4 + b.count * 1.0, 6);
          const opacity = Math.max(0.3, Math.min(0.7, 0.35 + b.count * 0.1));
          return (
            <g key={i} style={{ pointerEvents: "none" }}>
              <path d={d} fill="none" stroke={to.border} strokeOpacity={opacity}
                    strokeWidth={strokeW} strokeLinecap="round" strokeDasharray="6 10">
                <animate attributeName="stroke-dashoffset" from="0" to="-32" dur="1.2s" repeatCount="indefinite" />
              </path>
            </g>
          );
        })}

        {agentsSorted.map((a) => {
          const pos = spots.get(a.id);
          if (!pos) return null;
          const rank: Rank = ((a.rank as Rank) || "intern");
          const hasPosition = Object.values(a.positions).some((p) => p.qty !== 0);
          const halo = halos.get(a.id);
          const haloColor = halo?.kind === "promotion" ? "#34d399" : halo?.kind === "demotion" ? "#f87171" : null;
          const delay = `${-((a.id * 113) % 2500) / 1000}s`;

          return (
            <g
              key={a.id}
              transform={`translate(${pos.x}, ${pos.y})`}
              style={{
                transition: `transform ${WALK_MS}ms cubic-bezier(0.22, 1, 0.36, 1)`,
              }}
            >
              {haloColor && (
                <circle r={20} fill="none" stroke={haloColor} strokeOpacity={0.85} strokeWidth={2.4}>
                  <animate attributeName="r" from={10} to={28} dur="1.5s" repeatCount="indefinite" />
                  <animate attributeName="stroke-opacity" from={0.9} to={0} dur="1.5s" repeatCount="indefinite" />
                </circle>
              )}
              {hasPosition && (
                <circle r={15} fill="none" stroke="#fbbf24" strokeOpacity={0.85} strokeWidth={1.6} />
              )}
              <g
                transform={`scale(${SPRITE_SCALE})`}
                style={{
                  animation: `tf-bob 2.5s ease-in-out infinite`,
                  animationDelay: delay,
                  transformBox: "fill-box",
                  transformOrigin: "center bottom",
                }}
              >
                <use href={`#sprite-${rank}-xl`} />
              </g>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
