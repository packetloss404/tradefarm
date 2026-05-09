import { useEffect, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { SceneRotator } from "./scenes/SceneRotator";
import { PreRollScene } from "./scenes/PreRollScene";
import { Broadcast as V1Broadcast } from "./broadcast/v1/Broadcast";
import { AdminOverlay } from "./components/AdminOverlay";
import { useStreamData } from "./hooks/useStreamData";
import { useStreamAudio } from "./hooks/useStreamAudio";
import { useStreamCommands } from "./hooks/useStreamCommands";
import { streamAudio } from "./audio/StreamAudio";
import {
  DEFAULT_SETTINGS,
  loadSettings,
  restBase,
  saveSettings,
  wsTarget,
  type StreamSettings,
} from "./settings";
import { setBackendBase } from "./shared/api";

const IDLE_MS = 3_000;

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function setFullscreen(on: boolean): Promise<void> {
  if (!inTauri()) return;
  try {
    const mod = await import("@tauri-apps/api/window");
    const win = mod.getCurrentWindow();
    await win.setFullscreen(on);
  } catch {
    /* ignore — running in plain browser */
  }
}

export default function App() {
  const [settings, setSettings] = useState<StreamSettings | null>(null);
  const [showAdmin, setShowAdmin] = useState(false);
  const [prerollDone, setPrerollDone] = useState(false);
  const idleTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Load persisted settings once. Also prime the audio context — browsers
  // (and Tauri's webview) require a user gesture to unlock playback, so the
  // engine installs a one-shot pointer/key listener and resumes itself on
  // the first interaction.
  useEffect(() => {
    streamAudio.primeOnUserGesture();
    void (async () => {
      const s = await loadSettings();
      setBackendBase(restBase(s));
      setSettings(s);
      if (s.fullscreen) void setFullscreen(true);
    })();
  }, []);

  // CRT toggle is applied below from the resolved override-aware value so
  // dashboard-pushed `stream_crt` events take effect without a settings save.

  // Cursor-hide-on-idle for a clean stream capture.
  useEffect(() => {
    const reset = () => {
      document.body.classList.remove("idle");
      if (idleTimer.current) clearTimeout(idleTimer.current);
      idleTimer.current = setTimeout(() => document.body.classList.add("idle"), IDLE_MS);
    };
    reset();
    window.addEventListener("mousemove", reset);
    window.addEventListener("keydown", reset);
    return () => {
      window.removeEventListener("mousemove", reset);
      window.removeEventListener("keydown", reset);
      if (idleTimer.current) clearTimeout(idleTimer.current);
    };
  }, []);

  // Keyboard shortcuts: Ctrl+I admin, F11 fullscreen, Esc close overlay.
  useEffect(() => {
    const onKey = async (e: KeyboardEvent) => {
      if (e.ctrlKey && (e.key === "i" || e.key === "I")) {
        e.preventDefault();
        setShowAdmin((v) => !v);
      } else if (e.key === "F11") {
        e.preventDefault();
        if (inTauri()) {
          try {
            const mod = await import("@tauri-apps/api/window");
            const win = mod.getCurrentWindow();
            const cur = await win.isFullscreen();
            await win.setFullscreen(!cur);
          } catch {
            /* ignore */
          }
        }
      } else if (e.key === "Escape" && showAdmin) {
        setShowAdmin(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [showAdmin]);

  // Use a synchronously-resolvable WS URL on first render so the WebSocket
  // doesn't connect to the Tauri custom-protocol host before settings load.
  const wsUrl = wsTarget(settings ?? DEFAULT_SETTINGS);
  const snapshot = useStreamData(wsUrl);

  // Live event → Web Audio: kick on tick, note on fill, stinger on
  // promotion. Hook is safe to mount with default settings; it just won't
  // play until the first user gesture resumes the AudioContext.
  useStreamAudio({
    snapshot,
    enabled: settings?.audioEnabled ?? DEFAULT_SETTINGS.audioEnabled,
    volume: settings?.audioVolume ?? DEFAULT_SETTINGS.audioVolume,
  });

  const showPrerollGate = !prerollDone && (settings?.prerollDurationSec ?? 0) > 0;
  // The hook owns the dashboard-pushed override; we feed the persisted
  // setting in and read back the resolved effective value. Override is
  // ephemeral (lost on stream restart), matching the stream_audio pattern.
  const cmds = useStreamCommands({
    wsUrlOverride: wsUrl,
    currentScene: showPrerollGate ? "preroll" : "rotator",
    audioEnabled: settings?.audioEnabled ?? DEFAULT_SETTINGS.audioEnabled,
    audioVolume: settings?.audioVolume ?? DEFAULT_SETTINGS.audioVolume,
    fullscreen: settings?.fullscreen ?? DEFAULT_SETTINGS.fullscreen,
    rotationEnabledFromSettings: settings?.rotationEnabled ?? DEFAULT_SETTINGS.rotationEnabled,
    crtEnabledFromSettings: settings?.crtEnabled ?? DEFAULT_SETTINGS.crtEnabled,
    rotationSecFromSettings: settings?.sceneRotationSec ?? DEFAULT_SETTINGS.sceneRotationSec,
    layoutMode: settings?.layoutMode ?? DEFAULT_SETTINGS.layoutMode,
    onPreroll: () => setPrerollDone(false),
    onLayoutChange: (mode) => {
      // Layout swap requires a fresh component tree (V1 ↔ Scenes have wildly
      // different roots). Persist the new mode then full-reload.
      const cur = settings;
      if (!cur || cur.layoutMode === mode) return;
      void (async () => {
        await saveSettings({ ...cur, layoutMode: mode });
        location.reload();
      })();
    },
    onFullscreenChange: (enabled) => {
      void setFullscreen(enabled);
    },
  });

  // Apply the resolved CRT state (override + persisted) every render. Toggling
  // a body class is idempotent; React 19's `useEffect` cleanup isn't needed here.
  useEffect(() => {
    document.body.classList.toggle("crt-on", cmds.crtEnabled);
    return () => document.body.classList.remove("crt-on");
  }, [cmds.crtEnabled]);

  if (!settings) {
    return (
      <div className="h-full w-full flex items-center justify-center text-zinc-500 font-mono">
        Loading settings…
      </div>
    );
  }

  const showPreroll = !prerollDone && settings.prerollDurationSec > 0;

  // Layout selector: V1 broadcast frame OR the legacy scene rotator. Pre-roll
  // is honored in both modes so the launch splash still plays. The two layouts
  // are mutually exclusive — a settings change triggers location.reload() in
  // the AdminOverlay save flow, so we don't need cross-fade gymnastics here.
  const broadcastMode = settings.layoutMode === "v1-broadcast";

  return (
    <>
      <AnimatePresence mode="wait">
        {showPreroll ? (
          <PreRollScene
            key="preroll"
            snapshot={snapshot}
            durationSec={settings.prerollDurationSec}
            onComplete={() => setPrerollDone(true)}
          />
        ) : broadcastMode ? (
          <V1Broadcast key="v1-broadcast" snapshot={snapshot} />
        ) : (
          <SceneRotator
            key="rotator"
            snapshot={snapshot}
            rotationSec={cmds.rotationEnabled ? cmds.rotationSec : 0}
            paused={showAdmin}
            commentaryEnabled={settings.commentaryEnabled}
            tickerSpeedPxPerSec={settings.tickerSpeedPxPerSec}
            forceSceneId={cmds.forceSceneId}
            banner={cmds.banner}
          />
        )}
      </AnimatePresence>
      {showAdmin && (
        <AdminOverlay initial={settings} onClose={() => setShowAdmin(false)} />
      )}
    </>
  );
}
