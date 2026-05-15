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

export type MacroFireState = {
  id: string;
  label: string;
  color?: "profit" | "loss" | "neutral";
  subtitle?: string;
  firedAt: number;
};

export type CommentaryState = {
  id: string;
  text: string;
  kind: "color" | "play_by_play";
  source: "llm" | "fallback";
  receivedAt: number;
};

export type StreamCommandsHandle = {
  forceSceneId: string | null;
  setForceScene: (id: string | null) => void;
  banner: BannerState | null;
  setBanner: (b: BannerState | null) => void;
  // Effective auto-rotate state: dashboard-pushed override if present, else
  // the persisted setting passed in via args. The hook owns the override
  // and resolves it here so callers don't recombine it themselves.
  rotationEnabled: boolean;
  // Effective CRT-overlay state. Override layered on top of the persisted
  // settings.crtEnabled by `stream_crt` events.
  crtEnabled: boolean;
  // Effective scene cadence in seconds. Layered on top of settings.sceneRotationSec
  // by `stream_cadence` events. Used as `rotationSec` for SceneRotator when
  // rotationEnabled is true.
  rotationSec: number;
  // Single-slot director-moment burst pushed by the dashboard's macro fires.
  // Auto-clears ~1.5s after the event lands; re-keyed when a new event arrives.
  macroFire: MacroFireState | null;
  // Currently pinned agent id (dashboard-pushed via stream_scene). Null when
  // no pin is active. Hero/Brain scenes consume this to override their
  // default sort/sample logic and focus on a single agent.
  pinAgentId: number | null;
  // Most-recent live commentary pushed by the backend's CommentaryLoop. Null
  // until the first emission. SceneRotator forwards this to useCommentary so
  // server-side LLM takes preempt the client-side template highlights.
  commentary: CommentaryState | null;
};

export type UseStreamCommandsArgs = {
  wsUrlOverride?: string;
  currentScene: string;
  audioEnabled: boolean;
  audioVolume: number;
  fullscreen: boolean;
  // Persisted auto-rotate setting (stream's own admin overlay). The hook
  // layers a transient dashboard override on top of this.
  rotationEnabledFromSettings: boolean;
  // Persisted CRT-overlay setting. Override-layered same as rotation.
  crtEnabledFromSettings: boolean;
  // Persisted scene cadence (sceneRotationSec). Override-layered same as
  // rotation.
  rotationSecFromSettings: number;
  // Persisted layout mode — only published on the heartbeat so the dashboard
  // knows which UI surface is live. Layout switches go through onLayoutChange
  // (parent persists + reloads) rather than an in-memory override.
  layoutMode: "scenes" | "v1-broadcast";
  onPreroll: () => void;
  /** Called when a `stream_layout` cmd arrives. Parent should persist the
   *  setting and reload (the V1 ↔ Scenes swap requires a fresh tree). */
  onLayoutChange?: (mode: "scenes" | "v1-broadcast") => void;
  /** Called when a `stream_fullscreen` cmd arrives. Parent should call into
   *  Tauri's window API; in a plain browser this is a no-op. */
  onFullscreenChange?: (enabled: boolean) => void;
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
  const {
    currentScene,
    audioEnabled,
    audioVolume,
    fullscreen,
    rotationEnabledFromSettings,
    crtEnabledFromSettings,
    rotationSecFromSettings,
    layoutMode,
    onPreroll,
    onLayoutChange,
    onFullscreenChange,
    wsUrlOverride,
  } = args;

  const [forceSceneId, setForceSceneId] = useState<string | null>(null);
  const [banner, setBanner] = useState<BannerState | null>(null);
  const [macroFire, setMacroFire] = useState<MacroFireState | null>(null);
  const [pinAgentId, setPinAgentId] = useState<number | null>(null);
  const [commentary, setCommentary] = useState<CommentaryState | null>(null);
  const [rotationEnabledOverride, setRotationEnabledOverride] = useState<boolean | null>(null);
  const [crtEnabledOverride, setCrtEnabledOverride] = useState<boolean | null>(null);
  const [rotationSecOverride, setRotationSecOverride] = useState<number | null>(null);
  const rotationEnabled = rotationEnabledOverride ?? rotationEnabledFromSettings;
  const crtEnabled = crtEnabledOverride ?? crtEnabledFromSettings;
  const rotationSec = rotationSecOverride ?? rotationSecFromSettings;
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const macroFireTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onPrerollRef = useRef(onPreroll);
  onPrerollRef.current = onPreroll;
  const onLayoutChangeRef = useRef(onLayoutChange);
  onLayoutChangeRef.current = onLayoutChange;
  const onFullscreenChangeRef = useRef(onFullscreenChange);
  onFullscreenChangeRef.current = onFullscreenChange;

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

  const setMacroFireSafe = useCallback((next: MacroFireState | null) => {
    if (macroFireTimer.current) {
      clearTimeout(macroFireTimer.current);
      macroFireTimer.current = null;
    }
    setMacroFire(next);
    if (next) {
      // Dwell ~2.2s so a glanced label has time to register on stream.
      macroFireTimer.current = setTimeout(() => setMacroFire(null), 2200);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (bannerTimer.current) clearTimeout(bannerTimer.current);
      if (macroFireTimer.current) clearTimeout(macroFireTimer.current);
    };
  }, []);

  const handler = useCallback(
    (ev: LiveEvent) => {
      switch (ev.type) {
        case "stream_scene": {
          setForceSceneId(ev.payload.scene_id || null);
          // Pin is tri-state on the wire: number sets, null clears, absent
          // means "don't touch". Use `in` to distinguish absent from null.
          if ("pin_agent_id" in ev.payload) {
            const pin = ev.payload.pin_agent_id;
            if (pin === null) setPinAgentId(null);
            else if (typeof pin === "number") setPinAgentId(pin);
          }
          break;
        }
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
        case "stream_rotation":
          setRotationEnabledOverride(Boolean(ev.payload.enabled));
          break;
        case "stream_layout":
          if (ev.payload.mode === "scenes" || ev.payload.mode === "v1-broadcast") {
            onLayoutChangeRef.current?.(ev.payload.mode);
          }
          break;
        case "stream_crt":
          setCrtEnabledOverride(Boolean(ev.payload.enabled));
          break;
        case "stream_cadence": {
          const sec = Number(ev.payload.sec);
          if (Number.isFinite(sec) && sec >= 0) setRotationSecOverride(sec);
          break;
        }
        case "stream_fullscreen":
          onFullscreenChangeRef.current?.(Boolean(ev.payload.enabled));
          break;
        case "stream_macro_fired": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          const color =
            p.color === "profit" || p.color === "loss" || p.color === "neutral"
              ? p.color
              : undefined;
          setMacroFireSafe({
            id: p.id,
            label: typeof p.label === "string" ? p.label : "",
            color,
            subtitle: typeof p.subtitle === "string" && p.subtitle.length > 0 ? p.subtitle : undefined,
            firedAt: Date.now(),
          });
          break;
        }
        case "stream_commentary": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          if (typeof p.text !== "string" || p.text.length === 0) break;
          const kind = p.kind === "play_by_play" ? "play_by_play" : "color";
          const source = p.source === "llm" ? "llm" : "fallback";
          setCommentary({
            id: p.id,
            text: p.text,
            kind,
            source,
            receivedAt: Date.now(),
          });
          break;
        }
        default:
          break;
      }
    },
    [setBannerSafe, setMacroFireSafe],
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
  const rotationEnabledRef = useRef(rotationEnabled);
  rotationEnabledRef.current = rotationEnabled;
  const layoutModeRef = useRef(layoutMode);
  layoutModeRef.current = layoutMode;
  const crtEnabledRef = useRef(crtEnabled);
  crtEnabledRef.current = crtEnabled;
  const rotationSecRef = useRef(rotationSec);
  rotationSecRef.current = rotationSec;
  const pinAgentIdRef = useRef(pinAgentId);
  pinAgentIdRef.current = pinAgentId;

  useEffect(() => {
    let cancelled = false;
    const beat = () => {
      if (cancelled) return;
      void postCmd("stream_state", {
        scene: sceneRef.current,
        audio_enabled: audioEnabledRef.current,
        volume: volumeRef.current,
        fullscreen: fullscreenRef.current,
        rotation_enabled: rotationEnabledRef.current,
        layout_mode: layoutModeRef.current,
        crt_enabled: crtEnabledRef.current,
        rotation_sec: rotationSecRef.current,
        pin_agent_id: pinAgentIdRef.current,
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
    rotationEnabled,
    crtEnabled,
    rotationSec,
    macroFire,
    pinAgentId,
    commentary,
  };
}
