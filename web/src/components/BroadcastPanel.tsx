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
import { BroadcastRecordingSection } from "./broadcast/BroadcastRecordingSection";
import { PreviewPopoutButton } from "./broadcast/PreviewPopoutButton";
import { AudienceRequestsPanel } from "./AudienceRequestsPanel";
import { OfflineWarning } from "./broadcast/OfflineWarning";
import { LowerThirdBuilder } from "./LowerThirdBuilder";

type RecapPushResult = {
  moment_id: string;
  date: string;
  week_id: string;
  pushed_at: string;
};

async function postRecapPush(): Promise<RecapPushResult> {
  const r = await fetch("/admin/recap/push", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<RecapPushResult>;
}

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
  // 0.16.0 — 4pm recap push toast. Non-null while a "pushed at HH:MM"
  // confirmation is on screen. Auto-clears after a few seconds so the
  // operator can fire again without manual housekeeping.
  const [recapPushToast, setRecapPushToast] = useState<{
    week_id: string;
    pushedAtLabel: string;
  } | null>(null);

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

  // 0.16.0 — push the 4pm recap moment manually. The endpoint
  // publishes the canonical BroadcastMoment and returns the moment
  // id + a timestamp; we surface the timestamp as a brief toast so
  // the operator has visual confirmation that the push went through.
  const onRecapPush = () =>
    wrap("recap-push", async () => {
      const res = await postRecapPush();
      const at = new Date(res.pushed_at);
      const label = Number.isFinite(at.getTime())
        ? at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
        : "now";
      setRecapPushToast({ week_id: res.week_id, pushedAtLabel: label });
      // Auto-clear the toast after 6s so a re-push doesn't need manual cleanup.
      setTimeout(() => setRecapPushToast(null), 6000);
    });

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
      {!ss.isOnline && (
        <div className="mb-4">
          <OfflineWarning />
        </div>
      )}
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
            <BroadcastMacrosSection />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastSpotlightSection
              pinAgentId={ss.pinAgentId}
              scene={ss.scene}
              layoutMode={ss.layoutMode}
            />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <AudienceRequestsPanel />
          </div>

          {/* 0.17.0 — lower-third builder. New ad-hoc push surface
              (color picker, replay list) sitting above the existing
              banner form. The two sections stay side-by-side at md+
              widths so the operator sees both at once. */}
          <div className="border-t border-zinc-800 pt-4">
            <div className="grid grid-cols-12 gap-4">
              <div className="col-span-12 md:col-span-7">
                <LowerThirdBuilder />
              </div>
              <div className="col-span-12 md:col-span-5">
                <BroadcastSceneSection
                  scene={ss.scene}
                  rotationEnabled={ss.rotationEnabled}
                  layoutMode={ss.layoutMode}
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-12 gap-4 border-t border-zinc-800 pt-4">
            <div className="col-span-12 md:col-span-7 space-y-2">
              <SectionLabel>Lower-third banner (legacy)</SectionLabel>
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
          <BroadcastLayoutSection layoutMode={ss.layoutMode} />

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastAudioSection
              audioEnabled={ss.audioEnabled}
              volume={ss.volume}
            />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastCadenceSection
              rotationSec={ss.rotationSec}
              layoutMode={ss.layoutMode}
            />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastCrtSection crtEnabled={ss.crtEnabled} />
          </div>

          <div className="border-t border-zinc-800 pt-4">
            <BroadcastFullscreenSection fullscreen={ss.fullscreen} />
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

          {/* 0.16.0 — manual 4pm recap push. Bypasses the per-day
              idempotency row so operators can re-show the live recap
              during the last few minutes of a stream (the auto-fired
              one may have missed an earlier-in-the-day restart).
              Matches the panel's button style; uses the same `wrap`
              helper as the banner / pre-roll buttons. */}
          <div className="border-t border-zinc-800 pt-4 space-y-2">
            <SectionLabel>4pm recap</SectionLabel>
            <button
              onClick={onRecapPush}
              disabled={busy === "recap-push"}
              className="w-full rounded-sm border border-emerald-700/60 bg-emerald-900/20 px-3 py-1.5 text-xs font-medium text-emerald-100 hover:bg-emerald-900/40 disabled:opacity-50"
            >
              {busy === "recap-push" ? "Pushing..." : "Push 4pm recap"}
            </button>
            {recapPushToast && (
              <div className="font-mono text-[10px] text-(--color-profit)">
                pushed {recapPushToast.week_id} at {recapPushToast.pushedAtLabel}
              </div>
            )}
          </div>

          {/* 0.17.0 — WS frame recording. The right rail already
              hosts low-frequency operator controls; the recording
              panel fits the same "touch once, leave it" rhythm.
              Start/stop + on-disk list map to the three admin
              endpoints; the per-recording "Replay" affordance is a
              next-round deliverable (needs a second WS consumer
              that walks the NDJSON). */}
          <div className="border-t border-zinc-800 pt-4">
            <BroadcastRecordingSection />
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
