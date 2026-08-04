// Single shared WebSocket for the stream app. Mounted once in App.tsx so
// the stream's 2 separate /ws connections (useStreamData + useStreamCommands)
// collapse into one. The provider accepts an optional urlOverride so the
// Tauri webview can point at a remote backend; the dev-server Vite shell
// uses the default which goes through the proxy.
//
// The socket opens lazily — only when the first consumer registers — and
// closes on zero consumers, matching the web LiveContext behaviour. The
// replay-mode send-on-open logic from the old useLiveEvents is lifted here
// so both consumers get the same handshake.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { REPLAY } from "../shared/replayMode";
import type { LiveEvent, LiveEventHandler, LiveStatus } from "../shared/useLiveEvents";

const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 10_000;

type Unsubscribe = () => void;

type LiveContextValue = {
  addHandler: (h: LiveEventHandler) => Unsubscribe;
  subscribeStatus: (cb: () => void) => Unsubscribe;
  getStatus: () => LiveStatus;
  incRefCount: () => Unsubscribe;
};

const LiveCtx = createContext<LiveContextValue | null>(null);

function defaultWsUrl(): string {
  // Inside the packaged Tauri webview `location.host` is `tauri.localhost`
  // which won't accept a websocket connection. Fall back to the local
  // FastAPI port so the broadcast app works without explicit settings.
  if (typeof location !== "undefined" && location.hostname === "tauri.localhost") {
    return "ws://127.0.0.1:8000/ws";
  }
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function isLiveEvent(v: unknown): v is LiveEvent {
  if (!v || typeof v !== "object") return false;
  const o = v as { type?: unknown; ts?: unknown; payload?: unknown };
  return typeof o.type === "string" && typeof o.ts === "string" && o.payload !== undefined;
}

export function LiveProvider({
  urlOverride,
  children,
}: {
  /** Override the WebSocket URL. Used for the Tauri build to point at a
   *  remote backend; in dev/Vite the default /ws proxy is correct. */
  urlOverride?: string;
  children: ReactNode;
}) {
  const handlersRef = useRef<Set<LiveEventHandler>>(new Set());
  const statusListenersRef = useRef<Set<() => void>>(new Set());
  const refCountRef = useRef(0);
  const statusRef = useRef<LiveStatus>("connecting");

  // Force a re-render so the lazy-open effect re-evaluates refCountRef after
  // a consumer mounts. Without this, the interval-based opener can lag one
  // tick behind a freshly-mounted consumer.
  const [, force] = useState(0);

  useEffect(() => {
    const target = urlOverride && urlOverride.length > 0 ? urlOverride : defaultWsUrl();
    let ws: WebSocket | null = null;
    let backoff = BACKOFF_START_MS;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const setStatus = (next: LiveStatus) => {
      statusRef.current = next;
      for (const cb of statusListenersRef.current) cb();
    };

    const connect = () => {
      if (disposed) return;
      setStatus("connecting");
      ws = new WebSocket(target);

      ws.onopen = () => {
        backoff = BACKOFF_START_MS;
        setStatus("open");
        // In replay mode the backend waits for an opening frame. Send it
        // eagerly so the manifest pump can start; the live path ignores
        // the absence of this frame after a short timeout.
        if (REPLAY.active && REPLAY.sessionId) {
          try {
            ws?.send(
              JSON.stringify({
                type: "replay",
                session_id: REPLAY.sessionId,
                at: REPLAY.at,
                until: REPLAY.until,
                speed: REPLAY.speed,
              }),
            );
          } catch {
            /* WS may have closed between onopen and this send — let
               onerror / onclose handle it */
          }
        }
      };
      ws.onmessage = (m) => {
        try {
          const parsed: unknown = JSON.parse(typeof m.data === "string" ? m.data : "");
          if (isLiveEvent(parsed)) {
            for (const h of handlersRef.current) h(parsed);
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onerror = () => {
        try {
          ws?.close();
        } catch {
          /* noop */
        }
      };
      ws.onclose = () => {
        if (disposed) return;
        setStatus("closed");
        // Don't auto-reconnect in replay mode — the backend will close
        // the socket cleanly once it finishes pumping the manifest
        // window, and reopening would just start the replay over.
        if (REPLAY.active) return;
        retryTimer = setTimeout(connect, backoff);
        backoff = Math.min(backoff * 2, BACKOFF_MAX_MS);
      };
    };

    const close = () => {
      disposed = true;
      if (retryTimer) {
        clearTimeout(retryTimer);
        retryTimer = null;
      }
      if (ws) {
        ws.onopen = ws.onmessage = ws.onerror = ws.onclose = null;
        try {
          ws.close();
        } catch {
          /* noop */
        }
        ws = null;
      }
      setStatus("closed");
    };

    const tick = setInterval(() => {
      if (refCountRef.current > 0 && !ws && !disposed) {
        disposed = false;
        connect();
      } else if (refCountRef.current === 0 && ws) {
        close();
      }
    }, 250);

    return () => {
      clearInterval(tick);
      close();
    };
  }, [urlOverride]);

  const value = useMemo<LiveContextValue>(
    () => ({
      addHandler: (h) => {
        handlersRef.current.add(h);
        return () => {
          handlersRef.current.delete(h);
        };
      },
      subscribeStatus: (cb) => {
        statusListenersRef.current.add(cb);
        return () => {
          statusListenersRef.current.delete(cb);
        };
      },
      getStatus: () => statusRef.current,
      incRefCount: () => {
        refCountRef.current += 1;
        force((n) => n + 1);
        return () => {
          refCountRef.current = Math.max(0, refCountRef.current - 1);
          force((n) => n + 1);
        };
      },
    }),
    [],
  );

  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}

export function useLiveContext(): LiveContextValue {
  const ctx = useContext(LiveCtx);
  if (!ctx) {
    throw new Error("useLiveContext must be used inside <LiveProvider>");
  }
  return ctx;
}
