// Dashboard data hooks — designed to swap from mocks to real fetches
// with a one-line change. Hook names match the real backend endpoints
// from src/tradefarm/api/*.py.
//
// To wire up:
//   useAccount → GET /account
//   useAgents → GET /agents
//   useRecentFills → GET /recent_fills?limit=20
//   useLlmStats → GET /llm/stats
//   useMarketClock → GET /market/clock
//   useAdminConfig → GET /admin/config  (POST /admin/config to save)
//   useEpisodes → (new endpoint, see docs/vod-build-roadmap.md)
//   useStorylines → (new endpoint)
//
// All hooks return { data, error, isLoading } in SWR shape.

const { useState, useEffect, useMemo, useRef } = React;

// --- Generic stub: synchronous mock with SWR-shaped return ---------
function useStub(data, deps = []) {
  return { data, error: null, isLoading: false };
}

// --- Live "tick" that drives mock animation -----------------------
function useDashTick(ms = 800) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
  return tick;
}

// --- Today's session: piggy-back on the VOD mock hook --------------
function useToday() {
  // Single source of truth for the "today" view comes from useVodMock().
  // We add a light tick so equity + counters move.
  const vod = useVodMock();
  return vod;
}

// --- Past episodes archive ------------------------------------------

const EPISODE_TITLES = [
  'Quiet open, ugly close',
  'Five winners in a row',
  'LLM gets it wrong on NVDA',
  'Henry climbs to senior',
  'The day momentum_sma20 stopped working',
  'Brian vs Lisa, round three',
  'A walk through Tuesday',
  'Recap: a +2.4% day on no LLM calls',
  'Drawdown lessons',
  'Anna catches the gap',
  'Friday cleanup',
  'A boring Monday is still a Monday',
  'Ten fills, all green',
  'NVDA goes vertical',
  'Earnings risk: skip',
  'Mei takes #1 after 47 days',  // today
];

function dayShape(seed) {
  // Returns an array of [time(0..1), score(0..1), kindHue] tuples — the
  // detected beats for that episode. Used by the Episode card's
  // "beats-as-day-shape" sparkline.
  const r = seededRng2(`day-${seed}`);
  const n = 6 + Math.floor(r() * 8);
  const beats = [];
  for (let i = 0; i < n; i++) {
    const t = (i + 0.4 + r() * 0.4) / n;
    const score = 0.35 + r() * 0.6;
    const hueIdx = Math.floor(r() * 6);
    const hue = [145, 280, 50, 200, 350, 12][hueIdx];
    beats.push({ t, score, hue });
  }
  return beats;
}

function makeEpisodes() {
  const today = new Date('2026-05-19');
  const eps = [];
  for (let i = 0; i < 16; i++) {
    const d = new Date(today);
    d.setDate(d.getDate() - (15 - i));
    // skip weekends
    const day = d.getDay();
    if (day === 0 || day === 6) continue;
    const r = seededRng2(`ep-${i}`);
    const u = r();
    let pnlPct;
    if (u < 0.55) pnlPct = (r() - 0.4) * 2.4;
    else pnlPct = (r() - 0.5) * 6;
    const ep = {
      number: 32 + i,
      date: d.toISOString().slice(0, 10),
      title: EPISODE_TITLES[i] || `Day ${32 + i}`,
      pnlPct,
      pnlAbs: pnlPct * 1000,
      duration: 540 + Math.floor(r() * 240),
      views: i === 15 ? null : Math.floor(80 + r() * 1800),
      fills: 220 + Math.floor(r() * 180),
      beats: 8 + Math.floor(r() * 8),
      promotions: r() < 0.3 ? 1 : 0,
      demotions: r() < 0.1 ? 1 : 0,
      dayShape: dayShape(i),
      uploadedAt: i === 15 ? null : '16:30 ET',
      status: i === 15 ? 'rendering' : 'published',
      thumbHue: [145, 280, 50, 200, 350, 12][i % 6],
    };
    eps.push(ep);
  }
  return eps.reverse(); // newest first
}

const EPISODES = makeEpisodes();

function useEpisodes() {
  return useStub(EPISODES);
}

// --- Storylines (multi-day arcs) -----------------------------------

const STORYLINES = [
  {
    id: 'sl_brian_lisa',
    kind: 'rivalry',
    headline: 'Brian Anderson vs Lisa Garcia',
    sub: 'Same symbol, opposing sides — 11 occurrences across 8 days',
    score: 0.91,
    daysActive: 8,
    startDate: '2026-05-09',
    agents: [10, 5],
    standings: { 10: 4, 5: 3, ties: 4 },
    trend: 'escalating',
    nextHook: 'Both held AVGO into close — 4th time this week',
  },
  {
    id: 'sl_sarah_streak',
    kind: 'streak',
    headline: 'Sarah Brown · winning streak',
    sub: '7 closed trades, all green. Sharpe-30d 2.14',
    score: 0.78,
    daysActive: 4,
    startDate: '2026-05-14',
    agents: [3],
    standings: null,
    trend: 'hot',
    nextHook: 'Sharpe approaches principal eligibility threshold',
  },
  {
    id: 'sl_mei_climb',
    kind: 'leaderboard',
    headline: 'Mei Patel · climbing the leaderboard',
    sub: 'From #14 to #1 in 11 sessions',
    score: 0.86,
    daysActive: 11,
    startDate: '2026-05-04',
    agents: [98],
    standings: null,
    trend: 'completed',
    nextHook: 'Now defending #1 — Michael held it for 47 days',
  },
  {
    id: 'sl_momentum_decline',
    kind: 'strategy',
    headline: 'momentum_sma20 · cooling off',
    sub: '−2.8% week, lowest of three strategies. 6 demotion candidates',
    score: 0.64,
    daysActive: 6,
    startDate: '2026-05-12',
    agents: [],
    standings: null,
    trend: 'declining',
    nextHook: 'Consider freezing the strategy and rebalancing capital',
  },
  {
    id: 'sl_llm_skip',
    kind: 'cost',
    headline: 'LSTM+LLM · cost gate hitting 78%',
    sub: 'Skipping ~3,700 LLM calls/day. $2.84 spend vs $13.10 budget',
    score: 0.42,
    daysActive: 14,
    startDate: '2026-05-01',
    agents: [],
    standings: null,
    trend: 'steady',
    nextHook: 'Healthy — gate working as designed',
  },
];

const STORYLINE_KIND_META = {
  rivalry: { label: 'RIVALRY', accent: '#fb923c', hue: 12 },
  streak: { label: 'STREAK', accent: '#34d399', hue: 145 },
  leaderboard: { label: 'LEADERBOARD', accent: '#fbbf24', hue: 50 },
  strategy: { label: 'STRATEGY', accent: '#c084fc', hue: 280 },
  cost: { label: 'COST', accent: '#86c5ff', hue: 200 },
};

function useStorylines() {
  return useStub(STORYLINES);
}

// --- Pool equity over time (Research multi-day chart) -------------

function makePoolHistory() {
  const points = [];
  let v = 96000;
  const r = seededRng2('pool-history');
  for (let i = 0; i < 60; i++) {
    v += (r() - 0.45) * 600 + Math.sin(i / 6) * 80;
    points.push(v);
  }
  // ensure the latest snaps to the day's close ($101,840)
  points[points.length - 1] = 101840;
  return points;
}

const POOL_HISTORY = makePoolHistory();

function usePoolHistory() {
  return useStub(POOL_HISTORY);
}

// --- Leaderboard history (top 10 agents, rank-per-day for last 14 days) ---

function makeLeaderboardHistory() {
  // For each of the 14 trading days, list of {agentId, rank, pnl}
  const days = 14;
  const series = [];
  const ranked = [...VOD_AGENTS].sort((a, b) => b.pnl - a.pnl).slice(0, 10);
  for (let d = 0; d < days; d++) {
    const r = seededRng2(`lb-${d}`);
    const ranks = ranked.map((a, i) => {
      // each day, shuffle slightly
      const noise = Math.floor((r() - 0.5) * 4);
      return { id: a.id, rank: i + 1 + noise };
    });
    series.push({ day: d, ranks });
  }
  // Anchor today's ranks at the final
  series[series.length - 1] = { day: days - 1, ranks: ranked.map((a, i) => ({ id: a.id, rank: i + 1 })) };
  return { agents: ranked, series };
}

const LB_HISTORY = makeLeaderboardHistory();

function useLeaderboardHistory() {
  return useStub(LB_HISTORY);
}

// --- Admin config (mocked, shape matches /admin/config) -----------

const DEFAULT_ADMIN_CONFIG = {
  ai_enabled: true,
  execution_mode: 'simulated',
  llm_provider: 'anthropic',
  llm_model: 'claude-haiku-4-5',
  anthropic_api_key: '••••••••••••GH8X',
  minimax_api_key: '',
  llm_min_confidence: 0.40,
  auto_tick_interval_sec: 300,
  tick_outside_rth: false,
  agent_count: 100,
  agent_starting_capital: 1000,
  disabled_strategies: '',
  academy_eval_interval_sec: 600,
  academy_retrieval_enabled: true,
  academy_retrieval_k: 3,
  academy_demote_drawdown_pct: 0.08,
  academy_demote_consecutive_losses: 5,
};

function useAdminConfig() {
  const [config, setConfig] = useState(DEFAULT_ADMIN_CONFIG);
  const update = (key, value) => setConfig(c => ({ ...c, [key]: value }));
  return { config, update };
}

// --- Theme + density (for the tweaks panel) ----------------------

const DASH_TWEAKS_DEFAULT = /*EDITMODE-BEGIN*/{
  "theme": "studio-dark",
  "density": "comfortable",
  "showCostRail": true,
  "showPipelinePanel": true
}/*EDITMODE-END*/;

Object.assign(window, {
  useDashTick, useToday,
  useEpisodes, EPISODES,
  useStorylines, STORYLINES, STORYLINE_KIND_META,
  usePoolHistory, useLeaderboardHistory,
  useAdminConfig, DEFAULT_ADMIN_CONFIG,
  DASH_TWEAKS_DEFAULT,
});
