import { useCallback, useEffect, useRef, useState } from "react";
import { apiUrl } from "../shared/api";
import {
  useLiveEvents,
  type AgentDecisionPayload,
  type LiveEvent,
} from "../shared/useLiveEvents";
import { streamAudio } from "../audio/StreamAudio";

// Re-export so consumers (DecisionLabScene, SceneRotator) can import the
// decision payload type alongside the StreamCommandsHandle.
export type AgentDecision = AgentDecisionPayload;

const HEARTBEAT_MS = 5_000;
// Cap the in-memory realtime chat buffer. The strip only ever renders the
// last ~15 messages, so anything beyond this is dead weight.
const REALTIME_CHAT_CAP = 50;

export type RealtimeChatMessage = {
  id: string;
  user: string;
  text: string;
  color: "neutral" | "member" | "moderator" | "owner";
  source: "youtube";
  at: string; // ISO timestamp from YouTube
  receivedAt: number; // wall-clock ms; used for the 5-minute recency window
};

export type BannerState = {
  title: string;
  subtitle: string;
  ttl_sec: number;
  shown_at: number;
};

export type MacroFireState = {
  id: string;
  label: string;
  color?: "profit" | "loss" | "neutral";
  subtitle?: string;
  firedAt: number;
};

export type CommentaryState = {
  id: string;
  text: string;
  kind: "color" | "play_by_play";
  source: "llm" | "fallback";
  receivedAt: number;
};

// Audience interactivity surfaces (chat-driven engagement). Pin requests are
// intentionally absent from this handle — those go through the dashboard
// approval queue, never the stream.
export type AudienceSentimentState = {
  score: number;
  up: number;
  down: number;
  windowSec: number;
};

export type AudiencePinResolvedState = {
  id: string;
  status: "approved" | "rejected";
  agentId: number | null;
  firedAt: number;
};

export type PredictionState = {
  id: string;
  question: string;
  options: string[];
  status: "open" | "locked" | "revealed";
  tally: Record<string, number>;
  locksAt: string;
  revealsAt: string;
  winningOption: string | null;
};

export type StreamCommandsHandle = {
  forceSceneId: string | null;
  setForceScene: (id: string | null) => void;
  banner: BannerState | null;
  setBanner: (b: BannerState | null) => void;
  // Effective auto-rotate state: dashboard-pushed override if present, else
  // the persisted setting passed in via args. The hook owns the override
  // and resolves it here so callers don't recombine it themselves.
  rotationEnabled: boolean;
  // Effective CRT-overlay state. Override layered on top of the persisted
  // settings.crtEnabled by `stream_crt` events.
  crtEnabled: boolean;
  // Effective scene cadence in seconds. Layered on top of settings.sceneRotationSec
  // by `stream_cadence` events. Used as `rotationSec` for SceneRotator when
  // rotationEnabled is true.
  rotationSec: number;
  // Single-slot director-moment burst pushed by the dashboard's macro fires.
  // Auto-clears ~1.5s after the event lands; re-keyed when a new event arrives.
  macroFire: MacroFireState | null;
  // Currently pinned agent id (dashboard-pushed via stream_scene). Null when
  // no pin is active. Hero/Brain scenes consume this to override their
  // default sort/sample logic and focus on a single agent.
  pinAgentId: number | null;
  // Most-recent live commentary pushed by the backend's CommentaryLoop. Null
  // until the first emission. SceneRotator forwards this to useCommentary so
  // server-side LLM takes preempt the client-side template highlights.
  commentary: CommentaryState | null;
  // Rolling buffer of real chat messages pushed by the backend's YouTube
  // Live Chat poller via `chat_message` events. Capped at REALTIME_CHAT_CAP
  // (FIFO eviction); the chat strip decides how many to actually render.
  // Empty array means "no real chat seen this session" — the strip then
  // falls back to simulated messages if `simulatedChatFallback` is on.
  realtimeChat: RealtimeChatMessage[];
  // Audience-driven sentiment gauge state. Null until the first sample.
  // The overlay gates itself on `up + down >= 3` so a degenerate single-vote
  // gauge doesn't show up on-screen — we still hold the raw tally here.
  audienceSentiment: AudienceSentimentState | null;
  // Single-slot resolution burst — only the most-recent approval/rejection
  // is exposed; auto-clears ~4s after the event lands so the banner can
  // animate in/out without manual housekeeping by SceneRotator.
  audiencePinResolved: AudiencePinResolvedState | null;
  // Live predictions keyed by prediction id. Open / locked / revealed all
  // remain in the map; the overlay decides which to render and when to
  // animate the status transition. Caller-side cleanup (e.g. evicting
  // long-revealed predictions) is not done here — the backend is expected
  // to stop re-publishing terminal states after a grace window.
  predictions: Record<string, PredictionState>;
  // Latest per-agent decisions from the most-recent ``agent_decisions_batch``
  // event. Replaced wholesale on every tick — we only ever care about
  // "this tick's thinking", and the array itself is the natural bounded
  // buffer (100 agents max). Empty array before the first batch arrives.
  latestDecisions: AgentDecision[];
};

export type UseStreamCommandsArgs = {
  wsUrlOverride?: string;
  currentScene: string;
  audioEnabled: boolean;
  audioVolume: number;
  fullscreen: boolean;
  // Persisted auto-rotate setting (stream's own admin overlay). The hook
  // layers a transient dashboard override on top of this.
  rotationEnabledFromSettings: boolean;
  // Persisted CRT-overlay setting. Override-layered same as rotation.
  crtEnabledFromSettings: boolean;
  // Persisted scene cadence (sceneRotationSec). Override-layered same as
  // rotation.
  rotationSecFromSettings: number;
  // Persisted layout mode — only published on the heartbeat so the dashboard
  // knows which UI surface is live. Layout switches go through onLayoutChange
  // (parent persists + reloads) rather than an in-memory override.
  layoutMode: "scenes" | "v1-broadcast";
  onPreroll: () => void;
  /** Called when a `stream_layout` cmd arrives. Parent should persist the
   *  setting and reload (the V1 ↔ Scenes swap requires a fresh tree). */
  onLayoutChange?: (mode: "scenes" | "v1-broadcast") => void;
  /** Called when a `stream_fullscreen` cmd arrives. Parent should call into
   *  Tauri's window API; in a plain browser this is a no-op. */
  onFullscreenChange?: (enabled: boolean) => void;
};

async function postCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  await fetch(apiUrl("/api/stream/cmd"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ type, payload }),
  });
}

/**
 * Wires the broadcast app to dashboard-driven commands and emits a periodic
 * ``stream_state`` heartbeat so the dashboard can light its "ON AIR"
 * indicator. The hook owns the in-memory force-scene + banner slots; the
 * parent (``App``/``SceneRotator``) is expected to read them and override
 * its rotator/lower-third accordingly.
 */
export function useStreamCommands(args: UseStreamCommandsArgs): StreamCommandsHandle {
  const {
    currentScene,
    audioEnabled,
    audioVolume,
    fullscreen,
    rotationEnabledFromSettings,
    crtEnabledFromSettings,
    rotationSecFromSettings,
    layoutMode,
    onPreroll,
    onLayoutChange,
    onFullscreenChange,
    wsUrlOverride,
  } = args;

  const [forceSceneId, setForceSceneId] = useState<string | null>(null);
  const [banner, setBanner] = useState<BannerState | null>(null);
  const [macroFire, setMacroFire] = useState<MacroFireState | null>(null);
  const [pinAgentId, setPinAgentId] = useState<number | null>(null);
  const [commentary, setCommentary] = useState<CommentaryState | null>(null);
  const [realtimeChat, setRealtimeChat] = useState<RealtimeChatMessage[]>([]);
  const [audienceSentiment, setAudienceSentiment] = useState<AudienceSentimentState | null>(null);
  const [audiencePinResolved, setAudiencePinResolved] = useState<AudiencePinResolvedState | null>(null);
  const [predictions, setPredictions] = useState<Record<string, PredictionState>>({});
  const [latestDecisions, setLatestDecisions] = useState<AgentDecision[]>([]);
  const audiencePinResolvedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Dedup ring so a brief WS reconnect (which sometimes replays the last
  // few messages) doesn't double-render the same chat row.
  const seenChatIds = useRef<Set<string>>(new Set());
  const [rotationEnabledOverride, setRotationEnabledOverride] = useState<boolean | null>(null);
  const [crtEnabledOverride, setCrtEnabledOverride] = useState<boolean | null>(null);
  const [rotationSecOverride, setRotationSecOverride] = useState<number | null>(null);
  const rotationEnabled = rotationEnabledOverride ?? rotationEnabledFromSettings;
  const crtEnabled = crtEnabledOverride ?? crtEnabledFromSettings;
  const rotationSec = rotationSecOverride ?? rotationSecFromSettings;
  const bannerTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const macroFireTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onPrerollRef = useRef(onPreroll);
  onPrerollRef.current = onPreroll;
  const onLayoutChangeRef = useRef(onLayoutChange);
  onLayoutChangeRef.current = onLayoutChange;
  const onFullscreenChangeRef = useRef(onFullscreenChange);
  onFullscreenChangeRef.current = onFullscreenChange;

  const setBannerSafe = useCallback((next: BannerState | null) => {
    if (bannerTimer.current) {
      clearTimeout(bannerTimer.current);
      bannerTimer.current = null;
    }
    setBanner(next);
    if (next) {
      const ttl = Math.max(1, Math.min(120, next.ttl_sec || 8));
      bannerTimer.current = setTimeout(() => setBanner(null), ttl * 1000);
    }
  }, []);

  const setMacroFireSafe = useCallback((next: MacroFireState | null) => {
    if (macroFireTimer.current) {
      clearTimeout(macroFireTimer.current);
      macroFireTimer.current = null;
    }
    setMacroFire(next);
    if (next) {
      // Dwell ~2.2s so a glanced label has time to register on stream.
      macroFireTimer.current = setTimeout(() => setMacroFire(null), 2200);
    }
  }, []);

  // 4s dwell for the "Audience pinned X" banner. The slot auto-clears so
  // SceneRotator can read the value directly and AnimatePresence handles the
  // crossfade without callers needing to track the lifecycle.
  const setAudiencePinResolvedSafe = useCallback((next: AudiencePinResolvedState | null) => {
    if (audiencePinResolvedTimer.current) {
      clearTimeout(audiencePinResolvedTimer.current);
      audiencePinResolvedTimer.current = null;
    }
    setAudiencePinResolved(next);
    if (next) {
      audiencePinResolvedTimer.current = setTimeout(
        () => setAudiencePinResolved(null),
        4000,
      );
    }
  }, []);

  useEffect(() => {
    return () => {
      if (bannerTimer.current) clearTimeout(bannerTimer.current);
      if (macroFireTimer.current) clearTimeout(macroFireTimer.current);
      if (audiencePinResolvedTimer.current) clearTimeout(audiencePinResolvedTimer.current);
    };
  }, []);

  const handler = useCallback(
    (ev: LiveEvent) => {
      switch (ev.type) {
        case "stream_scene": {
          setForceSceneId(ev.payload.scene_id || null);
          // Pin is tri-state on the wire: number sets, null clears, absent
          // means "don't touch". Use `in` to distinguish absent from null.
          if ("pin_agent_id" in ev.payload) {
            const pin = ev.payload.pin_agent_id;
            if (pin === null) setPinAgentId(null);
            else if (typeof pin === "number") setPinAgentId(pin);
          }
          break;
        }
        case "stream_banner": {
          const p = ev.payload;
          if (!p.title) {
            setBannerSafe(null);
            break;
          }
          setBannerSafe({
            title: p.title,
            subtitle: p.subtitle ?? "",
            ttl_sec: typeof p.ttl_sec === "number" ? p.ttl_sec : 8,
            shown_at: Date.now(),
          });
          break;
        }
        case "stream_audio":
          streamAudio.setEnabled(ev.payload.enabled);
          streamAudio.setVolume(ev.payload.volume);
          break;
        case "stream_preroll":
          onPrerollRef.current();
          break;
        case "stream_rotation":
          setRotationEnabledOverride(Boolean(ev.payload.enabled));
          break;
        case "stream_layout":
          if (ev.payload.mode === "scenes" || ev.payload.mode === "v1-broadcast") {
            onLayoutChangeRef.current?.(ev.payload.mode);
          }
          break;
        case "stream_crt":
          setCrtEnabledOverride(Boolean(ev.payload.enabled));
          break;
        case "stream_cadence": {
          const sec = Number(ev.payload.sec);
          if (Number.isFinite(sec) && sec >= 0) setRotationSecOverride(sec);
          break;
        }
        case "stream_fullscreen":
          onFullscreenChangeRef.current?.(Boolean(ev.payload.enabled));
          break;
        case "stream_macro_fired": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          const color =
            p.color === "profit" || p.color === "loss" || p.color === "neutral"
              ? p.color
              : undefined;
          setMacroFireSafe({
            id: p.id,
            label: typeof p.label === "string" ? p.label : "",
            color,
            subtitle: typeof p.subtitle === "string" && p.subtitle.length > 0 ? p.subtitle : undefined,
            firedAt: Date.now(),
          });
          break;
        }
        case "stream_commentary": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          if (typeof p.text !== "string" || p.text.length === 0) break;
          const kind = p.kind === "play_by_play" ? "play_by_play" : "color";
          const source = p.source === "llm" ? "llm" : "fallback";
          setCommentary({
            id: p.id,
            text: p.text,
            kind,
            source,
            receivedAt: Date.now(),
          });
          break;
        }
        case "audience_sentiment": {
          const p = ev.payload;
          if (typeof p.score !== "number" || !Number.isFinite(p.score)) break;
          // Clamp score defensively — the wire spec is [-1, 1] but a buggy
          // backend computing (up-down)/total with rounding errors could
          // overshoot by a hair. The gauge math assumes the clamped range.
          const score = Math.max(-1, Math.min(1, p.score));
          const up = Math.max(0, Math.floor(Number(p.up) || 0));
          const down = Math.max(0, Math.floor(Number(p.down) || 0));
          const windowSec = Math.max(0, Number(p.window_sec) || 0);
          setAudienceSentiment({ score, up, down, windowSec });
          break;
        }
        case "audience_pin_request":
          // Operator-only — never surfaces here. The dashboard polls REST
          // for the queue and renders the approval UI. Swallow so the
          // generic `default` branch doesn't fire.
          break;
        case "audience_pin_resolved": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          const status = p.status === "approved" ? "approved" : "rejected";
          const agentId =
            typeof p.agent_id === "number" && Number.isFinite(p.agent_id)
              ? p.agent_id
              : null;
          setAudiencePinResolvedSafe({
            id: p.id,
            status,
            agentId,
            firedAt: Date.now(),
          });
          break;
        }
        case "prediction_state": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          const status: PredictionState["status"] =
            p.status === "locked" || p.status === "revealed" ? p.status : "open";
          const tally: Record<string, number> = {};
          if (p.tally && typeof p.tally === "object") {
            for (const [k, v] of Object.entries(p.tally)) {
              const n = Number(v);
              if (Number.isFinite(n)) tally[k] = n;
            }
          }
          const next: PredictionState = {
            id: p.id,
            question: typeof p.question === "string" ? p.question : "",
            options: Array.isArray(p.options) ? p.options.filter((o): o is string => typeof o === "string") : [],
            status,
            tally,
            locksAt: typeof p.locks_at === "string" ? p.locks_at : "",
            revealsAt: typeof p.reveals_at === "string" ? p.reveals_at : "",
            winningOption: typeof p.winning_option === "string" ? p.winning_option : null,
          };
          setPredictions((prev) => ({ ...prev, [next.id]: next }));
          break;
        }
        case "agent_decisions_batch": {
          const p = ev.payload;
          if (!Array.isArray(p?.decisions)) break;
          // Defensive: ignore malformed rows so the scene never blows up on a
          // partial payload. Keep `null` LSTM slots — they're meaningful (the
          // agent is momentum-only and has no LSTM bars to render).
          const cleaned: AgentDecision[] = [];
          for (const d of p.decisions) {
            if (!d || typeof d !== "object") continue;
            if (typeof d.agent_id !== "number") continue;
            if (typeof d.agent_name !== "string") continue;
            if (d.verdict !== "trade" && d.verdict !== "wait") continue;
            cleaned.push(d as AgentDecision);
          }
          setLatestDecisions(cleaned);
          break;
        }
        case "chat_message": {
          const p = ev.payload;
          if (typeof p.id !== "string" || p.id.length === 0) break;
          if (typeof p.user !== "string" || p.user.length === 0) break;
          if (typeof p.text !== "string" || p.text.length === 0) break;
          if (seenChatIds.current.has(p.id)) break;
          seenChatIds.current.add(p.id);
          const color =
            p.color === "member" || p.color === "moderator" || p.color === "owner"
              ? p.color
              : "neutral";
          const msg: RealtimeChatMessage = {
            id: p.id,
            user: p.user,
            text: p.text,
            color,
            source: "youtube",
            at: typeof p.at === "string" ? p.at : new Date().toISOString(),
            receivedAt: Date.now(),
          };
          setRealtimeChat((prev) => {
            const next = [...prev, msg];
            // FIFO trim once we cross the cap. Also prune the dedup set so it
            // doesn't grow unbounded over a long session — keep only ids that
            // are still in the visible buffer plus a small lookback.
            if (next.length > REALTIME_CHAT_CAP) {
              const evicted = next.slice(0, next.length - REALTIME_CHAT_CAP);
              const trimmed = next.slice(next.length - REALTIME_CHAT_CAP);
              for (const e of evicted) seenChatIds.current.delete(e.id);
              return trimmed;
            }
            return next;
          });
          break;
        }
        default:
          break;
      }
    },
    [setBannerSafe, setMacroFireSafe, setAudiencePinResolvedSafe],
  );

  useLiveEvents(handler, wsUrlOverride);

  // Heartbeat — separate from the scheduler's tick stream so the dashboard
  // sees liveness even when nothing else is happening.
  const sceneRef = useRef(currentScene);
  sceneRef.current = currentScene;
  const audioEnabledRef = useRef(audioEnabled);
  audioEnabledRef.current = audioEnabled;
  const volumeRef = useRef(audioVolume);
  volumeRef.current = audioVolume;
  const fullscreenRef = useRef(fullscreen);
  fullscreenRef.current = fullscreen;
  const rotationEnabledRef = useRef(rotationEnabled);
  rotationEnabledRef.current = rotationEnabled;
  const layoutModeRef = useRef(layoutMode);
  layoutModeRef.current = layoutMode;
  const crtEnabledRef = useRef(crtEnabled);
  crtEnabledRef.current = crtEnabled;
  const rotationSecRef = useRef(rotationSec);
  rotationSecRef.current = rotationSec;
  const pinAgentIdRef = useRef(pinAgentId);
  pinAgentIdRef.current = pinAgentId;

  useEffect(() => {
    let cancelled = false;
    const beat = () => {
      if (cancelled) return;
      void postCmd("stream_state", {
        scene: sceneRef.current,
        audio_enabled: audioEnabledRef.current,
        volume: volumeRef.current,
        fullscreen: fullscreenRef.current,
        rotation_enabled: rotationEnabledRef.current,
        layout_mode: layoutModeRef.current,
        crt_enabled: crtEnabledRef.current,
        rotation_sec: rotationSecRef.current,
        pin_agent_id: pinAgentIdRef.current,
        ts: Date.now(),
      }).catch(() => {
        /* heartbeat failures are non-fatal */
      });
    };
    beat();
    const t = setInterval(beat, HEARTBEAT_MS);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const setForceScene = useCallback((id: string | null) => setForceSceneId(id), []);

  return {
    forceSceneId,
    setForceScene,
    banner,
    setBanner: setBannerSafe,
    rotationEnabled,
    crtEnabled,
    rotationSec,
    macroFire,
    pinAgentId,
    commentary,
    realtimeChat,
    audienceSentiment,
    audiencePinResolved,
    predictions,
    latestDecisions,
  };
}
