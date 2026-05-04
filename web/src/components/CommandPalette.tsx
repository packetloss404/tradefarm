import { useEffect, useMemo, useRef, useState } from "react";
import type { Command, CommandSection } from "../lib/commands";
import { fuzzyFilter } from "../lib/commands";

type Props = {
  open: boolean;
  onClose: () => void;
  commands: Command[];
};

export function CommandPalette({ open, onClose, commands }: Props) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const filtered = useMemo(() => fuzzyFilter(query, commands), [query, commands]);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    setCursor(0);
    const t = window.setTimeout(() => inputRef.current?.focus(), 0);
    return () => window.clearTimeout(t);
  }, [open]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const row = listRef.current?.querySelector<HTMLElement>(`[data-cmd-idx="${cursor}"]`);
    if (row) row.scrollIntoView({ block: "nearest" });
  }, [cursor, open]);

  if (!open) return null;

  const onKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
      return;
    }
    if (e.key === "Tab") {
      e.preventDefault();
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      if (filtered.length === 0) return;
      setCursor((c) => (c + 1) % filtered.length);
      return;
    }
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (filtered.length === 0) return;
      setCursor((c) => (c - 1 + filtered.length) % filtered.length);
      return;
    }
    if (e.key === "Enter") {
      e.preventDefault();
      const cmd = filtered[cursor];
      if (!cmd) return;
      void Promise.resolve(cmd.action()).catch((err) => console.warn("command failed", err));
      onClose();
    }
  };

  const grouped: { section: CommandSection; items: { cmd: Command; idx: number }[] }[] = [];
  filtered.forEach((cmd, idx) => {
    const last = grouped[grouped.length - 1];
    if (last && last.section === cmd.section) {
      last.items.push({ cmd, idx });
    } else {
      grouped.push({ section: cmd.section, items: [{ cmd, idx }] });
    }
  });

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 backdrop-blur-sm pt-[10vh]"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      onKeyDown={onKey}
    >
      <div
        className="flex h-[80vh] w-[600px] max-w-[92vw] flex-col overflow-hidden rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl"
        role="dialog"
        aria-modal="true"
      >
        <div className="border-b border-zinc-800 p-3">
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command…"
            className="w-full rounded-sm border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm text-zinc-100 outline-none placeholder:text-zinc-600 focus:border-emerald-600"
            spellCheck={false}
            autoComplete="off"
          />
        </div>
        <div ref={listRef} className="flex-1 overflow-y-auto py-1">
          {grouped.length === 0 && (
            <div className="px-4 py-6 text-center text-xs text-zinc-500">No matching commands.</div>
          )}
          {grouped.map((group) => (
            <div key={group.section}>
              <div className="px-3 pt-3 pb-1 text-[10px] font-medium uppercase tracking-wider text-zinc-500">
                {group.section}
              </div>
              {group.items.map(({ cmd, idx }) => {
                const selected = idx === cursor;
                return (
                  <button
                    key={cmd.id}
                    data-cmd-idx={idx}
                    onMouseEnter={() => setCursor(idx)}
                    onClick={() => {
                      void Promise.resolve(cmd.action()).catch((err) =>
                        console.warn("command failed", err),
                      );
                      onClose();
                    }}
                    className={`flex w-full items-center justify-between gap-3 border-l-2 px-3 py-2 text-left text-sm ${
                      selected
                        ? "border-emerald-500 bg-zinc-800 text-zinc-100"
                        : "border-transparent text-zinc-300 hover:bg-zinc-800/60"
                    }`}
                  >
                    <span className="font-semibold">{cmd.label}</span>
                    {cmd.hint && (
                      <span className="truncate text-xs font-mono text-zinc-500">{cmd.hint}</span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </div>
        <div className="flex items-center justify-between border-t border-zinc-800 px-3 py-1.5 text-[10px] font-mono text-zinc-500">
          <span>↑↓ navigate · Enter run · Esc close</span>
          <span>{filtered.length} match{filtered.length === 1 ? "" : "es"}</span>
        </div>
      </div>
    </div>
  );
}
