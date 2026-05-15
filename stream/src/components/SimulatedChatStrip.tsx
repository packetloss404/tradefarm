import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useSimulatedChat, type ChatMessage, type ChatTone } from "../hooks/useSimulatedChat";
import type { StreamSnapshot } from "../hooks/useStreamData";

const TONE_USER_CLASS: Record<ChatTone, string> = {
  hype: "text-emerald-500",
  salty: "text-amber-500",
  neutral: "text-zinc-400",
  wow: "text-cyan-300",
};

const VIEWER_TICK_MS = 6_000;
const VIEWER_MIN = 6;
const VIEWER_MAX = 220;

function useDriftingViewerCount(): number {
  const [count, setCount] = useState<number>(() => 14 + Math.floor(Math.random() * 18));
  const targetRef = useRef<number>(count);

  useEffect(() => {
    const tick = window.setInterval(() => {
      // 60% chance to drift up by 0..3, 40% chance to drift down by 0..2.
      // Biases the average upward over a long session.
      const up = Math.random() < 0.6;
      const delta = up
        ? Math.floor(Math.random() * 4)
        : -Math.floor(Math.random() * 3);
      const next = Math.max(VIEWER_MIN, Math.min(VIEWER_MAX, targetRef.current + delta));
      targetRef.current = next;
      setCount(next);
    }, VIEWER_TICK_MS);
    return () => window.clearInterval(tick);
  }, []);

  return count;
}

/**
 * Twitch-style fake-audience chat overlay rendered in the bottom-left of the
 * scene body. Strictly decorative — feeds off the existing StreamSnapshot via
 * useSimulatedChat. Sits above scene content but below MacroFireBurst (z-30).
 */
export function SimulatedChatStrip({ snapshot }: { snapshot: StreamSnapshot }) {
  const { messages } = useSimulatedChat(snapshot);
  const viewers = useDriftingViewerCount();

  return (
    <div className="absolute left-3 bottom-3 w-[280px] z-20 pointer-events-none select-none">
      <div className="flex items-center gap-2 px-2 py-1 mb-1 rounded-md bg-zinc-950/70 backdrop-blur-sm border border-zinc-800/80 text-[10px] font-mono uppercase tracking-widest text-zinc-300">
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full rounded-full bg-rose-500 opacity-75 animate-ping" />
          <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-rose-500" />
        </span>
        <span>Live chat</span>
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
            {messages.map((m) => (
              <ChatRow key={m.id} msg={m} />
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}

function ChatRow({ msg }: { msg: ChatMessage }) {
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
