// Admin page — runtime config. Sections roughly match
// src/tradefarm/api/admin.py's EDITABLE allowlist.

function AdminHeader({ config, update }) {
  const { T } = useTheme();
  return (
    <div style={{ padding: '24px 24px 18px' }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between' }}>
        <div>
          <h1 style={{ fontFamily: '"Helvetica Neue"', fontSize: 28, fontWeight: 700, color: T.text, margin: 0, letterSpacing: -0.5 }}>
            Admin
          </h1>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2, marginTop: 6 }}>
            runtime config · persisted to .env via /admin/config
          </div>
        </div>
        <KillSwitch enabled={config.ai_enabled} onToggle={v => update('ai_enabled', v)} />
      </div>
    </div>
  );
}

function KillSwitch({ enabled, onToggle }) {
  const { T } = useTheme();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 14,
      padding: '12px 18px', borderRadius: 8,
      background: enabled ? T.panel : `${T.err}15`,
      border: `1px solid ${enabled ? T.borderHi : T.err}`,
    }}>
      <span style={{ width: 10, height: 10, borderRadius: 999, background: enabled ? T.ok : T.err, boxShadow: `0 0 10px ${enabled ? T.ok : T.err}` }} className="pulse-dot" />
      <div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.8, color: T.text3 }}>MASTER AI</div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 14, fontWeight: 700, color: enabled ? T.ok : T.err }}>
          {enabled ? 'ENABLED' : 'KILL SWITCH ACTIVE'}
        </div>
      </div>
      <button onClick={() => onToggle(!enabled)} style={{
        fontFamily: 'JetBrains Mono', fontSize: 11, fontWeight: 700, letterSpacing: 0.5,
        padding: '10px 16px', borderRadius: 4, cursor: 'pointer',
        background: enabled ? T.err : T.ok,
        border: 'none', color: '#fff',
      }}>
        {enabled ? '■ disable' : '▸ enable'}
      </button>
    </div>
  );
}

// --- Section primitive --------------------------------

function AdminSection({ title, sub, children, right }) {
  const { T } = useTheme();
  return (
    <div style={{ background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8, overflow: 'hidden' }}>
      <div style={{ padding: '14px 20px', borderBottom: `1px solid ${T.border}`, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: 1.6, color: T.text3 }}>{title}</div>
          {sub && <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text2, marginTop: 3 }}>{sub}</div>}
        </div>
        {right}
      </div>
      <div style={{ padding: 20 }}>
        {children}
      </div>
    </div>
  );
}

function Field({ label, hint, children, inline = false }) {
  const { T } = useTheme();
  if (inline) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 0', borderBottom: `1px solid ${T.border}` }}>
        <div>
          <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 13, fontWeight: 500, color: T.text }}>{label}</div>
          {hint && <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 3 }}>{hint}</div>}
        </div>
        <div>{children}</div>
      </div>
    );
  }
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: 1.4, color: T.text3, marginBottom: 6 }}>{label}</div>
      {children}
      {hint && <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 6 }}>{hint}</div>}
    </div>
  );
}

function Input({ value, onChange, mono = true, type = 'text', placeholder, suffix }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', alignItems: 'center', background: T.bg, border: `1px solid ${T.border}`, borderRadius: 4, paddingRight: suffix ? 10 : 0 }}>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          flex: 1, fontFamily: mono ? 'JetBrains Mono' : '"Helvetica Neue"',
          fontSize: 13, padding: '8px 10px', background: 'transparent',
          border: 'none', color: T.text, outline: 'none',
        }}
      />
      {suffix && <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text3 }}>{suffix}</span>}
    </div>
  );
}

function Select({ value, onChange, options }) {
  const { T } = useTheme();
  return (
    <select value={value} onChange={e => onChange(e.target.value)} style={{
      fontFamily: 'JetBrains Mono', fontSize: 13, padding: '8px 10px',
      background: T.bg, border: `1px solid ${T.border}`, borderRadius: 4, color: T.text,
      cursor: 'pointer', outline: 'none',
    }}>
      {options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
}

function Segment({ value, onChange, options }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', background: T.bg, border: `1px solid ${T.border}`, borderRadius: 4, padding: 2 }}>
      {options.map(o => (
        <button key={o.value} onClick={() => onChange(o.value)} style={{
          padding: '6px 14px', border: 'none', cursor: 'pointer',
          fontFamily: 'JetBrains Mono', fontSize: 12, fontWeight: 600,
          background: value === o.value ? T.panel2 : 'transparent',
          color: value === o.value ? T.text : T.text2,
          borderRadius: 3,
        }}>{o.label}</button>
      ))}
    </div>
  );
}

function Toggle({ value, onChange, label }) {
  const { T } = useTheme();
  return (
    <button onClick={() => onChange(!value)} style={{
      display: 'flex', alignItems: 'center', gap: 10, background: 'transparent', border: 'none', cursor: 'pointer', padding: 0,
    }}>
      <span style={{
        width: 38, height: 22, borderRadius: 999,
        background: value ? TOKENS['studio-dark'].accent : TOKENS['studio-dark'].panel2,
        border: `1px solid ${value ? TOKENS['studio-dark'].accent : TOKENS['studio-dark'].border}`,
        position: 'relative', transition: 'background 120ms',
      }}>
        <span style={{
          position: 'absolute', top: 2, left: value ? 18 : 2,
          width: 16, height: 16, borderRadius: 999,
          background: value ? '#1a1408' : T.text2,
          transition: 'left 120ms',
        }} />
      </span>
      {label && <span style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text2 }}>{label}</span>}
    </button>
  );
}

function Slider({ value, min, max, step = 0.01, onChange, format }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
      <input type="range" min={min} max={max} step={step} value={value} onChange={e => onChange(parseFloat(e.target.value))}
        style={{ flex: 1, accentColor: T.accent }}
      />
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 12, color: T.text, width: 70, textAlign: 'right', fontWeight: 600 }}>
        {format ? format(value) : value}
      </span>
    </div>
  );
}

// --- Strategy table -------------------------------------

function StrategyTable({ config, update }) {
  const { T } = useTheme();
  const disabled = new Set(config.disabled_strategies.split(',').map(s => s.trim()).filter(Boolean));
  const strategies = [
    { key: 'momentum_sma20', label: 'momentum_sma20', agents: 33, pnl: 700, fills: 102 },
    { key: 'lstm_v1', label: 'lstm_v1', agents: 33, pnl: 396, fills: 89 },
    { key: 'lstm_llm_v1', label: 'lstm_llm_v1', agents: 34, pnl: 744, fills: 121 },
  ];
  const toggleStrategy = k => {
    const next = new Set(disabled);
    if (next.has(k)) next.delete(k); else next.add(k);
    update('disabled_strategies', Array.from(next).join(','));
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {strategies.map(s => {
        const isDisabled = disabled.has(s.key);
        return (
          <div key={s.key} style={{
            display: 'grid', gridTemplateColumns: '160px 1fr auto auto auto',
            alignItems: 'center', gap: 16,
            padding: '12px 14px',
            background: isDisabled ? T.panel2 : T.bg,
            border: `1px solid ${T.border}`, borderRadius: 4,
            opacity: isDisabled ? 0.55 : 1,
          }}>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 600, color: T.text }}>{s.label}</span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2 }}>{s.agents} agents · {s.fills} fills</span>
            <span style={{ fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 600, color: s.pnl > 0 ? T.ok : T.err, width: 80, textAlign: 'right' }}>
              {fmtMoney(s.pnl, { signed: true, dp: 0 })}
            </span>
            <span style={{
              fontFamily: 'JetBrains Mono', fontSize: 9, fontWeight: 700, letterSpacing: 1,
              padding: '3px 8px', borderRadius: 3,
              background: isDisabled ? `${T.err}22` : `${T.ok}22`,
              color: isDisabled ? T.err : T.ok,
            }}>{isDisabled ? 'FROZEN' : 'ACTIVE'}</span>
            <Toggle value={!isDisabled} onChange={() => toggleStrategy(s.key)} />
          </div>
        );
      })}
    </div>
  );
}

// --- Env footer / danger zone ---------------------------

function DangerZone() {
  const { T } = useTheme();
  return (
    <div style={{
      background: T.panel, border: `1px solid ${T.err}55`, borderRadius: 8,
      padding: 20, display: 'flex', flexDirection: 'column', gap: 14,
    }}>
      <div>
        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: 1.6, color: T.err, fontWeight: 700 }}>DANGER ZONE</div>
        <div style={{ fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text2, marginTop: 4 }}>
          irreversible. confirm twice from the CLI.
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
        {[
          { label: 'reset all virtual books', sub: 'wipes positions + cash to $1,000 × 100' },
          { label: 'purge journal', sub: 'drops every agent_note row' },
          { label: 'retrain LSTM universe', sub: '~15 min · CPU only · pauses ticks' },
          { label: 'flush data_cache/', sub: 'drops EODHD parquet bars' },
        ].map(b => (
          <button key={b.label} style={{
            fontFamily: '"Helvetica Neue"', fontSize: 12, fontWeight: 600,
            padding: '10px 14px', borderRadius: 4, cursor: 'pointer',
            background: 'transparent', color: T.text, border: `1px solid ${T.border}`,
            textAlign: 'left',
          }}>
            <div>{b.label}</div>
            <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, marginTop: 4 }}>{b.sub}</div>
          </button>
        ))}
      </div>
    </div>
  );
}

// --- Top-level Admin page -----------------------------

function AdminPage({ vod }) {
  const { config, update } = useAdminConfig();
  const { T } = useTheme();
  return (
    <div>
      <AdminHeader config={config} update={update} />
      <div style={{ padding: '0 24px 24px', display: 'flex', flexDirection: 'column', gap: 16 }}>
        <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 1fr', gap: 16 }}>
          <AdminSection title="BRAIN PROVIDER" sub="LLM overlay for lstm_llm_v1 agents. Switch hot-reloads the overlay.">
            <Field label="Provider">
              <Segment value={config.llm_provider} onChange={v => update('llm_provider', v)}
                options={[
                  { value: 'anthropic', label: 'Anthropic (Claude)' },
                  { value: 'minimax', label: 'MiniMax' },
                ]} />
            </Field>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
              <Field label="Model">
                <Input value={config.llm_model} onChange={v => update('llm_model', v)} placeholder="claude-haiku-4-5" />
              </Field>
              <Field label="API key" hint="masked · stored in .env · /admin/config POST">
                <Input value={config.anthropic_api_key} onChange={v => update('anthropic_api_key', v)} mono />
              </Field>
            </div>
            <Field label="LSTM confidence gate" hint="LLM call is skipped when LSTM max_prob falls below this threshold. Default 0.40.">
              <Slider value={config.llm_min_confidence} min={0} max={1} step={0.01}
                onChange={v => update('llm_min_confidence', v)}
                format={v => v.toFixed(2)} />
            </Field>
          </AdminSection>
          <AdminSection title="EXECUTION" sub="Where the orders land. Paper only.">
            <Field label="Execution mode">
              <Segment value={config.execution_mode} onChange={v => update('execution_mode', v)}
                options={[
                  { value: 'simulated', label: 'Simulated (local)' },
                  { value: 'alpaca_paper', label: 'Alpaca paper' },
                ]} />
            </Field>
            <Field label="Tick interval" hint="0 = manual only · scheduler runs every N seconds during RTH" inline>
              <Input value={config.auto_tick_interval_sec} onChange={v => update('auto_tick_interval_sec', parseInt(v) || 0)} suffix="sec" />
            </Field>
            <Field label="Tick outside RTH" hint="When OFF, scheduler sleeps from 16:00 → 09:30 ET" inline>
              <Toggle value={config.tick_outside_rth} onChange={v => update('tick_outside_rth', v)} />
            </Field>
          </AdminSection>
        </div>

        <AdminSection title="STRATEGIES" sub="Freeze a strategy and its agents keep open positions but skip new decisions.">
          <StrategyTable config={config} update={update} />
        </AdminSection>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <AdminSection title="ACADEMY (rank · retrieval · curriculum)" sub="Phases 2-4. Rank-gated capital multiplier + auto promote / demote.">
            <Field label="Curriculum interval" hint="0 = disable auto promote/demote loop" inline>
              <Input value={config.academy_eval_interval_sec} onChange={v => update('academy_eval_interval_sec', parseInt(v) || 0)} suffix="sec" />
            </Field>
            <Field label="Retrieval-augmented prompt" hint="Phase 3 · pulls similar past setups into the LLM prompt" inline>
              <Toggle value={config.academy_retrieval_enabled} onChange={v => update('academy_retrieval_enabled', v)} />
            </Field>
            <Field label="Retrieval K" hint="number of similar past setups to surface" inline>
              <Input value={config.academy_retrieval_k} onChange={v => update('academy_retrieval_k', parseInt(v) || 0)} />
            </Field>
            <Field label="Demote on drawdown" hint="fraction of starting capital">
              <Slider value={config.academy_demote_drawdown_pct} min={0.02} max={0.30} step={0.01}
                onChange={v => update('academy_demote_drawdown_pct', v)}
                format={v => `${(v * 100).toFixed(0)}%`} />
            </Field>
            <Field label="Demote on consecutive losses" inline>
              <Input value={config.academy_demote_consecutive_losses} onChange={v => update('academy_demote_consecutive_losses', parseInt(v) || 1)} suffix="losses" />
            </Field>
          </AdminSection>
          <AdminSection title="VOD PIPELINE" sub="Auto-render at close, auto-upload at 16:30 ET">
            <Field label="Auto-render at close" inline>
              <Toggle value={true} onChange={() => {}} />
            </Field>
            <Field label="Auto-publish to YouTube" inline>
              <Toggle value={false} onChange={() => {}} />
            </Field>
            <Field label="Target episode length">
              <Slider value={10} min={3} max={20} step={1} onChange={() => {}} format={v => `${v} min`} />
            </Field>
            <Field label="TTS voice">
              <Select value="daniel" onChange={() => {}} options={[
                { value: 'daniel', label: 'Daniel · eleven flash-v2' },
                { value: 'rachel', label: 'Rachel · eleven flash-v2' },
                { value: 'openai-onyx', label: 'Onyx · openai-tts' },
                { value: 'piper-en', label: 'piper.exe · local · free' },
              ]} />
            </Field>
            <Field label="Visibility" inline>
              <Segment value="unlisted" onChange={() => {}}
                options={[{ value: 'public', label: 'Public' }, { value: 'unlisted', label: 'Unlisted' }, { value: 'private', label: 'Private' }]} />
            </Field>
          </AdminSection>
        </div>

        <DangerZone />

        <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text3, textAlign: 'center', padding: '8px 0' }}>
          /admin/config · last saved {' '}
          <span style={{ color: T.text2 }}>2026-05-19 14:18:42 ET</span> {' '}
          · changes apply live · {' '}
          <a href="#" style={{ color: T.accent2 }}>view audit log →</a>
        </div>
      </div>
    </div>
  );
}

Object.assign(window, { AdminPage });
