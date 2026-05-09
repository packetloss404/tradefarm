import { useEffect, useState } from "react";

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const res = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!res.ok) {
    throw new Error(`stream cmd ${type} failed: ${res.status}`);
  }
}

export function BroadcastCadenceSection(props: {
  rotationSec: number | null;
  layoutMode: "scenes" | "v1-broadcast" | null;
  isOnline: boolean;
}) {
  const { rotationSec, layoutMode, isOnline } = props;

  const [localSec, setLocalSec] = useState(30);
  const [hydrated, setHydrated] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Hydrate local state from the first non-null heartbeat. After that, the
  // slider is authoritative.
  useEffect(() => {
    if (hydrated) return;
    if (rotationSec !== null) {
      const clamped = Math.max(0, Math.min(180, Math.round(rotationSec)));
      // Snap to nearest step of 5.
      setLocalSec(Math.round(clamped / 5) * 5);
      setHydrated(true);
    }
  }, [hydrated, rotationSec]);

  // Native range inputs fire `change` on release — perfect for non-chatty POST.
  const onCommit = async (sec: number) => {
    setErr(null);
    try {
      await postCmd("stream_cadence", { sec });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    }
  };

  const disabled = !isOnline;
  const dimmed = layoutMode === "v1-broadcast";
  const display = localSec === 0 ? "off (Hero)" : `${localSec}s`;

  return (
    <div className={`space-y-3 ${dimmed ? "opacity-60" : ""}`}>
      <div className="space-y-1">
        <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider text-zinc-500">
          <span>Rotation cadence</span>
          <span className="font-mono text-zinc-300 tabular-nums">{display}</span>
        </div>
        <input
          type="range"
          min={0}
          max={180}
          step={5}
          value={localSec}
          onInput={(e) => setLocalSec(Number((e.target as HTMLInputElement).value))}
          onChange={(e) => {
            const next = Number(e.target.value);
            setLocalSec(next);
            void onCommit(next);
          }}
          disabled={disabled}
          className="w-full accent-emerald-500"
        />
      </div>
      {dimmed && (
        <div className="font-mono text-[10px] text-zinc-500 italic">
          applies to Scenes mode only
        </div>
      )}
      {err && <div className="font-mono text-[10px] text-(--color-loss)">error: {err}</div>}
    </div>
  );
}
