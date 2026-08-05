// Runtime values for the VOD pipeline mock — one simulated trading day
// (2026-05-19), the beat list, the 10-subsystem pipeline state, and the
// day's PnL roll-up. Ported 1:1 from the design prototype's vod-data.jsx
// so the four surfaces have a coherent fixture without depending on a
// running backend.
//
// Split from the old mockData.ts so type-only consumers can import the
// shapes from ./types.ts and stay out of the production bundle.

import type {
  Agent,
  Beat,
  BeatKind,
  BeatMeta,
  DaySummary,
  PipelineNode,
  Rank,
  StrategyBucket,
  StrategyRollup,
} from "./types";

export const OFFICE_FIRSTS = [
  "michael", "jennifer", "david", "sarah", "james", "lisa", "robert", "amy",
  "kevin", "emily", "brian", "rachel", "eric", "melissa", "chris", "jenna",
  "andrew", "kate", "ryan", "hannah", "paul", "anna", "thomas", "claire",
  "peter", "olivia", "joseph", "sophia", "matthew", "ava", "samuel", "mia",
  "jacob", "ella", "nathan", "lily", "anthony", "grace", "jonathan", "chloe",
  "benjamin", "zoe", "scott", "ruby", "patrick", "julia", "gregory", "kayla",
  "edward", "brooke", "derek", "alyssa", "frank", "taylor", "neil", "danielle",
  "ian", "vanessa", "glenn", "stephanie", "todd", "natalie", "alan", "monica",
  "philip", "christine", "vincent", "holly", "harold", "jasmine", "marcus", "simone",
  "leon", "autumn", "jeremy", "isabel", "dennis", "victoria", "calvin", "paige",
  "randy", "nora", "alex", "sienna", "chad", "audrey", "terrence", "miles",
  "oliver", "bianca", "henry", "willow", "raj", "priya", "arjun", "devi",
  "li", "mei", "wei", "yuki",
];

export const OFFICE_LASTS = [
  "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis",
  "rodriguez", "martinez", "hernandez", "lopez", "gonzalez", "wilson", "anderson", "thomas",
  "wagner", "moore", "jackson", "martin", "lee", "perez", "thompson", "white",
  "harris", "sanchez", "clark", "ramirez", "lewis", "robinson", "walker", "young",
  "allen", "king", "wright", "novak", "torres", "nguyen", "hill", "flores",
  "green", "adams", "nelson", "baker", "hall", "rivera", "campbell", "mitchell",
  "carter", "roberts", "gomez", "phillips", "evans", "turner", "diaz", "parker",
  "cruz", "edwards", "collins", "reyes", "stewart", "morris", "morales", "murphy",
  "cook", "rogers", "gutierrez", "ortiz", "morgan", "cooper", "peterson", "bailey",
  "reed", "kelly", "howard", "ramos", "kim", "cox", "ward", "richardson",
  "watson", "brooks", "chavez", "wood", "bennett", "gray", "mendoza", "ruiz",
  "hughes", "price", "alvarez", "castillo", "sanders", "patel", "myers", "long",
  "ross", "foster", "jimenez", "okafor",
];

export function officeName(id: number): string {
  return `${OFFICE_FIRSTS[id % 100]}_${OFFICE_LASTS[id % 100]}`;
}
export function officeDisplay(id: number): string {
  const n = officeName(id);
  const [a = "", b = ""] = n.split("_");
  return `${a[0]?.toUpperCase() ?? ""}${a.slice(1)} ${b[0]?.toUpperCase() ?? ""}${b.slice(1)}`;
}
export function officeInitials(id: number): string {
  const n = officeName(id);
  const [a = "", b = ""] = n.split("_");
  return `${a[0] ?? ""}${b[0] ?? ""}`.toUpperCase();
}

// 8-bucket strategy view: 7 live (momentum_12_1, mean_reversion_bb,
// rsi2, donchian_breakout, pairs_zscore, lstm, llm) + the legacy
// "momentum" alias for the pre-0.7 `momentum_sma20` mock. Listed in
// the order the studio surfaces them in the strategy panel — the
// momentum family first, then the mean-reversion / breakout rule
// strategies, then the LSTM family.
export const VOD_STRATEGIES = [
  "momentum",
  "momentum_12_1",
  "mean_reversion_bb",
  "rsi2",
  "donchian_breakout",
  "pairs_zscore",
  "lstm",
  "llm",
] as const satisfies readonly StrategyBucket[];

export const VOD_STRATEGY_LABEL: Record<StrategyBucket, string> = {
  momentum: "momentum_sma20",
  momentum_12_1: "momentum_12_1",
  mean_reversion_bb: "mean_reversion_bb",
  rsi2: "rsi2",
  donchian_breakout: "donchian_breakout",
  pairs_zscore: "pairs_zscore",
  lstm: "lstm_v1",
  llm: "lstm_llm_v1",
};
export const VOD_STRATEGY_SHORT: Record<StrategyBucket, string> = {
  momentum: "MOM",
  momentum_12_1: "MOM12",
  mean_reversion_bb: "BB",
  rsi2: "RSI2",
  donchian_breakout: "DON",
  pairs_zscore: "PAIR",
  lstm: "LSTM",
  llm: "LSTM+LLM",
};
export const VOD_STRATEGY_HUE: Record<StrategyBucket, number> = {
  momentum: 32,
  momentum_12_1: 24,
  mean_reversion_bb: 180,
  rsi2: 100,
  donchian_breakout: 12,
  pairs_zscore: 320,
  lstm: 200,
  llm: 280,
};

export const VOD_RANKS = ["intern", "junior", "senior", "principal"] as const;

// Deterministic PRNG so the mock day reproduces between renders.
function seededRng(seed: number): () => number {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

export function seededRngStr(id: string): () => number {
  let s = 0;
  for (let i = 0; i < id.length; i++) s = (s * 31 + id.charCodeAt(i)) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

export const SESSION_DATE = "2026-05-19";
export const SESSION_LABEL = "Tue, May 19 · session s_2026-05-19_a3f2";
export const SESSION_ID = "s_2026-05-19_a3f2";
export const SESSION_EP_NUMBER = 47;

export const SYMBOLS = [
  "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "AVGO", "BRK-B", "JPM",
  "JNJ", "COST", "HD", "ABBV", "XOM", "WMT", "PG", "MA", "V", "UNH",
  "SPY", "QQQ", "IWM", "DIA", "GLD", "ARKK", "LLY", "ORCL", "CRM", "NFLX",
];

function makeVodAgents(): Agent[] {
  const agents: Agent[] = [];
  // Stable count of buckets so a recompile doesn't reshuffle the seeded
  // assignment between the 8 strategy slots.
  const stratCount = VOD_STRATEGIES.length;
  for (let i = 0; i < 100; i++) {
    const r = seededRng(i + 47);
    const stratIdx = i % stratCount;
    const strat = VOD_STRATEGIES[stratIdx] ?? "momentum";
    const baseEquity = 1000;
    const u = r();
    let pnl: number;
    if (u < 0.5) pnl = (r() - 0.5) * 28;
    else if (u < 0.85) pnl = (r() - 0.35) * 90;
    else pnl = (r() - 0.4) * 260;
    const equity = baseEquity + pnl;
    const rankIdx = Math.min(3, Math.floor(Math.pow(r(), 2.2) * 4));
    const rank: Rank = VOD_RANKS[rankIdx] ?? "intern";
    const spark: number[] = [];
    let v = baseEquity;
    for (let k = 0; k < 40; k++) {
      v += (seededRng(i * 40 + k)() - 0.5) * 6;
      spark.push(v);
    }
    spark[spark.length - 1] = equity;
    const trades = Math.floor(r() * 9) + (rankIdx >= 2 ? 4 : 1);
    agents.push({
      id: i,
      name: officeName(i),
      display: officeDisplay(i),
      initials: officeInitials(i),
      strategy: strat,
      rank,
      equity,
      pnl,
      pnlPct: pnl / 10,
      sparkline: spark,
      trades,
      wins: Math.floor(trades * (0.4 + r() * 0.45)),
    });
  }
  return agents;
}

export const VOD_AGENTS: Agent[] = makeVodAgents();

export const BEATS: Beat[] = [
  {
    id: "b01", t: "09:30", tMs: 0,
    kind: "open", score: 0.62, scene: "preroll",
    headline: "Opening bell · 100 agents back at their desks",
    sub: "Pre-market gap +0.4%. SPY 502.18 → ?",
    duration: 12, refs: ["mkt_open_09_30"], agents: [], selected: true,
  },
  {
    id: "b02", t: "09:42", tMs: 720,
    kind: "big_fill", score: 0.78, scene: "hero",
    headline: "Marcus Wagner goes long NVDA — $9,600 notional",
    sub: 'LSTM max_prob 0.71, LLM stance "trade", size_pct 95%',
    duration: 32, refs: ["fill_4471"], agents: [70], selected: true,
  },
  {
    id: "b03", t: "10:14", tMs: 2640,
    kind: "divergence", score: 0.81, scene: "brain",
    headline: "Two LSTM+LLM agents take opposite sides of TSLA",
    sub: "Ada Hernandez sells, Yuki Okafor buys — same tick, same symbol",
    duration: 28, refs: ["fill_4503", "fill_4504"], agents: [8, 99], selected: true,
  },
  {
    id: "b04", t: "10:38", tMs: 4080,
    kind: "near_miss", score: 0.54, scene: "decision-lab",
    headline: "LSTM max_prob 0.398 — Anna Perez skips the LLM call",
    sub: "Cost gate triggered. Would have shorted COST. COST then -1.8%",
    duration: 22, refs: ["decision_18992"], agents: [21], selected: false,
  },
  {
    id: "b05", t: "11:02", tMs: 5520,
    kind: "streak", score: 0.74, scene: "leaderboard",
    headline: "Sarah Brown: 5 winners in a row, all NVDA",
    sub: "Up +$148 on the morning. Sharpe-30d climbs to 2.14",
    duration: 26, refs: ["streak_w_3"], agents: [3], selected: true,
  },
  {
    id: "b06", t: "11:47", tMs: 8220,
    kind: "chapter_change", score: 0.41, scene: "chapter",
    headline: "Lunch hour · volume drops 38%",
    sub: "32 of 100 agents on wait. Bridge to afternoon.",
    duration: 8, refs: ["chapter_lunch"], agents: [], selected: true,
  },
  {
    id: "b07", t: "12:24", tMs: 10440,
    kind: "top_loser", score: 0.69, scene: "hero",
    headline: "James Jones rides momentum into a drawdown",
    sub: "Down $84 on a single AVGO position. Stop loss at -8%",
    duration: 24, refs: ["fill_4612", "stop_loss_4612"], agents: [4], selected: true,
  },
  {
    id: "b08", t: "13:11", tMs: 13260,
    kind: "llm_bet", score: 0.66, scene: "decision-lab",
    headline: 'Claude overrides LSTM on AAPL — "earnings revision risk"',
    sub: "LSTM said up 0.62. Overlay flipped to sell. Filled at 184.22",
    duration: 30, refs: ["decision_19204"], agents: [14], selected: false,
  },
  {
    id: "b09", t: "14:05", tMs: 16500,
    kind: "leaderboard_shift", score: 0.72, scene: "leaderboard",
    headline: "Mei Patel overtakes Michael Smith at #1",
    sub: "47-day reign ends. Mei +$284 on the day",
    duration: 20, refs: ["rank_change_98_0"], agents: [98, 0], selected: true,
  },
  {
    id: "b10", t: "14:42", tMs: 18720,
    kind: "agent_rivalry", score: 0.83, scene: "showdown",
    headline: "Brian Anderson vs Lisa Garcia — same symbol, fourth time today",
    sub: "Both LSTM+LLM. Brian +$32, Lisa -$41 net. Rivalry score 0.83",
    duration: 34, refs: ["rivalry_10_5"], agents: [10, 5], selected: true,
  },
  {
    id: "b11", t: "15:18", tMs: 20880,
    kind: "promotion", score: 0.58, scene: "leaderboard",
    headline: "Promotion: Henry Bennett · junior → senior",
    sub: "37 closed trades, Sharpe-30d 1.81. Capital multiplier 1.0× → 1.5×",
    duration: 16, refs: ["promotion_89"], agents: [89], selected: true,
  },
  {
    id: "b12", t: "15:51", tMs: 22860,
    kind: "big_fill", score: 0.61, scene: "hero",
    headline: "Closing bell rush · 18 fills in last 9 minutes",
    sub: "Pool equity +1.84% on the day. Best since Apr 24.",
    duration: 22, refs: ["closing_burst"], agents: [], selected: true,
  },
  {
    id: "b13", t: "16:00", tMs: 23400,
    kind: "recap", score: 0.88, scene: "recap",
    headline: "Close · +1.84% pool, top mover Mei Patel +$284",
    sub: "momentum +2.1%, lstm +1.2%, lstm_llm +2.4%. 1 promo, 0 demos.",
    duration: 36, refs: ["close_16_00"], agents: [98], selected: true,
  },
];

export const BEAT_KIND_META: Record<BeatKind, BeatMeta> = {
  open:              { label: "OPEN",       hue: 200, accent: "#86c5ff" },
  big_fill:          { label: "BIG FILL",   hue: 145, accent: "#34d399" },
  divergence:        { label: "DIVERGENCE", hue: 280, accent: "#c084fc" },
  near_miss:         { label: "NEAR MISS",  hue: 50,  accent: "#fbbf24" },
  streak:            { label: "STREAK",     hue: 145, accent: "#34d399" },
  chapter_change:    { label: "CHAPTER",    hue: 220, accent: "#94a3b8" },
  top_loser:         { label: "DRAWDOWN",   hue: 350, accent: "#fb7185" },
  llm_bet:           { label: "LLM BET",    hue: 280, accent: "#c084fc" },
  leaderboard_shift: { label: "LEAD SHIFT", hue: 35,  accent: "#fbbf24" },
  agent_rivalry:     { label: "RIVALRY",    hue: 12,  accent: "#fb923c" },
  promotion:         { label: "PROMOTION",  hue: 145, accent: "#34d399" },
  recap:             { label: "RECAP",      hue: 200, accent: "#86c5ff" },
};

export const PIPELINE: PipelineNode[] = [
  {
    id: "session", label: "Session runner", cmd: "tradefarm.session.run",
    status: "done", started: "16:00:04", finished: "16:01:12", durationSec: 68,
    output: "manifest.json", outputSize: "184 KB",
    summary: "23,400 ticks · 4,812 decisions · 312 fills",
    tail: [
      "[16:00:04] session start s_2026-05-19_a3f2",
      "[16:00:51] tick 3000/23400 (12.8% · 38x realtime)",
      "[16:01:08] tick 23400/23400 (100% · finalizing manifest)",
      "[16:01:12] manifest written 184 KB · 4812 events indexed",
    ],
  },
  {
    id: "beats", label: "Beat detector", cmd: "tradefarm.session.beats",
    status: "done", started: "16:01:12", finished: "16:01:18", durationSec: 6,
    output: "beats.json", outputSize: "12.4 KB",
    summary: "13 beats picked from 47 candidates · μ score 0.68",
    tail: [
      "[16:01:12] beat detector start",
      "[16:01:14] scored 47 candidate moments",
      "[16:01:16] deduplicated 11 overlapping streak/promotion pairs",
      "[16:01:18] picked 13 beats · written beats.json",
    ],
  },
  {
    id: "render", label: "Headless renderer", cmd: "tradefarm.render.headless",
    status: "running", started: "16:01:19", finished: null, durationSec: 142,
    progress: 0.62, progressLabel: "8/13 clips · ETA 1m 28s",
    output: "clips/*.mp4", outputSize: "— (8/13 in progress)",
    summary: "Playwright @ 1920×1080 30fps · stream/?replay=s_…",
    tail: [
      "[16:01:19] launching chromium headless",
      "[16:01:22] beat b01 hero · captured 12.0s",
      "[16:01:34] beat b02 hero · captured 32.0s",
      "[16:02:05] beat b03 brain · captured 28.0s",
      "[16:02:39] beat b04 decision-lab · captured 22.0s",
      "[16:03:05] beat b05 leaderboard · captured 26.0s",
      "[16:03:35] beat b06 chapter · captured 8.0s",
      "[16:03:46] beat b07 hero · capturing… 14.2s / 24.0s",
    ],
  },
  {
    id: "stitch", label: "ffmpeg stitcher", cmd: "tradefarm.render.stitch",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "silent_reel.mp4", outputSize: null,
    summary: "crossfades 400ms · captions @ 64px · music bed -18 LUFS",
    tail: ["[—] waiting on renderer"],
  },
  {
    id: "script", label: "Script writer", cmd: "tradefarm.script.write",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "script.json", outputSize: null,
    summary: "claude-haiku-4-5 · 200 tok/beat · personality voicing on",
    tail: ["[—] waiting on stitch"],
  },
  {
    id: "tts", label: "TTS narration", cmd: "tradefarm.tts.run",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "vo/*.wav", outputSize: null,
    summary: 'elevenlabs flash-v2 · voice "Daniel" · 22050 Hz mono',
    tail: ["[—] waiting on script"],
  },
  {
    id: "mix", label: "Audio mixer", cmd: "tradefarm.render.mix",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "reel.mp4", outputSize: null,
    summary: "sidechain duck -12 dB · stingers on chapter/promotion",
    tail: ["[—] waiting on TTS"],
  },
  {
    id: "thumb", label: "Thumbnail", cmd: "tradefarm.thumb.gen",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "thumb.jpg", outputSize: null,
    summary: "best beat frame + title overlay · 1280×720",
    tail: ["[—] waiting on mix"],
  },
  {
    id: "meta", label: "YT metadata", cmd: "tradefarm.yt.metadata",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "episode.yaml", outputSize: null,
    summary: "title, description, chapter markers, tags",
    tail: ["[—] waiting on thumb"],
  },
  {
    id: "upload", label: "YT upload", cmd: "tradefarm.yt.upload",
    status: "queued", started: null, finished: null, durationSec: null,
    output: "youtu.be/—", outputSize: null,
    summary: "unlisted · scheduled 16:30 ET · auto-publish",
    tail: ["[—] waiting on metadata"],
  },
];

function makeDaySummary(agents: Agent[]): DaySummary {
  const totalEquity = agents.reduce((s, a) => s + a.equity, 0);
  const allocated = 100 * 1000;
  const totalPnl = totalEquity - allocated;
  const byStrategy = {} as Record<StrategyBucket, StrategyRollup>;
  for (const s of VOD_STRATEGIES) {
    const list = agents.filter((a) => a.strategy === s);
    const e = list.reduce((x, a) => x + a.equity, 0);
    const p = list.reduce((x, a) => x + a.pnl, 0);
    byStrategy[s] = {
      agents: list.length,
      equity: e,
      pnl: p,
      pnlPct: list.length === 0 ? 0 : (p / (list.length * 1000)) * 100,
      fills: list.reduce((x, a) => x + a.trades, 0),
    };
  }
  const ranked = [...agents].sort((a, b) => b.pnl - a.pnl);
  return {
    totalEquity, allocated, totalPnl,
    pnlPct: (totalPnl / allocated) * 100,
    byStrategy,
    topAgents: ranked.slice(0, 5),
    botAgents: ranked.slice(-3).reverse(),
    promotions: 1, demotions: 0,
    fillCount: 312, decisionCount: 4812,
    llmCalls: 1067, llmSkipped: 3745, llmSpend: 2.84,
  };
}

export const DAY_SUMMARY: DaySummary = makeDaySummary(VOD_AGENTS);

export const CAPTION_STYLES = ["minimal", "kinetic", "news-chyron", "serif"] as const;
export const COLOR_THEMES = ["studio dark", "studio light", "amber CRT"] as const;
