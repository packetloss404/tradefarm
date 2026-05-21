// Research page — multi-day storylines, leaderboard history, pool
// equity over time. The "what's the bigger story" view.

function ResearchHeader() {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', padding: '24px 24px 18px' }}>
      <div>
        <h1 style={{ fontFamily: '"Helvetica Neue"', fontSize: 28, fontWeight: 700, color: T.text, margin: 0, letterSpacing: -0.5 }}>
          Research
        </h1>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2, marginTop: 6 }}>
          multi-day arcs · leaderboard history · pool trajectory
        </div>
      </div>
      <div style={{ display: 'flex', gap: 8 }}>
        <RangeMenu />
      </div>
    </div>
  );
}

function RangeMenu() {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', background: T.panel, border: `1px solid ${T.border}`, borderRadius: 4, overflow: 'hidden' }}>
      {['7D', '14D', '30D', '90D', 'ALL'].map(r => (
        <button key={r} style={{
          fontFamily: 'JetBrains Mono', fontSize: 11, fontWeight: 600,
          padding: '8px 12px', cursor: 'pointer',
          background: r === '14D' ? T.panel3 : 'transparent', border: 'none',
          color: r === '14D' ? T.text : T.text2,
        }}>{r}</button>
      ))}
    </div>
  );
}

// --- Pool history chart -----------------------------------

function PoolHistoryChart() {
  const { T } = useTheme();
  const { data: points } = usePoolHistory();
  const W = 1200, H = 220;
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const pts = points.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p - min) / span) * (H - 16) - 8;
    return [x, y];
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `0,${H} ${line} ${W},${H}`;
  const last = points[points.length - 1];
  const first = points[0];
  const change = ((last - first) / first) * 100;
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 22 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            POOL EQUITY · 14 SESSIONS
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, marginTop: 6 }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 28, fontWeight: 600, color: T.text }}>
              ${last.toLocaleString('en-US', { maximumFractionDigits: 0 })}
            </span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 14, color: change > 0 ? T.ok : T.err, fontWeight: 600 }}>
              {fmtPct(change)} <span style={{ color: T.text2 }}>over 14d</span>
            </span>
          </div>
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2, textAlign: 'right' }}>
          <div>Sharpe-30d <span style={{ color: T.text, fontWeight: 600 }}>1.62</span></div>
          <div>Max drawdown <span style={{ color: T.err, fontWeight: 600 }}>−4.2%</span></div>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block', height: H }}>
        <defs>
          <linearGradient id="pool-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.accent} stopOpacity="0.18" />
            <stop offset="100%" stopColor={T.accent} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map(g => (
          <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke={T.border} strokeDasharray="2 4" />
        ))}
        <line x1="0" x2={W} y1={H - ((100000 - min) / span) * (H - 16) - 8} y2={H - ((100000 - min) / span) * (H - 16) - 8}
          stroke={T.text3} strokeDasharray="4 3" />
        <text x={W - 6} y={H - ((100000 - min) / span) * (H - 16) - 10}
          textAnchor="end" fontFamily="JetBrains Mono" fontSize="10" fill={T.text3}>
          $100k allocated
        </text>
        <polygon points={fill} fill="url(#pool-fill)" />
        <polyline points={line} fill="none" stroke={T.accent} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        {/* mark each session boundary */}
        {Array.from({ length: 14 }).map((_, i) => {
          const x = ((i + 1) / 14) * W - W / 28;
          return <line key={i} x1={x} x2={x} y1={H - 4} y2={H} stroke={T.text3} strokeWidth="1" />;
        })}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 4 }}>
        <span>May 4</span><span>May 7</span><span>May 10</span><span>May 13</span><span style={{ color: T.text }}>May 19 (today)</span>
      </div>
    </div>
  );
}

// --- Storyline ribbons --------------------------------------

function StorylineCard({ sl }) {
  const { T } = useTheme();
  const meta = STORYLINE_KIND_META[sl.kind];
  const involved = sl.agents.map(id => VOD_AGENTS[id]).filter(Boolean);
  const trendBadge = {
    escalating: { label: 'escalating', color: T.err },
    hot: { label: 'hot', color: T.ok },
    completed: { label: 'completed', color: T.text3 },
    declining: { label: 'declining', color: T.warn },
    steady: { label: 'steady', color: T.text2 },
  }[sl.trend] || { label: sl.trend, color: T.text2 };
  return (
    <div style={{
      background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8,
      padding: 18, position: 'relative',
    }}>
      <div style={{ position: 'absolute', left: 0, top: 18, bottom: 18, width: 3, background: meta.accent, borderRadius: 2 }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: meta.accent, fontWeight: 700 }}>
          {meta.label}
        </span>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3 }}>·</span>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>
          day {sl.daysActive} · since {new Date(sl.startDate).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{
          fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 700, letterSpacing: 1,
          padding: '2px 6px', borderRadius: 2, color: trendBadge.color,
          border: `1px solid ${trendBadge.color}55`,
        }}>{trendBadge.label}</span>
        <span style={{
          fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text, fontWeight: 600,
        }}>
          {(sl.score * 100).toFixed(0)}
        </span>
      </div>
      <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 16, fontWeight: 700, color: T.text, marginBottom: 4 }}>
        {sl.headline}
      </div>
      <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 12.5, color: T.text2, lineHeight: 1.5, marginBottom: 12 }}>
        {sl.sub}
      </div>
      {/* ribbon */}
      <StorylineRibbon sl={sl} />
      {involved.length > 0 && (
        <div style={{ display: 'flex', gap: 8, marginTop: 12, flexWrap: 'wrap' }}>
          {involved.map(a => (
            <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 8, background: T.bg, padding: '6px 10px', borderRadius: 4, border: `1px solid ${T.border}` }}>
              <div style={{ width: 22, height: 22, borderRadius: 3, background: stratColor(a.strategy), display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 700, color: '#0a0a0a' }}>
                {a.initials}
              </div>
              <span style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, fontWeight: 600, color: T.text }}>{a.display}</span>
              {sl.standings && (
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2 }}>
                  · {sl.standings[a.id]}W
                </span>
              )}
            </div>
          ))}
        </div>
      )}
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 12, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
        next hook · <span style={{ color: T.text2 }}>{sl.nextHook}</span>
      </div>
    </div>
  );
}

function StorylineRibbon({ sl }) {
  // Horizontal ribbon spanning the storyline's active days. Today (last
  // cell) is highlighted; intensity = activity that day.
  const { T } = useTheme();
  const meta = STORYLINE_KIND_META[sl.kind];
  const cells = 14;
  const startCell = Math.max(0, 14 - sl.daysActive);
  return (
    <div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.4, color: T.text3, marginBottom: 6 }}>
        ACTIVITY · 14 DAYS
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: `repeat(${cells}, 1fr)`, gap: 3, height: 18 }}>
        {Array.from({ length: cells }).map((_, i) => {
          const active = i >= startCell;
          const isToday = i === cells - 1;
          const r = seededRng2(`${sl.id}-${i}`);
          const intensity = active ? 0.45 + r() * 0.55 : 0;
          return (
            <div key={i} style={{
              background: active ? meta.accent : T.panel2,
              opacity: active ? intensity : 0.4,
              borderRadius: 2,
              border: isToday && active ? `1px solid ${T.text}` : 'none',
            }} title={`day -${cells - 1 - i}`} />
          );
        })}
      </div>
    </div>
  );
}

// --- Leaderboard history (rank-per-day) --------------------

function LeaderboardHistory() {
  const { T } = useTheme();
  const { data } = useLeaderboardHistory();
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 14 }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          LEADERBOARD HISTORY · TOP 10
        </span>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>
          rank evolution · 14 sessions
        </span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {data.agents.map((a, idx) => (
          <RankRow key={a.id} agent={a} rank={idx + 1} series={data.series} />
        ))}
      </div>
    </div>
  );
}

function RankRow({ agent, rank, series }) {
  const { T } = useTheme();
  // get this agent's rank-per-day
  const ranks = series.map(s => {
    const r = s.ranks.find(r => r.id === agent.id);
    return r ? r.rank : null;
  });
  const W = 360, H = 28, days = ranks.length;
  const min = 0.5, max = 11.5;
  const pts = ranks.map((r, i) => {
    if (r == null) return null;
    const x = (i / (days - 1)) * W;
    const y = ((Math.min(max, Math.max(min, r)) - min) / (max - min)) * H;
    return [x, y];
  }).filter(Boolean);
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 4px', borderBottom: `1px solid ${T.border}` }}>
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text3, width: 26 }}>#{rank}</span>
      <div style={{ width: 24, height: 24, borderRadius: 4, background: stratColor(agent.strategy), display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: 'JetBrains Mono', fontSize: 10, fontWeight: 700, color: '#0a0a0a' }}>
        {agent.initials}
      </div>
      <div style={{ width: 180 }}>
        <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, fontWeight: 600, color: T.text }}>{agent.display}</div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3 }}>
          {VOD_STRATEGY_SHORT[agent.strategy]} · {agent.rank}
        </div>
      </div>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ flexShrink: 0 }}>
        <polyline points={line} fill="none" stroke={T.accent2} strokeWidth="1.5" strokeLinejoin="round" />
        {pts.map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={i === pts.length - 1 ? 3 : 1.5} fill={i === pts.length - 1 ? T.text : T.accent2} />
        ))}
      </svg>
      <div style={{ flex: 1 }} />
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: agent.pnl > 0 ? T.ok : T.err, fontWeight: 600 }}>
        {fmtMoney(agent.pnl, { signed: true, dp: 0 })}
      </span>
    </div>
  );
}

// --- Strategy attribution mini-chart ----------------------

function StrategyAttribution({ vod }) {
  const { T } = useTheme();
  const totals = vod.summary.byStrategy;
  const totalPnl = Object.values(totals).reduce((s, x) => s + x.pnl, 0);
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18 }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3, marginBottom: 12 }}>
        STRATEGY ATTRIBUTION · TODAY
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(totals).map(([k, v]) => (
          <div key={k}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 11, marginBottom: 4 }}>
              <span style={{ color: T.text }}>{VOD_STRATEGY_LABEL[k]}</span>
              <span style={{ color: v.pnl > 0 ? T.ok : T.err, fontWeight: 600 }}>
                {fmtMoney(v.pnl, { signed: true, dp: 0 })} <span style={{ color: T.text3 }}>· {fmtPct(v.pnlPct)}</span>
              </span>
            </div>
            <div style={{ height: 6, background: T.panel2, borderRadius: 2, overflow: 'hidden', position: 'relative' }}>
              <div style={{
                position: 'absolute',
                left: v.pnl >= 0 ? '50%' : `${50 - Math.abs(v.pnl / Math.max(...Object.values(totals).map(x => Math.abs(x.pnl)))) * 50}%`,
                width: `${Math.abs(v.pnl / Math.max(...Object.values(totals).map(x => Math.abs(x.pnl)))) * 50}%`,
                height: '100%',
                background: stratColor(k),
              }} />
              <div style={{ position: 'absolute', left: '50%', width: 1, height: '100%', background: T.text3 }} />
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 4 }}>
              <span>{v.agents} agents</span>
              <span>{v.fills} fills</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Top-level Research page ---------------------

function ResearchPage({ vod }) {
  const { data: storylines } = useStorylines();
  return (
    <div>
      <ResearchHeader />
      <div style={{ padding: '0 24px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
        <PoolHistoryChart />
        <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: 18 }}>
          <LeaderboardHistory />
          <StrategyAttribution vod={vod} />
        </div>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: '#5e636f', marginBottom: 12 }}>
            ACTIVE STORYLINES · {storylines.length}
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(420px, 1fr))', gap: 16 }}>
            {storylines.map(sl => <StorylineCard key={sl.id} sl={sl} />)}
          </div>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { ResearchPage });
