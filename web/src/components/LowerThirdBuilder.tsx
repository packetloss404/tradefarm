import { useEffect, useState } from "react";
import useSWR, { mutate as globalMutate } from "swr";
import {
  api,
  type LowerThirdColor,
  type LowerThirdPayload,
  type LowerThirdPushInput,
} from "../api";

const RECENT_LIMIT = 10;
// 80 / 120 char caps are wire-shape (mirror the stream's display
// region for a 1080p-friendly banner; 80 fits two lines of the
// monospace subtitle at the design font-size without overflow).
const TITLE_MAX = 80;
const SUBTITLE_MAX = 120;
const TTL_MIN = 1;
const TTL_MAX = 120;
const TTL_DEFAULT = 8;

type ColorRadio = "profit" | "loss" | "neutral";
const COLORS: { id: ColorRadio; label: string; dotClass: string }[] = [
  { id: "profit", label: "Profit", dotClass: "bg-(--color-profit)" },
  { id: "loss", label: "Loss", dotClass: "bg-(--color-loss)" },
  { id: "neutral", label: "Neutral", dotClass: "bg-zinc-300" },
];

type PushState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "ok"; entry: LowerThirdPayload }
  | { kind: "err"; message: string };

function ageLabel(iso: string): string {
  // Server-stamped ISO -> relative age. `Date.parse` is the only
  // sane path; an unparseable string (operator typed their own
  // pushed_at via curl) falls back to "just now" rather than
  // rendering "NaN ago".
  const ms = Date.parse(iso);
  if (!Number.isFinite(ms)) return "just now";
  const sec = Math.max(0, Math.round((Date.now() - ms) / 1000));
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.round(sec / 60)}m ago`;
  return `${Math.round(sec / 3600)}h ago`;
}

function swrKeyForRecent(limit: number): string {
  return `lower_third_recent_${limit}`;
}

export function LowerThirdBuilder() {
  const [title, setTitle] = useState("");
  const [subtitle, setSubtitle] = useState("");
  const [ttl, setTtl] = useState<number>(TTL_DEFAULT);
  const [color, setColor] = useState<ColorRadio>("profit");
  const [state, setState] = useState<PushState>({ kind: "idle" });
  // Per-row busy indicator so the operator can hit "Replay" on one
  // row while the form stays usable.
  const [replaying, setReplaying] = useState<string>("");

  // Poll the recent list at a modest cadence so a re-push from
  // another browser / curl shows up without a manual refresh. SWR
  // dedupes across the page, so the same endpoint hits the wire
  // only once per interval even if multiple panels subscribe.
  const { data: recent, error: recentError } = useSWR<LowerThirdPayload[]>(
    swrKeyForRecent(RECENT_LIMIT),
    () => api.getRecentLowerThirds(RECENT_LIMIT),
    { refreshInterval: 5_000, revalidateOnFocus: true },
  );

  // Clear the success toast after a few seconds so a re-push doesn't
  // need manual cleanup. The form inputs stay populated so the
  // operator can tweak and re-push the same banner.
  useEffect(() => {
    if (state.kind !== "ok") return;
    const t = setTimeout(() => setState({ kind: "idle" }), 6000);
    return () => clearTimeout(t);
  }, [state]);

  const submit = async (input: LowerThirdPushInput): Promise<LowerThirdPayload | null> => {
    try {
      const res = await api.pushLowerThird(input);
      // Optimistic refresh of the recent-list cache so the new row
      // appears without waiting for the next 5s poll.
      void globalMutate(swrKeyForRecent(RECENT_LIMIT));
      return res;
    } catch (e) {
      setState({ kind: "err", message: e instanceof Error ? e.message : String(e) });
      return null;
    }
  };

  const onPush = async () => {
    setState({ kind: "busy" });
    const result = await submit({
      title: title.trim(),
      subtitle: subtitle.trim() || undefined,
      ttl_sec: ttl,
      color,
    });
    if (result) setState({ kind: "ok", entry: result });
    else setState({ kind: "idle" });
  };

  const onReplay = async (row: LowerThirdPayload) => {
    setReplaying(row.id);
    try {
      // Strip the original id; the server will mint a fresh one so
      // the recent-list de-dupes on the new id (otherwise the replay
      // would collapse onto the existing row).
      const result = await submit({
        title: row.title,
        subtitle: row.subtitle || undefined,
        ttl_sec: row.ttl_sec,
        color: row.color ?? undefined,
      });
      if (result) setState({ kind: "ok", entry: result });
    } finally {
      setReplaying("");
    }
  };

  const titleLen = title.length;
  const subtitleLen = subtitle.length;
  const ttlDisplay = `${ttl}s`;
  const canSubmit =
    state.kind !== "busy" && title.trim().length > 0 && titleLen <= TITLE_MAX;

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          Lower-third builder
        </div>
        <div className="font-mono text-[10px] text-zinc-500">
          {state.kind === "ok" ? (
            <span className="text-(--color-profit)">
              pushed {state.entry.id.slice(0, 8)}
            </span>
          ) : state.kind === "err" ? (
            <span className="text-(--color-loss)">error: {state.message}</span>
          ) : state.kind === "busy" ? (
            <span>pushing...</span>
          ) : (
            <span>ready</span>
          )}
        </div>
      </div>

      <div className="space-y-2">
        <div>
          <input
            type="text"
            placeholder="Title"
            value={title}
            maxLength={TITLE_MAX}
            onChange={(e) => setTitle(e.target.value)}
            className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
          />
          <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-zinc-500">
            <span>required</span>
            <span className={titleLen > TITLE_MAX ? "text-(--color-loss)" : ""}>
              {titleLen}/{TITLE_MAX}
            </span>
          </div>
        </div>

        <div>
          <input
            type="text"
            placeholder="Subtitle (optional)"
            value={subtitle}
            maxLength={SUBTITLE_MAX}
            onChange={(e) => setSubtitle(e.target.value)}
            className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
          />
          <div className="mt-1 flex items-center justify-between font-mono text-[10px] text-zinc-500">
            <span>optional</span>
            <span
              className={subtitleLen > SUBTITLE_MAX ? "text-(--color-loss)" : ""}
            >
              {subtitleLen}/{SUBTITLE_MAX}
            </span>
          </div>
        </div>

        <div className="space-y-1">
          <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider text-zinc-500">
            <span>TTL</span>
            <span className="font-mono text-zinc-300 tabular-nums">{ttlDisplay}</span>
          </div>
          <input
            type="range"
            min={TTL_MIN}
            max={TTL_MAX}
            step={1}
            value={ttl}
            onChange={(e) => setTtl(Number(e.target.value))}
            className="w-full accent-emerald-500"
          />
        </div>

        <div className="space-y-1">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            Color
          </div>
          <div className="flex flex-wrap gap-1.5">
            {COLORS.map((c) => {
              const active = color === c.id;
              return (
                <label
                  key={c.id}
                  className={`flex cursor-pointer items-center gap-1.5 rounded-sm border px-2.5 py-1 text-xs font-medium transition-colors ${
                    active
                      ? "border-(--color-profit) bg-(--color-profit)/15 text-(--color-profit)"
                      : "border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-zinc-700"
                  }`}
                >
                  <input
                    type="radio"
                    name="lower-third-color"
                    value={c.id}
                    checked={active}
                    onChange={() => setColor(c.id)}
                    className="sr-only"
                  />
                  <span className={`size-1.5 rounded-full ${c.dotClass}`} />
                  <span>{c.label}</span>
                </label>
              );
            })}
          </div>
        </div>

        <button
          onClick={() => void onPush()}
          disabled={!canSubmit}
          className="w-full rounded-sm border border-emerald-700/60 bg-emerald-900/20 px-3 py-1.5 text-xs font-medium text-emerald-100 hover:bg-emerald-900/40 disabled:opacity-50"
        >
          {state.kind === "busy" ? "Pushing..." : "Push to stream"}
        </button>
      </div>

      <div className="border-t border-zinc-800 pt-3">
        <div className="mb-2 flex items-baseline justify-between">
          <div className="text-[10px] uppercase tracking-wider text-zinc-500">
            Recent
          </div>
          <div className="font-mono text-[10px] text-zinc-500">
            {recentError
              ? "unavailable"
              : recent
                ? `${recent.length} item${recent.length === 1 ? "" : "s"}`
                : "loading..."}
          </div>
        </div>
        {recent && recent.length > 0 ? (
          <ul className="max-h-48 overflow-y-auto rounded-sm border border-zinc-800 bg-zinc-950/50 divide-y divide-zinc-800">
            {recent.map((row) => {
              const pending = replaying === row.id;
              const rowColor: LowerThirdColor = row.color ?? "profit";
              const dotClass =
                rowColor === "profit"
                  ? "bg-(--color-profit)"
                  : rowColor === "loss"
                    ? "bg-(--color-loss)"
                    : "bg-zinc-300";
              return (
                <li
                  key={row.id}
                  className="flex items-center gap-2 px-2 py-1.5"
                >
                  <span className={`size-1.5 shrink-0 rounded-full ${dotClass}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-xs text-zinc-100">
                      {row.title}
                    </div>
                    {row.subtitle && (
                      <div className="truncate font-mono text-[10px] text-zinc-500">
                        {row.subtitle}
                      </div>
                    )}
                    <div className="font-mono text-[10px] text-zinc-600">
                      {row.ttl_sec}s · {ageLabel(row.pushed_at)} · {row.id.slice(0, 8)}
                    </div>
                  </div>
                  <button
                    onClick={() => void onReplay(row)}
                    disabled={pending}
                    className="shrink-0 rounded-sm border border-zinc-700 bg-zinc-800 px-2 py-1 text-[10px] font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
                  >
                    {pending ? "..." : "Replay"}
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="px-2 py-3 text-center font-mono text-[10px] text-zinc-600">
            {recentError ? "could not load recent" : "no pushes yet"}
          </div>
        )}
      </div>
    </div>
  );
}
