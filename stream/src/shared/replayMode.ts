// Replay mode flag — parsed once from the URL at module load. Set
// by the headless renderer (and any operator who hand-types
// `?replay=…&at=…` for debugging).
//
// When active, the REST fetcher appends `?at=&session_id=` to every
// /api/* call so the backend returns historical state from the
// session's manifest. The WS client switches to its replay handshake
// (see useLiveEvents.ts).
//
// Wall-clock-derived UI (banner TTLs, "X seconds ago" formatters,
// recap ET-hour eligibility) still uses Date.now() in this round —
// they'll show as cosmetic glitches in replay capture but won't
// break the basic snapshot. Fixing those is a follow-up.

export type ReplayMode = {
  active: boolean;
  sessionId: string | null;
  at: string | null;
  until: string | null;
  speed: number;
  scene: string | null;
};

function read(): ReplayMode {
  if (typeof window === "undefined") {
    return { active: false, sessionId: null, at: null, until: null, speed: 60, scene: null };
  }
  const params = new URLSearchParams(window.location.search);
  const sessionId = params.get("replay");
  if (!sessionId) {
    return { active: false, sessionId: null, at: null, until: null, speed: 60, scene: null };
  }
  const speedRaw = params.get("speed");
  const speed = speedRaw ? Number.parseFloat(speedRaw) : 60;
  return {
    active: true,
    sessionId,
    at: params.get("at"),
    until: params.get("until"),
    speed: Number.isFinite(speed) ? speed : 60,
    scene: params.get("scene"),
  };
}

export const REPLAY: ReplayMode = read();

/** Append `?at=&session_id=` (or `&at=&session_id=`) to a REST path
 *  when replay mode is active. No-op otherwise. */
export function withReplayParams(path: string): string {
  if (!REPLAY.active || !REPLAY.sessionId) return path;
  const sep = path.includes("?") ? "&" : "?";
  const parts = [`session_id=${encodeURIComponent(REPLAY.sessionId)}`];
  if (REPLAY.at) parts.push(`at=${encodeURIComponent(REPLAY.at)}`);
  return `${path}${sep}${parts.join("&")}`;
}

// ─── replayNow() shim ────────────────────────────────────────────────
// Audit fix (H11): banner TTLs, "X seconds ago" formatters, recap
// eligibility, chapter labels — all of these were calling Date.now()
// directly, which means a replay capture rendered them with wall-clock
// today instead of the replayed timestamp. Result: a 2024 session's
// recap card would say "2 years ago" and a banner would expire in
// real-time while the replayed events were time-compressed.
//
// `replayNow()` returns the replayed timestamp when active, else
// `Date.now()`. Drop-in replacement at every wall-clock callsite.
//
// `REPLAY.at` is the start of the replay window; with `speed > 1` the
// effective "now" advances faster than wall time. We approximate the
// effective now as `at + (real_now - replay_started_at) * speed`,
// where replay_started_at is captured once at module load. Cheap and
// gives the UI a coherent monotonic clock across the run.

const _wallStartAtModuleLoad = Date.now();
const _replayStartParsed: number | null = (() => {
  if (!REPLAY.active || !REPLAY.at) return null;
  const t = Date.parse(REPLAY.at);
  return Number.isFinite(t) ? t : null;
})();

export function replayNow(): number {
  if (!REPLAY.active || _replayStartParsed === null) return Date.now();
  const elapsed = Date.now() - _wallStartAtModuleLoad;
  return _replayStartParsed + elapsed * REPLAY.speed;
}

/** Replayable Date() factory: returns a fresh Date object that
 *  reflects the replayed clock when active, else wall now. */
export function replayDate(): Date {
  return new Date(replayNow());
}
