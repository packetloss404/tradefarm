import { useEffect, useRef, useState } from "react";
import type { AccountSummary, PromotionEventPayload, TickResult } from "../api";

/** Connection lifecycle for the /ws socket. */
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
};
export type StreamScenePayload = { scene_id: string };
export type StreamBannerPayload = {
  title: string;
  subtitle?: string;
  ttl_sec?: number;
};
export type StreamAudioPayload = { enabled: boolean; volume: number };

/** Discriminated union of all server-pushed events on /ws. */
export type LiveEvent =
  | { type: "tick"; ts: string; payload: TickPayload }
  | { type: "fill"; ts: string; payload: FillPayload }
  | { type: "account"; ts: string; payload: AccountSummary }
  | { type: "pnl_snapshot"; ts: string; payload: PnlSnapshotPayload }
  | { type: "heartbeat"; ts: string; payload: HeartbeatPayload }
  | { type: "hello"; ts: string; payload: HelloPayload }
  // Phase 4 — curriculum events.
  | { type: "promotion"; ts: string; payload: PromotionEventPayload }
  | { type: "demotion"; ts: string; payload: PromotionEventPayload }
  // Broadcast control wire — fan-out from the dashboard, plus the stream
  // app's own state heartbeat that lights the dashboard liveness indicator.
  | { type: "stream_state"; ts: string; payload: StreamStatePayload }
  | { type: "stream_scene"; ts: string; payload: StreamScenePayload }
  | { type: "stream_banner"; ts: string; payload: StreamBannerPayload }
  | { type: "stream_audio"; ts: string; payload: StreamAudioPayload }
  | { type: "stream_preroll"; ts: string; payload: Record<string, never> };

export type LiveEventHandler = (ev: LiveEvent) => void;

const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 10_000;

function wsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function isLiveEvent(v: unknown): v is LiveEvent {
  if (!v || typeof v !== "object") return false;
  const o = v as { type?: unknown; ts?: unknown; payload?: unknown };
  return typeof o.type === "string" && typeof o.ts === "string" && o.payload !== undefined;
}

/**
 * Opens a single WebSocket to `/ws`, delivers typed events to `onEvent`, and
 * auto-reconnects with exponential backoff (500ms → 10s). Reconnection fires
 * on any non-clean close or error; there is no retry cap — the hook keeps
 * trying for the lifetime of the component.
 */
export function useLiveEvents(onEvent: LiveEventHandler): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("connecting");
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let backoff = BACKOFF_START_MS;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      ws = new WebSocket(wsUrl());

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
  }, []);

  return status;
}
