import { useEffect, useRef, useState } from "react";
import { AnimatePresence } from "framer-motion";
import { SceneRotator } from "./scenes/SceneRotator";
import { PreRollScene } from "./scenes/PreRollScene";
import { AdminOverlay } from "./components/AdminOverlay";
import { useStreamData } from "./hooks/useStreamData";
import { useStreamAudio } from "./hooks/useStreamAudio";
import { streamAudio } from "./audio/StreamAudio";
import {
  DEFAULT_SETTINGS,
  loadSettings,
  restBase,
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

  if (!settings) {
    return (
      <div className="h-full w-full flex items-center justify-center text-zinc-500 font-mono">
        Loading settings…
      </div>
    );
  }

  const showPreroll = !prerollDone && settings.prerollDurationSec > 0;

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
        ) : (
          <SceneRotator
            key="rotator"
            snapshot={snapshot}
            rotationSec={settings.sceneRotationSec}
            paused={showAdmin}
            commentaryEnabled={settings.commentaryEnabled}
            tickerSpeedPxPerSec={settings.tickerSpeedPxPerSec}
          />
        )}
      </AnimatePresence>
      {showAdmin && (
        <AdminOverlay initial={settings} onClose={() => setShowAdmin(false)} />
      )}
    </>
  );
}
