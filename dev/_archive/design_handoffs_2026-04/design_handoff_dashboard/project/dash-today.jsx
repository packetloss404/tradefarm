// Today page — the home screen. Live session + pipeline state +
// today's episode preview. Hero focus on what's happening NOW.

function HeroStrip({ vod }) {
  const { T } = useTheme();
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
      gap: 16, marginBottom: 16,
    }}>
      <HeroCard label="POOL EQUITY"
        value={'$' + vod.summary.totalEquity.toLocaleString('en-US', { maximumFractionDigits: 0 })}
        sub={`${vod.summary.totalEquity >= 100000 ? '+' : ''}${(vod.summary.totalEquity - 100000).toFixed(0)} since open`}
        color={T.ok} accent />
      <HeroCard label="DAY P&L" value={fmtPct(vod.summary.pnlPct)} sub="best since Apr 24" color={T.ok} />
      <HeroCard label="FILLS / DECISIONS" value={`${vod.summary.fillCount} / ${vod.summary.decisionCount.toLocaleString()}`} sub="6.5% fill rate" />
      <HeroCard label="LLM SPEND TODAY" value={`$${vod.summary.llmSpend.toFixed(2)}`} sub="of $13.10 daily cap (22%)" />
    </div>
  );
}

function HeroCard({ label, value, sub, color, accent }) {
  const { T } = useTheme();
  return (
    <div style={{
      background: T.panel, border: `1px solid ${accent ? T.borderHi : T.border}`,
      borderRadius: 8, padding: 18, position: 'relative',
    }}>
      {accent && <div style={{ position: 'absolute', left: 0, top: 18, bottom: 18, width: 3, background: T.accent, borderRadius: 2 }} />}
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.8, color: T.text3, marginBottom: 8 }}>
        {label}
      </div>
      <div style={{
        fontFamily: 'JetBrains Mono', fontSize: 28, fontWeight: 600,
        color: color || T.text, letterSpacing: -0.5, fontFeatureSettings: '"tnum"',
      }}>{value}</div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2, marginTop: 6 }}>{sub}</div>
    </div>
  );
}

// --- Live equity chart ---------------------------------------------

function LiveEquityChart({ vod }) {
  const { T } = useTheme();
  const W = 800, H = 180;
  const points = React.useMemo(() => {
    const arr = [];
    const r = seededRng2('today-equity');
    let v = 0;
    for (let i = 0; i < 280; i++) {
      v += (r() - 0.46) * 4 + Math.sin(i / 32) * 0.6;
      arr.push(v);
    }
    return arr;
  }, []);
  const progress = 0.62;
  const visible = points.slice(0, Math.max(2, Math.floor(points.length * progress)));
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const pts = visible.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p - min) / span) * (H - 12) - 6;
    return [x, y];
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `0,${H} ${line} ${pts[pts.length - 1][0].toFixed(1)},${H}`;
  const lastY = pts[pts.length - 1][1];
  const lastX = pts[pts.length - 1][0];
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>POOL EQUITY · LIVE</div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginTop: 4 }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 22, fontWeight: 600, color: T.text }}>
              $101,840
            </span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 14, fontWeight: 600, color: T.ok }}>
              +1.84%
            </span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2 }}>
              +$1,840 today
            </span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          {['1D','1W','1M','ALL'].map(p => (
            <button key={p} style={{
              fontFamily: 'JetBrains Mono', fontSize: 10, fontWeight: 600,
              padding: '4px 10px', borderRadius: 3, cursor: 'pointer',
              background: p === '1D' ? T.panel3 : 'transparent',
              border: `1px solid ${p === '1D' ? T.borderHi : T.border}`,
              color: p === '1D' ? T.text : T.text2,
            }}>{p}</button>
          ))}
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block', height: H }}>
        <defs>
          <linearGradient id="today-eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.ok} stopOpacity="0.3" />
            <stop offset="100%" stopColor={T.ok} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map(g => (
          <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke={T.border} strokeDasharray="2 4" />
        ))}
        <polygon points={fill} fill="url(#today-eq-fill)" />
        <polyline points={line} fill="none" stroke={T.ok} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
        <circle cx={lastX} cy={lastY} r="4" fill={T.ok} />
        <circle cx={lastX} cy={lastY} r="9" fill="none" stroke={T.ok} strokeOpacity="0.4" className="pulse-dot" />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3 }}>
        <span>09:30</span><span>11:00</span><span>12:30</span><span>14:00</span><span style={{ color: T.text }}>14:21</span><span style={{ opacity: 0.4 }}>16:00</span>
      </div>
    </div>
  );
}

// --- Agent pixel grid ----------------------------------------------

function AgentPixelGrid({ vod, hint = true }) {
  const { T } = useTheme();
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          ROSTER · 100 AGENTS
        </div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2, display: 'flex', gap: 12 }}>
          <Tag color={T.ok} label={`${vod.agents.filter(a => a.pnl > 8).length} profit`} />
          <Tag color={T.err} label={`${vod.agents.filter(a => a.pnl < -8).length} loss`} />
          <Tag color={T.text3} label={`${vod.agents.filter(a => Math.abs(a.pnl) <= 8).length} flat`} />
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(25, 1fr)', gap: 3 }}>
        {vod.agents.map(a => (
          <div key={a.id}
            title={`${a.display} · ${VOD_STRATEGY_SHORT[a.strategy]} · ${fmtMoney(a.pnl, { signed: true, dp: 0 })}`}
            style={{
              width: '100%', aspectRatio: '1', borderRadius: 2,
              background: a.pnl > 8 ? T.ok : a.pnl < -8 ? T.err : T.text3,
              opacity: Math.min(1, 0.35 + Math.abs(a.pnl) / 60),
              cursor: 'pointer',
            }}
          />
        ))}
      </div>
      {hint && (
        <div style={{ marginTop: 10, fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3 }}>
          opacity = |P&L| · 25 cols × 4 rows · click for detail
        </div>
      )}
    </div>
  );
}

function Tag({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 6, height: 6, background: color, borderRadius: 1 }} />
      {label}
    </span>
  );
}

// --- Pipeline strip (today's render) -----------------------------

function PipelineStrip({ vod }) {
  const { T } = useTheme();
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18 }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 14 }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          TONIGHT'S RENDER · EP {String(vod.episodeNumber).padStart(3, '0')}
        </span>
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>
          2 done · 1 running · 7 queued
        </span>
        <span style={{ width: 8, height: 8, borderRadius: 999, background: T.accent, marginLeft: 12, boxShadow: `0 0 8px ${T.accent}` }} className="pulse-dot" />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: 8 }}>
        {vod.pipeline.map((node, i) => {
          const isRunning = node.status === 'running';
          const isDone = node.status === 'done';
          const color = isDone ? T.ok : isRunning ? T.accent : T.text3;
          const progress = isDone ? 1 : isRunning ? vod.renderProgress : 0;
          return (
            <div key={node.id} style={{
              background: isRunning ? T.panel2 : 'transparent',
              border: `1px solid ${isRunning ? T.borderHi : T.border}`,
              borderRadius: 4, padding: '10px 10px 8px',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
                <span style={{ width: 6, height: 6, borderRadius: 999, background: color, boxShadow: isRunning ? `0 0 6px ${color}` : 'none' }} className={isRunning ? 'pulse-dot' : ''} />
                <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: T.text3 }}>0{i + 1}</span>
              </div>
              <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 11, fontWeight: 600, color: T.text, marginBottom: 6, height: 28, overflow: 'hidden' }}>
                {node.label}
              </div>
              <MicroBar pct={progress} color={isDone ? T.ok : T.accent} />
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Episode preview card --------------------------------------

function EpisodePreviewCard({ vod }) {
  const { T } = useTheme();
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
            TONIGHT'S EPISODE
          </div>
          <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 16, fontWeight: 600, color: T.text, marginTop: 4 }}>
            EP {String(vod.episodeNumber).padStart(3, '0')} · {vod.sessionDate.slice(5)}
          </div>
        </div>
        <span style={{
          fontFamily: 'JetBrains Mono', fontSize: 10, fontWeight: 700, letterSpacing: 1,
          padding: '3px 8px', borderRadius: 3,
          background: `${T.accent}22`, color: T.accent,
        }}>RENDERING</span>
      </div>
      {/* mini thumb */}
      <div style={{ aspectRatio: '16/9', borderRadius: 6, border: `1px solid ${T.border}`, position: 'relative', overflow: 'hidden', background: `linear-gradient(135deg, oklch(0.2 0.05 200) 0%, ${T.bg} 100%)` }}>
        <svg viewBox="0 0 320 180" preserveAspectRatio="xMidYMid slice" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
          {Array.from({ length: 6 }).map((_, i) => (
            <g key={i} transform={`translate(${60 + i * 30}, ${110 - i * 10})`}>
              <polygon points="0,0 26,15 0,30 -26,15" fill="none" stroke={T.accent} strokeOpacity="0.25" strokeWidth="1" />
            </g>
          ))}
          <polyline points="20,130 50,124 80,128 110,115 140,108 170,112 200,98 230,86 260,90 290,72" fill="none" stroke={T.ok} strokeWidth="2" strokeLinejoin="round" />
        </svg>
        <div style={{ position: 'absolute', inset: 16, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }}>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 2, color: T.accent, marginBottom: 4 }}>
            TODAY ON TRADEFARM · EP {String(vod.episodeNumber).padStart(3, '0')}
          </div>
          <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 20, fontWeight: 800, color: '#fff', lineHeight: 1.1, letterSpacing: -0.5 }}>
            Mei takes #1<br />after 47 days
          </div>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, padding: '8px 0' }}>
        <MiniStat label="ETA" value="14m" />
        <MiniStat label="DURATION" value={`${Math.floor(vod.totalDuration / 60)}:${String(vod.totalDuration % 60).padStart(2, '0')}`} />
        <MiniStat label="BEATS" value={`${vod.selectedBeats.size} / ${vod.beats.length}`} />
      </div>
      <a href="#beats" style={{
        display: 'block', textAlign: 'center', textDecoration: 'none',
        fontFamily: 'JetBrains Mono', fontSize: 11, fontWeight: 700, letterSpacing: 0.5,
        padding: '10px 12px', borderRadius: 4,
        background: T.accent, color: '#1a1408',
      }}>
        ▸ open beat picker
      </a>
    </div>
  );
}

function MiniStat({ label, value }) {
  const { T } = useTheme();
  return (
    <div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.4, color: T.text3, marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 15, fontWeight: 600, color: T.text }}>{value}</div>
    </div>
  );
}

// --- Recent fills feed ---------------------------------------

function RecentFills({ vod }) {
  const { T } = useTheme();
  const fills = React.useMemo(() => {
    return Array.from({ length: 12 }).map((_, i) => {
      const r = seededRng2('today-fill_' + i);
      const a = vod.agents[Math.floor(r() * vod.agents.length)];
      return {
        id: i,
        t: `14:${String(21 - i).padStart(2, '0')}`,
        symbol: SYMBOLS[Math.floor(r() * SYMBOLS.length)],
        side: r() > 0.5 ? 'BUY' : 'SELL',
        qty: Math.floor(1 + r() * 9),
        price: (50 + r() * 850).toFixed(2),
        agent: a,
        pnl: (r() - 0.45) * 80,
      };
    });
  }, []);
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          RECENT FILLS
        </span>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>last 12</span>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column' }}>
        {fills.map((f, i) => (
          <div key={f.id} style={{
            display: 'grid', gridTemplateColumns: '46px 38px 1fr auto',
            gap: 10, alignItems: 'center', padding: '7px 0',
            borderBottom: i < fills.length - 1 ? `1px solid ${T.border}` : 'none',
            fontFamily: 'JetBrains Mono', fontSize: 11,
          }}>
            <span style={{ color: T.text3 }}>{f.t}</span>
            <span style={{ color: f.side === 'BUY' ? T.ok : T.err, fontWeight: 700 }}>{f.side}</span>
            <span style={{ color: T.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              <span style={{ fontWeight: 600 }}>{f.symbol}</span>
              <span style={{ color: T.text3 }}> · </span>
              <span style={{ color: T.text2 }}>{f.qty}×{f.price}</span>
              <span style={{ color: T.text3 }}> · </span>
              <span style={{ color: T.text2 }}>{f.agent.display}</span>
            </span>
            <span style={{ color: f.pnl > 0 ? T.ok : T.err, fontWeight: 600 }}>
              {fmtMoney(f.pnl, { signed: true, dp: 0 })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Moments detected today ----------------------------------

function MomentsToday({ vod }) {
  const { T } = useTheme();
  const scored = vod.beats.slice(0, 8);
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, padding: 18, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          MOMENTS · DETECTED SO FAR
        </span>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>{scored.length} of ~13</span>
      </div>
      {scored.map(b => {
        const meta = BEAT_KIND_META[b.kind];
        return (
          <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '7px 0', borderBottom: `1px solid ${T.border}` }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, width: 36 }}>{b.t}</span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.2, fontWeight: 700, color: meta.accent, width: 84 }}>
              {meta.label}
            </span>
            <span style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {b.headline}
            </span>
            <div style={{ width: 40 }}>
              <MicroBar pct={b.score} color={meta.accent} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// --- Cost rail (toggleable) ---------------------------------

function CostRail({ vod }) {
  const { T } = useTheme();
  const burn = (vod.summary.llmSpend / 13.10) * 100;
  return (
    <div style={{
      background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8,
      padding: '12px 18px', display: 'flex', alignItems: 'center', gap: 24,
    }}>
      <div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>API SPEND TODAY</div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 18, fontWeight: 600, color: T.text }}>
          ${vod.summary.llmSpend.toFixed(2)} <span style={{ color: T.text3, fontSize: 12 }}>/ $13.10</span>
        </div>
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 6 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>
          <span>{burn.toFixed(0)}% of daily cap · projected to close at $4.30</span>
          <span style={{ color: T.text3 }}>{vod.summary.llmCalls} calls · {vod.summary.llmSkipped} skipped by gate (78%)</span>
        </div>
        <MicroBar pct={burn / 100} color={burn < 60 ? T.ok : burn < 90 ? T.warn : T.err} />
      </div>
      <div style={{ display: 'flex', gap: 14 }}>
        <CostMicro label="anthropic" value={`$${(vod.summary.llmSpend * 0.94).toFixed(2)}`} />
        <CostMicro label="eodhd" value="$0.65" />
        <CostMicro label="elevenlabs" value="$1.42 est" />
      </div>
    </div>
  );
}

function CostMicro({ label, value }) {
  const { T } = useTheme();
  return (
    <div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, color: T.text3 }}>{label}</div>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 600, color: T.text }}>{value}</div>
    </div>
  );
}

// --- Top-level Today page -------------------------------------

function TodayPage({ vod, tweaks }) {
  return (
    <div style={{ padding: 24, display: 'flex', flexDirection: 'column', gap: 16 }}>
      <HeroStrip vod={vod} />
      {tweaks.showCostRail && <CostRail vod={vod} />}
      <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: 16 }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <LiveEquityChart vod={vod} />
          <AgentPixelGrid vod={vod} />
        </div>
        <EpisodePreviewCard vod={vod} />
      </div>
      {tweaks.showPipelinePanel && <PipelineStrip vod={vod} />}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <RecentFills vod={vod} />
        <MomentsToday vod={vod} />
      </div>
    </div>
  );
}

Object.assign(window, { TodayPage });
