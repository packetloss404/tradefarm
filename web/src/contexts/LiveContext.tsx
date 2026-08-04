// Single shared WebSocket for the dashboard. Mounted once in main.tsx so the
// legacy dashboard's 3 separate /ws connections (useEventFeed +
// useStreamState × 2) collapse into one. The socket opens lazily — only when
// the first consumer registers — so the new dashboard's useVodSessionLive
// (which owns its own /ws) doesn't pay for an idle connection.
//
// The provider is intentionally permissive: handlers are kept in a Set<fn>
// with stable identity so consumers can re-render freely without re-adding.
// Status is exposed via useSyncExternalStore so consumers re-render on
// connect/disconnect without paying for a Context re-render.

import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { LiveEvent, LiveEventHandler, LiveStatus } from "../hooks/useLiveEvents";

const BACKOFF_START_MS = 500;
const BACKOFF_MAX_MS = 10_000;

type Unsubscribe = () => void;

type LiveContextValue = {
  /** Subscribe a handler. Returns a cleanup that removes it. */
  addHandler: (h: LiveEventHandler) => Unsubscribe;
  /** Subscribe to status changes. Returns a cleanup that removes the listener. */
  subscribeStatus: (cb: () => void) => Unsubscribe;
  /** Read the current status (used by useSyncExternalStore). */
  getStatus: () => LiveStatus;
  /** Track consumer count (used for lazy-open / close on zero consumers). */
  incRefCount: () => Unsubscribe;
};

const LiveCtx = createContext<LiveContextValue | null>(null);

function defaultWsUrl(): string {
  const scheme = location.protocol === "https:" ? "wss:" : "ws:";
  return `${scheme}//${location.host}/ws`;
}

function isLiveEvent(v: unknown): v is LiveEvent {
  if (!v || typeof v !== "object") return false;
  const o = v as { type?: unknown; ts?: unknown; payload?: unknown };
  return typeof o.type === "string" && typeof o.ts === "string" && o.payload !== undefined;
}

export function LiveProvider({ children }: { children: ReactNode }) {
  // Refs only — value object is stable so consumers' addHandler identity
  // doesn't churn on every status flip.
  const handlersRef = useRef<Set<LiveEventHandler>>(new Set());
  const statusListenersRef = useRef<Set<() => void>>(new Set());
  const refCountRef = useRef(0);
  const statusRef = useRef<LiveStatus>("connecting");

  // Used purely to force a re-render when the WS lifecycle wants to trigger
  // a re-evaluation of `refCountRef` on the next effect pass. Without this
  // the lazy-open effect could miss the first consumer in strict mode where
  // the effect runs twice.
  const [, force] = useState(0);

  useEffect(() => {
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
      ws = new WebSocket(defaultWsUrl());

      ws.onopen = () => {
        backoff = BACKOFF_START_MS;
        setStatus("open");
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

    // Watch the ref count: open on first consumer, close on zero.
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
  }, []);

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
