import { useState } from "react";

export type MacroColor = "profit" | "loss" | "neutral";

export type MacroStep =
  | { type: "stream_scene"; payload: { scene_id: string } }
  | { type: "stream_banner"; payload: { title: string; subtitle: string; ttl_sec: number } }
  | { type: "stream_rotation"; payload: { enabled: boolean } }
  | {
      type: "stream_macro_fired";
      payload: { id: string; label: string; color: MacroColor; subtitle?: string };
    };

export type Macro = {
  id: string;
  label: string;
  color: MacroColor;
  /** Whether the macro uses the shared subtitle input (Big win / Crash alert). */
  usesSubtitle?: boolean;
  buildSequence: (subtitle: string) => MacroStep[];
};

export const MACROS: Macro[] = [
  {
    id: "open-bell",
    label: "Open bell",
    color: "neutral",
    buildSequence: () => [
      { type: "stream_scene", payload: { scene_id: "hero" } },
      {
        type: "stream_banner",
        payload: { title: "🔔 Market open", subtitle: "Let's trade", ttl_sec: 8 },
      },
      {
        type: "stream_macro_fired",
        payload: { id: "open-bell", label: "Open bell", color: "neutral" },
      },
    ],
  },
  {
    id: "big-win",
    label: "Big win",
    color: "profit",
    usesSubtitle: true,
    buildSequence: (subtitle: string) => {
      const sub = subtitle.trim();
      return [
        { type: "stream_scene", payload: { scene_id: "leaderboard" } },
        {
          type: "stream_banner",
          payload: { title: "🏆 Big win!", subtitle: sub, ttl_sec: 8 },
        },
        {
          type: "stream_macro_fired",
          payload: {
            id: "big-win",
            label: "Big win",
            color: "profit",
            subtitle: sub || undefined,
          },
        },
      ];
    },
  },
  {
    id: "crash-alert",
    label: "Crash alert",
    color: "loss",
    usesSubtitle: true,
    buildSequence: (subtitle: string) => {
      const sub = subtitle.trim() || "Hands on the wheel";
      return [
        { type: "stream_scene", payload: { scene_id: "brain" } },
        {
          type: "stream_banner",
          payload: { title: "⚠ Crash alert", subtitle: sub, ttl_sec: 10 },
        },
        {
          type: "stream_macro_fired",
          payload: { id: "crash-alert", label: "Crash alert", color: "loss", subtitle: sub },
        },
      ];
    },
  },
  {
    id: "strategy-spotlight",
    label: "Strategy spotlight",
    color: "neutral",
    buildSequence: () => [
      { type: "stream_scene", payload: { scene_id: "strategy" } },
      {
        type: "stream_banner",
        payload: { title: "📊 Strategy breakdown", subtitle: "", ttl_sec: 6 },
      },
      {
        type: "stream_macro_fired",
        payload: { id: "strategy-spotlight", label: "Strategy spotlight", color: "neutral" },
      },
    ],
  },
  {
    id: "closing-recap",
    label: "Closing recap",
    color: "neutral",
    buildSequence: () => [
      { type: "stream_scene", payload: { scene_id: "recap" } },
      {
        type: "stream_banner",
        payload: { title: "🎬 Closing recap", subtitle: "", ttl_sec: 6 },
      },
      {
        type: "stream_macro_fired",
        payload: { id: "closing-recap", label: "Closing recap", color: "neutral" },
      },
    ],
  },
  {
    id: "reset",
    label: "Reset",
    color: "neutral",
    buildSequence: () => [
      // Empty title clears the banner (see useStreamCommands handler).
      { type: "stream_banner", payload: { title: "", subtitle: "", ttl_sec: 1 } },
      { type: "stream_rotation", payload: { enabled: true } },
      {
        type: "stream_macro_fired",
        payload: { id: "reset", label: "Reset", color: "neutral" },
      },
    ],
  },
];

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  const r = await fetch("/api/stream/cmd", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
}

export async function runMacro(macro: Macro, subtitle: string): Promise<void> {
  // Best-effort: a single failed step shouldn't swallow the burst ack or skip
  // later steps — the operator still gets the "moment" they clicked for.
  const steps = macro.buildSequence(subtitle);
  let firstErr: Error | null = null;
  for (const step of steps) {
    try {
      await postCmd(step.type, step.payload);
    } catch (e) {
      if (!firstErr) firstErr = e instanceof Error ? e : new Error(String(e));
    }
  }
  if (firstErr) throw firstErr;
}

function dotClass(color: MacroColor): string {
  if (color === "profit") return "size-1.5 rounded-full bg-(--color-profit)";
  if (color === "loss") return "size-1.5 rounded-full bg-(--color-loss)";
  return "size-1.5 rounded-full bg-zinc-500";
}

export function BroadcastMacrosSection(props: { isOnline: boolean }) {
  const { isOnline } = props;
  const [subtitle, setSubtitle] = useState("");
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");

  const onFire = async (macro: Macro) => {
    setBusy(macro.id);
    setErr("");
    try {
      await runMacro(macro, subtitle);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">Macros</div>
        <input
          type="text"
          placeholder="Subtitle (for win / crash)"
          value={subtitle}
          onChange={(e) => setSubtitle(e.target.value)}
          className="w-64 rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1 text-xs text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
        />
      </div>
      <div className="flex flex-wrap gap-1.5">
        {MACROS.map((m) => {
          const pending = busy === m.id;
          return (
            <button
              key={m.id}
              onClick={() => void onFire(m)}
              disabled={!isOnline || pending}
              className="flex items-center gap-2 rounded-sm border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs font-medium text-zinc-100 transition-colors hover:bg-zinc-700 disabled:opacity-50"
            >
              <span className={dotClass(m.color)} />
              <span>{m.label}</span>
              {pending && (
                <span className="font-mono text-[10px] text-zinc-500">firing…</span>
              )}
            </button>
          );
        })}
      </div>
      {err && (
        <div className="font-mono text-xs text-(--color-loss)">error: {err}</div>
      )}
    </div>
  );
}
