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
