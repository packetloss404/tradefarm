import { useTickCountdown } from "../hooks/useTickCountdown";

const SIZE = 40;
const STROKE = 4;
const RADIUS = (SIZE - STROKE) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const SOON_THRESHOLD_SEC = 60;

type Props = { lastTickIso: string | null };

function fmtMmSs(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function TickCountdownRing({ lastTickIso }: Props) {
  const { secsToNext, intervalSec, progress } = useTickCountdown(lastTickIso);

  if (intervalSec <= 0) {
    return (
      <div
        className="flex items-center justify-center font-mono text-[9px] text-zinc-600"
        style={{ width: SIZE, height: SIZE }}
        title="Auto-tick disabled"
      >
        OFF
      </div>
    );
  }

  const stroke = secsToNext <= SOON_THRESHOLD_SEC ? "var(--color-profit)" : "#f59e0b";
  const dashOffset = CIRCUMFERENCE * (1 - progress);

  return (
    <div className="relative" style={{ width: SIZE, height: SIZE }} title={`Next tick in ${secsToNext}s`}>
      <svg width={SIZE} height={SIZE} className="-rotate-90">
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke="rgba(63,63,70,0.6)"
          strokeWidth={STROKE}
          fill="none"
        />
        <circle
          cx={SIZE / 2}
          cy={SIZE / 2}
          r={RADIUS}
          stroke={stroke}
          strokeWidth={STROKE}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={CIRCUMFERENCE}
          strokeDashoffset={dashOffset}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[10px] tabular-nums text-zinc-300">
        {fmtMmSs(secsToNext)}
      </div>
    </div>
  );
}
