import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { StreamSnapshot } from "./useStreamData";
import { useMarketClock } from "./useMarketClock";
import type { MarketPhase } from "../shared/api";

export type ChatTone = "hype" | "salty" | "neutral" | "wow";

export type ChatMessage = {
  id: string;
  user: string;
  text: string;
  tone: ChatTone;
  at: number;
};

export type UseSimulatedChatOpts = {
  enabled?: boolean;
  /** Hard cap on visible buffer; default 15. */
  maxVisible?: number;
  /** Min ms between idle filler messages. Default 4000. */
  idleMinMs?: number;
  /** Max ms between idle filler messages. Default 8000. */
  idleMaxMs?: number;
};

const DEFAULT_OPTS: Required<UseSimulatedChatOpts> = {
  enabled: true,
  maxVisible: 15,
  idleMinMs: 4_000,
  idleMaxMs: 8_000,
};

const BIG_FILL_NOTIONAL = 50;
const BIG_LOSS_PCT = -0.05; // -5% unrealized vs equity proxy
const QUIET_MS = 30_000;
const REACTION_BURST_MAX = 3;
const REACTION_WINDOW_MS = 3_000;

// Add new usernames here. Keep the twitch flavor (lowercase, numbers, mixed
// cool/silly). They're chosen at random per emission.
const USERNAMES: readonly string[] = [
  "traderbro",
  "xX_quant_Xx",
  "lambo_or_food",
  "mom_check_my_pnl",
  "paper_hands_pete",
  "diamond_dan",
  "spy_or_die",
  "wendys_tendies",
  "thetagang_91",
  "yolo_yvette",
  "calls_only",
  "vix_or_vex",
  "rugpull_rita",
  "bagholder_bob",
  "fomo_frank",
  "no_stop_steve",
  "fed_pivot_now",
  "powell_pls",
  "rotation_riley",
  "macro_mike_",
  "lstm_lulu",
  "bid_ask_bandit",
  "tape_reader",
  "scalpz",
  "the_real_lambo",
  "buffett_jr",
  "wsb_refugee",
  "long_tom_short",
  "candle_cartel",
  "rsi_ricky",
  "anon_alpha",
  "options_owl",
  "tendieboy",
  "marginal_marge",
  "pump_my_bags",
];

// Add new templates here keyed by source. `{user}`, `{agent}`, `{symbol}`,
// `{random_agent_name}` are substituted at emit time.
type Template = { text: string; tone: ChatTone };

const T_BIG_FILL: readonly Template[] = [
  { text: "WOW {agent} loaded up on {symbol}!", tone: "wow" },
  { text: "that's a big swing", tone: "neutral" },
  { text: "someone's confident", tone: "neutral" },
  { text: "{agent} ALL IN??", tone: "wow" },
  { text: "size kings only", tone: "hype" },
  { text: "this man {agent} is unhinged", tone: "salty" },
  { text: "{symbol} go brrr", tone: "hype" },
  { text: "imagine the fees", tone: "salty" },
];

const T_PROMOTION: readonly Template[] = [
  { text: "GG {agent}!", tone: "hype" },
  { text: "deserved", tone: "hype" },
  { text: "from intern to junior, character arc", tone: "neutral" },
  { text: "{agent} ascending", tone: "hype" },
  { text: "POG {agent}", tone: "hype" },
  { text: "{agent} finally cooked", tone: "hype" },
];

const T_DEMOTION: readonly Template[] = [
  { text: "F in chat for {agent}", tone: "salty" },
  { text: "we knew it was coming", tone: "salty" },
  { text: "{agent} demoted, called it", tone: "salty" },
  { text: "back to the minors", tone: "neutral" },
  { text: "intern arc real", tone: "salty" },
];

const T_BIG_LOSS: readonly Template[] = [
  { text: "ouch.", tone: "salty" },
  { text: "F", tone: "salty" },
  { text: "stop loss when", tone: "salty" },
  { text: "{agent} is bleeding out", tone: "salty" },
  { text: "this is painful to watch", tone: "salty" },
  { text: "bagholder energy from {agent}", tone: "salty" },
  { text: "rip {agent} portfolio", tone: "salty" },
];

const T_QUIET: readonly Template[] = [
  { text: "anyone home?", tone: "neutral" },
  { text: "lull", tone: "neutral" },
  { text: "zzz", tone: "neutral" },
  { text: "where are the trades", tone: "salty" },
  { text: "is this thing on", tone: "neutral" },
  { text: "popcorn time i guess", tone: "neutral" },
];

const T_OPEN: readonly Template[] = [
  { text: "lfg open", tone: "hype" },
  { text: "bell rang let's gooo", tone: "hype" },
  { text: "first 5 mins are the wildest", tone: "hype" },
  { text: "{random_agent_name} you better be awake", tone: "neutral" },
];

const T_CLOSE: readonly Template[] = [
  { text: "closing soon, place bets", tone: "neutral" },
  { text: "MOC orders incoming", tone: "neutral" },
  { text: "last 10 mins always cooks", tone: "hype" },
  { text: "calling it now: SPY closes red", tone: "salty" },
];

const T_AFTERHOURS: readonly Template[] = [
  { text: "after hours = where dreams die", tone: "salty" },
  { text: "low volume crime scene", tone: "neutral" },
  { text: "ER szn", tone: "neutral" },
];

const T_PREMARKET: readonly Template[] = [
  { text: "premarket is rigged", tone: "salty" },
  { text: "futures looking spicy", tone: "hype" },
  { text: "watch the open print", tone: "neutral" },
];

const T_IDLE: readonly Template[] = [
  { text: "I'm rooting for {random_agent_name}", tone: "hype" },
  { text: "this is better than CNBC", tone: "hype" },
  { text: "who's pinned?", tone: "neutral" },
  { text: "{random_agent_name} is my guy", tone: "hype" },
  { text: "the LSTM agents always front-run", tone: "salty" },
  { text: "lol the intern is up again", tone: "neutral" },
  { text: "imagine paying for a bloomberg terminal", tone: "salty" },
  { text: "muting the chat won't help me cope", tone: "salty" },
  { text: "this is peak content", tone: "hype" },
  { text: "buy SPY hold SPY pray to SPY", tone: "hype" },
  { text: "anyone else just here for the vibes", tone: "neutral" },
  { text: "i could do better than {random_agent_name}", tone: "salty" },
  { text: "100 agents fighting over crumbs", tone: "neutral" },
  { text: "promote my boy {random_agent_name}", tone: "hype" },
];

function pick<T>(arr: readonly T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]!;
}

function fmtMessage(
  tpl: Template,
  ctx: { agent?: string; symbol?: string; randomAgent?: string },
): string {
  return tpl.text
    .replaceAll("{agent}", ctx.agent ?? "someone")
    .replaceAll("{symbol}", ctx.symbol ?? "the tape")
    .replaceAll("{random_agent_name}", ctx.randomAgent ?? "someone");
}

function phaseTemplates(phase: MarketPhase): readonly Template[] | null {
  if (phase === "rth") return T_OPEN; // emitted only at transition; see below
  if (phase === "premarket") return T_PREMARKET;
  if (phase === "afterhours") return T_AFTERHOURS;
  return null;
}

let nextId = 0;
function makeId(): string {
  nextId += 1;
  return `chat-${Date.now().toString(36)}-${nextId.toString(36)}`;
}

function fillKey(ts: string, agentId: number, symbol: string, qty: number, price: number): string {
  return `${ts}-${agentId}-${symbol}-${qty}-${price}`;
}

function promoKey(ts: string, agentId: number, toRank: string): string {
  return `${ts}-${agentId}-${toRank}`;
}

/**
 * Simulated Twitch-style chat. Emits jittered idle messages plus event-driven
 * reaction bursts when fills, promotions, or big losses occur. Pure
 * client-side — no network calls.
 */
export function useSimulatedChat(
  snapshot: StreamSnapshot,
  opts: UseSimulatedChatOpts = {},
): { messages: ChatMessage[] } {
  const cfg = { ...DEFAULT_OPTS, ...opts };
  const { phase } = useMarketClock();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const seenFills = useRef(new Set<string>());
  const seenPromos = useRef(new Set<string>());
  const flaggedLossAgents = useRef(new Map<number, number>()); // agentId -> when re-flagging is allowed
  // Seed both refs to mount time so the first idle tick doesn't compute a
  // huge `quietFor` against `0` and immediately fire the "zzz / anyone home"
  // burst before any real activity has had a chance to happen.
  const lastAnyMsgAt = useRef<number>(Date.now());
  const quietFiredAt = useRef<number>(Date.now());
  const lastPhase = useRef<MarketPhase | null>(null);
  const phaseFiredAt = useRef<number>(0);

  // Agent name lookup, memoized for stable random-agent picks.
  const agentNames = useMemo(
    () => snapshot.agents.map((a) => a.name).filter((n): n is string => Boolean(n)),
    [snapshot.agents],
  );
  const agentById = useMemo(() => {
    const m = new Map<number, string>();
    for (const a of snapshot.agents) m.set(a.id, a.name);
    return m;
  }, [snapshot.agents]);

  const pushMessages = useCallback(
    (incoming: ChatMessage[]) => {
      if (incoming.length === 0) return;
      lastAnyMsgAt.current = Date.now();
      setMessages((prev) => {
        const merged = [...prev, ...incoming];
        const overflow = merged.length - cfg.maxVisible;
        return overflow > 0 ? merged.slice(overflow) : merged;
      });
    },
    [cfg.maxVisible],
  );

  const scheduleBurst = useCallback(
    (templates: readonly Template[], ctx: { agent?: string; symbol?: string }) => {
      if (!cfg.enabled) return;
      const count = 1 + Math.floor(Math.random() * REACTION_BURST_MAX); // 1..3
      const picks: Template[] = [];
      const usedIdx = new Set<number>();
      for (let i = 0; i < count && picks.length < templates.length; i += 1) {
        let idx = Math.floor(Math.random() * templates.length);
        let guard = 0;
        while (usedIdx.has(idx) && guard < 8) {
          idx = Math.floor(Math.random() * templates.length);
          guard += 1;
        }
        usedIdx.add(idx);
        const tpl = templates[idx];
        if (tpl) picks.push(tpl);
      }
      picks.forEach((tpl, i) => {
        const delay = Math.floor((REACTION_WINDOW_MS / Math.max(picks.length, 1)) * i)
          + Math.floor(Math.random() * 400);
        setTimeout(() => {
          const random = agentNames.length > 0 ? pick(agentNames) : undefined;
          pushMessages([
            {
              id: makeId(),
              user: pick(USERNAMES),
              text: fmtMessage(tpl, { ...ctx, randomAgent: random }),
              tone: tpl.tone,
              at: Date.now(),
            },
          ]);
        }, delay);
      });
    },
    [agentNames, cfg.enabled, pushMessages],
  );

  // Fill detection
  useEffect(() => {
    if (!cfg.enabled || snapshot.fills.length === 0) return;
    for (const f of snapshot.fills) {
      const key = fillKey(f.ts, f.payload.agent_id, f.payload.symbol, f.payload.qty, f.payload.price);
      if (seenFills.current.has(key)) continue;
      seenFills.current.add(key);
      const notional = Math.abs(f.payload.qty * f.payload.price);
      if (notional < BIG_FILL_NOTIONAL) continue;
      const agentName = agentById.get(f.payload.agent_id) ?? `Agent #${f.payload.agent_id}`;
      scheduleBurst(T_BIG_FILL, { agent: agentName, symbol: f.payload.symbol });
    }
  }, [snapshot.fills, agentById, cfg.enabled, scheduleBurst]);

  // Promotion / demotion detection
  useEffect(() => {
    if (!cfg.enabled || snapshot.promotions.length === 0) return;
    for (const p of snapshot.promotions) {
      const key = promoKey(p.ts, p.payload.agent_id, p.payload.to_rank);
      if (seenPromos.current.has(key)) continue;
      seenPromos.current.add(key);
      const templates = p.type === "promotion" ? T_PROMOTION : T_DEMOTION;
      scheduleBurst(templates, { agent: p.payload.agent_name });
    }
  }, [snapshot.promotions, cfg.enabled, scheduleBurst]);

  // Big-loss detection (snapshot-poll based — fire at most once per agent
  // every 60s while still in loss territory)
  useEffect(() => {
    if (!cfg.enabled) return;
    const now = Date.now();
    for (const a of snapshot.agents) {
      const equity = a.equity || 1;
      const lossPct = a.unrealized_pnl / equity;
      if (lossPct > BIG_LOSS_PCT) {
        // recovered — clear the flag so it can fire again next time
        flaggedLossAgents.current.delete(a.id);
        continue;
      }
      const cooldownUntil = flaggedLossAgents.current.get(a.id) ?? 0;
      if (now < cooldownUntil) continue;
      flaggedLossAgents.current.set(a.id, now + 60_000);
      scheduleBurst(T_BIG_LOSS, { agent: a.name });
    }
  }, [snapshot.agents, cfg.enabled, scheduleBurst]);

  // Market-phase transitions
  useEffect(() => {
    if (!cfg.enabled) return;
    const prev = lastPhase.current;
    lastPhase.current = phase;
    if (prev === null) return; // skip first paint
    if (prev === phase) return;
    const now = Date.now();
    if (now - phaseFiredAt.current < 5_000) return;
    phaseFiredAt.current = now;
    if (phase === "rth") {
      scheduleBurst(T_OPEN, {});
    } else if (phase === "afterhours" && prev === "rth") {
      scheduleBurst(T_CLOSE, {});
    } else {
      const tpls = phaseTemplates(phase);
      if (tpls) scheduleBurst(tpls, {});
    }
  }, [phase, cfg.enabled, scheduleBurst]);

  // Idle filler + quiet-detection loop. Stable across snapshot refreshes by
  // routing latest closures through refs — otherwise SWR's 5s agents-poll
  // would tear down the timer before it ever fires.
  const idleRefs = useRef({ pushMessages, scheduleBurst, agentNames });
  idleRefs.current = { pushMessages, scheduleBurst, agentNames };

  useEffect(() => {
    if (!cfg.enabled) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const schedule = () => {
      if (cancelled) return;
      const wait = cfg.idleMinMs + Math.random() * (cfg.idleMaxMs - cfg.idleMinMs);
      timer = setTimeout(() => {
        if (cancelled) return;
        const now = Date.now();
        const quietFor = now - lastAnyMsgAt.current;
        if (
          quietFor > QUIET_MS
          && now - quietFiredAt.current > QUIET_MS
        ) {
          quietFiredAt.current = now;
          idleRefs.current.scheduleBurst(T_QUIET, {});
        } else {
          const tpl = pick(T_IDLE);
          const names = idleRefs.current.agentNames;
          const random = names.length > 0 ? pick(names) : undefined;
          idleRefs.current.pushMessages([
            {
              id: makeId(),
              user: pick(USERNAMES),
              text: fmtMessage(tpl, { randomAgent: random }),
              tone: tpl.tone,
              at: now,
            },
          ]);
        }
        schedule();
      }, wait);
    };
    schedule();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [cfg.enabled, cfg.idleMinMs, cfg.idleMaxMs]);

  return { messages };
}
