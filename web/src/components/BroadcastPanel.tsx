import { useState } from "react";
import { Panel } from "./Panel";
import { useStreamState } from "../hooks/useStreamState";
import { BroadcastLayoutSection } from "./broadcast/BroadcastLayoutSection";
import { BroadcastSceneSection } from "./broadcast/BroadcastSceneSection";
import { BroadcastAudioSection } from "./broadcast/BroadcastAudioSection";
import { BroadcastCrtSection } from "./broadcast/BroadcastCrtSection";
import { BroadcastCadenceSection } from "./broadcast/BroadcastCadenceSection";
import { BroadcastFullscreenSection } from "./broadcast/BroadcastFullscreenSection";

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

  // Banner state stays inline — it's a one-off composer that doesn't share the
  // optimistic / heartbeat-hydrated patterns the other section components use.
  const [bannerTitle, setBannerTitle] = useState("");
  const [bannerSubtitle, setBannerSubtitle] = useState("");
  const [bannerTtl, setBannerTtl] = useState(8);
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

  const onBanner = () =>
    wrap("banner", () =>
      postCmd("stream_banner", {
        title: bannerTitle,
        subtitle: bannerSubtitle,
        ttl_sec: bannerTtl,
      }),
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
      <span>layout: {ss.layoutMode ?? "—"}</span>
      <span className="text-zinc-600">·</span>
      <span>{ageLabel(ss.lastSeenAt)}</span>
    </div>
  );

  return (
    <Panel title="Broadcast" right={liveness}>
      <div className="space-y-4">
        {/* Top row: layout selector — full-width since it gates everything else. */}
        <BroadcastLayoutSection layoutMode={ss.layoutMode} isOnline={ss.isOnline} />

        {/* Main 3-col row: Scene | Banner | Audio. */}
        <div className="grid grid-cols-12 gap-4">
          <div className="col-span-12 md:col-span-5">
            <BroadcastSceneSection
              scene={ss.scene}
              rotationEnabled={ss.rotationEnabled}
              layoutMode={ss.layoutMode}
              isOnline={ss.isOnline}
            />
          </div>

          <div className="col-span-12 md:col-span-4 space-y-3">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">
              Lower-third banner
            </div>
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

          <div className="col-span-12 md:col-span-3">
            <BroadcastAudioSection
              audioEnabled={ss.audioEnabled}
              volume={ss.volume}
              isOnline={ss.isOnline}
            />
          </div>
        </div>

        {/* Bottom row: cadence | CRT | fullscreen | preroll. */}
        <div className="grid grid-cols-12 gap-4 border-t border-zinc-800 pt-3">
          <div className="col-span-12 md:col-span-5">
            <BroadcastCadenceSection
              rotationSec={ss.rotationSec}
              layoutMode={ss.layoutMode}
              isOnline={ss.isOnline}
            />
          </div>
          <div className="col-span-12 md:col-span-3">
            <BroadcastCrtSection crtEnabled={ss.crtEnabled} isOnline={ss.isOnline} />
          </div>
          <div className="col-span-12 md:col-span-2">
            <BroadcastFullscreenSection fullscreen={ss.fullscreen} isOnline={ss.isOnline} />
          </div>
          <div className="col-span-12 md:col-span-2 space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-zinc-500">Pre-roll</div>
            <button
              onClick={onPreroll}
              disabled={busy === "preroll"}
              className="w-full rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
            >
              Replay pre-roll
            </button>
          </div>
        </div>

        {err && (
          <div className="text-xs text-(--color-loss) font-mono">error: {err}</div>
        )}
      </div>
    </Panel>
  );
}
