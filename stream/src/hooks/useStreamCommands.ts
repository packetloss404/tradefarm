import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../shared/api";
import { useLiveEvents, type LiveEvent } from "../shared/useLiveEvents";
import { streamAudio } from "../audio/StreamAudio";

const HEARTBEAT_MS = 5_000;

export type BannerState = {
  title: string;
  subtitle: string;
  ttl_sec: number;
  shown_at: number;
};

export type StreamCommandsHandle = {
  forceSceneId: string | null;
  setForceScene: (id: string | null) => void;
  banner: BannerState | null;
  setBanner: (b: BannerState | null) => void;
};

export type UseStreamCommandsArgs = {
  wsUrlOverride?: string;
  currentScene: string;
  audioEnabled: boolean;
  audioVolume: number;
  fullscreen: boolean;
  onPreroll: () => void;
};

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  await fetch(apiUrl("/api/stream/cmd"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
}

/**
 * Wires the broadcast app to dashboard-driven commands and emits a periodic
 * ``stream_state`` heartbeat so the dashboard can light its "ON AIR"
 * indicator. The hook owns the in-memory force-scene + banner slots; the
 * parent (``App``/``SceneRotator``) is expected to read them and override
 * its rotator/lower-third accordingly.
 */
export function useStreamCommands(args: UseStreamCommandsArgs): StreamCommandsHandle {
  const { currentScene, audioEnabled, audioVolume, fullscreen, onPreroll, wsUrlOverride } = args;

  const [forceSceneId, setForceSceneId] = useState<string | null>(null);
  const [banner, setBanner] = useState<BannerState | null>(null);
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onPrerollRef = useRef(onPreroll);
  onPrerollRef.current = onPreroll;

  const setBannerSafe = useCallback((next: BannerState | null) => {
    if (bannerTimer.current) {
      clearTimeout(bannerTimer.current);
      bannerTimer.current = null;
    }
    setBanner(next);
    if (next) {
      const ttl = Math.max(1, Math.min(120, next.ttl_sec || 8));
      bannerTimer.current = setTimeout(() => setBanner(null), ttl * 1000);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (bannerTimer.current) clearTimeout(bannerTimer.current);
    };
  }, []);

  const handler = useCallback(
    (ev: LiveEvent) => {
      switch (ev.type) {
        case "stream_scene":
          setForceSceneId(ev.payload.scene_id || null);
          break;
        case "stream_banner": {
          const p = ev.payload;
          if (!p.title) {
            setBannerSafe(null);
            break;
          }
          setBannerSafe({
            title: p.title,
            subtitle: p.subtitle ?? "",
            ttl_sec: typeof p.ttl_sec === "number" ? p.ttl_sec : 8,
            shown_at: Date.now(),
          });
          break;
        }
        case "stream_audio":
          streamAudio.setEnabled(ev.payload.enabled);
          streamAudio.setVolume(ev.payload.volume);
          break;
        case "stream_preroll":
          onPrerollRef.current();
          break;
        default:
          break;
      }
    },
    [setBannerSafe],
  );

  useLiveEvents(handler, wsUrlOverride);

  // Heartbeat — separate from the scheduler's tick stream so the dashboard
  // sees liveness even when nothing else is happening.
  const sceneRef = useRef(currentScene);
  sceneRef.current = currentScene;
  const audioEnabledRef = useRef(audioEnabled);
  audioEnabledRef.current = audioEnabled;
  const volumeRef = useRef(audioVolume);
  volumeRef.current = audioVolume;
  const fullscreenRef = useRef(fullscreen);
  fullscreenRef.current = fullscreen;

  useEffect(() => {
    let cancelled = false;
    const beat = () => {
      if (cancelled) return;
      void postCmd("stream_state", {
        scene: sceneRef.current,
        audio_enabled: audioEnabledRef.current,
        volume: volumeRef.current,
        fullscreen: fullscreenRef.current,
        ts: Date.now(),
      }).catch(() => {
        /* heartbeat failures are non-fatal */
      });
    };
    beat();
    const t = setInterval(beat, HEARTBEAT_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const setForceScene = useCallback((id: string | null) => setForceSceneId(id), []);

  return {
    forceSceneId,
    setForceScene,
    banner,
    setBanner: setBannerSafe,
  };
}
