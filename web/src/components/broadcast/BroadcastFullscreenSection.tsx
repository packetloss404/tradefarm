import { useState } from "react";

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export function BroadcastFullscreenSection(props: {
  fullscreen: boolean | null;
  isOnline: boolean;
}) {
  const { fullscreen, isOnline } = props;
  // Optimistic flag — heartbeat is source of truth but round-trips every 5s,
  // so render a pending value until the wire catches up.
  const [pending, setPending] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const effective = pending !== null ? pending : fullscreen === true;
  const syncing = pending !== null && pending !== fullscreen;

  const label =
    fullscreen === true
      ? "Exit fullscreen"
      : fullscreen === false
        ? "Enter fullscreen"
        : "Toggle fullscreen";

  const statusLabel =
    fullscreen === null && pending === null
      ? "—"
      : syncing
        ? "syncing…"
        : effective
          ? "on"
          : "off";

  const onClick = () => {
    const next = !effective;
    setPending(next);
    setBusy(true);
    void (async () => {
      try {
        await postCmd("stream_fullscreen", { enabled: next });
      } catch {
        // Roll back on failure so the UI doesn't lie.
        setPending(null);
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div className="space-y-2">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">Window</div>
      <div className="flex items-center gap-2">
        <button
          onClick={onClick}
          disabled={!isOnline || busy}
          className="rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
        >
          {label}
        </button>
        <span className="font-mono text-[10px] text-zinc-500">fullscreen: {statusLabel}</span>
      </div>
    </div>
  );
}
