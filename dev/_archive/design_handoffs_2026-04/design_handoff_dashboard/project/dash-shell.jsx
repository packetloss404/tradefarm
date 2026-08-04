// Dashboard shell — top nav, hash routing, theme tokens, tweaks panel.
// Pages mount based on window.location.hash (#today, #episodes,
// #research, #admin). Default route is #today.

// --- Theme tokens (shared by every page) ---------------------------

const TOKENS = {
  'studio-dark': {
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
    warn: '#fbbf24',
    err: '#fb7185',
    rec: '#ef4444',
  },
  'studio-light': {
    bg: '#f4f2ee',
    panel: '#ffffff',
    panel2: '#f9f7f3',
    panel3: '#f0eee8',
    border: '#dcd8d2',
    borderHi: '#c4bfb8',
    text: '#1c1d22',
    text2: '#52555e',
    text3: '#888a92',
    accent: '#a36b00',
    accent2: '#1f6fd0',
    ok: '#0d8a5b',
    warn: '#a16207',
    err: '#c5183c',
    rec: '#d4133a',
  },
  'amber-crt': {
    bg: '#0a0805',
    panel: '#14100a',
    panel2: '#1e170d',
    panel3: '#2a200f',
    border: '#3a2f1a',
    borderHi: '#5a4a28',
    text: '#fbcf7e',
    text2: '#c79a4a',
    text3: '#80622c',
    accent: '#ffb347',
    accent2: '#ff9b50',
    ok: '#a8d65c',
    warn: '#ffd166',
    err: '#ff7a59',
    rec: '#ff5848',
  },
};

const DENSITY = {
  compact: { row: 32, gap: 8, pad: 12, font: 12 },
  comfortable: { row: 40, gap: 12, pad: 16, font: 13 },
  cozy: { row: 52, gap: 18, pad: 22, font: 14 },
};

const ThemeCtx = React.createContext({ T: TOKENS['studio-dark'], D: DENSITY.comfortable });
function useTheme() { return React.useContext(ThemeCtx); }

// --- Routing ------------------------------------------------------

const ROUTES = [
  { id: 'today', label: 'Today' },
  { id: 'episodes', label: 'Episodes' },
  { id: 'research', label: 'Research' },
  { id: 'admin', label: 'Admin' },
];

function useHashRoute(defaultId = 'today') {
  const [route, setRoute] = useState(() => (window.location.hash || '#' + defaultId).slice(1));
  useEffect(() => {
    const onChange = () => setRoute((window.location.hash || '#' + defaultId).slice(1));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [defaultId]);
  const go = id => { window.location.hash = '#' + id; };
  return [route, go];
}

// --- Tweaks ------------------------------------------------------

function useDashTweaks() {
  const [t, setT] = useState(DASH_TWEAKS_DEFAULT);
  // Persist via postMessage to host
  useEffect(() => {
    try {
      window.parent.postMessage({ type: '__edit_mode_set_keys', edits: t }, '*');
    } catch (e) { /* ignore */ }
  }, [t]);
  const setTweak = (k, v) => setT(prev => ({ ...prev, [k]: v }));
  return [t, setTweak];
}

// --- Top nav -----------------------------------------------------

function DashNav({ vod, route, go, tweaks, setTweak }) {
  const { T, D } = useTheme();
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 24px', height: 56,
      borderBottom: `1px solid ${T.border}`,
      background: T.panel,
      flexShrink: 0,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 6,
          background: `linear-gradient(135deg, ${T.accent}, ${T.accent2})`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontFamily: 'JetBrains Mono', fontSize: 13, fontWeight: 800, color: '#000'
        }}>tf</div>
        <span style={{ fontFamily: '"Helvetica Neue", sans-serif', fontSize: 15, fontWeight: 700, color: T.text }}>
          tradefarm
        </span>
      </div>
      <div style={{ width: 1, height: 22, background: T.border }} />
      <div style={{ display: 'flex', gap: 4 }}>
        {ROUTES.map(r => (
          <button
            key={r.id}
            onClick={() => go(r.id)}
            style={{
              fontFamily: '"Helvetica Neue", sans-serif',
              fontSize: 13, fontWeight: route === r.id ? 600 : 500,
              padding: '8px 14px', borderRadius: 4,
              border: 'none', cursor: 'pointer',
              background: route === r.id ? T.panel2 : 'transparent',
              color: route === r.id ? T.text : T.text2,
              transition: 'background 120ms',
            }}
          >
            {r.label}
          </button>
        ))}
      </div>
      <div style={{ flex: 1 }} />
      <NavStatusGroup vod={vod} />
    </div>
  );
}

function NavStatusGroup({ vod }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 18 }}>
      <NavStat label="POOL" value={fmtMoney(vod.summary.totalEquity, { compact: true })} mono />
      <NavStat label="DAY" value={fmtPct(vod.summary.pnlPct)} color={T.ok} mono />
      <NavStat label="EP" value={`#${vod.episodeNumber}`} mono />
      <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ width: 8, height: 8, borderRadius: 999, background: T.rec, boxShadow: `0 0 8px ${T.rec}` }} className="pulse-dot" />
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, fontWeight: 700, letterSpacing: 1.4, color: T.rec }}>
          REC
        </span>
      </div>
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 11, color: T.text2 }}>
        <ETClock /> ET
      </span>
    </div>
  );
}

function NavStat({ label, value, color, mono }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', minWidth: 60 }}>
      <span style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.4, color: T.text3 }}>{label}</span>
      <span style={{
        fontFamily: mono ? 'JetBrains Mono' : 'inherit',
        fontSize: 13, fontWeight: 600, color: color || T.text,
        fontFeatureSettings: '"tnum"',
      }}>{value}</span>
    </div>
  );
}

// --- Tweaks panel (floating bottom-right) ------------------------

function TweaksPanel({ tweaks, setTweak, open, onClose }) {
  const { T } = useTheme();
  if (!open) return null;
  return (
    <div style={{
      position: 'fixed', bottom: 18, right: 18, zIndex: 50,
      width: 280, background: T.panel, border: `1px solid ${T.borderHi}`,
      borderRadius: 8, padding: 16,
      boxShadow: '0 12px 48px rgba(0,0,0,0.4)',
      fontFamily: '"Helvetica Neue", sans-serif', color: T.text,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
        <span style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: 1.8, color: T.text3, flex: 1 }}>
          TWEAKS
        </span>
        <button onClick={onClose} style={{ background: 'transparent', border: 'none', color: T.text2, cursor: 'pointer', fontSize: 16 }}>×</button>
      </div>

      <TwSection label="Theme">
        <TwSegment value={tweaks.theme} onChange={v => setTweak('theme', v)}
          options={[
            { value: 'studio-dark', label: 'Dark' },
            { value: 'studio-light', label: 'Light' },
            { value: 'amber-crt', label: 'Amber' },
          ]} />
      </TwSection>

      <TwSection label="Density">
        <TwSegment value={tweaks.density} onChange={v => setTweak('density', v)}
          options={[
            { value: 'compact', label: 'Compact' },
            { value: 'comfortable', label: 'Cozy' },
            { value: 'cozy', label: 'Roomy' },
          ]} />
      </TwSection>

      <TwSection label="Today layout">
        <TwToggle label="Pipeline panel" value={tweaks.showPipelinePanel} onChange={v => setTweak('showPipelinePanel', v)} />
        <TwToggle label="Cost rail" value={tweaks.showCostRail} onChange={v => setTweak('showCostRail', v)} />
      </TwSection>
    </div>
  );
}

function TwSection({ label, children }) {
  const { T } = useTheme();
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3, marginBottom: 6 }}>{label}</div>
      {children}
    </div>
  );
}

function TwSegment({ value, onChange, options }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', background: T.bg, border: `1px solid ${T.border}`, borderRadius: 4, padding: 2 }}>
      {options.map(o => (
        <button key={o.value} onClick={() => onChange(o.value)} style={{
          flex: 1, padding: '6px 8px', border: 'none', cursor: 'pointer',
          fontFamily: 'JetBrains Mono', fontSize: 11, fontWeight: 600,
          background: value === o.value ? T.panel2 : 'transparent',
          color: value === o.value ? T.text : T.text2,
          borderRadius: 3,
        }}>{o.label}</button>
      ))}
    </div>
  );
}

function TwToggle({ label, value, onChange }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', alignItems: 'center', padding: '4px 0' }}>
      <span style={{ flex: 1, fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text2 }}>{label}</span>
      <button onClick={() => onChange(!value)} style={{
        width: 32, height: 18, borderRadius: 999, border: `1px solid ${value ? T.accent : T.border}`,
        background: value ? T.accent : T.bg, position: 'relative', cursor: 'pointer',
        transition: 'background 120ms',
      }}>
        <span style={{
          position: 'absolute', top: 1, left: value ? 15 : 1,
          width: 14, height: 14, borderRadius: 999,
          background: value ? '#1a1408' : T.text2,
          transition: 'left 120ms',
        }} />
      </button>
    </div>
  );
}

function TweaksButton({ onClick }) {
  const { T } = useTheme();
  return (
    <button onClick={onClick} style={{
      position: 'fixed', bottom: 18, right: 18, zIndex: 49,
      width: 40, height: 40, borderRadius: 999,
      background: T.panel, border: `1px solid ${T.borderHi}`,
      color: T.text, cursor: 'pointer',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      boxShadow: '0 6px 20px rgba(0,0,0,0.3)',
    }}>
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 2v2M8 12v2M14 8h-2M4 8H2M12.2 3.8l-1.4 1.4M5.2 10.8l-1.4 1.4M12.2 12.2l-1.4-1.4M5.2 5.2L3.8 3.8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    </button>
  );
}

// --- Tiny reusable UI atoms (the page files import these) ---------

function Panel({ title, children, right, padded = true, style }) {
  const { T } = useTheme();
  return (
    <div style={{
      background: T.panel, border: `1px solid ${T.border}`, borderRadius: 8,
      display: 'flex', flexDirection: 'column', minHeight: 0,
      ...style,
    }}>
      {title && (
        <div style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '12px 16px', borderBottom: `1px solid ${T.border}`,
        }}>
          <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, letterSpacing: 1.6, color: T.text3 }}>
            {title}
          </div>
          {right}
        </div>
      )}
      <div style={{ padding: padded ? 16 : 0, flex: 1, minHeight: 0, overflow: 'auto' }}>
        {children}
      </div>
    </div>
  );
}

function StatBig({ label, value, sub, color }) {
  const { T } = useTheme();
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ fontFamily: 'JetBrains Mono', fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>{label}</div>
      <div style={{
        fontFamily: 'JetBrains Mono', fontSize: 26, fontWeight: 600,
        color: color || T.text, fontFeatureSettings: '"tnum"', letterSpacing: -0.5,
      }}>{value}</div>
      {sub && <div style={{ fontFamily: 'JetBrains Mono', fontSize: 10, color: T.text2 }}>{sub}</div>}
    </div>
  );
}

function MicroBar({ pct, color }) {
  const { T } = useTheme();
  return (
    <div style={{ height: 4, background: T.panel2, borderRadius: 2, overflow: 'hidden' }}>
      <div style={{ width: `${Math.min(100, Math.max(0, pct * 100))}%`, height: '100%', background: color || T.accent, transition: 'width 200ms' }} />
    </div>
  );
}

Object.assign(window, {
  TOKENS, DENSITY, ThemeCtx, useTheme,
  ROUTES, useHashRoute, useDashTweaks,
  DashNav, TweaksPanel, TweaksButton,
  Panel, StatBig, MicroBar,
});
