import { useEffect, useMemo, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import type { StreamSnapshot } from "../hooks/useStreamData";
import { useMarketClock } from "../hooks/useMarketClock";
import type { AgentRow, MarketPhase } from "../shared/api";

function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtSignedPct(pct: number): string {
  const sign = pct >= 0 ? "+" : "";
  return `${sign}${pct.toFixed(2)}%`;
}

function pickLeaderLaggard(agents: AgentRow[]): { leader: AgentRow | null; laggard: AgentRow | null } {
  if (agents.length < 2) return { leader: null, laggard: null };
  const active = agents.filter((a) => a.status !== "waiting");
  const pool = active.length >= 2 ? active : agents;
  const sorted = [...pool].sort((a, b) => b.equity - a.equity);
  return { leader: sorted[0] ?? null, laggard: sorted[sorted.length - 1] ?? null };
}

function pickDioramaSample(agents: AgentRow[], n: number): AgentRow[] {
  // Spread the sample across the roster so the preview looks varied (not just
  // the first 12 in id order). Stride-based sampling beats random — stable
  // across re-renders during the splash.
  if (agents.length <= n) return agents.slice();
  const stride = Math.max(1, Math.floor(agents.length / n));
  const out: AgentRow[] = [];
  for (let i = 0; i < agents.length && out.length < n; i += stride) {
    const a = agents[i];
    if (a) out.push(a);
  }
  return out;
}

function fmtDuration(ms: number): string {
  if (ms <= 0) return "any moment";
  const s = Math.floor(ms / 1000);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}

function phaseLabel(phase: MarketPhase): { text: string; tone: "live" | "wait" | "off" } {
  switch (phase) {
    case "rth":
      return { text: "MARKETS OPEN", tone: "live" };
    case "premarket":
      return { text: "PRE-MARKET", tone: "wait" };
    case "afterhours":
      return { text: "AFTER-HOURS", tone: "wait" };
    case "closed":
      return { text: "MARKETS CLOSED", tone: "off" };
  }
}

/**
 * Splash card shown for `durationSec` seconds when the broadcast app boots,
 * then fades into the rotator. Length is configurable via the Admin
 * overlay; setting it to 0 skips the pre-roll entirely.
 */
export function PreRollScene({
  snapshot,
  durationSec,
  onComplete,
}: {
  snapshot: StreamSnapshot;
  durationSec: number;
  onComplete: () => void;
}) {
  const { phase, clock } = useMarketClock();
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = performance.now();
    const ticker = setInterval(() => {
      setElapsed((performance.now() - start) / 1000);
    }, 250);
    return () => clearInterval(ticker);
  }, []);

  useEffect(() => {
    const ms = Math.max(500, durationSec * 1000);
    const t = setTimeout(onComplete, ms);
    return () => clearTimeout(t);
  }, [durationSec, onComplete]);

  const today = new Date();
  const dateStr = today.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
  });

  const dayN = Math.max(1, snapshot.pnlDaily.length);
  const equity = snapshot.account?.total_equity ?? 0;

  const { leader, laggard } = useMemo(() => pickLeaderLaggard(snapshot.agents), [snapshot.agents]);
  const dioramaSample = useMemo(() => pickDioramaSample(snapshot.agents, 12), [snapshot.agents]);

  const phaseInfo = phaseLabel(phase);
  const countdown = useMemo(() => {
    if (!clock) return null;
    const now = new Date(clock.server_now).getTime();
    if (phase === "rth" || phase === "afterhours") {
      if (!clock.closes_at) return null;
      const close = new Date(clock.closes_at).getTime();
      return { label: "Closes in", duration: close - now };
    }
    if (phase === "premarket" || phase === "closed") {
      if (!clock.opens_at) return null;
      const open = new Date(clock.opens_at).getTime();
      return { label: "Opens in", duration: open - now };
    }
    return null;
  }, [clock, phase]);

  const remaining = Math.max(0, durationSec - elapsed);
  const finalCount = remaining > 0 && remaining <= 3 ? Math.ceil(remaining) : null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.4 }}
      className="absolute inset-0 flex flex-col items-center bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 text-zinc-100 overflow-hidden"
    >
      <Starfield />

      {/* Radial glow behind the wordmark — subtler than before to make room
          for the additional panels. */}
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/3 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[900px] rounded-full bg-emerald-500/10 blur-3xl" />
      </div>

      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.1 }}
        className="relative z-10 flex flex-col items-center pt-16"
      >
        <div className="flex items-center gap-4 mb-1">
          <img src="/favicon.svg" alt="" className="h-16 w-16 opacity-90" />
          <h1 className="text-[112px] font-bold tracking-tight leading-none">
            Trade<span className="text-(--color-profit)">Farm</span>
          </h1>
        </div>
        <h2 className="text-2xl text-zinc-400 mt-1 font-mono">
          Day {dayN} · {dateStr}
        </h2>
      </motion.div>

      {/* Middle band: tale-of-the-tape left + mini diorama center + tale right */}
      <div className="relative z-10 flex items-center justify-center gap-10 mt-10 px-12">
        <motion.div
          initial={{ x: -40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.5 }}
        >
          <TaleCard kind="leader" agent={leader} />
        </motion.div>

        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.7, delay: 0.7 }}
        >
          <MiniDiorama agents={dioramaSample} />
        </motion.div>

        <motion.div
          initial={{ x: 40, opacity: 0 }}
          animate={{ x: 0, opacity: 1 }}
          transition={{ duration: 0.6, delay: 0.5 }}
        >
          <TaleCard kind="laggard" agent={laggard} />
        </motion.div>
      </div>

      {/* Market clock + status row */}
      <motion.div
        initial={{ y: 20, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.9 }}
        className="relative z-10 mt-8 flex items-center gap-6 font-mono text-sm uppercase tracking-[0.25em]"
      >
        <span
          className={
            phaseInfo.tone === "live"
              ? "rounded-sm border border-(--color-profit) bg-(--color-profit)/15 px-3 py-1.5 text-(--color-profit) font-semibold"
              : phaseInfo.tone === "wait"
                ? "rounded-sm border border-amber-400/60 bg-amber-400/15 px-3 py-1.5 text-amber-300 font-semibold"
                : "rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-zinc-400 font-semibold"
          }
        >
          {phaseInfo.text}
        </span>
        {countdown && (
          <span className="text-zinc-400">
            {countdown.label}{" "}
            <span className="text-zinc-100 font-semibold tabular-nums">
              {fmtDuration(countdown.duration)}
            </span>
          </span>
        )}
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-400">
          Total equity{" "}
          <span className="text-zinc-100 font-semibold tabular-nums">${fmtUsd(equity)}</span>
        </span>
        <span className="text-zinc-600">·</span>
        <span className="text-zinc-400">
          Roster{" "}
          <span className="text-zinc-100 font-semibold tabular-nums">{snapshot.agents.length}</span>
        </span>
      </motion.div>

      {/* Bottom — either "live broadcast starting…" or the final countdown. */}
      <div className="relative z-10 mt-auto mb-12 h-24 flex items-center justify-center">
        <AnimatePresence mode="wait">
          {finalCount != null ? (
            <motion.div
              key={`count-${finalCount}`}
              initial={{ scale: 0.5, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 1.8, opacity: 0 }}
              transition={{ duration: 0.45, ease: [0.22, 1, 0.36, 1] }}
              className="flex flex-col items-center"
            >
              <span className="text-[10px] uppercase tracking-[0.5em] text-zinc-500 font-mono">
                Going live in
              </span>
              <span className="text-[120px] font-extrabold text-(--color-profit) leading-none tabular-nums drop-shadow-[0_0_24px_rgba(16,185,129,0.45)]">
                {finalCount}
              </span>
            </motion.div>
          ) : (
            <motion.div
              key="standby"
              initial={{ opacity: 0 }}
              animate={{ opacity: 0.6 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 1.0 }}
              className="text-zinc-500 font-mono uppercase tracking-[0.3em] text-sm"
            >
              Live broadcast starting…
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {/* Bottom progress bar — drains over the duration. */}
      <motion.div
        initial={{ width: "100%" }}
        animate={{ width: 0 }}
        transition={{ duration: durationSec, ease: "linear" }}
        className="absolute bottom-0 left-0 h-1 bg-emerald-500/60"
      />
    </motion.div>
  );
}

function TaleCard({ kind, agent }: { kind: "leader" | "laggard"; agent: AgentRow | null }) {
  const isLeader = kind === "leader";
  const ringClass = isLeader ? "border-(--color-profit)/50" : "border-(--color-loss)/50";
  const tintClass = isLeader ? "bg-(--color-profit)/5" : "bg-(--color-loss)/5";
  const accent = isLeader ? "text-(--color-profit)" : "text-(--color-loss)";
  const heading = isLeader ? "Today's leader" : "Today's laggard";

  if (!agent) {
    return (
      <div
        className={`flex w-[280px] h-[200px] flex-col items-center justify-center rounded-md border ${ringClass} ${tintClass} px-4 py-3 backdrop-blur-sm`}
      >
        <span className="text-[10px] uppercase tracking-[0.3em] text-zinc-500 font-mono">
          {heading}
        </span>
        <span className="mt-3 text-zinc-600 font-mono text-sm">waiting for activity</span>
      </div>
    );
  }

  const pct = ((agent.equity - 1000) / 1000) * 100;

  return (
    <div
      className={`flex w-[280px] h-[200px] flex-col rounded-md border ${ringClass} ${tintClass} px-5 py-4 backdrop-blur-sm`}
    >
      <span className={`text-[10px] uppercase tracking-[0.3em] font-mono ${accent}`}>
        {heading}
      </span>
      <span className="mt-2 text-2xl font-bold tracking-tight truncate">{agent.name}</span>
      <span className="text-xs text-zinc-500 font-mono uppercase tracking-wider mt-0.5">
        {agent.strategy} · rank {agent.rank ?? "intern"}
      </span>
      <div className="mt-auto flex items-baseline justify-between">
        <span className={`text-3xl font-extrabold tabular-nums ${accent}`}>{fmtSignedPct(pct)}</span>
        <span className="text-sm text-zinc-400 font-mono tabular-nums">${fmtUsd(agent.equity)}</span>
      </div>
    </div>
  );
}

function MiniDiorama({ agents }: { agents: AgentRow[] }) {
  // A small isometric preview — visual hint at the Hero scene's full diorama.
  // 12 agents arranged in a 4x3 grid with idle-bob via CSS animation seeded
  // by index so the motion is non-uniform.
  const rows = 3;
  const cols = 4;
  const tileW = 56;
  const tileH = 28;

  return (
    <div className="relative h-[200px] w-[360px] overflow-hidden rounded-md border border-zinc-800 bg-zinc-950/60 backdrop-blur-sm">
      <div className="absolute inset-0 flex items-center justify-center">
        <svg viewBox="-200 -120 400 240" className="h-full w-full">
          {/* iso ground plane */}
          <g opacity={0.35}>
            {Array.from({ length: rows + 1 }).map((_, i) => (
              <line
                key={`r${i}`}
                x1={-cols * tileW}
                y1={(i - rows / 2) * tileH}
                x2={cols * tileW}
                y2={(i - rows / 2) * tileH}
                stroke="rgb(82, 82, 91)"
                strokeWidth={0.5}
              />
            ))}
            {Array.from({ length: cols + 1 }).map((_, j) => (
              <line
                key={`c${j}`}
                x1={(j - cols / 2) * tileW}
                y1={-rows * tileH}
                x2={(j - cols / 2) * tileW}
                y2={rows * tileH}
                stroke="rgb(82, 82, 91)"
                strokeWidth={0.5}
              />
            ))}
          </g>

          {agents.map((a, idx) => {
            const r = Math.floor(idx / cols);
            const c = idx % cols;
            const x = (c - (cols - 1) / 2) * tileW * 0.85;
            const y = (r - (rows - 1) / 2) * tileH * 1.4;
            const tone =
              a.status === "profit"
                ? "rgb(16, 185, 129)"
                : a.status === "loss"
                  ? "rgb(244, 63, 94)"
                  : "rgb(161, 161, 170)";
            return (
              <g
                key={a.id}
                transform={`translate(${x},${y})`}
                style={{
                  animation: `tf-bob ${1.6 + (idx % 4) * 0.15}s ease-in-out ${idx * 0.07}s infinite`,
                }}
              >
                <ellipse cx={0} cy={6} rx={9} ry={3} fill="rgba(0,0,0,0.4)" />
                <rect x={-6} y={-12} width={12} height={14} rx={2} fill={tone} opacity={0.9} />
                <circle cx={0} cy={-16} r={4} fill={tone} />
              </g>
            );
          })}
        </svg>
      </div>
      <div className="absolute top-2 left-3 text-[9px] uppercase tracking-[0.3em] text-zinc-500 font-mono">
        Diorama preview
      </div>
    </div>
  );
}

function Starfield() {
  // 40 subtle drifting "particles" via inline-styled divs + CSS keyframes.
  // Cheap enough to not need framer-motion per-node; positions/durations are
  // index-seeded so the motion looks varied but doesn't re-randomize on
  // re-render.
  const stars = useMemo(() => {
    const out: { left: number; top: number; size: number; dur: number; delay: number; opacity: number }[] = [];
    for (let i = 0; i < 40; i++) {
      const seed = (i * 2654435761) >>> 0;
      out.push({
        left: ((seed >>> 8) % 100),
        top: ((seed >>> 16) % 100),
        size: 1 + ((seed >>> 24) % 3),
        dur: 8 + ((seed >>> 4) % 12),
        delay: (seed >>> 12) % 10,
        opacity: 0.15 + ((seed >>> 20) % 30) / 100,
      });
    }
    return out;
  }, []);

  return (
    <div className="absolute inset-0 pointer-events-none overflow-hidden">
      {stars.map((s, i) => (
        <span
          key={i}
          className="absolute rounded-full bg-emerald-300"
          style={{
            left: `${s.left}%`,
            top: `${s.top}%`,
            width: s.size,
            height: s.size,
            opacity: s.opacity,
            animation: `tf-star-drift ${s.dur}s linear ${s.delay}s infinite`,
          }}
        />
      ))}
    </div>
  );
}
