import { useEffect, useState } from "react";

const SCENES: { id: string; label: string; hint?: string }[] = [
  { id: "hero", label: "Hero" },
  { id: "leaderboard", label: "Leaderboard" },
  { id: "showdown", label: "Showdown" },
  { id: "brain", label: "Brain" },
  { id: "strategy", label: "Strategy" },
  { id: "recap", label: "Recap", hint: "after 4pm ET" },
];

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export function BroadcastSceneSection(props: {
  scene: string | null;
  rotationEnabled: boolean | null;
  layoutMode: "scenes" | "v1-broadcast" | null;
  isOnline: boolean;
}) {
  const { scene, rotationEnabled, layoutMode, isOnline } = props;
  const inert = layoutMode === "v1-broadcast";

  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");

  // Optimistic auto-rotate flag — heartbeat is the source of truth, but
  // it round-trips every ~5s so we render a pending value until the wire
  // catches up to avoid the toggle "snapping back" on click.
  const [pendingRotation, setPendingRotation] = useState<boolean | null>(null);
  useEffect(() => {
    if (pendingRotation !== null && rotationEnabled === pendingRotation) {
      setPendingRotation(null);
    }
  }, [rotationEnabled, pendingRotation]);
  const rotationOn = pendingRotation ?? rotationEnabled ?? false;

  // Optimistic scene — same idea: override incoming heartbeat until convergence.
  const [pendingScene, setPendingScene] = useState<string | null>(null);
  useEffect(() => {
    if (pendingScene !== null && scene === pendingScene) {
      setPendingScene(null);
    }
  }, [scene, pendingScene]);
  const activeScene = pendingScene ?? scene;

  const wrap = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const onScene = (id: string) => {
    setPendingScene(id);
    void wrap(`scene:${id}`, () => postCmd("stream_scene", { scene_id: id }));
  };

  const onRotation = (next: boolean) => {
    setPendingRotation(next);
    void wrap("rotation", () => postCmd("stream_rotation", { enabled: next }));
  };

  const rotationLabel =
    rotationEnabled === null
      ? "—"
      : pendingRotation !== null && pendingRotation !== rotationEnabled
        ? "syncing…"
        : rotationOn
          ? "on"
          : "off";

  return (
    <div className={`space-y-3 ${inert ? "opacity-50 pointer-events-none" : ""}`}>
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Scene</div>
        <label className="flex items-center gap-2 text-xs text-zinc-300">
          <input
            type="checkbox"
            checked={rotationOn}
            disabled={!isOnline || busy === "rotation" || inert}
            onChange={(e) => onRotation(e.target.checked)}
            className="size-3.5 accent-emerald-500"
          />
          <span>Auto-rotate</span>
          <span className="font-mono text-[10px] text-zinc-500">{rotationLabel}</span>
        </label>
      </div>

      {inert && (
        <div className="text-[10px] font-mono text-zinc-500 italic">
          stream is in V1 Broadcast — scene controls don&apos;t apply
        </div>
      )}

      <div className="flex flex-wrap gap-1.5">
        {SCENES.map((s) => {
          const active = activeScene === s.id;
          const pending = busy === `scene:${s.id}`;
          return (
            <button
              key={s.id}
              onClick={() => onScene(s.id)}
              disabled={!isOnline || pending || inert}
              className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                active
                  ? "border-(--color-profit) bg-(--color-profit)/15 text-(--color-profit)"
                  : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
              }`}
            >
              <div className="flex flex-col items-center leading-tight">
                <span>{s.label}</span>
                {s.hint && (
                  <span className="text-[9px] text-zinc-500 font-normal normal-case">
                    {s.hint}
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>

      {err && (
        <div className="text-xs text-(--color-loss) font-mono">error: {err}</div>
      )}
    </div>
  );
}
