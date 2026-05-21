// Beat picker — main component. Composes header, preview pane,
// detail card, timeline strip, and beat-list rail.

// --- Timeline strip --------------------------------------------------
// Horizontal map of the trading day, 09:30 → 16:00 ET, with beat
// markers stacked by score. Selected beats sit in the master line;
// rejected beats are dimmed underneath.

function TimelineStrip({ vod, currentId, setCurrentId }) {
  const TOTAL_MS = 23400; // 6h30m * 60 = 390 min, but using same scale as data tMs
  const beats = vod.beats;
  return (
    <div style={{ background: BP.panel, border: `1px solid ${BP.border}`, borderRadius: 6, padding: '14px 16px 8px', display: 'flex', flexDirection: 'column', gap: 6, position: 'relative' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline' }}>
        <div style={{ fontFamily: BP.mono, fontSize: 10, letterSpacing: 1.8, color: BP.text3 }}>
          session timeline · 09:30 → 16:00 ET
        </div>
        <div style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3 }}>
          {beats.length} beats detected · {vod.selectedBeats.size} selected
        </div>
      </div>
      {/* time ruler */}
      <div style={{ position: 'relative', height: 18, marginTop: 4 }}>
        {['09:30','10:30','11:30','12:30','13:30','14:30','15:30','16:00'].map((t, i, arr) => {
          const x = (i / (arr.length - 1)) * 100;
          return (
            <div key={t} style={{ position: 'absolute', left: `${x}%`, top: 0, transform: 'translateX(-50%)', fontFamily: BP.mono, fontSize: 10, color: BP.text3 }}>
              {t}
            </div>
          );
        })}
        <div style={{ position: 'absolute', left: 0, right: 0, top: 16, height: 1, background: BP.border }} />
      </div>
      {/* selected lane */}
      <BeatLane label="MASTER" beats={beats.filter(b => vod.selectedBeats.has(b.id))} TOTAL={TOTAL_MS} currentId={currentId} setCurrentId={setCurrentId} selected />
      {/* rejected lane */}
      <BeatLane label="REJECTED" beats={beats.filter(b => !vod.selectedBeats.has(b.id))} TOTAL={TOTAL_MS} currentId={currentId} setCurrentId={setCurrentId} selected={false} />
    </div>
  );
}

function BeatLane({ label, beats, TOTAL, currentId, setCurrentId, selected }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
      <span style={{ fontFamily: BP.mono, fontSize: 9, letterSpacing: 1.6, color: BP.text3, width: 70, flexShrink: 0, textAlign: 'right' }}>
        {label}
      </span>
      <div style={{ flex: 1, height: selected ? 64 : 36, position: 'relative', background: selected ? BP.panel2 : '#10111600', borderRadius: 4, border: selected ? `1px solid ${BP.border}` : 'none' }}>
        {beats.map(b => {
          const left = (b.tMs / TOTAL) * 100;
          const width = (b.duration / 60 * 1000 / TOTAL) * 100; // beat width on the same scale
          const meta = BEAT_KIND_META[b.kind];
          const isCurrent = b.id === currentId;
          const barHeight = (selected ? 52 : 26) * Math.max(0.35, b.score);
          return (
            <div key={b.id}
              onClick={() => setCurrentId(b.id)}
              style={{
                position: 'absolute', left: `${left}%`, width: `max(${Math.max(2.4, width)}%, 18px)`,
                bottom: 6, height: barHeight,
                background: selected ? meta.accent : `${meta.accent}40`,
                border: isCurrent ? `2px solid ${BP.text}` : selected ? 'none' : `1px dashed ${meta.accent}80`,
                borderRadius: 2,
                cursor: 'pointer',
                opacity: selected ? 1 : 0.5,
              }}
              title={`${b.t} · ${b.headline}`}
            />
          );
        })}
      </div>
    </div>
  );
}

// --- Beat list rail (bottom) ----------------------------------------

function BeatListRail({ vod, currentId, setCurrentId }) {
  return (
    <div style={{ display: 'flex', gap: 10, overflowX: 'auto', padding: '2px 2px 6px' }}>
      {vod.beats.map((b, i) => (
        <BeatChip key={b.id} beat={b} index={i + 1} vod={vod}
          isCurrent={b.id === currentId}
          onSelect={() => setCurrentId(b.id)}
        />
      ))}
    </div>
  );
}

function BeatChip({ beat, index, vod, isCurrent, onSelect }) {
  const meta = BEAT_KIND_META[beat.kind];
  const selected = vod.selectedBeats.has(beat.id);
  return (
    <div
      onClick={onSelect}
      style={{
        flex: '0 0 224px',
        background: isCurrent ? BP.panel3 : BP.panel,
        border: `1px solid ${isCurrent ? BP.borderHi : BP.border}`,
        borderRadius: 6,
        padding: 12,
        cursor: 'pointer',
        opacity: selected ? 1 : 0.55,
        position: 'relative',
        transition: 'background 120ms',
      }}
    >
      {/* score bar accent */}
      <div style={{ position: 'absolute', left: 0, top: 12, bottom: 12, width: 2, borderRadius: 2, background: meta.accent }} />
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <span style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3, letterSpacing: 1 }}>#{String(index).padStart(2, '0')}</span>
        <span style={{ fontFamily: BP.mono, fontSize: 10, letterSpacing: 1.6, color: meta.accent, fontWeight: 700 }}>
          {meta.label}
        </span>
        <div style={{ flex: 1 }} />
        <ScoreCircle score={beat.score} />
      </div>
      <div style={{ fontFamily: BP.font, fontSize: 12, fontWeight: 600, color: BP.text, marginBottom: 6, lineHeight: 1.3, height: 32, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
        {beat.headline}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, fontFamily: BP.mono, fontSize: 10, color: BP.text2 }}>
        <span>{beat.t}</span>
        <span>·</span>
        <span>{beat.duration}s</span>
        <span>·</span>
        <span>{beat.scene}</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={(e) => { e.stopPropagation(); vod.toggleBeat(beat.id); }}
          style={{
            fontFamily: BP.mono, fontSize: 9, fontWeight: 700, letterSpacing: 0.8,
            padding: '2px 6px', borderRadius: 3,
            border: `1px solid ${selected ? BP.ok : BP.text3}`,
            background: 'transparent',
            color: selected ? BP.ok : BP.text3,
            cursor: 'pointer',
          }}
        >
          {selected ? 'IN' : 'OUT'}
        </button>
      </div>
    </div>
  );
}

function ScoreCircle({ score }) {
  const r = 11, c = 2 * Math.PI * r;
  return (
    <div style={{ position: 'relative', width: 26, height: 26 }}>
      <svg width="26" height="26" viewBox="0 0 26 26">
        <circle cx="13" cy="13" r={r} fill="none" stroke={BP.panel3} strokeWidth="2" />
        <circle cx="13" cy="13" r={r} fill="none" stroke={score > 0.7 ? BP.accent : score > 0.5 ? BP.accent2 : BP.text3}
          strokeWidth="2" strokeDasharray={`${c * score} ${c}`} transform="rotate(-90 13 13)" strokeLinecap="round" />
      </svg>
      <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: BP.mono, fontSize: 9, color: BP.text, fontWeight: 700 }}>
        {(score * 100).toFixed(0)}
      </div>
    </div>
  );
}

// --- Detail card (right of preview) ---------------------------------

function BeatDetailCard({ vod, beat }) {
  if (!beat) return null;
  const meta = BEAT_KIND_META[beat.kind];
  const involved = beat.agents.map(id => VOD_AGENTS[id]).filter(Boolean);
  return (
    <div style={{ width: 360, background: BP.panel, border: `1px solid ${BP.border}`, borderRadius: 6, padding: 18, display: 'flex', flexDirection: 'column', gap: 14, overflow: 'auto' }}>
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
          <span style={{ fontFamily: BP.mono, fontSize: 10, letterSpacing: 1.6, color: meta.accent, fontWeight: 700 }}>
            {meta.label}
          </span>
          <span style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3 }}>· {beat.t} ET · {beat.duration}s</span>
          <div style={{ flex: 1 }} />
          <ScoreCircle score={beat.score} />
        </div>
        <div style={{ fontFamily: BP.font, fontSize: 16, fontWeight: 700, color: BP.text, lineHeight: 1.35 }}>
          {beat.headline}
        </div>
      </div>

      <div>
        <SubLabel>caption · editable</SubLabel>
        <div className="dc-editable" contentEditable suppressContentEditableWarning style={{
          fontFamily: BP.font, fontSize: 13, color: BP.text2, lineHeight: 1.5,
          background: BP.bg, border: `1px solid ${BP.border}`, borderRadius: 4,
          padding: '8px 10px', minHeight: 56,
        }}>
          {beat.sub}
        </div>
      </div>

      <div>
        <SubLabel>scene · render hint</SubLabel>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <code style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text, background: BP.bg, padding: '4px 8px', borderRadius: 3, border: `1px solid ${BP.border}` }}>
            scene={beat.scene}
          </code>
          <span style={{ fontFamily: BP.mono, fontSize: 11, color: BP.text3 }}>
            ?replay={vod.sessionId}&at={beat.t}
          </span>
        </div>
      </div>

      {involved.length > 0 && (
        <div>
          <SubLabel>personalities</SubLabel>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {involved.map(a => (
              <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, background: BP.bg, padding: '8px 10px', borderRadius: 4, border: `1px solid ${BP.border}` }}>
                <div style={{ width: 28, height: 28, borderRadius: 4, background: stratColor(a.strategy), display: 'flex', alignItems: 'center', justifyContent: 'center', fontFamily: BP.mono, fontSize: 11, fontWeight: 700, color: '#0a0a0a' }}>
                  {a.initials}
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontFamily: BP.font, fontSize: 12, fontWeight: 600, color: BP.text }}>{a.display}</div>
                  <div style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text3 }}>
                    {VOD_STRATEGY_LABEL[a.strategy]} · {a.rank} · {a.trades}/{a.wins} W
                  </div>
                </div>
                <div style={{ fontFamily: BP.mono, fontSize: 12, fontWeight: 600, color: a.pnl > 0 ? BP.ok : BP.err }}>
                  {fmtMoney(a.pnl, { signed: true, dp: 0 })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div>
        <SubLabel>event refs · manifest pointers</SubLabel>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {beat.refs.map(r => (
            <code key={r} style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text2, background: BP.bg, padding: '3px 6px', borderRadius: 3, border: `1px solid ${BP.border}` }}>
              {r}
            </code>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: 8, marginTop: 'auto' }}>
        <button onClick={() => vod.toggleBeat(beat.id)} style={btnBP(vod.selectedBeats.has(beat.id) ? BP.ok : BP.text3)}>
          {vod.selectedBeats.has(beat.id) ? '✓ included' : '+ include'}
        </button>
        <button style={btnBP()}>↻ regenerate caption</button>
      </div>
    </div>
  );
}

function SubLabel({ children }) {
  return <div style={{ fontFamily: BP.mono, fontSize: 9, letterSpacing: 1.8, color: BP.text3, marginBottom: 6 }}>{children}</div>;
}

function btnBP(color) {
  return {
    fontFamily: BP.mono, fontSize: 10, letterSpacing: 0.8, fontWeight: 700,
    padding: '8px 12px', borderRadius: 4,
    border: `1px solid ${color || BP.border}`,
    background: color === BP.ok ? `${BP.ok}18` : 'transparent',
    color: color || BP.text2,
    cursor: 'pointer',
    flex: 1,
  };
}

// --- Header ----------------------------------------------------------

function BeatHeader({ vod }) {
  const dur = vod.totalDuration;
  const mins = Math.floor(dur / 60), secs = dur % 60;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '16px 24px', borderBottom: `1px solid ${BP.border}`, background: BP.panel }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontFamily: BP.mono, fontSize: 10, letterSpacing: 2, color: BP.text3 }}>EP</span>
        <span style={{ fontFamily: BP.mono, fontSize: 22, fontWeight: 700, color: BP.text, letterSpacing: -0.5 }}>
          {String(vod.episodeNumber).padStart(3, '0')}
        </span>
      </div>
      <div style={{ width: 1, height: 24, background: BP.border }} />
      <div>
        <div style={{ fontFamily: BP.font, fontSize: 14, fontWeight: 600, color: BP.text }}>
          Beat picker
        </div>
        <div style={{ fontFamily: BP.mono, fontSize: 10, color: BP.text2 }}>
          {vod.sessionLabel}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <Pill label="reel length" value={`${mins}:${String(secs).padStart(2, '0')}`} accent={BP.accent} />
      <Pill label="beats in master" value={`${vod.selectedBeats.size} / ${vod.beats.length}`} />
      <Pill label="target" value="08:00–12:00" subtle />
      <div style={{ width: 1, height: 24, background: BP.border }} />
      <button style={{ ...btnBP(), flex: 'none' }}>↻ re-detect</button>
      <button style={{ ...btnBP(BP.accent), background: BP.accent, color: '#1a1408', flex: 'none' }}>
        ▸ render selected
      </button>
    </div>
  );
}

function Pill({ label, value, accent, subtle }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontFamily: BP.mono, fontSize: 9, letterSpacing: 1.6, color: BP.text3 }}>{label}</span>
      <span style={{ fontFamily: BP.mono, fontSize: 14, color: subtle ? BP.text2 : (accent || BP.text), fontWeight: 600, fontFeatureSettings: '"tnum"' }}>
        {value}
      </span>
    </div>
  );
}

// --- Top-level component --------------------------------------------

function BeatPicker({ vod }) {
  const initial = vod.beats.find(b => vod.selectedBeats.has(b.id))?.id || vod.beats[0].id;
  const [currentId, setCurrentId] = React.useState(initial);
  const current = vod.beats.find(b => b.id === currentId) || vod.beats[0];
  return (
    <div style={{ width: '100%', height: '100%', background: BP.bg, color: BP.text, fontFamily: BP.font, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <BeatHeader vod={vod} />
      <div style={{ flex: 1, display: 'flex', minHeight: 0, gap: 14, padding: 14 }}>
        {/* Left column: preview + timeline + beat-list */}
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
          <div style={{ flex: 1, minHeight: 0, display: 'flex' }}>
            <PreviewPane beat={current} />
          </div>
          <TimelineStrip vod={vod} currentId={currentId} setCurrentId={setCurrentId} />
          <BeatListRail vod={vod} currentId={currentId} setCurrentId={setCurrentId} />
        </div>
        {/* Right column: beat detail */}
        <BeatDetailCard vod={vod} beat={current} />
      </div>
    </div>
  );
}

Object.assign(window, { BeatPicker });
