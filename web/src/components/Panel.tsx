import type { ReactNode } from "react";

export function Panel({
  title,
  badge,
  right,
  children,
  className = "",
}: {
  title?: ReactNode;
  badge?: ReactNode;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-lg border border-zinc-800 bg-zinc-900/60 p-4 ${className}`}>
      {(title || right) && (
        <header className="mb-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            {badge}
            {title && <h2 className="text-xs font-medium uppercase tracking-wider text-zinc-400">{title}</h2>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  );
}

export function LiveBadge() {
  return (
    <span className="inline-flex items-center gap-1 rounded-sm bg-emerald-600/20 px-1.5 py-0.5 text-[10px] font-bold text-emerald-400">
      <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
      LIVE
    </span>
  );
}
