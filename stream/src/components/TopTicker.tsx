import { useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { api, type AccountSummary, type AdminConfig } from "../shared/api";

const SPARK_BUFFER_SIZE = 30;
const ADMIN_CONFIG_REFRESH_MS = 60_000;
const COUNTDOWN_SOON_THRESHOLD_SEC = 60;

function fmtUsd(n: number): string {
  return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

function fmtSign(n: number, frac = 2): string {
  const sign = n >= 0 ? "+" : "";
  return `${sign}${n.toFixed(frac)}`;
}

function tickAge(iso: string | null): string {
  if (!iso) return "never";
  const sec = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

export function TopTicker({
  account,
  agentCount,
  wsStatus,
}: {
  account: AccountSummary | null;
  agentCount: number;
  wsStatus: "connecting" | "open" | "closed";
}) {
  // Rolling 30-tick equity buffer. Pushed once per snapshot delivery — SWR
  // returns a fresh `account` reference on every poll, and the WS account
  // event also swaps the live reference in `useStreamData`, so identity
  // comparison via the dependency array is the right trigger.
  const bufferRef = useRef<number[]>([]);
  const [spark, setSpark] = useState<number[]>([]);
  useEffect(() => {
    if (!account) return;
    const buf = bufferRef.current;
    buf.push(account.total_equity);
    if (buf.length > SPARK_BUFFER_SIZE) buf.shift();
    setSpark([...buf]);
  }, [account]);

  if (!account) {
    return (
      <div className="h-[60px] flex items-center px-8 bg-zinc-950/90 border-b border-zinc-800">
        <span className="text-zinc-500 text-sm font-mono">connecting…</span>
      </div>
    );
  }

  const totalAllocated = agentCount * 1000;
  const todayPnl = account.total_equity - totalAllocated;
  const todayPct = totalAllocated > 0 ? (todayPnl / totalAllocated) * 100 : 0;
  const tone = todayPnl >= 0 ? "text-(--color-profit)" : "text-(--color-loss)";
  const wsColor =
    wsStatus === "open" ? "text-emerald-500" : wsStatus === "connecting" ? "text-amber-500" : "text-rose-500";

  return (
    <div className="h-[60px] flex items-center justify-between px-8 bg-gradient-to-b from-zinc-950 via-zinc-950/95 to-zinc-950/80 border-b border-zinc-800">
      <div className="flex items-center gap-3">
        <img src="/favicon.svg" alt="" className="h-7 w-7" />
        <h1 className="text-xl font-semibold tracking-tight">
          Trade<span className="text-(--color-profit)">Farm</span>
        </h1>
        <span className="text-zinc-500 text-xs font-mono ml-1 mt-1">live</span>
      </div>

      <div className="flex items-center gap-8">
        <div className="flex items-center gap-2">
          <Stat label="Equity" value={`$${fmtUsd(account.total_equity)}`} />
          <EquitySparkline values={spark} />
        </div>
        <Stat
          label="Today"
          value={`${fmtSign(todayPnl, 0)} USD`}
          sub={`${fmtSign(todayPct, 3)}%`}
          tone={todayPnl >= 0 ? "profit" : "loss"}
        />
        <Stat
          label="Realized"
          value={`${fmtSign(account.realized_pnl)}`}
          tone={account.realized_pnl >= 0 ? "profit" : "loss"}
        />
        <Stat
          label="Unrealized"
          value={`${fmtSign(account.unrealized_pnl)}`}
          tone={account.unrealized_pnl >= 0 ? "profit" : "loss"}
        />
        <div className="flex items-center gap-3 pl-6 border-l border-zinc-800">
          <Pill label="Profit" value={account.profit_ai} tone="profit" />
          <Pill label="Loss" value={account.loss_ai} tone="loss" />
          <Pill label="Wait" value={account.waiting_ai} tone="wait" />
        </div>
      </div>

      <div className="flex items-center gap-3 text-xs font-mono text-zinc-500">
        <TickCountdownRing lastTickIso={account.last_tick_at} />
        <span>last tick {tickAge(account.last_tick_at)}</span>
        <span className={wsColor}>● ws:{wsStatus}</span>
      </div>

      {/* Tone hint span — keeps Tailwind from purging the dynamic class */}
      <span className={`hidden ${tone}`} />
    </div>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "profit" | "loss" | "wait";
}) {
  const toneCls =
    tone === "profit" ? "text-(--color-profit)" : tone === "loss" ? "text-(--color-loss)" : "text-zinc-100";
  return (
    <div className="flex flex-col items-end leading-none">
      <span className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</span>
      <span className={`mt-0.5 text-lg font-semibold tabular-nums ${toneCls}`}>{value}</span>
      {sub && <span className={`text-[11px] tabular-nums ${toneCls} opacity-80`}>{sub}</span>}
    </div>
  );
}

function Pill({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone: "profit" | "loss" | "wait";
}) {
  const toneCls =
    tone === "profit"
      ? "bg-emerald-500/10 text-(--color-profit) border-emerald-500/30"
      : tone === "loss"
        ? "bg-rose-500/10 text-(--color-loss) border-rose-500/30"
        : "bg-zinc-500/10 text-(--color-wait) border-zinc-500/30";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-mono ${toneCls}`}>
      <span className="opacity-70">{label}</span>
      <span className="tabular-nums font-semibold">{value}</span>
    </span>
  );
}

const COUNTDOWN_SIZE = 30;
const COUNTDOWN_STROKE = 3;
const COUNTDOWN_RADIUS = (COUNTDOWN_SIZE - COUNTDOWN_STROKE) / 2;
const COUNTDOWN_CIRCUMFERENCE = 2 * Math.PI * COUNTDOWN_RADIUS;

function fmtMmSs(secs: number): string {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function TickCountdownRing({ lastTickIso }: { lastTickIso: string | null }) {
  const { data: cfg } = useSWR<AdminConfig>("stream-admin-config", api.adminConfig, {
    refreshInterval: ADMIN_CONFIG_REFRESH_MS,
    shouldRetryOnError: false,
    revalidateOnFocus: false,
  });
  const intervalSec = cfg?.auto_tick_interval_sec ?? 0;

  const [now, setNow] = useState<number>(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (intervalSec <= 0 || lastTickIso === null) {
    return (
      <span
        className="inline-flex items-center justify-center font-mono text-[8px] text-zinc-600"
        style={{ width: COUNTDOWN_SIZE, height: COUNTDOWN_SIZE }}
        title="Auto-tick disabled"
      >
        OFF
      </span>
    );
  }

  const lastTickMs = new Date(lastTickIso).getTime();
  const intervalMs = intervalSec * 1000;
  const elapsedMs = Math.max(0, now - lastTickMs);
  const secsToNext = Math.max(0, Math.ceil((intervalMs - elapsedMs) / 1000));
  const progress = Math.min(1, Math.max(0, 1 - elapsedMs / intervalMs));

  const stroke = secsToNext <= COUNTDOWN_SOON_THRESHOLD_SEC ? "var(--color-profit)" : "#f59e0b";
  const dashOffset = COUNTDOWN_CIRCUMFERENCE * (1 - progress);

  return (
    <div
      className="relative"
      style={{ width: COUNTDOWN_SIZE, height: COUNTDOWN_SIZE }}
      title={`Next tick in ${secsToNext}s`}
    >
      <svg width={COUNTDOWN_SIZE} height={COUNTDOWN_SIZE} className="-rotate-90">
        <circle
          cx={COUNTDOWN_SIZE / 2}
          cy={COUNTDOWN_SIZE / 2}
          r={COUNTDOWN_RADIUS}
          stroke="rgba(63,63,70,0.6)"
          strokeWidth={COUNTDOWN_STROKE}
          fill="none"
        />
        <circle
          cx={COUNTDOWN_SIZE / 2}
          cy={COUNTDOWN_SIZE / 2}
          r={COUNTDOWN_RADIUS}
          stroke={stroke}
          strokeWidth={COUNTDOWN_STROKE}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={COUNTDOWN_CIRCUMFERENCE}
          strokeDashoffset={dashOffset}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center font-mono text-[8px] tabular-nums text-zinc-300">
        {fmtMmSs(secsToNext)}
      </div>
    </div>
  );
}

const SPARK_W = 64;
const SPARK_H = 22;

function EquitySparkline({ values }: { values: number[] }) {
  if (values.length < 2) {
    return <span className="inline-block" style={{ width: SPARK_W, height: SPARK_H }} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const stepX = SPARK_W / (values.length - 1);
  const points = values
    .map((v, i) => {
      const x = i * stepX;
      const y = SPARK_H - ((v - min) / span) * SPARK_H;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const first = values[0] as number;
  const last = values[values.length - 1] as number;
  const stroke = last >= first ? "var(--color-profit)" : "var(--color-loss)";
  return (
    <svg
      width={SPARK_W}
      height={SPARK_H}
      className="overflow-visible"
      role="img"
      aria-label="rolling equity"
    >
      <polyline
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        points={points}
      />
    </svg>
  );
}
