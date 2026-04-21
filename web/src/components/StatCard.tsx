type Props = {
  label: string;
  value: string | number;
  sub?: string;
  tone?: "default" | "profit" | "loss" | "wait";
  big?: boolean;
};

const toneClass = {
  default: "text-zinc-100",
  profit: "text-(--color-profit)",
  loss: "text-(--color-loss)",
  wait: "text-(--color-wait)",
};

export function StatCard({ label, value, sub, tone = "default", big = false }: Props) {
  return (
    <div className="flex flex-col gap-1">
      <div className="text-[10px] uppercase tracking-wider text-zinc-500">{label}</div>
      <div
        className={`font-mono font-semibold tabular-nums ${toneClass[tone]} ${big ? "text-3xl" : "text-lg"}`}
      >
        {value}
      </div>
      {sub && <div className="text-[10px] text-zinc-500">{sub}</div>}
    </div>
  );
}
