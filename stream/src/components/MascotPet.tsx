import { useEffect, useRef, useState } from "react";

/* ------------------------------------------------------------------ *
 * MascotPet — pure-flavor wandering sprite for AgentWorldXL.
 *
 * A tiny chicken / cat / farmer that random-walks between caller-supplied
 * waypoints (typically the bridge endpoints in BRIDGES). It never trades,
 * never reads market state, and is deliberately oblivious. State machine:
 *
 *   pick start node
 *   loop forever:
 *     idle (idleMs)        — sit still, do a subtle bob
 *     walk to a new node   — CSS transition handles interpolation (walkMs)
 *
 * Renders a bare <g> so the parent <svg> in AgentWorldXL owns the canvas.
 * ------------------------------------------------------------------ */

type MascotVariant = "chicken" | "cat" | "farmer";

type MascotNode = { x: number; y: number };

type MascotPetProps = {
  /** Pre-projected iso coordinates of waypoints the mascot may visit.
   *  Caller computes these from AgentWorldXL's BRIDGES via iso(). */
  nodes: MascotNode[];
  idleMs?: number;
  walkMs?: number;
  variant?: MascotVariant;
};

/** Pick a random index in [0, len) that is not equal to `exclude`. */
function pickOtherIndex(len: number, exclude: number): number {
  if (len <= 1) return 0;
  let i = Math.floor(Math.random() * len);
  if (i === exclude) i = (i + 1) % len;
  return i;
}

export function MascotPet({
  nodes,
  idleMs = 3000,
  walkMs = 2000,
  variant = "chicken",
}: MascotPetProps) {
  // Stable initial index so the mascot doesn't jump on remount-without-nodes.
  const initialIndexRef = useRef<number>(
    nodes.length > 0 ? Math.floor(Math.random() * nodes.length) : 0,
  );
  const [idx, setIdx] = useState<number>(initialIndexRef.current);
  const [walking, setWalking] = useState<boolean>(false);

  useEffect(() => {
    if (nodes.length < 2) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    let current = initialIndexRef.current;
    if (current >= nodes.length) {
      current = 0;
      setIdx(0);
    }

    const idlePhase = () => {
      if (cancelled) return;
      setWalking(false);
      timer = setTimeout(walkPhase, idleMs);
    };

    const walkPhase = () => {
      if (cancelled) return;
      const next = pickOtherIndex(nodes.length, current);
      current = next;
      setWalking(true);
      setIdx(next);
      timer = setTimeout(idlePhase, walkMs);
    };

    // Begin in idle so the sprite doesn't lurch on mount.
    idlePhase();

    return () => {
      cancelled = true;
      if (timer !== null) clearTimeout(timer);
    };
  }, [nodes, idleMs, walkMs]);

  if (nodes.length < 2) return <g style={{ pointerEvents: "none" }} />;

  const safeIdx = idx < nodes.length ? idx : 0;
  const pos = nodes[safeIdx];
  if (!pos) return <g style={{ pointerEvents: "none" }} />;

  return (
    <g
      transform={`translate(${pos.x}, ${pos.y})`}
      style={{
        transition: `transform ${walkMs}ms cubic-bezier(0.22, 1, 0.36, 1)`,
        pointerEvents: "none",
      }}
    >
      {/* Soft ground shadow — stays put under the sprite during the bob. */}
      <ellipse cx={0} cy={1.2} rx={4.6} ry={1.3} fill="rgba(0,0,0,0.45)" />

      {/* Bob group: idle = gentle vertical oscillation, walking = small hop. */}
      <g>
        <animateTransform
          attributeName="transform"
          type="translate"
          values={walking ? "0 0; 0 -1.6; 0 0" : "0 0; 0 -0.7; 0 0"}
          dur={walking ? "0.32s" : "1.6s"}
          repeatCount="indefinite"
        />
        <MascotSprite variant={variant} />
      </g>
    </g>
  );
}

/* ------------------------------------------------------------------ *
 * Variant sprites — small (~14–18px tall in local SVG units), aligned
 * so y=0 is the ground line and the body grows upward into negative y.
 * ------------------------------------------------------------------ */

function MascotSprite({ variant }: { variant: MascotVariant }) {
  if (variant === "cat") return <CatSprite />;
  if (variant === "farmer") return <FarmerSprite />;
  return <ChickenSprite />;
}

function ChickenSprite() {
  // White body, red comb, orange beak/feet. ~16px tall.
  return (
    <g>
      {/* feet */}
      <rect x={-2.2} y={-0.4} width={1.2} height={1.6} fill="#f97316" />
      <rect x={1.0} y={-0.4} width={1.2} height={1.6} fill="#f97316" />
      {/* body */}
      <ellipse cx={0} cy={-4.2} rx={4.2} ry={4.0} fill="#fafafa" stroke="#e5e7eb" strokeWidth={0.4} />
      {/* tail tuft */}
      <path d="M 3.4 -5.6 L 5.8 -7.0 L 5.0 -4.8 Z" fill="#fafafa" stroke="#e5e7eb" strokeWidth={0.3} />
      {/* head */}
      <circle cx={-2.4} cy={-8.6} r={2.4} fill="#fafafa" stroke="#e5e7eb" strokeWidth={0.3} />
      {/* comb */}
      <path d="M -3.6 -10.6 Q -3.0 -11.6 -2.4 -10.6 Q -1.8 -11.7 -1.2 -10.6 L -1.2 -10.0 L -3.6 -10.0 Z"
        fill="#dc2626" />
      {/* eye */}
      <circle cx={-3.0} cy={-8.8} r={0.35} fill="#0f172a" />
      {/* beak */}
      <polygon points="-4.6,-8.4 -5.8,-8.0 -4.6,-7.6" fill="#f97316" />
      {/* wattle */}
      <path d="M -3.6 -7.4 Q -3.4 -6.6 -2.8 -6.8" fill="none" stroke="#dc2626" strokeWidth={0.6} />
    </g>
  );
}

function CatSprite() {
  // Grey/orange tabby with triangle ears + tail. ~16px tall.
  return (
    <g>
      {/* feet */}
      <rect x={-2.6} y={-0.4} width={1.2} height={1.6} fill="#71717a" />
      <rect x={1.4} y={-0.4} width={1.2} height={1.6} fill="#71717a" />
      {/* tail (curls back) */}
      <path d="M 3.6 -3.6 Q 6.4 -2.0 5.2 -6.4" fill="none" stroke="#a1a1aa" strokeWidth={1.6} strokeLinecap="round" />
      {/* body */}
      <ellipse cx={0} cy={-3.6} rx={4.2} ry={3.0} fill="#a1a1aa" />
      {/* tabby stripes */}
      <path d="M -2.4 -5.6 L -2.4 -1.8" stroke="#fb923c" strokeWidth={0.5} opacity={0.85} />
      <path d="M 0.4 -6.0 L 0.4 -1.6" stroke="#fb923c" strokeWidth={0.5} opacity={0.85} />
      <path d="M 2.6 -5.4 L 2.6 -2.2" stroke="#fb923c" strokeWidth={0.5} opacity={0.85} />
      {/* head */}
      <circle cx={-3.0} cy={-7.6} r={2.6} fill="#a1a1aa" />
      {/* ears */}
      <polygon points="-4.6,-9.6 -3.8,-11.8 -3.0,-9.8" fill="#a1a1aa" />
      <polygon points="-3.0,-9.6 -2.2,-11.4 -1.4,-9.4" fill="#a1a1aa" />
      <polygon points="-4.2,-9.8 -3.8,-10.9 -3.4,-9.8" fill="#fb923c" opacity={0.7} />
      {/* eyes */}
      <circle cx={-3.8} cy={-7.6} r={0.32} fill="#0f172a" />
      <circle cx={-2.2} cy={-7.6} r={0.32} fill="#0f172a" />
      {/* nose */}
      <polygon points="-3.0,-7.0 -3.3,-6.6 -2.7,-6.6" fill="#fb7185" />
    </g>
  );
}

function FarmerSprite() {
  // Tiny human with a yellow straw hat + brown overalls. ~17px tall.
  return (
    <g>
      {/* legs */}
      <rect x={-1.6} y={-3.4} width={1.4} height={3.4} fill="#1f2937" />
      <rect x={0.2} y={-3.4} width={1.4} height={3.4} fill="#1f2937" />
      {/* body / overalls */}
      <rect x={-2.4} y={-8.4} width={4.8} height={5.2} rx={1.0} fill="#92400e" />
      {/* overall strap detail */}
      <rect x={-0.4} y={-8.4} width={0.8} height={5.0} fill="#78350f" />
      {/* arms */}
      <rect x={-3.2} y={-7.8} width={0.9} height={3.6} rx={0.3} fill="#fcd34d" />
      <rect x={2.3} y={-7.8} width={0.9} height={3.6} rx={0.3} fill="#fcd34d" />
      {/* head */}
      <circle cx={0} cy={-10.4} r={2.2} fill="#fcd34d" />
      {/* eyes */}
      <circle cx={-0.8} cy={-10.4} r={0.3} fill="#0f172a" />
      <circle cx={0.8} cy={-10.4} r={0.3} fill="#0f172a" />
      {/* straw hat — wide brim ellipse + crown */}
      <ellipse cx={0} cy={-12.2} rx={3.8} ry={0.9} fill="#eab308" stroke="#a16207" strokeWidth={0.3} />
      <path d="M -1.8 -12.4 Q 0 -14.4 1.8 -12.4 Z" fill="#facc15" stroke="#a16207" strokeWidth={0.3} />
      <rect x={-1.6} y={-12.6} width={3.2} height={0.4} fill="#a16207" opacity={0.8} />
    </g>
  );
}
