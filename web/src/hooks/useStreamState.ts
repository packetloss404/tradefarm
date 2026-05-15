import { useCallback, useEffect, useRef, useState } from "react";
import { useLiveEvents, type LiveEvent } from "./useLiveEvents";

const ONLINE_TIMEOUT_MS = 15_000;
const POLL_MS = 1_000;

export type StreamState = {
  isOnline: boolean;
  scene: string | null;
  audioEnabled: boolean | null;
  volume: number | null;
  fullscreen: boolean | null;
  rotationEnabled: boolean | null;
  layoutMode: "scenes" | "v1-broadcast" | null;
  crtEnabled: boolean | null;
  rotationSec: number | null;
  pinAgentId: number | null;
  lastSeenAt: number | null;
};

/**
 * Subscribes to ``/ws`` and tracks the latest ``stream_state`` heartbeat
 * pushed by the broadcast app. ``isOnline`` decays to false 15s after the
 * last heartbeat so the ON AIR indicator goes dark when the stream window
 * closes. Multiple consumers of this hook each open their own WS — the
 * server fan-out supports unlimited subscribers.
 */
export function useStreamState(): StreamState {
  const [state, setState] = useState<StreamState>({
    isOnline: false,
    scene: null,
    audioEnabled: null,
    volume: null,
    fullscreen: null,
    rotationEnabled: null,
    layoutMode: null,
    crtEnabled: null,
    rotationSec: null,
    pinAgentId: null,
    lastSeenAt: null,
  });
  const lastSeenRef = useRef<number | null>(null);

  const handler = useCallback((ev: LiveEvent) => {
    if (ev.type !== "stream_state") return;
    const p = ev.payload;
    const now = Date.now();
    lastSeenRef.current = now;
    setState((prev) => ({
      isOnline: true,
      scene: p.scene ?? null,
      audioEnabled: p.audio_enabled ?? null,
      volume: typeof p.volume === "number" ? p.volume : null,
      fullscreen: p.fullscreen ?? null,
      rotationEnabled: typeof p.rotation_enabled === "boolean" ? p.rotation_enabled : null,
      layoutMode: p.layout_mode === "scenes" || p.layout_mode === "v1-broadcast" ? p.layout_mode : null,
      crtEnabled: typeof p.crt_enabled === "boolean" ? p.crt_enabled : null,
      rotationSec: typeof p.rotation_sec === "number" ? p.rotation_sec : null,
      pinAgentId:
        "pin_agent_id" in p
          ? typeof p.pin_agent_id === "number"
            ? p.pin_agent_id
            : p.pin_agent_id === null
              ? null
              : prev.pinAgentId
          : prev.pinAgentId,
      lastSeenAt: now,
    }));
  }, []);

  useLiveEvents(handler);

  // Decay isOnline once the heartbeat window expires.
  useEffect(() => {
    const t = setInterval(() => {
      const last = lastSeenRef.current;
      if (last == null) return;
      const stale = Date.now() - last > ONLINE_TIMEOUT_MS;
      setState((prev) => (prev.isOnline === !stale ? prev : { ...prev, isOnline: !stale }));
    }, POLL_MS);
    return () => clearInterval(t);
  }, []);

  return state;
}
