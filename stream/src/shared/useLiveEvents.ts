import { useEffect, useRef, useSyncExternalStore } from "react";
import { useLiveContext } from "../contexts/LiveContext";
import type { AccountSummary, PromotionEventPayload, TickResult } from "./api";

// Streaming-app copy of the LiveEvent type. The two apps diverge: the
// stream app also consumes broadcast-control events (`stream_layout`,
// `stream_crt`, `stream_cadence`, `stream_fullscreen`). The dashboard
// side only needs to PUBLISH those events, not consume them, so they're
// absent there.

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
// 0.17.0 — operator-pushed lower-third. Mirrors the server-side
// `lower_third` WS event published by `POST /admin/lower_third/push`.
// Carries an `id` (uuid hex) so the stream can dedup against a
// canonical publish, plus the optional `color` accent the legacy
// `stream_banner` doesn't expose. Routed to the same in-stream slot
// as `stream_banner` — the visual is identical.
export type LowerThirdPayload = {
  id: string;
  title: string;
  subtitle?: string;
  ttl_sec: number;
  color?: "profit" | "loss" | "neutral";
};
export type StreamAudioPayload = { enabled: boolean; volume: number };
export type StreamMacroFiredPayload = {
  id: string;
  label: string;
  color?: "profit" | "loss" | "neutral";
  subtitle?: string;
};
export type BroadcastMomentPayload = {
  id: string;
  kind:
    | "agent_pnl"
    | "market_move"
    | "rank_change"
    | "streak"
    | "day_leader"
    | "activity"
    | "commentary";
  title: string;
  subtitle?: string;
  priority: number;
  color: "profit" | "loss" | "neutral";
  outputs: Array<"macro_burst" | "lower_third" | "ticker" | "recap_log" | "audio">;
  ttl_sec: number;
  created_at: string;
  agent_id?: number;
  trigger?: string;
  metadata: Record<string, unknown>;
};
export type StreamCommentaryPayload = {
  id: string;
  text: string;
  kind: "color" | "play_by_play";
  source: "llm" | "fallback";
};
export type ChatMessagePayload = {
  id: string;
  user: string;
  text: string;
  color?: "neutral" | "member" | "moderator" | "owner";
  source: "youtube";
  at: string;
};

// ── Decision Lab ──────────────────────────────────────────────────────────
// Per-agent reasoning, fired once per tick as a single batch event so the
// fan-out cost stays bounded at 100 agents/tick. WAIT verdicts are first-
// class: this is what the broadcast app renders when no fills are happening.
export type AgentDecisionPayload = {
  agent_id: number;
  agent_name: string;
  strategy: string;
  symbol: string | null;
  verdict: "trade" | "wait";
  lstm_probs: [number, number, number] | null;
  lstm_max_prob: number | null;
  lstm_direction: "down" | "flat" | "up" | null;
  llm_bias: "long" | "flat" | "short" | null;
  llm_stance: "trade" | "wait" | null;
  reason: string;
  at: string;
};
export type AgentDecisionsBatchPayload = {
  at: string;
  tick_id: string;
  decisions: AgentDecisionPayload[];
};

// ── Audience interactivity ────────────────────────────────────────────────
// Score is signed in [-1, 1] (-1 fully bearish, +1 fully bullish). `up`/`down`
// are raw tally counts within a rolling `window_sec` window so the overlay can
// gate on minimum sample size.
export type AudienceSentimentPayload = {
  score: number;
  up: number;
  down: number;
  window_sec: number;
};
// Operator-only — pin requests never surface to the stream overlay; the
// dashboard polls REST and renders them in the approval queue.
export type AudiencePinRequestPayload = {
  id: string;
  requester: string;
  agent_id: number | null;
  agent_name_query: string;
  requested_at: string;
};
// Resolution event — fans out to the stream so the AudiencePinBanner can fire
// the "Audience pinned X" overlay on approval. Rejected resolutions are also
// emitted but the banner ignores them.
export type AudiencePinResolvedPayload = {
  id: string;
  status: "approved" | "rejected";
  agent_id: number | null;
};
// Prediction lifecycle: open → locked → revealed. Tally is a vote count per
// option keyed by option string.
export type PredictionStatePayload = {
  id: string;
  question: string;
  options: string[];
  status: "open" | "locked" | "revealed";
  tally: Record<string, number>;
  locks_at: string;
  reveals_at: string;
  winning_option: string | null;
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
  | { type: "lower_third"; ts: string; payload: LowerThirdPayload }
  | { type: "stream_audio"; ts: string; payload: StreamAudioPayload }
  | { type: "stream_preroll"; ts: string; payload: Record<string, never> }
  | { type: "stream_rotation"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_layout"; ts: string; payload: { mode: "scenes" | "v1-broadcast" } }
  | { type: "stream_crt"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_cadence"; ts: string; payload: { sec: number } }
  | { type: "stream_fullscreen"; ts: string; payload: { enabled: boolean } }
  | { type: "stream_macro_fired"; ts: string; payload: StreamMacroFiredPayload }
  | { type: "broadcast_moment"; ts: string; payload: BroadcastMomentPayload }
  | { type: "stream_commentary"; ts: string; payload: StreamCommentaryPayload }
  | { type: "chat_message"; ts: string; payload: ChatMessagePayload }
  | { type: "audience_sentiment"; ts: string; payload: AudienceSentimentPayload }
  | { type: "audience_pin_request"; ts: string; payload: AudiencePinRequestPayload }
  | { type: "audience_pin_resolved"; ts: string; payload: AudiencePinResolvedPayload }
  | { type: "prediction_state"; ts: string; payload: PredictionStatePayload }
  | { type: "agent_decisions_batch"; ts: string; payload: AgentDecisionsBatchPayload };

export type LiveEventHandler = (ev: LiveEvent) => void;

/**
 * Subscribes to the shared /ws WebSocket owned by `<LiveProvider>`. The
 * provider handles the open / close / exponential reconnect backoff plus
 * the replay-mode handshake, so the hook is just a fan-out registration.
 *
 * The optional ``urlOverride`` is accepted for API compatibility with the
 * previous per-consumer implementation but is no longer consulted — the
 * Provider is configured at mount time and is the single source of truth
 * for the target URL.
 */
export function useLiveEvents(onEvent: LiveEventHandler, _urlOverride?: string): LiveStatus {
  const ctx = useLiveContext();

  const handlerRef = useRef(onEvent);
  handlerRef.current = onEvent;

  useEffect(() => {
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
