// Session control room — start / monitor / abort a running trading
// session. The "let the simulation run" view. Live tick clock, agent
// roster ticker, fills feed, manifest counters.

const SC = {
  bg: '#0c0d10',
  panel: '#13141a',
  panel2: '#191a22',
  border: '#23252e',
  borderHi: '#363946',
  text: '#e7e8ec',
  text2: '#9094a0',
  text3: '#5e636f',
  accent: '#d4a02e',
  ok: '#34d399',
  err: '#fb7185',
  rec: '#ef4444',
  font: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: 'JetBrains Mono, ui-monospace, monospace',
};

function SessionHeader({ vod, sessionRunning, elapsed }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '14px 24px', borderBottom: `1px solid ${SC.border}`, background: SC.panel }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span style={{ width: 10, height: 10, borderRadius: 999, background: SC.rec, boxShadow: `0 0 10px ${SC.rec}` }} className="pulse-dot" />
        <span style={{ fontFamily: SC.mono, fontSize: 11, fontWeight: 800, letterSpacing: 1.4, color: SC.rec }}>
          REC · SESSION
        </span>
      </div>
      <div style={{ width: 1, height: 22, background: SC.border }} />
      <div>
        <div style={{ fontFamily: SC.font, fontSize: 14, fontWeight: 600, color: SC.text }}>
          Session control
        </div>
        <div style={{ fontFamily: SC.mono, fontSize: 10, color: SC.text2 }}>
          {vod.sessionId} · started 09:30:04 ET · {sessionRunning ? 'running' : 'paused'}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <Stat3 label="session time" value={formatElapsed(elapsed)} mono />
      <Stat3 label="market time" value={<ETClock />} mono />
      <Stat3 label="tick" value="3,840 / 23,400" mono />
      <Stat3 label="speed" value="38× realtime" mono />
      <div style={{ width: 1, height: 22, background: SC.border }} />
      <button style={scBtn()}>⏸ pause</button>
      <button style={{ ...scBtn(SC.err), color: SC.err, borderColor: SC.err }}>■ abort</button>
    </div>
  );
}

function formatElapsed(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

function scBtn(color) {
  return {
    fontFamily: SC.mono, fontSize: 11, letterSpacing: 0.4, fontWeight: 600,
    padding: '7px 12px', border: `1px solid ${color || SC.border}`,
    background: 'transparent', color: color || SC.text, borderRadius: 4, cursor: 'pointer',
  };
}

function Stat3({ label, value, color, mono }) {
  return (
    <div style={{ minWidth: 92 }}>
      <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.4, color: SC.text3, marginBottom: 3 }}>{label}</div>
      <div style={{ fontFamily: mono ? SC.mono : SC.font, fontSize: 14, color: color || SC.text, fontWeight: 600, fontFeatureSettings: '"tnum"' }}>
        {value}
      </div>
    </div>
  );
}

// --- Live equity chart ---------------------------------------------

function EquityChart({ progress }) {
  const W = 760, H = 220;
  const points = React.useMemo(() => {
    const arr = [];
    const r = seededRng2('equity');
    let v = 0;
    for (let i = 0; i < 240; i++) {
      v += (r() - 0.48) * 4 + Math.sin(i / 32) * 0.6;
      arr.push(v);
    }
    return arr;
  }, []);
  const visibleCount = Math.floor(points.length * progress);
  const visible = points.slice(0, Math.max(2, visibleCount));
  const min = Math.min(...points), max = Math.max(...points);
  const span = max - min || 1;
  const pts = visible.map((p, i) => {
    const x = (i / (points.length - 1)) * W;
    const y = H - ((p - min) / span) * (H - 12) - 6;
    return [x, y];
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = `0,${H} ${line} ${pts.length > 0 ? pts[pts.length - 1][0].toFixed(1) : 0},${H}`;
  const lastY = pts.length > 0 ? pts[pts.length - 1][1] : H;
  const lastX = pts.length > 0 ? pts[pts.length - 1][0] : 0;
  return (
    <div style={{ background: SC.panel, border: `1px solid ${SC.border}`, borderRadius: 6, padding: 16, position: 'relative' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.6, color: SC.text3 }}>POOL EQUITY · LIVE</div>
          <div style={{ fontFamily: SC.mono, fontSize: 26, fontWeight: 700, color: SC.text, marginTop: 2 }}>
            $101,840 <span style={{ color: SC.ok, fontSize: 16 }}>+1.84%</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 12, fontFamily: SC.mono, fontSize: 11, color: SC.text2 }}>
          <span>open $100,000</span>
          <span>·</span>
          <span>high $101,840</span>
          <span>·</span>
          <span>low $99,460</span>
        </div>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block', height: H }}>
        <defs>
          <linearGradient id="eq-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={SC.ok} stopOpacity="0.35" />
            <stop offset="100%" stopColor={SC.ok} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map(g => (
          <line key={g} x1="0" x2={W} y1={H * g} y2={H * g} stroke={SC.border} strokeDasharray="2 4" />
        ))}
        {pts.length > 1 && (
          <>
            <polygon points={fill} fill="url(#eq-fill)" />
            <polyline points={line} fill="none" stroke={SC.ok} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            <circle cx={lastX} cy={lastY} r="4" fill={SC.ok} />
            <circle cx={lastX} cy={lastY} r="9" fill="none" stroke={SC.ok} strokeOpacity="0.4" className="pulse-dot" />
          </>
        )}
        {/* hour ticks */}
        {[0.077, 0.231, 0.385, 0.538, 0.692, 0.846, 1].map((p, i) => (
          <line key={i} x1={p * W} x2={p * W} y1={H - 4} y2={H} stroke={SC.text3} strokeWidth="1" />
        ))}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: SC.mono, fontSize: 10, color: SC.text3, marginTop: 4 }}>
        <span>09:30</span><span>10:30</span><span>11:30</span><span>12:30</span><span>13:30</span><span>14:30</span><span>15:30</span><span>16:00</span>
      </div>
    </div>
  );
}

// --- Agent roster grid (100 dots) ----------------------------------

function AgentDot({ a, tick }) {
  const c = a.pnl > 8 ? SC.ok : a.pnl < -8 ? SC.err : SC.text3;
  return (
    <div title={`${a.display} · ${VOD_STRATEGY_SHORT[a.strategy]} · ${fmtMoney(a.pnl, { signed: true, dp: 0 })}`}
      style={{
        width: '100%', aspectRatio: '1', borderRadius: 3,
        background: c, opacity: Math.min(1, 0.4 + Math.abs(a.pnl) / 60),
        cursor: 'pointer',
      }}
    />
  );
}

function AgentRoster({ vod }) {
  return (
    <div style={{ background: SC.panel, border: `1px solid ${SC.border}`, borderRadius: 6, padding: 16, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between' }}>
        <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.6, color: SC.text3 }}>
          ROSTER · 100 AGENTS
        </div>
        <div style={{ fontFamily: SC.mono, fontSize: 10, color: SC.text2, display: 'flex', gap: 12 }}>
          <span><span style={{ display: 'inline-block', width: 6, height: 6, background: SC.ok, marginRight: 5, borderRadius: 1 }} />profit {vod.agents.filter(a => a.pnl > 8).length}</span>
          <span><span style={{ display: 'inline-block', width: 6, height: 6, background: SC.err, marginRight: 5, borderRadius: 1 }} />loss {vod.agents.filter(a => a.pnl < -8).length}</span>
          <span><span style={{ display: 'inline-block', width: 6, height: 6, background: SC.text3, marginRight: 5, borderRadius: 1 }} />flat {vod.agents.filter(a => Math.abs(a.pnl) <= 8).length}</span>
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(20, 1fr)', gap: 4 }}>
        {vod.agents.map(a => <AgentDot key={a.id} a={a} tick={vod.renderTick} />)}
      </div>
    </div>
  );
}

// --- Moment rail (recently scored beats so far) --------------------

function MomentRail({ vod }) {
  // Beats up to ~"now" — first 8 for the demo.
  const scored = vod.beats.slice(0, 8);
  return (
    <div style={{ background: SC.panel, border: `1px solid ${SC.border}`, borderRadius: 6, padding: 16, flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.6, color: SC.text3 }}>
          MOMENTS · DETECTED SO FAR
        </div>
        <div style={{ fontFamily: SC.mono, fontSize: 10, color: SC.text2 }}>
          {scored.length} of ~13 expected · beat detector runs at close
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, overflow: 'auto', flex: 1, minHeight: 0 }}>
        {scored.map(b => {
          const meta = BEAT_KIND_META[b.kind];
          return (
            <div key={b.id} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 10px', background: SC.bg, border: `1px solid ${SC.border}`, borderRadius: 4 }}>
              <span style={{ fontFamily: SC.mono, fontSize: 10, color: SC.text3, width: 40 }}>{b.t}</span>
              <span style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.4, color: meta.accent, fontWeight: 700, width: 84 }}>
                {meta.label}
              </span>
              <span style={{ fontFamily: SC.font, fontSize: 12, color: SC.text, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {b.headline}
              </span>
              <div style={{ width: 60, height: 4, background: SC.panel2, borderRadius: 2, overflow: 'hidden' }}>
                <div style={{ width: `${b.score * 100}%`, height: '100%', background: meta.accent }} />
              </div>
              <span style={{ fontFamily: SC.mono, fontSize: 10, color: SC.text2, width: 28, textAlign: 'right' }}>
                {(b.score * 100).toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Live fills feed ----------------------------------------------

function LiveFillsFeed({ vod }) {
  const fills = React.useMemo(() => {
    return Array.from({ length: 18 }).map((_, i) => {
      const r = seededRng2('fill_' + i);
      const a = vod.agents[Math.floor(r() * vod.agents.length)];
      return {
        id: i,
        t: `${String(9 + Math.floor((i * 21) / 60)).padStart(2, '0')}:${String((i * 21) % 60).padStart(2, '0')}`,
        symbol: SYMBOLS[Math.floor(r() * SYMBOLS.length)],
        side: r() > 0.5 ? 'BUY' : 'SELL',
        qty: Math.floor(1 + r() * 9),
        price: (50 + r() * 850).toFixed(2),
        agent: a,
      };
    });
  }, [vod.renderTick > 0]);
  return (
    <div style={{ background: SC.panel, border: `1px solid ${SC.border}`, borderRadius: 6, padding: 16, display: 'flex', flexDirection: 'column', gap: 10, height: '100%' }}>
      <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.6, color: SC.text3 }}>
        FILLS · LAST 18
      </div>
      <div style={{ overflow: 'auto', flex: 1, fontFamily: SC.mono, fontSize: 11 }}>
        {fills.map(f => (
          <div key={f.id} style={{
            display: 'grid', gridTemplateColumns: '52px 44px 54px 70px 1fr',
            gap: 8, padding: '5px 0', borderBottom: `1px solid ${SC.border}`,
            color: SC.text2,
          }}>
            <span style={{ color: SC.text3 }}>{f.t}</span>
            <span style={{ color: f.side === 'BUY' ? SC.ok : SC.err, fontWeight: 700 }}>{f.side}</span>
            <span style={{ color: SC.text }}>{f.symbol}</span>
            <span style={{ color: SC.text, fontFeatureSettings: '"tnum"' }}>{f.qty}×{f.price}</span>
            <span style={{ color: SC.text2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {f.agent.display}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

// --- Manifest panel ----------------------------------------------

function ManifestPanel({ vod, progress }) {
  const counters = [
    { label: 'ticks', value: Math.floor(23400 * progress).toLocaleString(), max: '23,400' },
    { label: 'decisions', value: Math.floor(4812 * progress).toLocaleString(), max: '4,812 est' },
    { label: 'fills', value: Math.floor(312 * progress), max: '312 est' },
    { label: 'LLM calls', value: Math.floor(1067 * progress), max: '~$2.84' },
    { label: 'manifest', value: `${Math.floor(184 * progress)} KB`, max: '184 KB at close' },
  ];
  return (
    <div style={{ background: SC.panel, border: `1px solid ${SC.border}`, borderRadius: 6, padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ fontFamily: SC.mono, fontSize: 9, letterSpacing: 1.6, color: SC.text3 }}>
        MANIFEST · BUILDING
      </div>
      {counters.map(c => (
        <div key={c.label}>
          <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: SC.mono, fontSize: 10, marginBottom: 4 }}>
            <span style={{ color: SC.text2 }}>{c.label}</span>
            <span style={{ color: SC.text3 }}>{c.max}</span>
          </div>
          <div style={{ fontFamily: SC.mono, fontSize: 16, color: SC.text, fontWeight: 600 }}>
            {c.value}
          </div>
        </div>
      ))}
      <div style={{ paddingTop: 6, borderTop: `1px solid ${SC.border}`, fontFamily: SC.mono, fontSize: 10, color: SC.text3 }}>
        writing → out/sessions/{vod.sessionId}/
      </div>
    </div>
  );
}

// --- Top-level component ----------------------------------------

function SessionControl({ vod }) {
  const [elapsed, setElapsed] = React.useState(6240); // ~1h44m
  React.useEffect(() => {
    const id = setInterval(() => setElapsed(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);
  // sim "progress" of the day — fixed at ~50% for the mock
  const progress = 0.55;
  return (
    <div style={{ width: '100%', height: '100%', background: SC.bg, color: SC.text, fontFamily: SC.font, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <SessionHeader vod={vod} sessionRunning={true} elapsed={elapsed} />
      <div style={{ flex: 1, minHeight: 0, padding: 16, display: 'grid', gridTemplateColumns: '1.6fr 1fr', gridTemplateRows: 'auto 1fr', gap: 14 }}>
        <EquityChart progress={progress} />
        <ManifestPanel vod={vod} progress={progress} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <AgentRoster vod={vod} />
          <MomentRail vod={vod} />
        </div>
        <LiveFillsFeed vod={vod} />
      </div>
    </div>
  );
}

Object.assign(window, { SessionControl });
