import { useEffect, useRef, useState } from "react";
import type { AccountSummary, PromotionEventPayload, TickResult } from "./api";

// Streaming-app copy of web/src/hooks/useLiveEvents.ts. The two have
// diverged: this version's LiveEvent union also includes the broadcast-control
// events the stream consumes (`stream_layout`, `stream_crt`, `stream_cadence`,
// `stream_fullscreen`). The dashboard side only needs to PUBLISH those events,
// not consume them, so they're absent there.

export type LiveStatus = "connecting" | "open" | "closed";

type TickPayload = TickResult & { at: string };
type FillPayload = {
  agent_id: number;
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  price: number;
};
type PnlSnapshotPayload = { date: string; equity: number; pnl_pct: number };
type HeartbeatPayload = { seq: number };
type HelloPayload = { session: string; server_time: string };

export type StreamStatePayload = {
  scene?: string | null;
  audio_enabled?: boolean | null;
  volume?: number | null;
  fullscreen?: boolean | null;
  ts?: number | string | null;
  pin_agent_id?: number | null;
};
export type StreamScenePayload = { scene_id: string; pin_agent_id?: number | null };
export type StreamBannerPayload = {
  title: string;
  subtitle?: string;
  ttl_sec?: number;
};
export type StreamAudioPayload = { enabled: boolean; volume: number };
export type StreamMacroFiredPayload = {
  id: string;
  label: string;
  color?: "profit" | "loss" | "neutral";
  subtitle?: string;
};
export type StreamCommentaryPayload = {
  id: string;
  text: string;
  kind: "color" | "play_by_play";
  source: "llm" | "fallback";
};

export type LiveEvent =
  | { type: "tick"; ts: string; payload: TickPayload }
  | { type: "fill"; ts: string; payload: FillPayload }
  | { type: "account"; ts: string; payload: AccountSummary }
  | { type: "pnl_snapshot"; ts: string; payload: PnlSnapshotPayload }
  | { type: "heartbeat"; ts: string; payload: HeartbeatPayload }
  | { type: "hello"; ts: string; payload: HelloPayload }
  | { type: "promotion"; ts: string; payload: PromotionEventPayload }
  | { type: "demotion"; ts: string; payload: PromotionEventPayload }
  | { type: "stream_state"; ts: string; payload: StreamStatePayload }
  | { type: "stream_scene"; ts: string; payload: StreamScenePayload }
  | { type: "stream_banner"; ts: string; payload: StreamBannerPayload }
  | { type: "stream_audio"; ts: string; payload: StreamAudioPayload }
  | { type: "stream_preroll"; ts: string; payload: Record<string, never> }
  | { type: "stream_rotation"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_layout"; ts: string; payload: { mode: "scenes" | "v1-broadcast" } }
  | { type: "stream_crt"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_cadence"; ts: string; payload: { sec: number } }
  | { type: "stream_fullscreen"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_macro_fired"; ts: string; payload: StreamMacroFiredPayload }
  | { type: "stream_commentary"; ts: string; payload: StreamCommentaryPayload };

export type LiveEventHandler = (ev: LiveEvent) => void;

const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 10_000;

function defaultWsUrl(): string {
  // Inside the packaged Tauri webview `location.host` is `tauri.localhost`
  // which won't accept a websocket connection. Fall back to the local
  // FastAPI port so the broadcast app works without explicit settings.
  if (typeof location !== "undefined" && location.hostname === "tauri.localhost") {
    return "ws://127.0.0.1:8000/ws";
  }
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function isLiveEvent(v: unknown): v is LiveEvent {
  if (!v || typeof v !== "object") return false;
  const o = v as { type?: unknown; ts?: unknown; payload?: unknown };
  return typeof o.type === "string" && typeof o.ts === "string" && o.payload !== undefined;
}

/**
 * Opens a WebSocket to either the runtime-overridden URL (for packaged Tauri
 * builds pointing at a remote backend) or the dev-server proxy `/ws` path.
 * Auto-reconnects with exponential backoff (500ms -> 10s).
 */
export function useLiveEvents(onEvent: LiveEventHandler, urlOverride?: string): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let backoff = BACKOFF_START_MS;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const target = urlOverride && urlOverride.length > 0 ? urlOverride : defaultWsUrl();

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      ws = new WebSocket(target);

      ws.onopen = () => {
        backoff = BACKOFF_START_MS;
        setStatus("open");
      };

      ws.onmessage = (m) => {
        try {
          const parsed: unknown = JSON.parse(typeof m.data === "string" ? m.data : "");
          if (isLiveEvent(parsed)) handlerRef.current(parsed);
        } catch {
          /* ignore malformed frames */
        }
      };

      const scheduleReconnect = () => {
        if (disposed) return;
        setStatus("closed");
        retryTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
      };

      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* noop */
        }
      };
      ws.onclose = scheduleReconnect;
    };

    connect();

    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      if (ws) {
        ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
        try {
          ws.close();
        } catch {
          /* noop */
        }
      }
    };
  }, [urlOverride]);

  return status;
}
