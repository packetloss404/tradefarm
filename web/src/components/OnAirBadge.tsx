import { useStreamState } from "../hooks/useStreamState";

export function OnAirBadge() {
  const { isOnline } = useStreamState();
  if (isOnline) {
    return (
      <span
        className="inline-flex items-center gap-1 rounded-full border border-rose-700/40 bg-rose-900/40 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-rose-300"
        title="Broadcast app is connected"
      >
        <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-rose-400" />
        ON AIR
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full border border-zinc-700/50 bg-zinc-800/60 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-zinc-500"
      title="Broadcast app not connected"
    >
      <span className="inline-block h-1.5 w-1.5 rounded-full bg-zinc-600" />
      OFFLINE
    </span>
  );
}
