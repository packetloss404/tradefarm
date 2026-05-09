// Stream-app settings: backend URL + display preferences.
// In a packaged Tauri build the values are persisted to a JSON file in
// appDataDir. In the Vite dev shell (no Tauri runtime) we fall back to
// localStorage so the same UI works in a plain browser tab for iteration.

export type StreamSettings = {
  backendBaseUrl: string;
  wsUrl: string;
  fullscreen: boolean;
  commentaryEnabled: boolean;
  tickerSpeedPxPerSec: number;
  // Pre-roll opener: 0 disables it, otherwise number of seconds to show
  // the splash card before the rotator/Hero scene takes over.
  prerollDurationSec: number;
  // Scene rotator: how many seconds each scene gets before advancing.
  // Set to 0 to disable rotation and stay on Hero.
  sceneRotationSec: number;
  // Auto-rotate scenes. When false the rotator stays on Hero (or whatever
  // scene the dashboard has forced). The cadence above is only consulted
  // when this is true. Off by default — operator drives scene selection
  // via the dashboard's BroadcastPanel scene buttons.
  rotationEnabled: boolean;
  // Web Audio: kicks on tick, piano notes on fill, promotion stinger.
  audioEnabled: boolean;
  audioVolume: number; // 0..1
  // CSS-only CRT/VHS overlay (scanlines + chroma fringe + vignette).
  crtEnabled: boolean;
  // Top-level layout selection. "scenes" keeps the existing PreRoll +
  // SceneRotator pipeline; "v1-broadcast" swaps it for the sports-broadcast
  // 1920×1080 frame (Scoreboard / Leaderboard / Race Lanes / Farm grid /
  // Plays / Lower third / Ticker). The two are mutually exclusive at runtime.
  layoutMode: "scenes" | "v1-broadcast";
};

export const DEFAULT_SETTINGS: StreamSettings = {
  // The packaged Tauri webview cannot use Vite's dev proxy, so we default
  // these to the local FastAPI backend. In Vite dev mode the same absolute
  // URLs work because the backend has CORS entries for the stream origins.
  // Override via the Admin overlay (Ctrl+I) to point at a remote machine.
  backendBaseUrl: "http://127.0.0.1:8000",
  wsUrl: "ws://127.0.0.1:8000/ws",
  fullscreen: true,
  commentaryEnabled: true,
  tickerSpeedPxPerSec: 60,
  prerollDurationSec: 5,
  sceneRotationSec: 60,
  rotationEnabled: false,
  audioEnabled: true,
  audioVolume: 0.6,
  crtEnabled: false,
  layoutMode: "scenes",
};

const SETTINGS_FILE = "stream-settings.json";
const LS_KEY = "tradefarm.stream.settings";

type TauriFs = {
  readTextFile: (path: string, opts: { baseDir: number }) => Promise<string>;
  writeTextFile: (path: string, contents: string, opts: { baseDir: number }) => Promise<void>;
  exists: (path: string, opts: { baseDir: number }) => Promise<boolean>;
  BaseDirectory: { AppData: number };
};

async function loadTauriFs(): Promise<TauriFs | null> {
  // The plugin module only exists in a Tauri runtime; importing it from a
  // plain browser tab throws. Wrap in try/catch and fall back to localStorage.
  try {
    const mod = await import("@tauri-apps/plugin-fs");
    return mod as unknown as TauriFs;
  } catch {
    return null;
  }
}

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export async function loadSettings(): Promise<StreamSettings> {
  if (inTauri()) {
    const fs = await loadTauriFs();
    if (fs) {
      try {
        const has = await fs.exists(SETTINGS_FILE, { baseDir: fs.BaseDirectory.AppData });
        if (has) {
          const txt = await fs.readTextFile(SETTINGS_FILE, { baseDir: fs.BaseDirectory.AppData });
          return { ...DEFAULT_SETTINGS, ...(JSON.parse(txt) as Partial<StreamSettings>) };
        }
      } catch {
        /* fall through to defaults */
      }
    }
  }
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (raw) return { ...DEFAULT_SETTINGS, ...(JSON.parse(raw) as Partial<StreamSettings>) };
  } catch {
    /* ignore */
  }
  return { ...DEFAULT_SETTINGS };
}

export async function saveSettings(s: StreamSettings): Promise<void> {
  if (inTauri()) {
    const fs = await loadTauriFs();
    if (fs) {
      try {
        await fs.writeTextFile(SETTINGS_FILE, JSON.stringify(s, null, 2), {
          baseDir: fs.BaseDirectory.AppData,
        });
        return;
      } catch {
        /* fall through */
      }
    }
  }
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

/** Resolve the absolute REST base; empty string means "use relative paths". */
export function restBase(s: StreamSettings): string {
  return s.backendBaseUrl.replace(/\/$/, "");
}

/** Resolve the absolute WS URL; empty string means "use relative /ws". */
export function wsTarget(s: StreamSettings): string {
  if (s.wsUrl) return s.wsUrl;
  if (s.backendBaseUrl) return s.backendBaseUrl.replace(/^http/, "ws").replace(/\/$/, "") + "/ws";
  return "";
}
