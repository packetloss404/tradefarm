import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { StreamSnapshot } from "../hooks/useStreamData";
import {
  useRecap,
  type RecapBiggestFill,
  type RecapBiggestLoss,
  type RecapDay,
  type RecapPrediction,
  type RecapPromotion,
  type RecapTopWinner,
} from "../hooks/useRecap";

type CardKind =
  | "title"
  | "session_pnl"
  | "biggest_fill"
  | "podium"
  | "biggest_loss"
  | "promotions"
  | "predictions"
  | "end";

type CardSpec = {
  kind: CardKind;
  durationMs: number;
};

const BASE_DURATIONS: Record<CardKind, number> = {
  title: 3000,
  session_pnl: 4000,
  biggest_fill: 4000,
  podium: 5000,
  biggest_loss: 4000,
  promotions: 5000,
  predictions: 6000,
  end: 3000,
};

function fmtUsd(n: number, frac = 0): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  });
}

function fmtSigned(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "−";
  return `${sign}${Math.abs(n).toLocaleString("en-US", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  })}`;
}

function fmtSignedPct(pct: number, frac = 2): string {
  const sign = pct >= 0 ? "+" : "−";
  return `${sign}${Math.abs(pct).toFixed(frac)}%`;
}

function fmtRelative(iso: string): string {
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "";
  const deltaSec = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (deltaSec < 60) return `${deltaSec}s ago`;
  if (deltaSec < 3600) return `${Math.floor(deltaSec / 60)}m ago`;
  const h = Math.floor(deltaSec / 3600);
  const m = Math.floor((deltaSec % 3600) / 60);
  return m === 0 ? `${h}h ago` : `${h}h ${m}m ago`;
}

function buildSequence(data: RecapDay): CardSpec[] {
  const seq: CardSpec[] = [
    { kind: "title", durationMs: BASE_DURATIONS.title },
    { kind: "session_pnl", durationMs: BASE_DURATIONS.session_pnl },
  ];
  let reclaimedMs = 0;

  if (data.biggest_fill) {
    seq.push({ kind: "biggest_fill", durationMs: BASE_DURATIONS.biggest_fill });
  } else {
    reclaimedMs += BASE_DURATIONS.biggest_fill;
  }
  if (data.top_winners.length > 0) {
    seq.push({ kind: "podium", durationMs: BASE_DURATIONS.podium });
  } else {
    reclaimedMs += BASE_DURATIONS.podium;
  }
  if (data.biggest_loss) {
    seq.push({ kind: "biggest_loss", durationMs: BASE_DURATIONS.biggest_loss });
  } else {
    reclaimedMs += BASE_DURATIONS.biggest_loss;
  }
  if (data.promotions.length > 0) {
    seq.push({ kind: "promotions", durationMs: BASE_DURATIONS.promotions });
  } else {
    reclaimedMs += BASE_DURATIONS.promotions;
  }
  const revealed = data.predictions.filter((p) => p.status === "revealed");
  if (revealed.length > 0) {
    seq.push({ kind: "predictions", durationMs: BASE_DURATIONS.predictions });
  } else {
    reclaimedMs += BASE_DURATIONS.predictions;
  }

  seq.push({ kind: "end", durationMs: BASE_DURATIONS.end + reclaimedMs });
  return seq;
}

export function RecapScene({ snapshot }: { snapshot: StreamSnapshot }) {
  const { data, loading, error } = useRecap();

  if (loading) return <RecapShell><LoadingCard /></RecapShell>;
  if (error || !data) return <RecapShell><ErrorCard message={error ?? "no data"} /></RecapShell>;

  return <RecapSequence data={data} agentCount={snapshot.agents.length} />;
}

function RecapSequence({ data, agentCount }: { data: RecapDay; agentCount: number }) {
  const sequence = useMemo(() => buildSequence(data), [data]);
  const [idx, setIdx] = useState(0);

  useEffect(() => {
    if (sequence.length === 0) return;
    const current = sequence[idx];
    if (!current) return;
    const t = setTimeout(() => {
      setIdx((cur) => Math.min(cur + 1, sequence.length - 1));
    }, current.durationMs);
    return () => clearTimeout(t);
  }, [idx, sequence]);

  const active = sequence[idx];
  if (!active) return <RecapShell><EndCard /></RecapShell>;

  return (
    <RecapShell pip={{ index: idx + 1, total: sequence.length }}>
      <AnimatePresence mode="wait">
        <motion.div
          key={`${active.kind}-${idx}`}
          initial={{ opacity: 0, scale: 0.985 }}
          animate={{ opacity: 1, scale: 1 }}
          exit={{ opacity: 0, scale: 1.01 }}
          transition={{ duration: 0.55, ease: [0.22, 1, 0.36, 1] }}
          className="absolute inset-0 flex items-center justify-center"
        >
          {active.kind === "title" && <TitleCard date={data.date} agentCount={agentCount} />}
          {active.kind === "session_pnl" && (
            <SessionPnlCard
              pct={data.session_pnl_pct}
              equity={data.session_total_equity}
              fills={data.total_fills}
            />
          )}
          {active.kind === "biggest_fill" && data.biggest_fill && (
            <BiggestFillCard fill={data.biggest_fill} />
          )}
          {active.kind === "podium" && (
            <PodiumCard winners={data.top_winners} />
          )}
          {active.kind === "biggest_loss" && data.biggest_loss && (
            <BiggestLossCard loss={data.biggest_loss} />
          )}
          {active.kind === "promotions" && (
            <PromotionsCard promotions={data.promotions} />
          )}
          {active.kind === "predictions" && (
            <PredictionsRevealCard
              predictions={data.predictions.filter((p) => p.status === "revealed")}
            />
          )}
          {active.kind === "end" && <EndCard />}
        </motion.div>
      </AnimatePresence>
    </RecapShell>
  );
}

function RecapShell({
  children,
  pip,
}: {
  children: React.ReactNode;
  pip?: { index: number; total: number };
}) {
  return (
    <div className="absolute inset-0 overflow-hidden bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 text-zinc-100">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1100px] h-[900px] rounded-full bg-emerald-500/10 blur-3xl" />
      </div>
      <div className="absolute inset-0">{children}</div>
      {pip && (
        <div className="absolute top-4 right-6 text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-600">
          {pip.index} / {pip.total}
        </div>
      )}
    </div>
  );
}

function LoadingCard() {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center">
      <motion.div
        initial={{ opacity: 0.4 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.9, repeat: Infinity, repeatType: "reverse" }}
        className="text-3xl font-bold tracking-tight text-zinc-300"
      >
        Building today's recap…
      </motion.div>
      <span className="mt-4 text-[10px] uppercase tracking-[0.3em] font-mono text-zinc-600">
        Compiling highlights
      </span>
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center">
      <span className="text-3xl font-bold tracking-tight text-zinc-200">
        Unable to assemble recap
      </span>
      <span className="mt-3 text-sm font-mono text-zinc-500 max-w-[60%] text-center">
        {message}
      </span>
    </div>
  );
}

function TitleCard({ date, agentCount }: { date: string; agentCount: number }) {
  const pretty = useMemo(() => {
    const d = new Date(`${date}T12:00:00`);
    if (Number.isNaN(d.getTime())) return date;
    return d.toLocaleDateString(undefined, {
      weekday: "long",
      month: "long",
      day: "numeric",
      year: "numeric",
    });
  }, [date]);

  return (
    <div className="flex flex-col items-center px-12">
      <motion.span
        initial={{ y: -10, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        End-of-day recap
      </motion.span>
      <motion.h1
        initial={{ scale: 0.92, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.7, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        className="mt-6 text-[96px] leading-none font-extrabold tracking-tight text-center"
      >
        TODAY ON <span className="text-(--color-profit)">TRADEFARM</span>
      </motion.h1>
      <motion.div
        initial={{ y: 12, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.55, delay: 0.55 }}
        className="mt-8 text-4xl font-mono tabular-nums text-zinc-300"
      >
        {pretty}
      </motion.div>
      <motion.div
        initial={{ y: 12, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.55, delay: 0.8 }}
        className="mt-4 text-base font-mono uppercase tracking-[0.3em] text-zinc-500"
      >
        {agentCount} agents on the floor
      </motion.div>
    </div>
  );
}

function SessionPnlCard({
  pct,
  equity,
  fills,
}: {
  pct: number;
  equity: number;
  fills: number;
}) {
  const positive = pct >= 0;
  const accent = positive ? "text-(--color-profit)" : "text-(--color-loss)";
  const glow = positive
    ? "drop-shadow-[0_0_36px_rgba(16,185,129,0.45)]"
    : "drop-shadow-[0_0_36px_rgba(244,63,94,0.45)]";

  return (
    <div className="flex flex-col items-center px-12">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        Session P&amp;L
      </motion.span>
      <motion.div
        initial={{ scale: 0.85, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
        className={`mt-6 text-[200px] leading-none font-extrabold tabular-nums ${accent} ${glow}`}
      >
        {fmtSignedPct(pct)}
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.5 }}
        className="mt-8 flex items-baseline gap-4 font-mono"
      >
        <span className="text-[11px] uppercase tracking-[0.3em] text-zinc-500">
          Total equity
        </span>
        <span className="text-4xl font-bold tabular-nums text-zinc-100">
          ${fmtUsd(equity)}
        </span>
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.7 }}
        className="mt-3 text-sm font-mono uppercase tracking-[0.3em] text-zinc-500"
      >
        {fills} fills today
      </motion.div>
    </div>
  );
}

function BiggestFillCard({ fill }: { fill: RecapBiggestFill }) {
  const isBuy = fill.side === "buy";
  const sideAccent = isBuy
    ? "border-emerald-500/40 text-emerald-300 bg-emerald-500/10"
    : "border-rose-500/40 text-rose-300 bg-rose-500/10";
  return (
    <div className="flex flex-col items-center px-12 w-full max-w-[1100px]">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        Biggest fill of the day
      </motion.span>
      <motion.div
        initial={{ y: 14, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.15 }}
        className="mt-5 text-4xl font-bold tracking-tight"
      >
        {fill.agent_name ?? `agent #${fill.agent_id}`}
      </motion.div>
      <motion.div
        initial={{ y: 14, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.3 }}
        className="mt-4 flex items-center gap-3 text-2xl font-mono"
      >
        <span
          className={`text-sm uppercase font-bold px-2.5 py-1 rounded border ${sideAccent}`}
        >
          {fill.side}
        </span>
        <span className="tabular-nums text-zinc-200">
          {fill.qty.toFixed(2)}
        </span>
        <span className="font-bold tracking-tight text-zinc-100">
          {fill.symbol}
        </span>
        <span className="text-zinc-500">@</span>
        <span className="tabular-nums text-zinc-200">
          ${fmtUsd(fill.price, 2)}
        </span>
      </motion.div>
      <motion.div
        initial={{ scale: 0.9, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.55, delay: 0.5, ease: [0.22, 1, 0.36, 1] }}
        className="mt-8 text-[120px] leading-none font-extrabold tabular-nums text-zinc-100 drop-shadow-[0_0_24px_rgba(255,255,255,0.18)]"
      >
        ${fmtUsd(fill.notional)}
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.4, delay: 0.85 }}
        className="mt-4 text-xs font-mono uppercase tracking-[0.3em] text-zinc-500"
      >
        notional · {fmtRelative(fill.at)}
      </motion.div>
    </div>
  );
}

function PodiumCard({ winners }: { winners: RecapTopWinner[] }) {
  // Visual order: 2nd, 1st, 3rd.
  const first = winners[0] ?? null;
  const second = winners[1] ?? null;
  const third = winners[2] ?? null;

  return (
    <div className="flex flex-col items-center px-12 w-full max-w-[1200px]">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        Top winners
      </motion.span>

      <div className="mt-10 flex items-end justify-center gap-8 w-full">
        <PodiumStep winner={second} place={2} height={200} delay={0.15} />
        <PodiumStep winner={first} place={1} height={280} delay={0.0} glow />
        <PodiumStep winner={third} place={3} height={150} delay={0.3} />
      </div>
    </div>
  );
}

function PodiumStep({
  winner,
  place,
  height,
  delay,
  glow,
}: {
  winner: RecapTopWinner | null;
  place: 1 | 2 | 3;
  height: number;
  delay: number;
  glow?: boolean;
}) {
  const accent =
    place === 1
      ? "text-(--color-profit)"
      : place === 2
        ? "text-amber-300"
        : "text-orange-300";
  const border =
    place === 1
      ? "border-(--color-profit)/60"
      : place === 2
        ? "border-amber-400/40"
        : "border-orange-400/30";
  const bg =
    place === 1
      ? "bg-emerald-500/10"
      : place === 2
        ? "bg-amber-500/5"
        : "bg-orange-500/5";

  return (
    <motion.div
      initial={{ y: 30, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
      className="flex flex-col items-center w-[280px]"
    >
      <div className="mb-3 text-center min-h-[88px]">
        {winner ? (
          <>
            <div className="text-xl font-bold tracking-tight truncate">
              {winner.agent_name ?? `agent #${winner.agent_id}`}
            </div>
            <div className="text-xs font-mono uppercase tracking-wider text-zinc-500 mt-1">
              {winner.symbol}
            </div>
            <div className={`mt-2 text-2xl font-extrabold tabular-nums ${accent}`}>
              {fmtSigned(winner.realized_pnl)}
            </div>
          </>
        ) : (
          <div className="text-zinc-600 font-mono text-sm">—</div>
        )}
      </div>
      <div
        className={`w-full rounded-t-md border ${border} ${bg} flex items-start justify-center pt-3 ${
          glow ? "shadow-[0_0_40px_rgba(16,185,129,0.25)]" : ""
        }`}
        style={{ height }}
      >
        <span className={`text-5xl font-extrabold font-mono ${accent}`}>
          #{place}
        </span>
      </div>
    </motion.div>
  );
}

function BiggestLossCard({ loss }: { loss: RecapBiggestLoss }) {
  return (
    <div className="flex flex-col items-center px-12 w-full max-w-[1100px]">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-(--color-loss) font-mono"
      >
        Biggest loss of the day
      </motion.span>
      <div className="mt-6 w-full max-w-[860px] rounded-2xl border border-rose-500/30 bg-rose-500/5 backdrop-blur-sm px-12 py-10 flex flex-col items-center">
        <motion.div
          initial={{ y: 14, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.5, delay: 0.15 }}
          className="text-4xl font-bold tracking-tight"
        >
          {loss.agent_name ?? `agent #${loss.agent_id}`}
        </motion.div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.3 }}
          className="mt-2 text-sm font-mono uppercase tracking-[0.3em] text-zinc-500"
        >
          on {loss.symbol}
        </motion.div>
        <motion.div
          initial={{ scale: 0.9, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ duration: 0.55, delay: 0.45, ease: [0.22, 1, 0.36, 1] }}
          className="mt-8 text-[140px] leading-none font-extrabold tabular-nums text-(--color-loss) drop-shadow-[0_0_28px_rgba(244,63,94,0.45)]"
        >
          {fmtSigned(loss.realized_pnl)}
        </motion.div>
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.4, delay: 0.85 }}
          className="mt-6 text-lg font-mono uppercase tracking-[0.3em] text-rose-300/70"
        >
          ouch.
        </motion.div>
      </div>
    </div>
  );
}

function PromotionsCard({ promotions }: { promotions: RecapPromotion[] }) {
  const visible = promotions.slice(0, 4);
  const extra = promotions.length - visible.length;

  return (
    <div className="flex flex-col items-center px-12 w-full max-w-[1100px]">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        Promotions today
      </motion.span>
      <div className="mt-8 w-full max-w-[820px] flex flex-col gap-3">
        {visible.map((p, i) => (
          <motion.div
            key={`${p.agent_id}-${p.at}-${i}`}
            initial={{ x: -20, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            transition={{ duration: 0.45, delay: 0.1 + i * 0.12 }}
            className="flex items-center gap-5 rounded-lg border border-emerald-500/25 bg-emerald-500/5 px-6 py-4"
          >
            <span className="text-xl font-bold tracking-tight w-[280px] truncate">
              {p.agent_name ?? `agent #${p.agent_id}`}
            </span>
            <span className="text-sm font-mono uppercase tracking-[0.25em] text-zinc-500">
              {p.from}
            </span>
            <motion.span
              initial={{ x: -6, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              transition={{ duration: 0.4, delay: 0.25 + i * 0.12 }}
              className="text-2xl text-(--color-profit) font-bold"
            >
              →
            </motion.span>
            <span className="text-base font-mono uppercase tracking-[0.25em] text-(--color-profit) font-bold">
              {p.to}
            </span>
          </motion.div>
        ))}
        {extra > 0 && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.4, delay: 0.1 + visible.length * 0.12 }}
            className="text-center text-sm font-mono uppercase tracking-[0.3em] text-zinc-500 pt-2"
          >
            and {extra} more
          </motion.div>
        )}
      </div>
    </div>
  );
}

function PredictionsRevealCard({ predictions }: { predictions: RecapPrediction[] }) {
  const display = predictions.slice(0, 2);

  return (
    <div className="flex flex-col items-center px-12 w-full max-w-[1280px]">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.4 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        Predictions revealed
      </motion.span>
      <div className="mt-8 w-full grid grid-cols-1 md:grid-cols-2 gap-8">
        {display.map((p, i) => (
          <PredictionColumn key={p.id} prediction={p} delay={0.15 + i * 0.2} />
        ))}
      </div>
    </div>
  );
}

function PredictionColumn({
  prediction,
  delay,
}: {
  prediction: RecapPrediction;
  delay: number;
}) {
  const entries = Object.entries(prediction.tally);
  const total = entries.reduce((a, [, v]) => a + v, 0);
  const maxVotes = entries.reduce((m, [, v]) => Math.max(m, v), 1);

  return (
    <motion.div
      initial={{ y: 24, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.55, delay, ease: [0.22, 1, 0.36, 1] }}
      className="rounded-xl border border-zinc-800 bg-zinc-900/40 backdrop-blur-sm p-6"
    >
      <div className="text-lg font-bold tracking-tight leading-snug min-h-[56px]">
        {prediction.question}
      </div>
      <div className="mt-4 flex flex-col gap-2">
        {entries.map(([option, votes], i) => {
          const isWinner = prediction.winning_option === option;
          const pct = total > 0 ? (votes / total) * 100 : 0;
          const widthPct = Math.max(2, (votes / maxVotes) * 100);
          return (
            <motion.div
              key={option}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.4, delay: delay + 0.3 + i * 0.08 }}
              className={`relative rounded-md border px-4 py-2.5 ${
                isWinner
                  ? "border-(--color-profit)/60 bg-emerald-500/10"
                  : "border-zinc-800 bg-zinc-950/40"
              }`}
            >
              <div
                className={`absolute inset-y-0 left-0 rounded-md ${
                  isWinner ? "bg-emerald-500/20" : "bg-zinc-800/40"
                }`}
                style={{ width: `${widthPct}%` }}
              />
              <div className="relative flex items-center justify-between gap-3">
                <span
                  className={`font-semibold ${
                    isWinner ? "text-(--color-profit)" : "text-zinc-200"
                  }`}
                >
                  {option}
                  {isWinner && (
                    <span className="ml-2 text-[10px] uppercase tracking-[0.3em] font-mono">
                      winner
                    </span>
                  )}
                </span>
                <span className="font-mono tabular-nums text-sm text-zinc-300">
                  {votes} · {pct.toFixed(0)}%
                </span>
              </div>
            </motion.div>
          );
        })}
      </div>
      <div className="mt-4 text-[10px] uppercase tracking-[0.3em] font-mono text-zinc-500">
        {prediction.total_votes} total votes
      </div>
    </motion.div>
  );
}

function EndCard() {
  return (
    <div className="flex flex-col items-center px-12">
      <motion.span
        initial={{ y: -8, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.45 }}
        className="text-[12px] uppercase tracking-[0.5em] text-zinc-500 font-mono"
      >
        That's a wrap
      </motion.span>
      <motion.div
        initial={{ scale: 0.92, opacity: 0 }}
        animate={{ scale: 1, opacity: 1 }}
        transition={{ duration: 0.6, delay: 0.15, ease: [0.22, 1, 0.36, 1] }}
        className="mt-8 text-[72px] leading-tight font-extrabold tracking-tight text-center text-zinc-100"
      >
        Tomorrow at <span className="text-(--color-profit)">7:30 AM ET</span>
      </motion.div>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.5 }}
        className="mt-4 text-2xl font-mono uppercase tracking-[0.3em] text-zinc-400"
      >
        pre-show open
      </motion.div>
      <motion.div
        initial={{ y: 16, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.85 }}
        className="mt-16 flex items-center gap-3 opacity-80"
      >
        <img src="/favicon.svg" alt="" className="h-9 w-9" />
        <span className="text-2xl font-bold tracking-tight">
          Trade<span className="text-(--color-profit)">Farm</span>
        </span>
      </motion.div>
    </div>
  );
}
