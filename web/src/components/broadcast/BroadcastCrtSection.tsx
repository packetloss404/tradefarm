import { useState } from "react";

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export function BroadcastCrtSection(props: {
  crtEnabled: boolean | null;
  isOnline: boolean;
}) {
  const { crtEnabled, isOnline } = props;
  // Optimistic flag — heartbeat is source of truth but round-trips every 5s,
  // so render a pending value until the wire catches up.
  const [pending, setPending] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);

  const effective = pending !== null ? pending : crtEnabled === true;
  const syncing = pending !== null && pending !== crtEnabled;

  const onToggle = (next: boolean) => {
    setPending(next);
    setBusy(true);
    void (async () => {
      try {
        await postCmd("stream_crt", { enabled: next });
      } catch {
        // Roll back on failure so the UI doesn't lie.
        setPending(null);
      } finally {
        setBusy(false);
      }
    })();
  };

  const statusLabel =
    crtEnabled === null && pending === null
      ? "—"
      : syncing
        ? "syncing…"
        : effective
          ? "on"
          : "off";

  return (
    <div className="flex items-baseline justify-between">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">Effects</div>
      <label className="flex items-center gap-2 text-xs text-zinc-300">
        <input
          type="checkbox"
          checked={effective}
          disabled={!isOnline || busy}
          onChange={(e) => onToggle(e.target.checked)}
          className="size-3.5 accent-emerald-500"
        />
        <span>CRT effect (scanlines + chroma + vignette)</span>
        <span className="font-mono text-[10px] text-zinc-500">{statusLabel}</span>
      </label>
    </div>
  );
}
