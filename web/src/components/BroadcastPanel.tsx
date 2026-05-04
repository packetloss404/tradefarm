import { useState } from "react";
import { Panel } from "./Panel";
import { useStreamState } from "../hooks/useStreamState";

const SCENES: { id: string; label: string }[] = [
  { id: "hero", label: "Hero" },
  { id: "leaderboard", label: "Leaderboard" },
  { id: "brain", label: "Brain" },
  { id: "strategy", label: "Strategy" },
  { id: "recap", label: "Recap" },
];

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

function ageLabel(ts: number | null): string {
  if (!ts) return "no heartbeat yet";
  const sec = Math.max(0, Math.round((Date.now() - ts) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

export function BroadcastPanel() {
  const ss = useStreamState();
  const [bannerTitle, setBannerTitle] = useState("");
  const [bannerSubtitle, setBannerSubtitle] = useState("");
  const [bannerTtl, setBannerTtl] = useState(8);
  const [audioEnabled, setAudioEnabled] = useState(true);
  const [volume, setVolume] = useState(60);
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");

  const wrap = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    setErr("");
    try {
      await fn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const onScene = (id: string) =>
    wrap(`scene:${id}`, () => postCmd("stream_scene", { scene_id: id }));

  const onBanner = () =>
    wrap("banner", () =>
      postCmd("stream_banner", {
        title: bannerTitle,
        subtitle: bannerSubtitle,
        ttl_sec: bannerTtl,
      }),
    );

  const onAudio = () =>
    wrap("audio", () =>
      postCmd("stream_audio", { enabled: audioEnabled, volume: volume / 100 }),
    );

  const onPreroll = () => wrap("preroll", () => postCmd("stream_preroll", {}));

  const onlineDotClass = ss.isOnline
    ? "size-2 rounded-full bg-(--color-profit) animate-pulse"
    : "size-2 rounded-full bg-zinc-600";
  const onlineLabel = ss.isOnline ? "ON AIR" : "OFFLINE";
  const onlineLabelClass = ss.isOnline
    ? "text-[10px] font-bold uppercase tracking-wider text-(--color-profit)"
    : "text-[10px] font-bold uppercase tracking-wider text-zinc-500";

  const liveness = (
    <div className="flex items-center gap-2 font-mono text-[10px] text-zinc-500">
      <span className={onlineDotClass} />
      <span className={onlineLabelClass}>{onlineLabel}</span>
      <span className="text-zinc-600">·</span>
      <span>scene: {ss.scene ?? "—"}</span>
      <span className="text-zinc-600">·</span>
      <span>{ageLabel(ss.lastSeenAt)}</span>
    </div>
  );

  return (
    <Panel title="Broadcast" right={liveness}>
      <div className="grid grid-cols-12 gap-4">
        <div className="col-span-12 md:col-span-5 space-y-3">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">Scene</div>
          <div className="flex flex-wrap gap-1.5">
            {SCENES.map((s) => {
              const active = ss.scene === s.id;
              return (
                <button
                  key={s.id}
                  onClick={() => onScene(s.id)}
                  disabled={busy === `scene:${s.id}`}
                  className={`rounded-sm border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 ${
                    active
                      ? "border-(--color-profit) bg-(--color-profit)/15 text-(--color-profit)"
                      : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
                  }`}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
          <div className="border-t border-zinc-800 pt-3">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500 mb-2">Pre-roll</div>
            <button
              onClick={onPreroll}
              disabled={busy === "preroll"}
              className="rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
            >
              Replay pre-roll
            </button>
          </div>
        </div>

        <div className="col-span-12 md:col-span-4 space-y-3">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">Lower-third banner</div>
          <input
            type="text"
            placeholder="Title"
            value={bannerTitle}
            onChange={(e) => setBannerTitle(e.target.value)}
            className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
          />
          <input
            type="text"
            placeholder="Subtitle"
            value={bannerSubtitle}
            onChange={(e) => setBannerSubtitle(e.target.value)}
            className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
          />
          <div className="flex items-center gap-2">
            <label className="text-[10px] uppercase tracking-wider text-zinc-500">TTL</label>
            <input
              type="number"
              min={1}
              max={120}
              value={bannerTtl}
              onChange={(e) => setBannerTtl(Math.max(1, Number(e.target.value) || 1))}
              className="w-16 rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1 text-sm text-zinc-100 font-mono focus:outline-none focus:border-zinc-500"
            />
            <span className="text-[10px] text-zinc-500">sec</span>
            <button
              onClick={onBanner}
              disabled={busy === "banner" || !bannerTitle.trim()}
              className="ml-auto rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
            >
              Send
            </button>
          </div>
        </div>

        <div className="col-span-12 md:col-span-3 space-y-3">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">Audio</div>
          <label className="flex items-center gap-2 text-xs text-zinc-300">
            <input
              type="checkbox"
              checked={audioEnabled}
              onChange={(e) => setAudioEnabled(e.target.checked)}
              className="size-3.5 accent-emerald-500"
            />
            Enabled
          </label>
          <div className="space-y-1">
            <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider text-zinc-500">
              <span>Volume</span>
              <span className="font-mono text-zinc-300 tabular-nums">{volume}%</span>
            </div>
            <input
              type="range"
              min={0}
              max={100}
              value={volume}
              onChange={(e) => setVolume(Number(e.target.value))}
              className="w-full accent-emerald-500"
            />
          </div>
          <button
            onClick={onAudio}
            disabled={busy === "audio"}
            className="w-full rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
          >
            Apply audio
          </button>
        </div>

        {err && (
          <div className="col-span-12 text-xs text-(--color-loss) font-mono">error: {err}</div>
        )}
      </div>
    </Panel>
  );
}
