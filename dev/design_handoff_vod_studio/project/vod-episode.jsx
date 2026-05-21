// Episode page — the finished VOD card: thumbnail, title, chapters,
// description, upload status. Operator's "review before publish" view.

const EP = {
  bg: '#0c0d10',
  panel: '#13141a',
  panel2: '#191a22',
  border: '#23252e',
  borderHi: '#363946',
  text: '#e7e8ec',
  text2: '#9094a0',
  text3: '#5e636f',
  accent: '#d4a02e',
  yt: '#ff0033',
  ok: '#34d399',
  err: '#fb7185',
  font: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: 'JetBrains Mono, ui-monospace, monospace',
};

function EpisodeHeader({ vod }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '16px 24px', borderBottom: `1px solid ${EP.border}`, background: EP.panel }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontFamily: EP.mono, fontSize: 10, letterSpacing: 2, color: EP.text3 }}>EP</span>
        <span style={{ fontFamily: EP.mono, fontSize: 22, fontWeight: 700, color: EP.text, letterSpacing: -0.5 }}>
          {String(vod.episodeNumber).padStart(3, '0')}
        </span>
      </div>
      <div style={{ width: 1, height: 24, background: EP.border }} />
      <div>
        <div style={{ fontFamily: EP.font, fontSize: 14, fontWeight: 600, color: EP.text }}>Episode review</div>
        <div style={{ fontFamily: EP.mono, fontSize: 10, color: EP.text2 }}>
          ready · upload window 16:30–16:45 ET · auto-publish ON
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <button style={epBtn()}>← back to beats</button>
      <button style={epBtn()}>↓ download mp4</button>
      <button style={{ ...epBtn(EP.yt), background: EP.yt, color: '#fff' }}>
        ▲ upload to YouTube
      </button>
    </div>
  );
}

function epBtn(color) {
  return {
    fontFamily: EP.mono, fontSize: 11, letterSpacing: 0.4, fontWeight: 600,
    padding: '8px 12px', border: `1px solid ${color || EP.border}`,
    background: 'transparent', color: color || EP.text, borderRadius: 4, cursor: 'pointer',
  };
}

function Thumbnail({ vod }) {
  return (
    <div style={{ position: 'relative', aspectRatio: '16/9', width: '100%', background: 'linear-gradient(135deg, #1a1f2e 0%, #0a0a0d 100%)', borderRadius: 8, overflow: 'hidden', border: `1px solid ${EP.border}` }}>
      <svg viewBox="0 0 1280 720" preserveAspectRatio="xMidYMid slice" style={{ position: 'absolute', inset: 0, width: '100%', height: '100%' }}>
        <defs>
          <linearGradient id="thumb-bg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1d2440" />
            <stop offset="100%" stopColor="#08080d" />
          </linearGradient>
          <radialGradient id="thumb-glow" cx="0.78" cy="0.42" r="0.6">
            <stop offset="0%" stopColor={EP.ok} stopOpacity="0.5" />
            <stop offset="100%" stopColor={EP.ok} stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="1280" height="720" fill="url(#thumb-bg)" />
        <rect width="1280" height="720" fill="url(#thumb-glow)" />
        {/* iso diorama hint */}
        {Array.from({ length: 10 }).map((_, i) => (
          <g key={i} transform={`translate(${260 + i * 70}, ${480 - i * 18})`}>
            <polygon points="0,0 64,38 0,76 -64,38" fill="none" stroke={EP.accent} strokeOpacity="0.18" strokeWidth="1.5" />
          </g>
        ))}
        {/* sparkline */}
        <polyline points="60,540 100,520 140,530 180,500 220,480 260,490 300,460 340,440 380,450 420,420 460,400 500,380 540,360"
          fill="none" stroke={EP.ok} strokeWidth="4" strokeLinejoin="round" strokeLinecap="round" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, padding: '36px 40px', display: 'flex', flexDirection: 'column', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
          <div>
            <div style={{ fontFamily: EP.mono, fontSize: 12, letterSpacing: 3, color: EP.accent, marginBottom: 8 }}>
              TODAY ON TRADEFARM · EP {String(vod.episodeNumber).padStart(3, '0')}
            </div>
            <div style={{ fontFamily: EP.font, fontSize: 60, fontWeight: 800, color: '#fff', letterSpacing: -1.5, lineHeight: 1, maxWidth: 600 }}>
              Mei takes #1<br />after 47 days
            </div>
          </div>
          <div style={{ fontFamily: EP.mono, fontSize: 13, color: '#fff8' }}>
            tue · may 19
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between' }}>
          <div style={{ fontFamily: EP.font, fontSize: 22, fontWeight: 600, color: '#cdd1da', maxWidth: 540 }}>
            <span style={{ color: EP.ok, fontWeight: 800 }}>+1.84%</span> day · biggest rivalry yet · 1 promotion
          </div>
          <div style={{ fontFamily: EP.mono, fontSize: 13, color: '#fff8', textAlign: 'right' }}>
            100 agents · 312 fills · {String(Math.floor(vod.totalDuration / 60)).padStart(2, '0')}:{String(vod.totalDuration % 60).padStart(2, '0')}
          </div>
        </div>
      </div>
      <div style={{ position: 'absolute', bottom: 12, right: 14, fontFamily: EP.mono, fontSize: 11, color: '#fff', background: 'rgba(0,0,0,0.7)', padding: '3px 7px', borderRadius: 3 }}>
        {String(Math.floor(vod.totalDuration / 60)).padStart(2, '0')}:{String(vod.totalDuration % 60).padStart(2, '0')}
      </div>
    </div>
  );
}

function MetaField({ label, children, mono }) {
  return (
    <div>
      <div style={{ fontFamily: EP.mono, fontSize: 9, letterSpacing: 1.8, color: EP.text3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: mono ? EP.mono : EP.font, fontSize: 13, color: EP.text, lineHeight: 1.5 }}>
        {children}
      </div>
    </div>
  );
}

function ChapterList({ vod }) {
  const selected = vod.beats.filter(b => vod.selectedBeats.has(b.id));
  let cumulative = 0;
  const rows = selected.map(b => {
    const start = cumulative;
    cumulative += b.duration;
    return { ...b, start };
  });
  const fmtStamp = s => {
    const m = Math.floor(s / 60), r = s % 60;
    return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  };
  return (
    <div>
      <div style={{ fontFamily: EP.mono, fontSize: 9, letterSpacing: 1.8, color: EP.text3, marginBottom: 8 }}>
        chapters · auto · {rows.length}
      </div>
      <div style={{ background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 4, padding: 12, fontFamily: EP.mono, fontSize: 12, lineHeight: 1.9, color: EP.text2, maxHeight: 240, overflow: 'auto' }}>
        {rows.map(r => (
          <div key={r.id} style={{ display: 'flex', gap: 12 }}>
            <span style={{ color: EP.accent, width: 52, flexShrink: 0 }}>{fmtStamp(r.start)}</span>
            <span style={{ color: EP.text, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.headline}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function UploadStrip({ vod }) {
  const steps = [
    { label: 'reel.mp4', sub: '1080p · 47.2 MB', ok: true },
    { label: 'thumbnail', sub: '1280×720 · 184 KB', ok: true },
    { label: 'metadata', sub: 'title · desc · 13 chapters', ok: true },
    { label: 'YT upload', sub: 'queued · 16:30 ET', ok: false, pending: true },
  ];
  return (
    <div style={{ display: 'flex', gap: 10, background: EP.panel, border: `1px solid ${EP.border}`, borderRadius: 6, padding: 14 }}>
      {steps.map((s, i) => (
        <div key={s.label} style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 10, padding: '6px 8px', borderRight: i < steps.length - 1 ? `1px solid ${EP.border}` : 'none' }}>
          <span style={{
            width: 22, height: 22, borderRadius: 999,
            background: s.ok ? `${EP.ok}22` : `${EP.accent}22`,
            border: `1px solid ${s.ok ? EP.ok : EP.accent}`,
            color: s.ok ? EP.ok : EP.accent,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: EP.mono, fontSize: 11, fontWeight: 700,
          }} className={s.pending ? 'pulse-dot' : ''}>
            {s.ok ? '✓' : '⋯'}
          </span>
          <div>
            <div style={{ fontFamily: EP.font, fontSize: 12, color: EP.text, fontWeight: 600 }}>{s.label}</div>
            <div style={{ fontFamily: EP.mono, fontSize: 10, color: EP.text3 }}>{s.sub}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function EpisodePage({ vod }) {
  return (
    <div style={{ width: '100%', height: '100%', background: EP.bg, color: EP.text, fontFamily: EP.font, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <EpisodeHeader vod={vod} />
      <div style={{ flex: 1, minHeight: 0, overflow: 'auto', padding: 20 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 20 }}>
          {/* Left: thumbnail + upload */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Thumbnail vod={vod} />
            <UploadStrip vod={vod} />
            <div style={{ background: EP.panel, border: `1px solid ${EP.border}`, borderRadius: 6, padding: 16 }}>
              <div style={{ fontFamily: EP.mono, fontSize: 9, letterSpacing: 1.8, color: EP.text3, marginBottom: 8 }}>
                episode stats
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14 }}>
                <Stat2 label="duration" value={`${Math.floor(vod.totalDuration / 60)}:${String(vod.totalDuration % 60).padStart(2, '0')}`} />
                <Stat2 label="beats" value={`${vod.selectedBeats.size} / ${vod.beats.length}`} />
                <Stat2 label="cost (LLM + TTS)" value={`$${(vod.summary.llmSpend + 1.42).toFixed(2)}`} />
                <Stat2 label="render time" value="8m 14s" />
                <Stat2 label="pool P&L" value={fmtPct(vod.summary.pnlPct)} color={EP.ok} />
                <Stat2 label="fills" value={fmtInt(vod.summary.fillCount)} />
                <Stat2 label="promotions" value="1 ↑ · 0 ↓" />
                <Stat2 label="biggest mover" value="Mei Patel +$284" />
              </div>
            </div>
          </div>
          {/* Right: metadata */}
          <div style={{ background: EP.panel, border: `1px solid ${EP.border}`, borderRadius: 6, padding: 18, display: 'flex', flexDirection: 'column', gap: 18 }}>
            <MetaField label="title · editable">
              <div className="dc-editable" contentEditable suppressContentEditableWarning style={{
                fontSize: 18, fontWeight: 700, color: EP.text, lineHeight: 1.3,
                background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 4,
                padding: '10px 12px',
              }}>
                Mei takes #1 after 47 days · TradeFarm Day {vod.episodeNumber}
              </div>
            </MetaField>

            <MetaField label="description · auto-generated">
              <div className="dc-editable" contentEditable suppressContentEditableWarning style={{
                color: EP.text2, lineHeight: 1.6,
                background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 4,
                padding: '10px 12px', minHeight: 120, fontSize: 12.5,
              }}>
                100 paper-trading AI agents had their best day since April 24. Mei Patel overtook a 47-day reign at #1, Marcus Wagner went big on NVDA, and a four-time rivalry between Brian Anderson and Lisa Garcia finally tipped. <br /><br />
                Pool finished +1.84% with 1 promotion (Henry Bennett to senior). Watch through to the close — the last nine minutes had 18 fills.
              </div>
            </MetaField>

            <ChapterList vod={vod} />

            <MetaField label="tags · auto" mono>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {['tradefarm','ai trading','paper trading','llm','lstm','daily recap','agent academy','autonomous','vod'].map(t => (
                  <span key={t} style={{ fontSize: 11, padding: '3px 8px', background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 3, color: EP.text2 }}>
                    {t}
                  </span>
                ))}
              </div>
            </MetaField>

            <MetaField label="schedule · YT" mono>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <input type="text" defaultValue="2026-05-19 16:30 ET" readOnly style={{
                  flex: 1, fontFamily: EP.mono, fontSize: 12, padding: '8px 10px',
                  background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 4, color: EP.text,
                }} />
                <select style={{
                  fontFamily: EP.mono, fontSize: 12, padding: '8px 10px',
                  background: EP.bg, border: `1px solid ${EP.border}`, borderRadius: 4, color: EP.text,
                }} defaultValue="unlisted">
                  <option>public</option>
                  <option>unlisted</option>
                  <option>private</option>
                </select>
              </div>
            </MetaField>
          </div>
        </div>
      </div>
    </div>
  );
}

function Stat2({ label, value, color }) {
  return (
    <div>
      <div style={{ fontFamily: EP.mono, fontSize: 9, letterSpacing: 1.4, color: EP.text3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontFamily: EP.mono, fontSize: 14, color: color || EP.text, fontWeight: 600, fontFeatureSettings: '"tnum"' }}>
        {value}
      </div>
    </div>
  );
}

Object.assign(window, { EpisodePage });
