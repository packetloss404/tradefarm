// Shared simulated tick stream for all 4 streamer variations.
// One useStreamMock() lives at the top-level App and feeds props down.

const STRATEGIES = ['momentum', 'lstm', 'llm'];
const STRATEGY_LABEL = { momentum: 'MOM', lstm: 'LSTM', llm: 'LSTM+LLM' };
const STRATEGY_FULL = { momentum: 'momentum_sma20', lstm: 'lstm_v1', llm: 'lstm_llm_v1' };
const STRATEGY_HUE = { momentum: 24, lstm: 200, llm: 280 }; // amber, blue, violet
const RANKS = ['intern', 'junior', 'senior', 'principal'];
const RANK_LABEL = { intern: 'IN', junior: 'JR', senior: 'SR', principal: 'PR' };

const SYMBOLS = [
  'AAPL','MSFT','NVDA','GOOGL','AMZN','META','TSLA','AVGO','BRK-B','JPM',
  'JNJ','COST','HD','ABBV','XOM','WMT','PG','MA','V','UNH',
  'SPY','QQQ','IWM','DIA','GLD','ARKK','LLY','ORCL','CRM','NFLX',
];

const FIRST = ['Tick','Vol','Hedge','Carry','Drift','Beta','Alpha','Vega','Theta','Gamma',
  'Bid','Ask','Limit','Stop','Slip','Spread','Fade','Pump','Yield','Roll',
  'Skew','Tape','Wick','Print','Flip','Wash','Pivot','Range','Burst','Quant',
  'Lever','Margin','Quote','Strike','Curve','Delta','Sigma','Kappa','Rho','Iota',
  'Lambda','Sharpe','Sortino','Omega','Atlas','Echo','Nova','Pyx','Ridge','Slate'];
const LAST = ['Belinda','Stan','Ada','Vito','Mira','Otto','Quinn','Pax','Rune','Sable',
  'Hugo','Iris','Gus','Naomi','Jett','Kira','Leo','Maeve','Nico','Opal',
  'Piper','Reed','Sloan','Theo','Uma','Vince','Wade','Xan','Yara','Zane',
  'Bea','Cleo','Dax','Eli','Fern','Gale','Hank','Ivy','Jax','Knox',
  'Liv','Moss','Nash','Orla','Pace','Quill','Rio','Saxe','Tate','Ula'];

function rngFromSeed(seed) {
  let s = (seed * 2654435761) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

function nameFor(i) {
  return `${FIRST[i % FIRST.length]} ${LAST[(i * 13 + 7) % LAST.length]}`;
}
function initialsFor(i) {
  const n = nameFor(i);
  const [a, b] = n.split(' ');
  return (a[0] + b[0]).toUpperCase();
}

function makeInitialAgents() {
  const agents = [];
  for (let i = 0; i < 100; i++) {
    const r = rngFromSeed(i + 11);
    const strat = STRATEGIES[i % 3];
    const baseEquity = 1000;
    // skewed distribution: most small, fat tails
    const u = r();
    let pnl;
    if (u < 0.55) pnl = (r() - 0.5) * 30;
    else if (u < 0.85) pnl = (r() - 0.3) * 80;
    else pnl = (r() - 0.4) * 240;
    const equity = baseEquity + pnl;
    const rankIdx = Math.min(3, Math.floor(Math.pow(r(), 2) * 4));
    const symbol = r() < 0.65 ? SYMBOLS[Math.floor(r() * SYMBOLS.length)] : null;
    const status = pnl > 8 ? 'profit' : pnl < -8 ? 'loss' : symbol ? 'trading' : 'waiting';
    const spark = [];
    let v = baseEquity;
    for (let k = 0; k < 32; k++) {
      v += (rngFromSeed(i * 32 + k)() - 0.5) * 5;
      spark.push(v);
    }
    spark[spark.length - 1] = equity;
    agents.push({
      id: i + 1,
      name: nameFor(i),
      initials: initialsFor(i),
      strategy: strat,
      status,
      rank: RANKS[rankIdx],
      symbol,
      equity,
      pnl,
      pnlPct: pnl / 10,
      sparkline: spark,
      lstmConf: 0.35 + r() * 0.6,
      lstmDir: ['up', 'flat', 'down'][Math.floor(r() * 3)],
      llmStance: r() < 0.55 ? 'trade' : 'wait',
      drift: (r() - 0.5) * 0.6, // per-tick bias, makes some agents trend
    });
  }
  return agents;
}

function makeFill(agent) {
  const r = Math.random;
  const symbol = agent.symbol || SYMBOLS[Math.floor(r() * SYMBOLS.length)];
  return {
    id: r().toString(36).slice(2, 9) + Date.now().toString(36),
    t: Date.now(),
    agentId: agent.id,
    agentName: agent.name,
    initials: initialsFor(agent.id - 1),
    strategy: agent.strategy,
    rank: agent.rank,
    symbol,
    side: r() > 0.5 ? 'buy' : 'sell',
    qty: Math.floor(1 + r() * 9),
    price: 50 + r() * 850,
  };
}

function makePromotion(agent, direction) {
  const fromIdx = RANKS.indexOf(agent.rank);
  const toIdx = direction === 'up' ? Math.min(3, fromIdx + 1) : Math.max(0, fromIdx - 1);
  return {
    id: Math.random().toString(36).slice(2, 9) + Date.now().toString(36),
    t: Date.now(),
    agentId: agent.id,
    agentName: agent.name,
    initials: initialsFor(agent.id - 1),
    fromRank: RANKS[fromIdx],
    toRank: RANKS[toIdx],
    direction,
    reason:
      direction === 'up'
        ? ['Sharpe>2.0 30d', '5/5 winners', 'Beat strategy +18%', 'Hot streak', 'Top decile alpha'][Math.floor(Math.random() * 5)]
        : ['Drawdown>12%', '3 stop-outs', 'Below benchmark', 'Concentration risk', 'Vol spike'][Math.floor(Math.random() * 5)],
  };
}

const TICK_MS = 600;

function useStreamMock() {
  const [agents, setAgents] = React.useState(makeInitialAgents);
  const [fills, setFills] = React.useState([]);
  const [promotions, setPromotions] = React.useState([]);
  const [tick, setTick] = React.useState(0);
  const agentsRef = React.useRef(agents);
  agentsRef.current = agents;

  React.useEffect(() => {
    const id = setInterval(() => {
      setTick(t => t + 1);
      setAgents(prev => prev.map(a => {
        const dirBias = a.lstmDir === 'up' ? 0.4 : a.lstmDir === 'down' ? -0.4 : 0;
        const delta = (Math.random() - 0.5) * 5 + dirBias + a.drift;
        const newEquity = Math.max(200, a.equity + delta);
        const pnl = newEquity - 1000;
        const newSpark = a.sparkline.length >= 32
          ? [...a.sparkline.slice(1), newEquity]
          : [...a.sparkline, newEquity];
        let status = a.status;
        if (Math.random() < 0.025) status = Math.random() < 0.6 ? 'trading' : 'waiting';
        const auto = pnl > 8 ? 'profit' : pnl < -8 ? 'loss' : status;
        return {
          ...a,
          equity: newEquity,
          pnl,
          pnlPct: pnl / 10,
          sparkline: newSpark,
          status: auto,
          lstmConf: Math.max(0.2, Math.min(0.99, a.lstmConf + (Math.random() - 0.5) * 0.04)),
          lstmDir: Math.random() < 0.04
            ? ['up', 'flat', 'down'][Math.floor(Math.random() * 3)]
            : a.lstmDir,
        };
      }));

      // 1–2 fills most ticks
      const r = Math.random;
      const fillCount = r() < 0.78 ? (r() < 0.35 ? 2 : 1) : 0;
      if (fillCount > 0) {
        const newFills = [];
        for (let k = 0; k < fillCount; k++) {
          const idx = Math.floor(r() * agentsRef.current.length);
          const a = agentsRef.current[idx];
          if (a) newFills.push(makeFill(a));
        }
        setFills(prev => [...newFills, ...prev].slice(0, 30));
      }

      // promotion every ~15s
      if (r() < 0.04) {
        const idx = Math.floor(r() * agentsRef.current.length);
        const a = agentsRef.current[idx];
        if (a) {
          setPromotions(prev => [
            makePromotion(a, r() < 0.65 ? 'up' : 'down'),
            ...prev,
          ].slice(0, 20));
        }
      }
    }, TICK_MS);
    return () => clearInterval(id);
  }, []);

  const account = React.useMemo(() => {
    const total = agents.reduce((s, a) => s + a.equity, 0);
    const allocated = 100 * 1000;
    return {
      totalEquity: total,
      allocated,
      pnl: total - allocated,
      pnlPct: ((total - allocated) / allocated) * 100,
      profit: agents.filter(a => a.status === 'profit').length,
      loss: agents.filter(a => a.status === 'loss').length,
      waiting: agents.filter(a => a.status === 'waiting').length,
      trading: agents.filter(a => a.status === 'trading').length,
      tick,
    };
  }, [agents, tick]);

  const byStrategy = React.useMemo(() => {
    const groups = { momentum: [], lstm: [], llm: [] };
    agents.forEach(a => groups[a.strategy].push(a));
    const stats = {};
    for (const s of STRATEGIES) {
      const list = groups[s];
      const totalE = list.reduce((x, a) => x + a.equity, 0);
      const totalP = list.reduce((x, a) => x + a.pnl, 0);
      stats[s] = {
        agents: list,
        equity: totalE,
        pnl: totalP,
        pnlPct: (totalP / (list.length * 1000)) * 100,
        winners: list.filter(a => a.pnl > 0).length,
      };
    }
    return stats;
  }, [agents]);

  return { agents, fills, promotions, account, tick, byStrategy };
}

Object.assign(window, {
  useStreamMock,
  STRATEGIES,
  STRATEGY_LABEL,
  STRATEGY_FULL,
  STRATEGY_HUE,
  RANKS,
  RANK_LABEL,
  SYMBOLS,
  nameFor,
  initialsFor,
});
