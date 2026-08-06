// 0.17.0 — WS recording control surface.
//
// The dashboard's operator UI for starting / stopping a WS frame
// recorder on the backend. Mirrors the three admin endpoints in
// `tradefarm.api.admin`:
//
//   POST /admin/ws_recording/start   — pre-arm a recorder
//   POST /admin/ws_recording/stop    — close + remove a recorder
//   GET  /admin/ws_recording/list    — list session_ids with a recording
//
// A "recording" is per-session_id: the operator picks a name
// (default: a fresh ISO timestamp), the backend opens a
// line-buffered NDJSON at `data_cache/ws_recordings/<sid>.ndjson`,
// and every frame the WS sends to the dashboard's connection
// (when the URL includes `?session_id=<sid>`) is appended.
//
// We keep this section thin: no new hooks, no SWR mutation
// helpers — the three calls are one-shot POSTs, the list is a
// 2s-poll SWR keyed on "ws-recordings". The "Replay" button
// (open `/replay/<session_id>`) is intentionally not wired —
// that needs a second WS consumer that replays the NDJSON and
// is a next-round deliverable.

import { useState } from "react";
import useSWR from "swr";

type WsRecordingList = {
  base_dir: string;
  sessions: string[];
};

type StartResponse = {
  ok: boolean;
  session_id: string;
  path: string;
  frames_recorded: number;
  already_active: boolean;
};

type StopResponse = {
  ok: boolean;
  session_id: string;
  frames_recorded: number;
  path: string;
};

const DEFAULT_BASE_DIR = "data_cache/ws_recordings";

async function fetcher<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return (await r.json()) as T;
}

async function startRecording(
  sessionId: string,
  baseDir: string,
): Promise<StartResponse> {
  const r = await fetch("/admin/ws_recording/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, base_dir: baseDir }),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`start failed: ${r.status} ${text}`);
  }
  return (await r.json()) as StartResponse;
}

async function stopRecording(sessionId: string): Promise<StopResponse> {
  const r = await fetch("/admin/ws_recording/stop", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }),
  });
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`stop failed: ${r.status} ${text}`);
  }
  return (await r.json()) as StopResponse;
}

function defaultSessionId(): string {
  // s_<YYYY-MM-DD>_<HHMM> — matches the `session.run` namespace
  // and is safe per the replay-mode id regex (alphanumeric +
  // underscore, leading alpha).
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `s_${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}`;
}

export function BroadcastRecordingSection() {
  // SWR'd list of recordings on disk. 2s poll is fine — this is
  // a low-frequency operator surface, not a hot dashboard tile.
  // No revalidation on focus: the operator is already sitting in
  // front of the panel; aggressive refetching would just churn.
  const { data, error: listError, mutate } = useSWR<WsRecordingList>(
    "/admin/ws_recording/list",
    fetcher<WsRecordingList>,
    { refreshInterval: 2000, revalidateOnFocus: false },
  );

  const [sessionInput, setSessionInput] = useState<string>(defaultSessionId);
  const [baseDir, setBaseDir] = useState<string>(DEFAULT_BASE_DIR);
  const [busy, setBusy] = useState<string>("");
  const [err, setErr] = useState<string>("");
  // Last "stopped" toast — clears itself after a few seconds so
  // the operator can fire another stop without manual housekeeping.
  const [stopToast, setStopToast] = useState<{ sid: string; n: number } | null>(null);
  // Last "started" toast — separate so the operator can see both
  // if they happen in quick succession.
  const [startToast, setStartToast] = useState<{
    sid: string;
    frames: number;
    already: boolean;
  } | null>(null);

  const sessions = data?.sessions ?? [];

  const onStart = async () => {
    const sid = sessionInput.trim();
    if (!sid) {
      setErr("session_id is required");
      return;
    }
    setBusy(`start:${sid}`);
    setErr("");
    try {
      const res = await startRecording(sid, baseDir.trim() || DEFAULT_BASE_DIR);
      setStartToast({ sid: res.session_id, frames: res.frames_recorded, already: res.already_active });
      setTimeout(() => setStartToast(null), 6000);
      await mutate();
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  const onStop = async (sid: string) => {
    setBusy(`stop:${sid}`);
    setErr("");
    try {
      const res = await stopRecording(sid);
      setStopToast({ sid: res.session_id, n: res.frames_recorded });
      setTimeout(() => setStopToast(null), 6000);
      await mutate();
    } catch (e) {
      // 404 — the session was already stopped (e.g. another panel
      // closed it). Surface the message but don't pollute the toast.
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between text-[10px] uppercase tracking-wider text-zinc-500">
        <span>WS recording</span>
        <span className="font-mono text-zinc-500 normal-case">
          {sessions.length} on disk
        </span>
      </div>

      <div className="space-y-1.5">
        <label className="block text-[10px] uppercase tracking-wider text-zinc-500">
          Session id
        </label>
        <input
          type="text"
          value={sessionInput}
          onChange={(e) => setSessionInput(e.target.value)}
          placeholder="s_2026-08-05_1430"
          className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 font-mono placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
        />
        <label className="block text-[10px] uppercase tracking-wider text-zinc-500">
          Base dir
        </label>
        <input
          type="text"
          value={baseDir}
          onChange={(e) => setBaseDir(e.target.value)}
          placeholder={DEFAULT_BASE_DIR}
          className="w-full rounded-sm border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 font-mono placeholder:text-zinc-600 focus:outline-none focus:border-zinc-500"
        />
        <button
          onClick={() => void onStart()}
          disabled={busy.startsWith("start:") || !sessionInput.trim()}
          className="w-full rounded-sm border border-emerald-700/60 bg-emerald-900/20 px-3 py-1.5 text-xs font-medium text-emerald-100 hover:bg-emerald-900/40 disabled:opacity-50"
        >
          {busy === `start:${sessionInput.trim()}` ? "Starting..." : "Start recording"}
        </button>
      </div>

      {startToast && (
        <div className="font-mono text-[10px] text-(--color-profit)">
          {startToast.already ? "already" : "started"} {startToast.sid}{" "}
          {startToast.frames > 0 ? `(${startToast.frames} prior frames)` : ""}
        </div>
      )}

      <div className="space-y-1">
        <div className="text-[10px] uppercase tracking-wider text-zinc-500">
          Recordings on disk
        </div>
        {listError && (
          <div className="font-mono text-[10px] text-(--color-loss)">
            list error: {listError.message}
          </div>
        )}
        {sessions.length === 0 && !listError && (
          <div className="font-mono text-[10px] text-zinc-500 italic">
            no recordings yet
          </div>
        )}
        <ul className="space-y-1 max-h-40 overflow-y-auto">
          {sessions.map((sid) => (
            <li
              key={sid}
              className="flex items-center justify-between gap-2 rounded-sm border border-zinc-800 bg-zinc-900/40 px-2 py-1.5"
            >
              <span className="font-mono text-[11px] text-zinc-200 truncate" title={sid}>
                {sid}
              </span>
              <button
                onClick={() => void onStop(sid)}
                disabled={busy === `stop:${sid}`}
                className="rounded-sm border border-zinc-700 bg-zinc-800 px-2 py-0.5 text-[10px] font-medium text-zinc-100 hover:bg-zinc-700 disabled:opacity-50"
              >
                {busy === `stop:${sid}` ? "Stopping..." : "Stop"}
              </button>
            </li>
          ))}
        </ul>
      </div>

      {stopToast && (
        <div className="font-mono text-[10px] text-(--color-profit)">
          stopped {stopToast.sid} ({stopToast.n} frames captured)
        </div>
      )}

      {err && (
        <div className="font-mono text-[10px] text-(--color-loss)">error: {err}</div>
      )}

      <div className="font-mono text-[10px] text-zinc-500 italic leading-snug">
        Open <span className="text-zinc-400">?session_id=&lt;sid&gt;</span> in the
        stream URL (or pass it on the dashboard's WS) to capture frames. Files
        land in <span className="text-zinc-400">{DEFAULT_BASE_DIR}</span>.
      </div>
    </div>
  );
}
