import type { DailyPnlPoint } from "../api";

export function MonthlyPnlChart({
  data,
  totalUnrealized,
  monthName,
}: {
  data: DailyPnlPoint[];
  totalUnrealized: number;
  monthName: string;
}) {
  const today = new Date();
  const todayStr = today.toISOString().slice(0, 10);
  const ymPrefix = todayStr.slice(0, 7);
  const monthData = data.filter((d) => d.date.startsWith(ymPrefix));

  const monthlyPnlUsd = monthData.length
    ? monthData[monthData.length - 1]!.equity - 100 * 1000
    : 0;

  const byDay = new Map(monthData.map((d) => [Number(d.date.slice(8, 10)), d.pnl_pct]));
  const daysInMonth = new Date(today.getFullYear(), today.getMonth() + 1, 0).getDate();
  const points = Array.from({ length: daysInMonth }, (_, i) => ({
    day: i + 1,
    pnlPct: byDay.get(i + 1) ?? 0,
  }));

  const absMax = Math.max(0.5, ...points.map((p) => Math.abs(p.pnlPct)));
  const ceiling = Math.ceil(absMax * 10) / 10;

  const total = monthlyPnlUsd + totalUnrealized;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div>
          <div className="text-xs uppercase tracking-wider text-zinc-400">This Month PNL</div>
          <div className="text-[10px] text-zinc-500">{monthName}</div>
        </div>
        <div className="text-right">
          <div
            className={`text-2xl font-mono font-semibold tabular-nums ${total >= 0 ? "text-(--color-profit)" : "text-(--color-loss)"}`}
          >
            {total >= 0 ? "+" : ""}
            {total.toFixed(1)} USD
          </div>
          <div className="text-[10px] text-zinc-500">
            realized {monthlyPnlUsd.toFixed(1)} · unrealized {totalUnrealized.toFixed(1)}
          </div>
        </div>
      </div>

      <div className="relative h-24 border-y border-zinc-800">
        <div className="absolute inset-y-0 left-0 flex flex-col justify-between text-[8px] text-zinc-600">
          <span>+{ceiling}%</span>
          <span>0</span>
          <span>−{ceiling}%</span>
        </div>
        <div className="ml-6 flex h-full items-center gap-[2px]">
          {points.map((d) => {
            const h = Math.min(Math.abs(d.pnlPct), ceiling) / ceiling;
            const positive = d.pnlPct >= 0;
            const isToday = d.day === today.getDate();
            return (
              <div key={d.day} className="flex-1 flex flex-col h-full justify-center">
                <div className="flex flex-col h-full w-full justify-center">
                  <div className="flex-1 flex items-end">
                    {positive && d.pnlPct !== 0 && (
                      <div
                        className={`w-full rounded-t-sm ${isToday ? "bg-emerald-300" : "bg-(--color-profit)"}`}
                        style={{ height: `${h * 100}%` }}
                      />
                    )}
                  </div>
                  <div className="flex-1 flex items-start">
                    {!positive && d.pnlPct !== 0 && (
                      <div
                        className={`w-full rounded-b-sm ${isToday ? "bg-rose-300" : "bg-(--color-loss)"}`}
                        style={{ height: `${h * 100}%` }}
                      />
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      <div className="ml-6 flex justify-between text-[9px] text-zinc-600 font-mono">
        {[1, 5, 10, 15, 20, 25, daysInMonth].map((d) => (
          <span key={d}>{d.toString().padStart(2, "0")}</span>
        ))}
      </div>
    </div>
  );
}
