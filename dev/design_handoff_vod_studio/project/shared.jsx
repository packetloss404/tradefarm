// Shared helpers + tiny components used across all 4 variations.
const { useState, useEffect, useRef, useMemo } = React;

const fmtMoney = (n, opts = {}) => {
  const sign = n >= 0 ? '+' : '−';
  const abs = Math.abs(n);
  if (opts.compact && abs >= 1000) return (n >= 0 ? '+' : '−') + '$' + (abs / 1000).toFixed(2) + 'k';
  if (opts.compact && abs >= 1_000_000) return (n >= 0 ? '+' : '−') + '$' + (abs / 1_000_000).toFixed(2) + 'M';
  const v = '$' + abs.toLocaleString('en-US', { maximumFractionDigits: opts.dp ?? 2, minimumFractionDigits: opts.dp ?? 2 });
  return opts.signed ? sign + v : v;
};
const fmtPct = (n, dp = 2) => (n >= 0 ? '+' : '−') + Math.abs(n).toFixed(dp) + '%';
const fmtInt = n => Math.round(n).toLocaleString('en-US');

function useNow(intervalMs = 500) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

function useTickPulse(deps) {
  // returns true briefly after deps change — for "I just updated" flashes
  const [pulse, setPulse] = useState(false);
  useEffect(() => {
    setPulse(true);
    const t = setTimeout(() => setPulse(false), 250);
    return () => clearTimeout(t);
  }, deps);
  return pulse;
}

function Sparkline({ data, color = 'currentColor', width = 80, height = 22, strokeWidth = 1.5, fillBelow = false }) {
  if (!data || data.length < 2) return null;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((v - min) / range) * (height - 2) - 1;
    return [x, y];
  });
  const line = pts.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(' ');
  const fill = fillBelow ? `0,${height} ${line} ${width},${height}` : null;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      {fill && <polygon points={fill} fill={color} opacity="0.18" />}
      <polyline points={line} fill="none" stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// rank dot color
const rankColor = r => ({ intern: '#71717a', junior: '#a1a1aa', senior: '#fbbf24', principal: '#22d3ee' }[r] || '#71717a');
const stratColor = s => `oklch(0.72 0.18 ${STRATEGY_HUE[s]})`;
const stratColorDim = s => `oklch(0.5 0.12 ${STRATEGY_HUE[s]})`;
const pnlColor = (n, neutral = '#a1a1aa') => n > 1 ? '#10b981' : n < -1 ? '#f43f5e' : neutral;

function ETClock({ format = 'HH:mm:ss' }) {
  const now = useNow(500);
  const s = now.toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/New_York' });
  return <span>{s}</span>;
}

function MarketBadge() {
  // assume RTH for the demo
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '4px 10px', borderRadius: 4,
      background: 'oklch(0.32 0.14 145)', color: '#a7f3d0',
      fontSize: 11, letterSpacing: 0.6, fontWeight: 700,
      fontFamily: 'JetBrains Mono, monospace',
    }}>
      <span style={{ width: 6, height: 6, borderRadius: 999, background: '#34d399', boxShadow: '0 0 8px #34d399' }} />
      RTH · NYSE
    </span>
  );
}

function LiveDot({ color = '#ef4444', label = 'LIVE' }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      fontSize: 11, fontWeight: 800, letterSpacing: 1.4,
      color, fontFamily: 'JetBrains Mono, monospace',
    }}>
      <span className="pulse-dot" style={{ width: 8, height: 8, borderRadius: 999, background: color }} />
      {label}
    </span>
  );
}

// AnimatedNumber: smoothly transitions between values (60fps interpolation)
function useAnimatedNumber(target, ms = 350) {
  const [val, setVal] = useState(target);
  const ref = useRef({ from: target, to: target, t0: 0 });
  useEffect(() => {
    ref.current = { from: val, to: target, t0: performance.now() };
    let raf;
    const step = () => {
      const { from, to, t0 } = ref.current;
      const p = Math.min(1, (performance.now() - t0) / ms);
      const eased = 1 - Math.pow(1 - p, 3);
      setVal(from + (to - from) * eased);
      if (p < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target]);
  return val;
}

Object.assign(window, {
  fmtMoney, fmtPct, fmtInt,
  useNow, useTickPulse, useAnimatedNumber,
  Sparkline,
  rankColor, stratColor, stratColorDim, pnlColor,
  ETClock, MarketBadge, LiveDot,
});
