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

export function BroadcastAudioSection(props: {
  audioEnabled: boolean | null;
  volume: number | null;
  isOnline: boolean;
}) {
  const { audioEnabled, volume, isOnline } = props;

  const [localEnabled, setLocalEnabled] = useState(false);
  const [localVolume, setLocalVolume] = useState(70);
  const [hydrated, setHydrated] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Hydrate local state from the first non-null heartbeat. After that, the
  // local slider is authoritative — heartbeat changes don't override edits.
  useEffect(() => {
    if (hydrated) return;
    if (audioEnabled !== null && volume !== null) {
      setLocalEnabled(audioEnabled);
      setLocalVolume(Math.round(volume * 100));
      setHydrated(true);
    }
  }, [hydrated, audioEnabled, volume]);

  const onApply = async () => {
    setBusy(true);
    setErr(null);
    try {
      await postCmd("stream_audio", {
        enabled: localEnabled,
        volume: localVolume / 100,
      });
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const disabled = !isOnline;

  const streamLabel = (() => {
    if (audioEnabled === null || volume === null) return "stream: —";
    return `stream: ${audioEnabled ? "on" : "off"} · ${Math.round(volume * 100)}%`;
  })();

  return (
    <div className="space-y-3">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">Audio</div>
      <label className="flex items-center gap-2 text-xs text-zinc-300">
        <input
          type="checkbox"
          checked={localEnabled}
          onChange={(e) => setLocalEnabled(e.target.checked)}
          disabled={disabled}
          className="size-3.5 accent-emerald-500"
        />
        Enabled
      </label>
      <div className="space-y-1">
        <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider text-zinc-500">
          <span>Volume</span>
          <span className="font-mono text-zinc-300 tabular-nums">{localVolume}%</span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={localVolume}
          onChange={(e) => setLocalVolume(Number(e.target.value))}
          disabled={disabled}
          className="w-full accent-emerald-500"
        />
      </div>
      <button
        onClick={onApply}
        disabled={disabled || busy}
        className="w-full rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
      >
        {busy ? "applying…" : "Apply audio"}
      </button>
      <div className="font-mono text-[10px] text-zinc-500">{streamLabel}</div>
      {err && <div className="font-mono text-[10px] text-(--color-loss)">error: {err}</div>}
    </div>
  );
}
