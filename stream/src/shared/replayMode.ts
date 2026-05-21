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
