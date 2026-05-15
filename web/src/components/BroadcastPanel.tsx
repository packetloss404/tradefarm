import { useState } from "react";
import useSWR from "swr";
import { Panel } from "./Panel";
import { useStreamState } from "../hooks/useStreamState";
import { api, type AgentRow } from "../api";
import { BroadcastLayoutSection } from "./broadcast/BroadcastLayoutSection";
import { BroadcastSceneSection } from "./broadcast/BroadcastSceneSection";
import { BroadcastAudioSection } from "./broadcast/BroadcastAudioSection";
import { BroadcastCrtSection } from "./broadcast/BroadcastCrtSection";
import { BroadcastCadenceSection } from "./broadcast/BroadcastCadenceSection";
import { BroadcastFullscreenSection } from "./broadcast/BroadcastFullscreenSection";
import { BroadcastMacrosSection } from "./broadcast/BroadcastMacrosSection";
import { BroadcastSpotlightSection } from "./broadcast/BroadcastSpotlightSection";
import { PreviewPopoutButton } from "./broadcast/PreviewPopoutButton";

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

function layoutShort(mode: "scenes" | "v1-broadcast" | null): string {
  if (mode === "scenes") return "scenes";
  if (mode === "v1-broadcast") return "v1";
  return "—";
}

export function BroadcastPanel() {
  const ss = useStreamState();

  // Banner composer state. Stays inline because it doesn't share the
  // optimistic / heartbeat-hydrated patterns the dedicated sections use.
  const [bannerTitle, setBannerTitle] = useState("");
  const [bannerSubtitle, setBannerSubtitle] = useState("");
  const [bannerTtl, setBannerTtl] = useState(8);
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");

  // Agent roster — already fetched elsewhere; shared SWR cache resolves the
  // pinned agent's name for the status header without a second request.
  const { data: agents } = useSWR<AgentRow[]>("agents", api.agents);
  const pinnedAgent =
    ss.pinAgentId != null && agents ? agents.find((a) => a.id === ss.pinAgentId) ?? null : null;

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

  const pinLabel =
    ss.pinAgentId == null
      ? null
      : pinnedAgent
        ? `pin: #${ss.pinAgentId} ${pinnedAgent.name}`
        : `pin: #${ss.pinAgentId}`;

  const liveness = (
    <div className="flex items-center gap-2 font-mono text-[10px] text-zinc-500">
      <PreviewPopoutButton />
      <span className="text-zinc-700">|</span>
      <span className={onlineDotClass} />
      <span className={onlineLabelClass}>{onlineLabel}</span>
      <span className="text-zinc-600">·</span>
      <span>scene: {ss.scene ?? "—"}</span>
      <span className="text-zinc-600">·</span>
      <span>layout: {layoutShort(ss.layoutMode)}</span>
      {pinLabel && (
        <>
          <span className="text-zinc-600">·</span>
          <span className="font-semibold text-(--color-profit)">{pinLabel}</span>
        </>
      )}
      <span className="text-zinc-600">·</span>
      <span>{ageLabel(ss.lastSeenAt)}</span>
    </div>
  );

  return (
    <Panel title="Broadcast" right={liveness}>
      <div className="grid grid-cols-12 gap-x-6 gap-y-4">
        {/* ─────────────────────────────────────────────────────────────────
            DIRECTOR (left, ~3/4): high-frequency live controls. This is what
            the operator's eye lives in during a stream — macros to fire
            moments, spotlight to pin a story, scene/banner for ad-hoc
            overrides.
            ───────────────────────────────────────────────────────────────── */}
        <div className="col-span-12 lg:col-span-9 space-y-4">
          <div>
            <SectionLabel>Macros</SectionLabel>
            <BroadcastMacrosSection isOnline={ss.isOnline} />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastSpotlightSection
              isOnline={ss.isOnline}
              pinAgentId={ss.pinAgentId}
              scene={ss.scene}
              layoutMode={ss.layoutMode}
            />
          </div>

          <div className="grid grid-cols-12 gap-4 border-t border-zinc-800 pt-4">
            <div className="col-span-12 md:col-span-5">
              <BroadcastSceneSection
                scene={ss.scene}
                rotationEnabled={ss.rotationEnabled}
                layoutMode={ss.layoutMode}
                isOnline={ss.isOnline}
              />
            </div>

            <div className="col-span-12 md:col-span-7 space-y-2">
              <SectionLabel>Lower-third banner</SectionLabel>
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
                  Send banner
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* ─────────────────────────────────────────────────────────────────
            SHOW SETTINGS (right rail, ~1/4): low-frequency configuration.
            Layout, audio, cadence, CRT, window, pre-roll. Touched once at
            the start of a session and then left alone.
            ───────────────────────────────────────────────────────────────── */}
        <div className="col-span-12 lg:col-span-3 lg:border-l lg:border-zinc-800 lg:pl-6 space-y-4">
          <BroadcastLayoutSection layoutMode={ss.layoutMode} isOnline={ss.isOnline} />

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastAudioSection
              audioEnabled={ss.audioEnabled}
              volume={ss.volume}
              isOnline={ss.isOnline}
            />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastCadenceSection
              rotationSec={ss.rotationSec}
              layoutMode={ss.layoutMode}
              isOnline={ss.isOnline}
            />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastCrtSection crtEnabled={ss.crtEnabled} isOnline={ss.isOnline} />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastFullscreenSection fullscreen={ss.fullscreen} isOnline={ss.isOnline} />
          </div>

          <div className="border-t border-zinc-800 pt-4 space-y-2">
            <SectionLabel>Pre-roll</SectionLabel>
            <button
              onClick={onPreroll}
              disabled={busy === "preroll"}
              className="w-full rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
            >
              Replay pre-roll opener
            </button>
          </div>
        </div>

        {err && (
          <div className="col-span-12 font-mono text-xs text-(--color-loss)">error: {err}</div>
        )}
      </div>
    </Panel>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-2 text-[10px] uppercase tracking-wider text-zinc-500">
      {children}
    </div>
  );
}
