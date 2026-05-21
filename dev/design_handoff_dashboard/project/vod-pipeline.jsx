// Pipeline status board — overview of all 10 subsystems in the VOD
// pipeline for today's session. The operator's "what's running, what's
// stuck, what's done" view.

const VP = {
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
  warn: '#fbbf24',
  err: '#fb7185',
  rec: '#ef4444',
  font: '"Helvetica Neue", Helvetica, Arial, sans-serif',
  mono: 'JetBrains Mono, ui-monospace, monospace',
};

function PipelineHeader({ vod }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18, padding: '20px 28px', borderBottom: `1px solid ${VP.border}`, background: VP.panel }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
        <span style={{ fontFamily: VP.mono, fontSize: 11, letterSpacing: 2, color: VP.text3 }}>EP</span>
        <span style={{ fontFamily: VP.mono, fontSize: 32, fontWeight: 700, color: VP.text, letterSpacing: -1 }}>
          {String(vod.episodeNumber).padStart(3, '0')}
        </span>
      </div>
      <div style={{ width: 1, height: 36, background: VP.border }} />
      <div>
        <div style={{ fontFamily: VP.font, fontSize: 18, fontWeight: 600, color: VP.text, marginBottom: 2 }}>
          Today on TradeFarm
        </div>
        <div style={{ fontFamily: VP.mono, fontSize: 11, color: VP.text2 }}>
          {vod.sessionLabel}
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: 'flex', gap: 28, fontFamily: VP.mono }}>
        <Stat label="POOL P&L" value={fmtMoney(vod.summary.totalPnl, { signed: true, compact: true })} color={VP.ok} />
        <Stat label="FILLS" value={fmtInt(vod.summary.fillCount)} />
        <Stat label="DECISIONS" value={fmtInt(vod.summary.decisionCount)} />
        <Stat label="LLM SPEND" value={'$' + vod.summary.llmSpend.toFixed(2)} />
      </div>
      <div style={{ width: 1, height: 36, background: VP.border }} />
      <PipelineActions vod={vod} />
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div>
      <div style={{ fontSize: 10, letterSpacing: 1.6, color: VP.text3, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 600, color: color || VP.text, fontFeatureSettings: '"tnum"' }}>{value}</div>
    </div>
  );
}

function PipelineActions({ vod }) {
  const queued = vod.pipeline.filter(p => p.status === 'queued').length;
  const running = vod.pipeline.filter(p => p.status === 'running').length;
  const done = vod.pipeline.filter(p => p.status === 'done').length;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <div style={{ display: 'flex', gap: 8, fontFamily: VP.mono, fontSize: 11, color: VP.text2 }}>
        <span style={{ color: VP.ok }}>● {done} done</span>
        <span style={{ color: VP.accent }}>● {running} running</span>
        <span>● {queued} queued</span>
      </div>
      <button style={{ ...btnStyle(VP.accent, '#fff'), background: VP.accent, color: '#1a1408' }}>
        ▸ resume pipeline
      </button>
      <button style={btnStyle()}>open out/</button>
    </div>
  );
}

function btnStyle(border = VP.border, color = VP.text) {
  return {
    fontFamily: VP.mono, fontSize: 11, letterSpacing: 0.4, fontWeight: 600,
    padding: '8px 12px', border: `1px solid ${border}`,
    background: 'transparent', color, borderRadius: 4, cursor: 'pointer',
  };
}

function StatusDot({ status }) {
  const color = status === 'done' ? VP.ok : status === 'running' ? VP.accent
    : status === 'failed' ? VP.err : VP.text3;
  return (
    <span style={{
      width: 8, height: 8, borderRadius: 999, background: color,
      boxShadow: status === 'running' ? `0 0 8px ${color}` : 'none',
      flexShrink: 0,
    }} className={status === 'running' ? 'pulse-dot' : ''} />
  );
}

function ProgressBar({ progress, color = VP.accent, height = 4 }) {
  return (
    <div style={{ height, background: VP.panel2, borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ width: `${progress * 100}%`, height: '100%', background: color, transition: 'width 200ms ease' }} />
    </div>
  );
}

function SubsystemCard({ node, vod, isSelected, onSelect }) {
  const isRunning = node.status === 'running';
  const isDone = node.status === 'done';
  const isQueued = node.status === 'queued';
  const progress = isRunning ? vod.renderProgress
                : isDone ? 1 : 0;
  return (
    <div
      onClick={onSelect}
      style={{
        background: isSelected ? VP.panel2 : VP.panel,
        border: `1px solid ${isSelected ? VP.borderHi : VP.border}`,
        borderRadius: 6, padding: 14, cursor: 'pointer',
        opacity: isQueued ? 0.6 : 1,
        transition: 'background 120ms',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
        <StatusDot status={node.status} />
        <span style={{ fontFamily: VP.font, fontSize: 13, fontWeight: 600, color: VP.text, flex: 1 }}>
          {node.label}
        </span>
        <span style={{ fontFamily: VP.mono, fontSize: 10, color: VP.text3 }}>
          {node.status}
        </span>
      </div>
      <div style={{ fontFamily: VP.mono, fontSize: 10, color: VP.text3, marginBottom: 10, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
        {node.cmd}
      </div>
      <ProgressBar progress={progress} color={isDone ? VP.ok : VP.accent} />
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontFamily: VP.mono, fontSize: 10, color: VP.text2 }}>
        <span>{node.output}</span>
        <span>{node.durationSec != null ? `${node.durationSec}s` : '—'}</span>
      </div>
    </div>
  );
}

function PipelineGraph({ vod, selected, setSelected }) {
  return (
    <div style={{ padding: '20px 28px', flex: 1, overflow: 'auto' }}>
      <SectionLabel>pipeline · 2026-05-19 16:00:04 ET</SectionLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: 12 }}>
        {vod.pipeline.map(node => (
          <SubsystemCard
            key={node.id}
            node={node}
            vod={vod}
            isSelected={selected === node.id}
            onSelect={() => setSelected(node.id)}
          />
        ))}
      </div>
    </div>
  );
}

function SectionLabel({ children, right }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 12 }}>
      <div style={{ fontFamily: VP.mono, fontSize: 10, letterSpacing: 1.8, color: VP.text3 }}>
        {children}
      </div>
      {right && (
        <div style={{ fontFamily: VP.mono, fontSize: 10, color: VP.text3 }}>{right}</div>
      )}
    </div>
  );
}

function DetailPane({ vod, selectedId }) {
  const node = vod.pipeline.find(p => p.id === selectedId) || vod.pipeline[2];
  return (
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0, padding: '0 28px 28px' }}>
      <div style={{ background: VP.panel, border: `1px solid ${VP.border}`, borderRadius: 6, padding: 18, display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
          <StatusDot status={node.status} />
          <span style={{ fontFamily: VP.font, fontSize: 16, fontWeight: 700, color: VP.text }}>
            {node.label}
          </span>
          <span style={{ fontFamily: VP.mono, fontSize: 11, color: VP.text3 }}>
            {node.cmd}
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: VP.mono, fontSize: 11, color: VP.text2 }}>{node.summary}</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 16 }}>
          <DetailField label="started" value={node.started || '—'} />
          <DetailField label="finished" value={node.finished || '—'} />
          <DetailField label="duration" value={node.durationSec != null ? `${node.durationSec}s` : node.status === 'running' ? `${Math.floor(node.durationSec || 0)}s · running` : '—'} />
          <DetailField label="output" value={`${node.output} · ${node.outputSize || '—'}`} mono />
        </div>
        {node.progressLabel && (
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: VP.mono, fontSize: 10, color: VP.text2, marginBottom: 6 }}>
              <span>progress</span>
              <span>{node.progressLabel}</span>
            </div>
            <ProgressBar progress={vod.renderProgress} />
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column' }}>
          <SectionLabel right="tail · log">stdout</SectionLabel>
          <div style={{
            flex: 1, minHeight: 0,
            background: VP.bg, border: `1px solid ${VP.border}`, borderRadius: 4,
            padding: '10px 12px', overflow: 'auto',
            fontFamily: VP.mono, fontSize: 11, lineHeight: 1.6, color: VP.text2,
          }}>
            {node.tail.map((line, i) => (
              <div key={i} style={{ color: i === node.tail.length - 1 && node.status === 'running' ? VP.text : VP.text2 }}>
                {line}
                {i === node.tail.length - 1 && node.status === 'running' && (
                  <span className="cursor-blink" style={{ color: VP.accent, marginLeft: 4 }}>▌</span>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function DetailField({ label, value, mono }) {
  return (
    <div>
      <div style={{ fontFamily: VP.mono, fontSize: 10, letterSpacing: 1.4, color: VP.text3, marginBottom: 4 }}>
        {label}
      </div>
      <div style={{ fontFamily: mono ? VP.mono : VP.font, fontSize: 13, fontWeight: 500, color: VP.text }}>
        {value}
      </div>
    </div>
  );
}

function PipelineBoard({ vod }) {
  const [selected, setSelected] = React.useState('render');
  return (
    <div style={{ width: '100%', height: '100%', background: VP.bg, color: VP.text, fontFamily: VP.font, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
      <PipelineHeader vod={vod} />
      <PipelineGraph vod={vod} selected={selected} setSelected={setSelected} />
      <DetailPane vod={vod} selectedId={selected} />
    </div>
  );
}

Object.assign(window, { PipelineBoard });
