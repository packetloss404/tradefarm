import { useEffect, useRef, useSyncExternalStore } from "react";
import { useLiveContext } from "../contexts/LiveContext";
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
  rotation_enabled?: boolean | null;
  layout_mode?: "scenes" | "v1-broadcast" | null;
  crt_enabled?: boolean | null;
  rotation_sec?: number | null;
  pin_agent_id?: number | null;
  ts?: number | string | null;
};
export type StreamScenePayload = { scene_id: string; pin_agent_id?: number | null };
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

/**
 * Subscribes to the shared /ws WebSocket owned by `<LiveProvider>`. Multiple
 * consumers across the dashboard (useEventFeed, useStreamState × 2) all
 * multiplex off the same socket — the provider handles connection lifecycle
 * (open / close / exponential reconnect backoff) and fans events to every
 * registered handler.
 *
 * Must be called inside `<LiveProvider>`. The hook returns the current
 * connection status via `useSyncExternalStore`, and increments the provider's
 * ref count so the socket opens lazily on first consumer and closes on zero.
 */
export function useLiveEvents(onEvent: LiveEventHandler): LiveStatus {
  const ctx = useLiveContext();

  // Refs keep the latest handler available to the stable wrapper below.
  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
    // Stable wrapper: the Set holds this identity for the lifetime of the
    // consumer, so handler updates flow through the ref without churning
    // the Set.
    const wrapper = (ev: LiveEvent): void => {
      handlerRef.current(ev);
    };
    return ctx.addHandler(wrapper);
  }, [ctx]);

  useEffect(() => {
    return ctx.incRefCount();
  }, [ctx]);

  return useSyncExternalStore(ctx.subscribeStatus, ctx.getStatus, ctx.getStatus);
}
