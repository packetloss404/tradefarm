type Shortcut = {
  keys: string[];
  description: string;
};

type Group = {
  label: string;
  items: Shortcut[];
};

const SHORTCUTS: Group[] = [
  {
    label: "Global",
    items: [
      { keys: ["Ctrl", "K"], description: "Open command palette" },
      { keys: ["?"], description: "Show this keyboard map" },
      { keys: ["Esc"], description: "Close modal or overlay" },
    ],
  },
  {
    label: "Command palette",
    items: [
      { keys: ["↑", "↓"], description: "Move selection" },
      { keys: ["Enter"], description: "Run highlighted command" },
      { keys: ["Esc"], description: "Dismiss palette" },
    ],
  },
];

export function KeyboardMapOverlay({ open, onClose }: { open: boolean; onClose: () => void }) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      role="dialog"
      aria-modal="true"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="w-[520px] max-w-[92vw] max-h-[88vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
          <div>
            <div className="text-lg font-semibold">Keyboard shortcuts</div>
            <div className="text-[11px] uppercase tracking-wider text-zinc-500">
              press <Kbd>?</Kbd> any time to toggle
            </div>
          </div>
          <button
            onClick={onClose}
            className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
            aria-label="close"
          >
            esc
          </button>
        </header>

        <div className="space-y-5 p-5">
          {SHORTCUTS.map((group) => (
            <section
              key={group.label}
              className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4"
            >
              <div className="mb-3 text-[10px] uppercase tracking-wider text-zinc-400">
                {group.label}
              </div>
              <ul className="divide-y divide-zinc-800">
                {group.items.map((sc) => (
                  <li
                    key={`${group.label}-${sc.keys.join("+")}`}
                    className="flex items-center justify-between gap-3 py-2 text-xs"
                  >
                    <span className="text-zinc-300">{sc.description}</span>
                    <span className="flex items-center gap-1">
                      {sc.keys.map((k, i) => (
                        <span key={`${k}-${i}`} className="flex items-center gap-1">
                          {i > 0 && (
                            <span className="text-zinc-600 font-mono text-[10px]">+</span>
                          )}
                          <Kbd>{k}</Kbd>
                        </span>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}

function Kbd({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex min-w-[1.5rem] items-center justify-center rounded border border-zinc-700 bg-zinc-800 px-1.5 py-0.5 font-mono text-[11px] text-zinc-200 shadow-[inset_0_-1px_0_rgba(0,0,0,0.4)]">
      {children}
    </kbd>
  );
}
