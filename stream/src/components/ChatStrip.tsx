import { useEffect, useMemo, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useSimulatedChat, type ChatMessage as SimChatMessage, type ChatTone } from "../hooks/useSimulatedChat";
import type { StreamSnapshot } from "../hooks/useStreamData";
import type { RealtimeChatMessage } from "../hooks/useStreamCommands";

// Twitch-style color tokens for the simulated stream's tones — unchanged
// from the previous SimulatedChatStrip implementation so the demo look stays
// identical when no real chat is flowing.
const TONE_USER_CLASS: Record<ChatTone, string> = {
  hype: "text-emerald-500",
  salty: "text-amber-500",
  neutral: "text-zinc-400",
  wow: "text-cyan-300",
};

// YouTube Live Chat color groups → tone classes. "owner" maps to the
// channel-owner gold; "moderator" to the YouTube moderator blue; "member"
// to the channel-member green; "neutral" is a regular viewer.
const COLOR_USER_CLASS: Record<RealtimeChatMessage["color"], string> = {
  neutral: "text-zinc-400",
  member: "text-emerald-400",
  moderator: "text-sky-400",
  owner: "text-amber-400",
};

const VIEWER_TICK_MS = 6_000;
const VIEWER_MIN = 6;
const VIEWER_MAX = 220;
// Considered "live" when at least one real chat message has arrived within
// this window. After 5 min of silence we silently fall back to demo chat
// (if the operator hasn't disabled the fallback). This is intentionally
// generous — real streams have quiet stretches.
const LIVE_RECENCY_MS = 5 * 60_000;
// How many trailing messages the strip actually renders, regardless of how
// large the backing buffer is. Mirrors the simulated hook's default cap.
const VISIBLE_CAP = 15;

/**
 * Operator's perspective on the strip mode. `live` = real YouTube chat is
 * actively flowing. `demo` = the simulated source is filling the gap. We
 * surface this in a tiny pill at the top so the operator can verify the
 * pipeline at a glance; viewers reading along won't read it as anything
 * special.
 */
type StripMode = "live" | "demo" | "empty";

function useDriftingViewerCount(opts: { bias: "low" | "high" }): number {
  // Start lower when we expect to be on real chat so the fake number doesn't
  // overshoot an actual small audience. The drift behavior is otherwise
  // identical to the original implementation — we'll wire a real
  // broadcast-side viewer count once the backend exposes one. See task
  // report for the flag.
  const seedLow = 4 + Math.floor(Math.random() * 6); // 4..9
  const seedHigh = 14 + Math.floor(Math.random() * 18); // 14..31
  const [count, setCount] = useState<number>(opts.bias === "low" ? seedLow : seedHigh);
  const targetRef = useRef<number>(count);

  useEffect(() => {
    const tick = window.setInterval(() => {
      // Slightly biased upward on average so the number trends up over a long
      // session; "low" bias halves both halves of the drift to keep the fake
      // number small while waiting for a real viewer count to land.
      const up = Math.random() < (opts.bias === "low" ? 0.55 : 0.6);
      const scale = opts.bias === "low" ? 2 : 4;
      const delta = up
        ? Math.floor(Math.random() * scale)
        : -Math.floor(Math.random() * Math.max(1, scale - 1));
      const next = Math.max(VIEWER_MIN, Math.min(VIEWER_MAX, targetRef.current + delta));
      targetRef.current = next;
      setCount(next);
    }, VIEWER_TICK_MS);
    return () => window.clearInterval(tick);
  }, [opts.bias]);

  return count;
}

/**
 * Live chat overlay rendered in the bottom-left of the scene body. Switches
 * cleanly between two sources:
 *
 *   - "live": real YouTube Live Chat messages routed in via the `/ws`
 *     `chat_message` event. Triggered when `realtimeMessages` has at least
 *     one message whose `receivedAt` is within `LIVE_RECENCY_MS`.
 *
 *   - "demo": simulated audience messages from `useSimulatedChat`. Only
 *     shown if `simulatedChatFallback` is true. Never mixed with live
 *     messages — the strip is either fully real or fully simulated, with
 *     a single cutover.
 *
 * The small `LIVE` / `DEMO` pill at the top of the strip is for the
 * operator's benefit; it's small and unlabeled enough that a stream viewer
 * won't read it as anything special.
 */
export function ChatStrip({
  snapshot,
  realtimeMessages,
  simulatedFallback,
}: {
  snapshot: StreamSnapshot;
  realtimeMessages: RealtimeChatMessage[];
  simulatedFallback: boolean;
}) {
  // Recompute the "is live" verdict on a 30s heartbeat so the strip can
  // gracefully degrade back to demo chat after the LIVE_RECENCY_MS window
  // passes without a new real message. Without this, a stale `realtimeMessages`
  // tail would keep the strip in live mode indefinitely.
  const [nowTick, setNowTick] = useState(() => Date.now());
  useEffect(() => {
    const t = window.setInterval(() => setNowTick(Date.now()), 30_000);
    return () => window.clearInterval(t);
  }, []);

  const recentRealtime = useMemo(() => {
    if (realtimeMessages.length === 0) return [];
    const cutoff = nowTick - LIVE_RECENCY_MS;
    return realtimeMessages.filter((m) => m.receivedAt >= cutoff);
  }, [realtimeMessages, nowTick]);

  // Always mount the simulated hook (it owns its own timers and is cheap to
  // keep running). We just don't render its messages while we're in live mode.
  const { messages: simMessages } = useSimulatedChat(snapshot);

  let mode: StripMode;
  if (recentRealtime.length > 0) mode = "live";
  else if (simulatedFallback) mode = "demo";
  else mode = "empty";

  const viewers = useDriftingViewerCount({ bias: mode === "live" ? "low" : "high" });

  const visibleReal = recentRealtime.slice(-VISIBLE_CAP);
  const visibleSim = simMessages.slice(-VISIBLE_CAP);

  return (
    <div className="absolute left-3 bottom-3 w-[280px] z-20 pointer-events-none select-none">
      <div className="flex items-center gap-2 px-2 py-1 mb-1 rounded-md bg-zinc-950/70 backdrop-blur-sm border border-zinc-800/80 text-[10px] font-mono uppercase tracking-widest text-zinc-300">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-rose-500 opacity-75 animate-ping" />
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-rose-500" />
        </span>
        <span>Live chat</span>
        <ModeBadge mode={mode} />
        <span className="ml-auto text-zinc-400">{viewers} viewers</span>
      </div>

      <div
        className="relative h-[300px] overflow-hidden"
        style={{
          maskImage: "linear-gradient(to bottom, transparent 0%, black 35%)",
          WebkitMaskImage: "linear-gradient(to bottom, transparent 0%, black 35%)",
        }}
      >
        <div className="absolute inset-x-0 bottom-0 flex flex-col justify-end gap-0.5">
          <AnimatePresence initial={false}>
            {mode === "live"
              ? visibleReal.map((m) => <RealtimeRow key={m.id} msg={m} />)
              : mode === "demo"
                ? visibleSim.map((m) => <SimulatedRow key={m.id} msg={m} />)
                : null}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function ModeBadge({ mode }: { mode: StripMode }) {
  if (mode === "live") {
    return (
      <span className="ml-1 px-1.5 py-px rounded-sm bg-emerald-500/15 text-emerald-400 text-[9px] tracking-wider not-italic">
        LIVE
      </span>
    );
  }
  if (mode === "demo") {
    return (
      <span className="ml-1 px-1.5 py-px rounded-sm bg-zinc-800/80 text-zinc-500 text-[9px] tracking-wider italic">
        DEMO
      </span>
    );
  }
  return (
    <span className="ml-1 px-1.5 py-px rounded-sm bg-zinc-900/60 text-zinc-600 text-[9px] tracking-wider italic">
      OFF
    </span>
  );
}

function SimulatedRow({ msg }: { msg: SimChatMessage }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="text-xs leading-tight font-mono px-2 py-0.5 rounded-sm bg-zinc-950/50 backdrop-blur-[2px]"
    >
      <span className={`${TONE_USER_CLASS[msg.tone]} font-semibold`}>{msg.user}</span>
      <span className="text-zinc-300">: {msg.text}</span>
    </motion.div>
  );
}

function RealtimeRow({ msg }: { msg: RealtimeChatMessage }) {
  return (
    <motion.div
      layout
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, y: -4 }}
      transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
      className="text-xs leading-tight font-mono px-2 py-0.5 rounded-sm bg-zinc-950/50 backdrop-blur-[2px]"
    >
      <span className={`${COLOR_USER_CLASS[msg.color]} font-semibold`}>{msg.user}</span>
      <span className="text-zinc-300">: {msg.text}</span>
    </motion.div>
  );
}
