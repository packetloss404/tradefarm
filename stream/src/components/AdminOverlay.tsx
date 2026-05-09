import { useState } from "react";
import { saveSettings, type StreamSettings } from "../settings";

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

async function quitApp(): Promise<void> {
  if (inTauri()) {
    try {
      const mod = await import("@tauri-apps/api/window");
      await mod.getCurrentWindow().close();
      return;
    } catch {
      /* fall through */
    }
  }
  // Browser fallback (dev): just close the tab if scriptable, else no-op.
  try {
    window.close();
  } catch {
    /* ignore */
  }
}

async function exitFullscreen(): Promise<void> {
  if (!inTauri()) return;
  try {
    const mod = await import("@tauri-apps/api/window");
    await mod.getCurrentWindow().setFullscreen(false);
  } catch {
    /* ignore */
  }
}

/**
 * Admin overlay (Ctrl+I). Two boxes:
 *
 *   - Settings: backend URL, WS URL, commentary toggle, ticker speed.
 *     Apply persists and reloads so REST/WS clients pick up new URLs.
 *
 *   - Actions: a Quit App button (since the broadcast window is normally
 *     fullscreen and there's no visible chrome to click an X). Also an
 *     Exit Fullscreen helper for cases where you just want to alt-tab out.
 */
export function AdminOverlay({
  initial,
  onClose,
}: {
  initial: StreamSettings;
  onClose: () => void;
}) {
  const [draft, setDraft] = useState<StreamSettings>(initial);
  const [saving, setSaving] = useState(false);

  const apply = async () => {
    setSaving(true);
    try {
      await saveSettings(draft);
      location.reload();
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="absolute inset-0 z-50 bg-black/85 backdrop-blur-md flex items-center justify-center">
      <div className="w-[1080px] max-w-[95vw] rounded-xl border border-zinc-800 bg-zinc-900 p-6 shadow-2xl">
        <div className="flex items-center justify-between mb-5">
          <div>
            <h2 className="text-xl font-semibold">Admin</h2>
            <p className="text-[11px] text-zinc-500 font-mono mt-0.5">
              Ctrl+I toggles this panel · F11 toggles fullscreen · Esc closes
            </p>
          </div>
          <button
            onClick={onClose}
            className="rounded-md border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-sm hover:bg-zinc-700"
          >
            Close
          </button>
        </div>

        <div className="grid grid-cols-2 gap-5">
          {/* Settings box */}
          <section className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-5">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-zinc-400 mb-4 font-mono">
              Settings
            </h3>
            <div className="grid grid-cols-1 gap-4">
              <Field
                label="Backend Base URL"
                hint="Empty = use Vite dev proxy. Example: http://192.168.1.10:8000"
              >
                <input
                  className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm"
                  placeholder="http://127.0.0.1:8000"
                  value={draft.backendBaseUrl}
                  onChange={(e) => setDraft({ ...draft, backendBaseUrl: e.target.value })}
                />
              </Field>
              <Field
                label="WebSocket URL"
                hint="Empty = derive from Backend URL (http -> ws)"
              >
                <input
                  className="w-full rounded-md border border-zinc-700 bg-zinc-950 px-3 py-2 font-mono text-sm"
                  placeholder="ws://127.0.0.1:8000/ws"
                  value={draft.wsUrl}
                  onChange={(e) => setDraft({ ...draft, wsUrl: e.target.value })}
                />
              </Field>
              <div className="flex items-center gap-6">
                <Toggle
                  label="Commentary captions"
                  value={draft.commentaryEnabled}
                  onChange={(v) => setDraft({ ...draft, commentaryEnabled: v })}
                />
                <Toggle
                  label="Open in fullscreen"
                  value={draft.fullscreen}
                  onChange={(v) => setDraft({ ...draft, fullscreen: v })}
                />
              </div>
              <Field label={`Ticker speed: ${draft.tickerSpeedPxPerSec} px/s`} hint="">
                <input
                  type="range"
                  min={20}
                  max={200}
                  step={5}
                  value={draft.tickerSpeedPxPerSec}
                  onChange={(e) =>
                    setDraft({ ...draft, tickerSpeedPxPerSec: parseInt(e.target.value, 10) })
                  }
                  className="w-full"
                />
              </Field>
              <Field
                label={`Pre-roll: ${draft.prerollDurationSec === 0 ? "off" : `${draft.prerollDurationSec}s`}`}
                hint="Splash card shown on launch (0 = skip)."
              >
                <input
                  type="range"
                  min={0}
                  max={15}
                  step={1}
                  value={draft.prerollDurationSec}
                  onChange={(e) =>
                    setDraft({ ...draft, prerollDurationSec: parseInt(e.target.value, 10) })
                  }
                  className="w-full"
                />
              </Field>
              <Field
                label={`Scene rotation: ${draft.sceneRotationSec === 0 ? "off (Hero only)" : `${draft.sceneRotationSec}s`}`}
                hint="Cycles Hero / Leaderboard / Brain / Strategy (0 = stay on Hero)."
              >
                <input
                  type="range"
                  min={0}
                  max={180}
                  step={5}
                  value={draft.sceneRotationSec}
                  onChange={(e) =>
                    setDraft({ ...draft, sceneRotationSec: parseInt(e.target.value, 10) })
                  }
                  className="w-full"
                />
              </Field>
              <div className="flex items-center gap-6">
                <Toggle
                  label="Audio (tick kicks, fill notes, stingers)"
                  value={draft.audioEnabled}
                  onChange={(v) => setDraft({ ...draft, audioEnabled: v })}
                />
              </div>
              <div className="flex items-center gap-6">
                <Toggle
                  label="CRT effect (scanlines + chroma)"
                  value={draft.crtEnabled}
                  onChange={(v) => setDraft({ ...draft, crtEnabled: v })}
                />
              </div>
              <Field
                label={`Audio volume: ${Math.round(draft.audioVolume * 100)}%`}
                hint=""
              >
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={Math.round(draft.audioVolume * 100)}
                  onChange={(e) =>
                    setDraft({
                      ...draft,
                      audioVolume: parseInt(e.target.value, 10) / 100,
                    })
                  }
                  className="w-full"
                />
              </Field>
            </div>
            <div className="mt-5 flex justify-end gap-3">
              <button
                onClick={() => setDraft(initial)}
                className="rounded-md border border-zinc-700 bg-zinc-800 px-4 py-2 text-sm hover:bg-zinc-700"
              >
                Revert
              </button>
              <button
                onClick={apply}
                disabled={saving}
                className="rounded-md bg-emerald-600 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-500 disabled:opacity-50"
              >
                {saving ? "Saving…" : "Apply & Reload"}
              </button>
            </div>
          </section>

          {/* Actions box */}
          <section className="rounded-lg border border-zinc-800 bg-zinc-950/60 p-5 flex flex-col">
            <h3 className="text-sm font-semibold uppercase tracking-widest text-zinc-400 mb-4 font-mono">
              Actions
            </h3>

            <div className="flex flex-col gap-3">
              <ActionButton
                label="Exit Fullscreen"
                hint="Useful when alt-tabbing won't escape the broadcast window."
                onClick={exitFullscreen}
                tone="neutral"
              />
              <ActionButton
                label="Quit App"
                hint="Closes the broadcast window. Required because there is no visible window chrome in fullscreen."
                onClick={quitApp}
                tone="danger"
              />
            </div>

            <div className="mt-auto pt-5 text-[11px] text-zinc-500 font-mono leading-relaxed">
              <div>Hot keys</div>
              <div className="mt-1 grid grid-cols-2 gap-x-4 gap-y-1 text-zinc-400">
                <span>Ctrl+I</span><span>Toggle this panel</span>
                <span>F11</span><span>Toggle fullscreen</span>
                <span>Esc</span><span>Close panel</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs uppercase tracking-wider text-zinc-400 font-mono">{label}</span>
      {children}
      {hint && <span className="text-[11px] text-zinc-600">{hint}</span>}
    </label>
  );
}

function Toggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <label className="inline-flex items-center gap-2 cursor-pointer select-none">
      <input
        type="checkbox"
        checked={value}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 accent-emerald-500"
      />
      <span className="text-sm">{label}</span>
    </label>
  );
}

function ActionButton({
  label,
  hint,
  onClick,
  tone,
}: {
  label: string;
  hint: string;
  onClick: () => void | Promise<void>;
  tone: "neutral" | "danger";
}) {
  const cls =
    tone === "danger"
      ? "border-rose-500/50 bg-rose-500/15 hover:bg-rose-500/25 text-(--color-loss)"
      : "border-zinc-700 bg-zinc-800 hover:bg-zinc-700 text-zinc-100";
  return (
    <button
      onClick={() => void onClick()}
      className={`rounded-md border px-4 py-3 text-left transition ${cls}`}
    >
      <div className="text-base font-semibold leading-tight">{label}</div>
      <div className="text-[11px] text-zinc-400 mt-1 leading-snug">{hint}</div>
    </button>
  );
}
