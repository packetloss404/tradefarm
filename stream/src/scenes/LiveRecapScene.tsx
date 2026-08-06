import { motion } from "framer-motion";
import { useRecapLedger, type RecapLedgerPayload } from "../hooks/useRecapLedger";
import {
  useWeeklyRollup,
  type WeeklyRollupPayload,
  type WeeklyRivalry,
} from "../hooks/useWeeklyRollup";

// 0.16.0 — 4pm ET live recap scene. Different from `RecapScene.tsx`:
// that one is a 30-second card rotator reading `/api/recap/today`
// (today's PnL, biggest fill, podium). THIS one is a single-frame
// "closing the day" card reading the broadcast ledger + weekly
// rollup, auto-activated by the `day_leader` moment the scheduler
// fires at 4:00 ET.
//
// Layout follows the design-doc mockup: KPI line / top 3 moves /
// rivalries, all inside a `LiveRecapShell` chrome. Re-uses the same
// visual vocabulary as `RecapScene.tsx` (zinc gradient + emerald
// glow) so the audience doesn't see a jarring palette swap when the
// rotator slides in.

function fmtPct(n: number, frac = 2): string {
  return `${n >= 0 ? "+" : ""}${n.toFixed(frac)}%`;
}

function fmtUsd(n: number, frac = 0): string {
  return n.toLocaleString("en-US", {
    minimumFractionDigits: frac,
    maximumFractionDigits: frac,
  });
}

function shortTime(iso: string): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "";
  // The dashboard's moment.created_at is UTC ISO; the stream renders
  // in ET (the audience is US-equity-trading), so format in ET.
  return new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(t));
}

function topMoveTitle(m: Record<string, unknown>): string {
  // The BroadcastMoment.to_payload() shape includes `title` (the
  // human-readable label). Falls back to `subtitle` if missing.
  const t = typeof m.title === "string" ? m.title : "";
  if (t) return t;
  const s = typeof m.subtitle === "string" ? m.subtitle : "";
  return s || "Moment";
}

function topMoveTrigger(m: Record<string, unknown>): string {
  // Show `trigger` (e.g. "big_win", "market_surge", "crash") so the
  // audience knows WHY this moved. Fall back to `kind` if no trigger.
  const t = typeof m.trigger === "string" ? m.trigger : "";
  if (t) return t.replace(/_/g, " ");
  const k = typeof m.kind === "string" ? m.kind : "activity";
  return k.replace(/_/g, " ");
}

function topMoveTime(m: Record<string, unknown>): string {
  // The payload's `created_at` is UTC; the audience is ET. Format in ET.
  return shortTime(typeof m.created_at === "string" ? m.created_at : "");
}

function pickWeeklyPoolPct(week: WeeklyRollupPayload | null): number | null {
  if (!week) return null;
  const p = week.pool_pnl_pct;
  return Number.isFinite(p) ? p : null;
}

function pickWeeklyStrategies(
  week: WeeklyRollupPayload | null,
): Array<{ strategy: string; pnlPct: number }> {
  if (!week) return [];
  const out: Array<{ strategy: string; pnlPct: number }> = [];
  for (const [name, info] of Object.entries(week.strategy_rollup)) {
    if (!info || typeof info !== "object") continue;
    const pct = (info as { pnlPct?: number }).pnlPct ?? 0;
    out.push({ strategy: name, pnlPct: pct });
  }
  // Sort descending by pnlPct so the "winner" is first.
  out.sort((a, b) => b.pnlPct - a.pnlPct);
  return out;
}

function pickTop3Moves(ledger: RecapLedgerPayload | null): Array<Record<string, unknown>> {
  if (!ledger) return [];
  // The backend's `top` slice is already sorted by priority desc +
  // recency, so the first 3 are what the design doc calls "top 3
  // moves". Slice defensively (the ledger can be smaller).
  return ledger.top.slice(0, 3);
}

function pickRivalries(week: WeeklyRollupPayload | null): WeeklyRivalry[] {
  if (!week) return [];
  return week.rivalries.slice(0, 2);
}

export function LiveRecapScene({ weekId }: { weekId: string | null }) {
  const { data: ledger, loading: ledgerLoading, error: ledgerError } = useRecapLedger();
  const { data: week, loading: weekLoading, error: weekError } = useWeeklyRollup(weekId);

  if (ledgerLoading || weekLoading) {
    return <LiveRecapShell><LoadingBlock label="compiling today's recap" /></LiveRecapShell>;
  }
  if (ledgerError) {
    return (
      <LiveRecapShell>
        <ErrorBlock message={`recap ledger: ${ledgerError}`} />
      </LiveRecapShell>
    );
  }
  if (weekError && weekId) {
    // Weekly rollup fetch failure is non-fatal — the daily KPI line
    // can still render. Surface the error inline rather than
    // short-circuiting the whole scene.
    // eslint-disable-next-line no-console
    console.warn("live_recap_weekly_rollup_error", weekError);
  }
  if (!ledger) {
    return <LiveRecapShell><ErrorBlock message="no recap data" /></LiveRecapShell>;
  }

  const topMoves = pickTop3Moves(ledger);
  const rivalries = pickRivalries(week);
  const strategies = pickWeeklyStrategies(week);
  const weeklyPnlPct = pickWeeklyPoolPct(week);

  return (
    <LiveRecapShell>
      {/* KPI line: today's top-line numbers (recap-ledger top-moment
          count + weekly pool PnL%). The design doc calls this the
          "TODAY'S POOL / WEEKLY ROLLUP" two-column row. */}
      <motion.div
        initial={{ y: 10, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.45 }}
        className="grid grid-cols-2 gap-x-12 w-full max-w-[1180px] mt-2"
      >
        <div>
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-500 font-mono">
            Today's pool
          </div>
          <div className="mt-2 text-5xl font-extrabold tabular-nums text-(--color-profit) drop-shadow-[0_0_22px_rgba(16,185,129,0.4)]">
            {fmtPct(weeklyPnlPct ?? 0)}
          </div>
          <div className="mt-1 text-xs font-mono text-zinc-500">
            {ledger.count} moments today
          </div>
        </div>
        <div>
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-500 font-mono">
            Weekly rollup
          </div>
          <div className="mt-2 flex flex-col gap-1 font-mono text-zinc-200">
            {strategies.length === 0 ? (
              <span className="text-zinc-500 text-sm">no sessions this week yet</span>
            ) : (
              strategies.slice(0, 2).map((s) => (
                <div key={s.strategy} className="flex items-baseline gap-2 text-base">
                  <span className="text-zinc-300 truncate">{s.strategy}</span>
                  <span className={s.pnlPct >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}>
                    {fmtPct(s.pnlPct)}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </motion.div>

      <Divider />

      {/* Top 3 moves — from the broadcast ledger's `top` slice. */}
      <motion.div
        initial={{ y: 14, opacity: 0 }}
        animate={{ y: 0, opacity: 1 }}
        transition={{ duration: 0.5, delay: 0.1 }}
        className="w-full max-w-[1180px]"
      >
        <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-500 font-mono">
          Top 3 moves
        </div>
        <div className="mt-3 flex flex-col gap-2">
          {topMoves.length === 0 ? (
            <div className="text-zinc-500 font-mono text-sm">no moments fired today</div>
          ) : (
            topMoves.map((m, i) => {
              const title = topMoveTitle(m);
              const trigger = topMoveTrigger(m);
              const at = topMoveTime(m);
              return (
                <div
                  key={typeof m.id === "string" ? m.id : `m_${i}`}
                  className="flex items-baseline gap-3 font-mono text-zinc-200"
                >
                  <span className="w-6 text-zinc-500 text-sm">#{i + 1}</span>
                  <span className="flex-1 truncate text-base">{title}</span>
                  <span className="text-xs text-zinc-500 uppercase tracking-wider">
                    {trigger}
                  </span>
                  <span className="text-xs text-zinc-500 tabular-nums">{at}</span>
                </div>
              );
            })
          )}
        </div>
      </motion.div>

      {rivalries.length > 0 && (
        <>
          <Divider />
          <motion.div
            initial={{ y: 14, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, delay: 0.2 }}
            className="w-full max-w-[1180px]"
          >
            <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-500 font-mono">
              Rivalries this week
            </div>
            <div className="mt-3 flex flex-col gap-2 font-mono text-zinc-200 text-base">
              {rivalries.map((r) => {
                const aWin = r.a_pnl >= r.b_pnl;
                return (
                  <div
                    key={`${r.a}-${r.b}-${r.symbol}`}
                    className="flex items-baseline gap-3"
                  >
                    <span className="text-zinc-300">
                      Agent {r.a} vs Agent {r.b}
                    </span>
                    <span className="text-zinc-500 text-xs">{r.symbol}</span>
                    <span className="text-xs text-zinc-500 tabular-nums">
                      {r.count} trades
                    </span>
                    <span
                      className={aWin ? "text-(--color-profit)" : "text-(--color-loss)"}
                    >
                      {`Agent ${aWin ? r.a : r.b} ${aWin ? r.a_pnl - r.b_pnl : r.b_pnl - r.a_pnl >= 0 ? "wins" : ""}`}
                    </span>
                  </div>
                );
              })}
            </div>
          </motion.div>
        </>
      )}

      {/* Lower-third with the closing-bell title. The TTL is short
          (matches the existing LowerThird component's slot timer) so
          the lower-third doesn't outlast the scene itself. */}
      <div className="absolute left-0 right-0 bottom-12 flex justify-center">
        <div className="rounded-sm border border-zinc-700 bg-zinc-900/85 backdrop-blur-sm px-4 py-2 font-mono text-xs uppercase tracking-[0.3em] text-zinc-200">
          Closing bell - today's recap
        </div>
      </div>
    </LiveRecapShell>
  );
}

function Divider() {
  return <div className="w-full max-w-[1180px] my-6 border-t border-zinc-800/80" />;
}

function LiveRecapShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="absolute inset-0 overflow-hidden bg-gradient-to-br from-zinc-950 via-zinc-900 to-zinc-950 text-zinc-100">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[1100px] h-[900px] rounded-full bg-emerald-500/10 blur-3xl" />
      </div>
      <div className="absolute inset-0 px-12 py-10 flex flex-col items-center">
        {/* Title strip at the top — mirrors the design-doc mockup's
            "CLOSING BELL · Tue Aug 5 · 47 moments today" line. */}
        <motion.div
          initial={{ y: -8, opacity: 0 }}
          animate={{ y: 0, opacity: 1 }}
          transition={{ duration: 0.45 }}
          className="self-stretch flex items-center justify-between"
        >
          <div className="text-[11px] uppercase tracking-[0.5em] text-zinc-400 font-mono">
            Closing Bell
          </div>
          <div className="text-[10px] uppercase tracking-[0.4em] text-zinc-600 font-mono">
            today's recap
          </div>
        </motion.div>
        {children}
      </div>
    </div>
  );
}

function LoadingBlock({ label }: { label: string }) {
  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center">
      <motion.div
        initial={{ opacity: 0.4 }}
        animate={{ opacity: 1 }}
        transition={{ duration: 0.9, repeat: Infinity, repeatType: "reverse" }}
        className="text-3xl font-bold tracking-tight text-zinc-300"
      >
        {label}...
      </motion.div>
    </div>
  );
}

function ErrorBlock({ message }: { message: string }) {
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

// Avoid an "unused" lint hit on the helper. `fmtUsd` is reserved
// for a future "today's biggest fill" line; the ledger payload
// doesn't currently expose that data, so the import is informational
// for the next iteration.
void fmtUsd;
