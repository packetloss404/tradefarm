import { useMarketClock, type MarketPhase } from "../hooks/useMarketClock";

const TONE: Record<MarketPhase, string> = {
  rth: "border-emerald-700/40 bg-emerald-900/30 text-emerald-300",
  premarket: "border-sky-700/40 bg-sky-900/30 text-sky-300",
  afterhours: "border-amber-700/40 bg-amber-900/30 text-amber-300",
  closed: "border-zinc-700/50 bg-zinc-800/60 text-zinc-300",
  unknown: "border-zinc-700/50 bg-zinc-800/60 text-zinc-500",
};

function formatOpensWeekday(iso: string | null): string {
  if (iso === null) return "—";
  const d = new Date(iso);
  const wd = d.toLocaleString("en-US", { weekday: "short", timeZone: "America/New_York" });
  const t = d.toLocaleString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  });
  return `${wd} ${t} ET`;
}

export function MarketClockBadge() {
  const { phase, openCountdown, closeCountdown, opensAtIso } = useMarketClock();

  let label: string;
  switch (phase) {
    case "rth":
      label = `OPEN · closes in ${closeCountdown}`;
      break;
    case "premarket":
      label = `PREMARKET · opens in ${openCountdown}`;
      break;
    case "afterhours":
      label = `AFTERHOURS · opens ${formatOpensWeekday(opensAtIso)}`;
      break;
    case "closed":
      label = `CLOSED · opens ${formatOpensWeekday(opensAtIso)}`;
      break;
    default:
      label = "MARKET …";
  }

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${TONE[phase]}`}
      title="NYSE market session (XNYS calendar)"
    >
      {label}
    </span>
  );
}
