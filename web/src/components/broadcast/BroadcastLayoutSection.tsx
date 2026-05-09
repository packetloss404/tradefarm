import { useEffect, useState } from "react";

type LayoutMode = "scenes" | "v1-broadcast";

const LAYOUTS: { id: LayoutMode; label: string; activeClass: string }[] = [
  {
    id: "scenes",
    label: "Scenes",
    activeClass:
      "border-(--color-profit) bg-(--color-profit)/15 text-(--color-profit)",
  },
  {
    id: "v1-broadcast",
    label: "V1 Broadcast",
    activeClass: "border-amber-400 bg-amber-400/15 text-amber-300",
  },
];

async function postCmd(
  type: string,
  payload: Record<string, unknown>,
): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export function BroadcastLayoutSection(props: {
  layoutMode: LayoutMode | null;
  isOnline: boolean;
}) {
  const { layoutMode, isOnline } = props;
  // Optimistic pending value — heartbeat is the source of truth, but it
  // round-trips every ~5s (and switching layouts forces a stream reload),
  // so we render the pending choice until the wire catches up.
  const [pendingMode, setPendingMode] = useState<LayoutMode | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (pendingMode !== null && layoutMode === pendingMode) {
      setPendingMode(null);
    }
  }, [layoutMode, pendingMode]);

  const effectiveMode = pendingMode ?? layoutMode;
  const syncing = pendingMode !== null && pendingMode !== layoutMode;

  const onPick = async (mode: LayoutMode) => {
    if (busy || !isOnline) return;
    setPendingMode(mode);
    setBusy(true);
    try {
      await postCmd("stream_layout", { mode });
    } catch {
      // On failure, drop the optimistic value so the UI reflects the wire.
      setPendingMode(null);
    } finally {
      setBusy(false);
    }
  };

  const statusText =
    layoutMode === null
      ? "—"
      : syncing
        ? "syncing…"
        : effectiveMode === "scenes"
          ? "on"
          : effectiveMode === "v1-broadcast"
            ? "on"
            : "off";

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          Layout
        </div>
        <span className="font-mono text-[10px] text-zinc-500">
          {statusText}
        </span>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {LAYOUTS.map((l) => {
          const active = effectiveMode === l.id;
          return (
            <button
              key={l.id}
              onClick={() => void onPick(l.id)}
              disabled={!isOnline || busy}
              className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                active
                  ? l.activeClass
                  : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
              }`}
            >
              {l.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
