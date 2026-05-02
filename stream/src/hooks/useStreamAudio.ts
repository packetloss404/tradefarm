import { useEffect, useRef } from "react";
import { streamAudio } from "../audio/StreamAudio";
import type { StreamSnapshot } from "./useStreamData";

/**
 * Wires the live event stream into the Web Audio engine.
 *
 * - On every new tick: kick drum.
 * - On every new fill: a pentatonic piano-ish note (pitch hashed by symbol,
 *   octave by side).
 * - On every new promotion/demotion: a 4-note arpeggio stinger.
 *
 * Dedupe is keyed off the event timestamp + agent so reconnects or
 * snapshot rerenders don't re-trigger sounds.
 */
export function useStreamAudio({
  snapshot,
  enabled,
  volume,
}: {
  snapshot: StreamSnapshot;
  enabled: boolean;
  volume: number;
}): void {
  useEffect(() => {
    streamAudio.setEnabled(enabled);
  }, [enabled]);

  useEffect(() => {
    streamAudio.setVolume(volume);
  }, [volume]);

  // Tick kicks.
  const lastTickTs = useRef<string | null>(null);
  useEffect(() => {
    const t = snapshot.lastTick;
    if (!t) return;
    if (t.ts === lastTickTs.current) return;
    lastTickTs.current = t.ts;
    streamAudio.playKick();
  }, [snapshot.lastTick]);

  // Fill notes.
  const seenFills = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const ev of snapshot.fills) {
      const key = `${ev.ts}::${ev.payload.agent_id}::${ev.payload.symbol}`;
      if (seenFills.current.has(key)) continue;
      seenFills.current.add(key);
      streamAudio.playFill(ev.payload.symbol, ev.payload.side, ev.payload.qty);
    }
    if (seenFills.current.size > 200) {
      seenFills.current = new Set(Array.from(seenFills.current).slice(-100));
    }
  }, [snapshot.fills]);

  // Promotion / demotion stingers.
  const seenPromos = useRef<Set<string>>(new Set());
  useEffect(() => {
    for (const ev of snapshot.promotions) {
      const key = `${ev.ts}::${ev.payload.agent_id}::${ev.type}`;
      if (seenPromos.current.has(key)) continue;
      seenPromos.current.add(key);
      streamAudio.playStinger(ev.type === "promotion" ? "promotion" : "demotion");
    }
    if (seenPromos.current.size > 200) {
      seenPromos.current = new Set(Array.from(seenPromos.current).slice(-100));
    }
  }, [snapshot.promotions]);
}
