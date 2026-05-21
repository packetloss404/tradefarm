// Beat picker — the keystone surface. Operator reviews the
// auto-detected dramatic moments for the day, toggles them in/out,
// reorders, and edits headlines before render.
//
// Layout: header · preview + detail · timeline strip · beat-list rail.

const BP = {
  bg: '#0c0d10',
  panel: '#13141a',
  panel2: '#191a22',
  panel3: '#1f2129',
  border: '#23252e',
  borderHi: '#363946',
  text: '#e7e8ec',
  text2: '#9094a0',
  text3: '#5e636f',
  accent: '#d4a02e',
  accent2: '#86c5ff',
  ok: '#34d399',
  err: '#fb7185',
  font: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: 'JetBrains Mono, ui-monospace, monospace',
};

// --- Preview pane (left side of top) ---------------------------------

function PreviewPane({ beat }) {
  const meta = BEAT_KIND_META[beat.kind];
  return (
    <div style={{ background: '#000', border: `1px solid ${BP.border}`, borderRadius: 6, flex: 1, position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
      {/* fake scene render based on scene_hint */}
      <div style={{ flex: 1, position: 'relative', background: `radial-gradient(ellipse at 30% 20%, oklch(0.28 0.08 ${meta.hue}) 0%, #0a0a0d 70%)` }}>
        <SceneVignette beat={beat} />
        <div style={{ position: 'absolute', inset: 0, padding: 22, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', pointerEvents: 'none' }}>
          <div style={{ display: 'inline-block', fontFamily: BP.mono, fontSize: 10, letterSpacing: 1.8, color: meta.accent, padding: '4px 8px', background: `oklch(0.2 0.05 ${meta.hue} / 0.85)`, border: `1px solid ${meta.accent}40`, borderRadius: 3, alignSelf: 'flex-start', marginBottom: 8 }}>
            {meta.label} · {beat.scene}
          </div>
          <div style={{ fontFamily: BP.font, fontSize: 26, fontWeight: 700, color: '#fff', letterSpacing: -0.3, marginBottom: 4, textShadow: '0 2px 8px rgba(0,0,0,0.8)' }}>
            {beat.headline}
          </div>
          <div style={{ fontFamily: BP.mono, fontSize: 13, color: '#cdd1da', textShadow: '0 2px 6px rgba(0,0,0,0.8)' }}>
            {beat.sub}
          </div>
        </div>
        <div style={{ position: 'absolute', top: 16, left: 16, display: 'flex', alignItems: 'center', gap: 8, fontFamily: BP.mono, fontSize: 11, color: '#fff8' }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: BP.err }} className="pulse-dot" />
          REPLAY · {beat.t} ET
        </div>
        <div style={{ position: 'absolute', top: 16, right: 16, fontFamily: BP.mono, fontSize: 11, color: '#fff8' }}>
          {beat.duration}.0s · 1920×1080 · 30fps
        </div>
      </div>
      {/* scrubber */}
      <div style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: 12, borderTop: `1px solid ${BP.border}`, background: BP.panel2 }}>
        <span style={{ fontFamily: BP.mono, fontSize: 14, color: BP.text }}>▸</span>
        <span style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text2, width: 80 }}>00:12 / {String(beat.duration).padStart(2, '0')}:00</span>
        <div style={{ flex: 1, height: 4, background: BP.panel3, borderRadius: 2, overflow: 'hidden', position: 'relative' }}>
          <div style={{ position: 'absolute', inset: 0, width: '24%', background: BP.accent }} />
        </div>
        <span style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3 }}>volume −18 dB</span>
      </div>
    </div>
  );
}

function SceneVignette({ beat }) {
  // Quick visual cue per scene_hint so the preview doesn't look empty.
  const meta = BEAT_KIND_META[beat.kind];
  if (beat.scene === 'leaderboard') return <LeaderboardSceneCue agents={VOD_AGENTS} highlight={beat.agents[0]} />;
  if (beat.scene === 'brain' || beat.scene === 'decision-lab') return <BrainSceneCue beat={beat} meta={meta} />;
  if (beat.scene === 'showdown') return <ShowdownSceneCue beat={beat} />;
  if (beat.scene === 'recap') return <RecapSceneCue />;
  return <HeroSceneCue beat={beat} meta={meta} />;
}

function HeroSceneCue({ beat, meta }) {
  // diorama hint — concentric iso tiles
  const r = seededRng2(beat.id);
  return (
    <svg viewBox="0 0 600 320" preserveAspectRatio="xMidYMid slice" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: 0.55 }}>
      <defs>
        <linearGradient id={`hero-${beat.id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={meta.accent} stopOpacity="0.5" />
          <stop offset="100%" stopColor={meta.accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {Array.from({ length: 8 }).map((_, i) => (
        <g key={i} transform={`translate(${100 + i * 50}, ${220 - i * 14})`}>
          <polygon points="0,0 48,28 0,56 -48,28" fill="none" stroke={meta.accent} strokeOpacity="0.18" strokeWidth="1" />
        </g>
      ))}
      {Array.from({ length: 14 }).map((_, i) => {
        const x = r() * 600, y = 80 + r() * 200, sz = 6 + r() * 8;
        return <rect key={i} x={x} y={y} width={sz} height={sz} fill={meta.accent} opacity={0.4 + r() * 0.5} />;
      })}
      <rect x="0" y="200" width="600" height="120" fill={`url(#hero-${beat.id})`} />
    </svg>
  );
}

function LeaderboardSceneCue({ agents, highlight }) {
  const top = [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 8);
  return (
    <div style={{ position: 'absolute', inset: 24, display: 'flex', flexDirection: 'column', gap: 6, opacity: 0.85 }}>
      {top.map((a, i) => {
        const isHi = highlight != null && a.id === highlight;
        return (
          <div key={a.id} style={{
            display: 'flex', alignItems: 'center', gap: 12,
            background: isHi ? `oklch(0.3 0.12 50 / 0.6)` : 'rgba(255,255,255,0.04)',
            border: `1px solid ${isHi ? BP.accent : 'rgba(255,255,255,0.08)'}`,
            padding: '6px 12px', borderRadius: 4,
          }}>
            <span style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text3, width: 24 }}>#{i + 1}</span>
            <span style={{ width: 24, height: 24, borderRadius: 4, background: stratColor(a.strategy), display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: BP.mono, fontSize: 10, fontWeight: 700, color: '#0a0a0a' }}>
              {a.initials}
            </span>
            <span style={{ fontFamily: BP.font, fontSize: 13, color: '#fff', flex: 1 }}>{a.display}</span>
            <span style={{ fontFamily: BP.mono, fontSize: 13, color: a.pnl > 0 ? BP.ok : BP.err, fontWeight: 600 }}>
              {fmtMoney(a.pnl, { signed: true, dp: 0 })}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BrainSceneCue({ beat, meta }) {
  const agent = VOD_AGENTS[beat.agents[0] || 0];
  return (
    <div style={{ position: 'absolute', inset: 32, display: 'flex', gap: 18 }}>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.4)', borderRadius: 6, padding: 16 }}>
        <div style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3, marginBottom: 8 }}>LSTM probs</div>
        {['up', 'flat', 'down'].map((d, i) => (
          <div key={d} style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <span style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text2, width: 36 }}>{d}</span>
            <div style={{ flex: 1, height: 10, background: '#0008', borderRadius: 2, overflow: 'hidden' }}>
              <div style={{ width: `${[71, 18, 11][i]}%`, height: '100%', background: i === 0 ? meta.accent : `${meta.accent}55` }} />
            </div>
            <span style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text }}>{['0.71','0.18','0.11'][i]}</span>
          </div>
        ))}
      </div>
      <div style={{ flex: 1, background: 'rgba(0,0,0,0.4)', borderRadius: 6, padding: 16 }}>
        <div style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3, marginBottom: 8 }}>LLM overlay · claude-haiku-4-5</div>
        <div style={{ fontFamily: BP.font, fontSize: 12, color: '#cdd1da', lineHeight: 1.6 }}>
          "Strong upside conviction. 19/19 features point up, sector flow positive, no earnings risk in window. Sizing 95%."
        </div>
        <div style={{ marginTop: 12, fontFamily: BP.mono, fontSize: 11, color: BP.accent }}>
          stance: trade · bias: long · size_pct: 0.95
        </div>
      </div>
    </div>
  );
}

function ShowdownSceneCue({ beat }) {
  const [a, b] = beat.agents.map(id => VOD_AGENTS[id]);
  if (!a || !b) return null;
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <ShowdownAvatar agent={a} side="left" />
      <div style={{ fontFamily: BP.mono, fontSize: 48, fontWeight: 800, color: BP.err, padding: '0 36px', opacity: 0.7 }}>VS</div>
      <ShowdownAvatar agent={b} side="right" />
    </div>
  );
}

function ShowdownAvatar({ agent, side }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}>
      <div style={{ width: 80, height: 80, borderRadius: 12, background: stratColor(agent.strategy), display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: BP.mono, fontSize: 28, fontWeight: 700, color: '#0a0a0a' }}>
        {agent.initials}
      </div>
      <div style={{ fontFamily: BP.font, fontSize: 14, color: '#fff', fontWeight: 600 }}>{agent.display}</div>
      <div style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text2 }}>{VOD_STRATEGY_SHORT[agent.strategy]} · {agent.rank}</div>
      <div style={{ fontFamily: BP.mono, fontSize: 14, color: agent.pnl > 0 ? BP.ok : BP.err, fontWeight: 600 }}>
        {fmtMoney(agent.pnl, { signed: true })}
      </div>
    </div>
  );
}

function RecapSceneCue() {
  return (
    <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 6 }}>
      <div style={{ fontFamily: BP.mono, fontSize: 11, letterSpacing: 3, color: BP.accent }}>POOL P&L · DAY</div>
      <div style={{ fontFamily: BP.font, fontSize: 88, fontWeight: 800, color: BP.ok, letterSpacing: -3 }}>
        +1.84%
      </div>
      <div style={{ fontFamily: BP.mono, fontSize: 13, color: BP.text2 }}>
        +$1,840 · best since Apr 24
      </div>
    </div>
  );
}

function seededRng2(id) {
  let s = 0;
  for (let i = 0; i < id.length; i++) s = (s * 31 + id.charCodeAt(i)) >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

Object.assign(window, { PreviewPane, SceneVignette });
