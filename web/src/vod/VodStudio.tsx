// Top-level VOD Studio shell. The original design lives on a pan/zoom
// design canvas with four artboards side-by-side — that's a design-tool
// pattern, not an operator workflow. For the real app the operator
// looks at one surface at a time, so we use a tab nav instead. The four
// surfaces themselves are pixel-faithful to the prototype.

import { useEffect, useState } from "react";
import { T } from "./tokens";
import { useVodMock } from "./useVodMock";
import { useVodLiveData } from "./data.live";
import { BeatPicker } from "./BeatPicker";
import { PipelineBoard } from "./PipelineBoard";
import { SessionControl } from "./SessionControl";
import { EpisodePage } from "./EpisodePage";

// Data-source toggle: applies to ALL surfaces (BeatPicker, Pipeline,
// Session, Episode) when set to "live". The previous behaviour
// limited the toggle to Session Control only; the new useVodLiveData
// hook serves every surface.
//
// Falls back to the prototype mock on any backend error so a flapping
// API never blocks the operator from the studio.
const LIVE_PREF_KEY = "vod-studio.session-live";

function loadLivePref(): boolean {
  try {
    return window.localStorage.getItem(LIVE_PREF_KEY) === "1";
  } catch {
    return false;
  }
}

function saveLivePref(v: boolean) {
  try {
    window.localStorage.setItem(LIVE_PREF_KEY, v ? "1" : "0");
  } catch {
    /* ignore — private mode etc */
  }
}

type SurfaceId = "beats" | "pipeline" | "session" | "episode";

const SURFACES: { id: SurfaceId; label: string; sub: string }[] = [
  { id: "beats", label: "Beat picker", sub: "the keystone" },
  { id: "pipeline", label: "Pipeline status", sub: "10 subsystems" },
  { id: "session", label: "Session control", sub: "let it run" },
  { id: "episode", label: "Episode review", sub: "ready to publish" },
];

// Read the active tab from the URL hash, e.g. #vod-studio/beats. The
// chrome lets the operator deep-link to a specific surface and reload
// without losing place.
function tabFromHash(): SurfaceId {
  const m = window.location.hash.match(/^#vod-studio\/(\w+)/);
  const raw = m?.[1];
  if (raw === "beats" || raw === "pipeline" || raw === "session" || raw === "episode") {
    return raw;
  }
  return "beats";
}

function TabButton({
  surface,
  active,
  onClick,
}: {
  surface: (typeof SURFACES)[number];
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        background: active ? T.panel2 : "transparent",
        border: `1px solid ${active ? T.borderHi : "transparent"}`,
        color: active ? T.text : T.text2,
        padding: "8px 14px",
        borderRadius: 6,
        cursor: "pointer",
        textAlign: "left",
        display: "flex",
        flexDirection: "column",
        minWidth: 0,
        fontFamily: T.font,
        transition: "background 120ms, border-color 120ms, color 120ms",
      }}
    >
      <span style={{ fontSize: 13, fontWeight: 600, letterSpacing: -0.2 }}>{surface.label}</span>
      <span
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: 1.4,
          color: T.text3,
          marginTop: 2,
        }}
      >
        {surface.sub}
      </span>
    </button>
  );
}

export default function VodStudio() {
  const vod = useVodMock();
  // Always subscribe so the toggle doesn't race a cold cache and the
  // SWR/WS state stays warm. Cheap when no consumer is mounted.
  // `useVodLiveData` is the new all-surfaces live source. We pass no
  // sessionId so it uses today's synthetic live session id; the
  // EpisodePage will deep-link the operator to a real session once
  // /sessions/current is wired.
  const live = useVodLiveData();
  const [active, setActive] = useState<SurfaceId>(() => tabFromHash());
  const [useLive, setUseLive] = useState<boolean>(() => loadLivePref());

  useEffect(() => {
    const onHash = () => setActive(tabFromHash());
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const setSurface = (id: SurfaceId) => {
    setActive(id);
    // pushing into the hash keeps reloads and copy-paste links honest
    window.history.replaceState(null, "", `#vod-studio/${id}`);
  };

  const toggleLive = () => {
    setUseLive((v) => {
      const next = !v;
      saveLivePref(next);
      return next;
    });
  };

  // Pick the right data source per surface. The `live` hook falls back
  // to the mock on backend errors, so even when the pill says "live"
  // a flapping API still shows a coherent studio.
  const data = useLive ? live : vod;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: T.bg,
        color: T.text,
        fontFamily: T.font,
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 18,
          padding: "12px 20px",
          borderBottom: `1px solid ${T.border}`,
          background: T.panel,
          flexShrink: 0,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: T.text, letterSpacing: -0.3 }}>
            tradefarm
          </span>
          <span style={{ color: T.text3, fontSize: 14 }}>·</span>
          <span style={{ fontFamily: T.mono, fontSize: 12, color: T.text2, letterSpacing: 1 }}>
            VOD studio
          </span>
        </div>
        <div style={{ width: 1, height: 22, background: T.border }} />
        <div style={{ display: "flex", gap: 6, flex: 1, minWidth: 0 }}>
          {SURFACES.map((s) => (
            <TabButton
              key={s.id}
              surface={s}
              active={active === s.id}
              onClick={() => setSurface(s.id)}
            />
          ))}
        </div>
        <button
          onClick={toggleLive}
          title={
            useLive
              ? "Live: reading from /api/agents, /api/account, /api/pnl/daily and the session's manifest + beats."
              : "Mock: using the prototype's 3-strategy / 1-day fixture. Flip to live to read from the backend."
          }
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            color: useLive ? T.ok : T.text2,
            background: useLive ? `${T.ok}18` : "transparent",
            border: `1px solid ${useLive ? T.ok : T.border}`,
            padding: "6px 10px",
            borderRadius: 4,
            cursor: "pointer",
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span
            className={useLive ? "vod-pulse-dot" : undefined}
            style={{
              display: "inline-block",
              width: 6,
              height: 6,
              borderRadius: 999,
              background: useLive ? T.ok : T.text3,
            }}
          />
          {useLive ? "live" : "mock"}
        </button>
        <a
          href="#"
          onClick={(e) => {
            e.preventDefault();
            window.location.hash = "";
            window.location.reload();
          }}
          style={{
            fontFamily: T.mono,
            fontSize: 11,
            color: T.text2,
            textDecoration: "none",
            padding: "6px 10px",
            border: `1px solid ${T.border}`,
            borderRadius: 4,
          }}
          title="Return to the live dashboard"
        >
          ← dashboard
        </a>
      </div>
      <div style={{ flex: 1, minHeight: 0, position: "relative" }}>
        {active === "beats" && <BeatPicker vod={data} />}
        {active === "pipeline" && <PipelineBoard vod={data} />}
        {active === "session" && <SessionControl vod={data} />}
        {active === "episode" && <EpisodePage vod={data} />}
      </div>
    </div>
  );
}
