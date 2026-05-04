import type { ReactNode } from "react";
import { useState } from "react";
import { Panel, LiveBadge } from "./Panel";
import { usePersistedTab } from "../hooks/usePersistedTab";

export type TabSpec = {
  id: string;
  label: string;
  badge?: ReactNode;
  content: ReactNode;
};

type Props = {
  tabs: TabSpec[];
  defaultTabId?: string;
  persistKey?: string;
};

export function TabbedPanel({ tabs, defaultTabId, persistKey }: Props) {
  const initial = defaultTabId ?? tabs[0]?.id ?? "";

  const persisted = usePersistedTab(persistKey ?? "", initial);
  const transient = useState<string>(initial);

  const [activeId, setActiveId] = persistKey ? persisted : transient;

  const known = tabs.some((t) => t.id === activeId);
  const effectiveId = known ? activeId : initial;

  return (
    <Panel title="Insights" badge={<LiveBadge />}>
      <div className="-mt-1 mb-3 flex flex-wrap items-center gap-1.5 border-b border-zinc-800 pb-3">
        {tabs.map((t) => {
          const active = t.id === effectiveId;
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setActiveId(t.id)}
              aria-selected={active}
              role="tab"
              className={[
                "rounded-sm border px-2.5 py-1 text-[11px] font-medium uppercase tracking-wider transition-colors",
                active
                  ? "border-emerald-500/70 bg-emerald-500/10 text-emerald-300"
                  : "border-zinc-700 bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
              ].join(" ")}
            >
              <span>{t.label}</span>
              {t.badge !== undefined && <span className="ml-1.5">{t.badge}</span>}
            </button>
          );
        })}
      </div>

      {tabs.map((t) => (
        <div
          key={t.id}
          role="tabpanel"
          aria-labelledby={`tab-${t.id}`}
          className={t.id === effectiveId ? "" : "hidden"}
        >
          {t.content}
        </div>
      ))}
    </Panel>
  );
}
