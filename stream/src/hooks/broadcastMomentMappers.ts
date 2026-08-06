import type { BroadcastMomentPayload } from "../shared/useLiveEvents";
import type { BannerState, MacroFireState } from "./useStreamCommands";

/**
 * Canonical-to-legacy mapping for stream visuals.
 *
 * The Broadcast OS contract is the source of truth: every `broadcast_moment`
 * carries an `outputs` array listing which presentation surfaces it should
 * light up. The stream app still renders via the legacy `MacroFireState` /
 * `BannerState` slots, so we translate the canonical payload into the
 * per-slot state shape.
 *
 * Pure functions, no React, no side effects. The hook in `useStreamCommands`
 * owns the dedup ref and the timestamp; these helpers just shape the data.
 */

const MACRO_BURST = "macro_burst";
const LOWER_THIRD = "lower_third";
const RECAP_LOG = "recap_log";
// 0.16.0 — live recap scene trigger. The `day_leader` moment with
// `outputs=("recap_log",)` (and `trigger="daily_recap"`) auto-activates
// the `LiveRecapScene` for the moment's TTL. The hook owns the
// force-scene slot; this helper just shapes the data.
const DAY_LEADER = "day_leader";
const DAILY_RECAP_TRIGGER = "daily_recap";

export type LiveRecapState = {
  momentId: string;
  weekId: string;
  ttlSec: number;
  firedAt: number;
};

export function broadcastMomentToMacroFire(
  payload: BroadcastMomentPayload,
  firedAt: number,
): MacroFireState | null {
  if (!payload.outputs.includes(MACRO_BURST)) return null;
  if (typeof payload.id !== "string" || payload.id.length === 0) return null;
  const color: MacroFireState["color"] =
    payload.color === "profit" || payload.color === "loss" || payload.color === "neutral"
      ? payload.color
      : undefined;
  return {
    id: payload.id,
    label: payload.title,
    color,
    subtitle: payload.subtitle && payload.subtitle.length > 0 ? payload.subtitle : undefined,
    firedAt,
  };
}

export function broadcastMomentToBanner(
  payload: BroadcastMomentPayload,
  shownAt: number,
): BannerState | null {
  if (!payload.outputs.includes(LOWER_THIRD)) return null;
  if (typeof payload.title !== "string" || payload.title.length === 0) return null;
  return {
    title: payload.title,
    subtitle: payload.subtitle ?? "",
    ttl_sec: typeof payload.ttl_sec === "number" ? Math.max(1, Math.min(120, payload.ttl_sec || 8)) : 8,
    shown_at: shownAt,
  };
}

// 0.16.0 — daily recap mapper. Reads the `metadata.week_id` (set by
// the orchestrator's shared `_build_daily_recap_moment` helper) and
// the canonical `ttl_sec` so the `LiveRecapScene` knows how long to
// stay on-air. The hook in `useStreamCommands` consumes this and
// pushes the scene into the rotator's force-scene slot.
export function broadcastMomentToLiveRecap(
  payload: BroadcastMomentPayload,
  firedAt: number,
): LiveRecapState | null {
  if (payload.kind !== DAY_LEADER) return null;
  if (payload.trigger !== DAILY_RECAP_TRIGGER) return null;
  if (!payload.outputs.includes(RECAP_LOG)) return null;
  if (typeof payload.id !== "string" || payload.id.length === 0) return null;
  const meta = payload.metadata as { week_id?: unknown } | undefined;
  const weekId = typeof meta?.week_id === "string" ? meta.week_id : "";
  if (!weekId) return null;
  return {
    momentId: payload.id,
    weekId,
    ttlSec:
      typeof payload.ttl_sec === "number" ? Math.max(1, Math.min(180, payload.ttl_sec || 60)) : 60,
    firedAt,
  };
}
