// V3 — Casino / Racetrack
// 1920×1080: agents as horses on a track, tote board, race calls, marquee.

const V3_GREEN = '#0a3a2a';      // velvet
const V3_GREEN_DARK = '#072218';
const V3_GOLD = '#f0b90b';
const V3_GOLD_HI = '#fcd34d';
const V3_CREAM = '#f7e9c8';
const V3_RED = '#dc2626';
const V3_TRACK = '#3b1e0e';      // dirt track
const V3_TRACK_HI = '#5a2d12';

function V3Header({ account }) {
  return (
    <div style={{
      height: 92,
      background: `linear-gradient(180deg, ${V3_GREEN_DARK}, ${V3_GREEN})`,
      borderBottom: `4px double ${V3_GOLD}`,
      display: 'grid', gridTemplateColumns: '1fr auto 1fr',
      alignItems: 'center', padding: '0 28px',
      fontFamily: '"Yeseva One", "Bodoni Moda", Georgia, serif',
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <V3MarqueeBulbs />
        <div>
          <div style={{ fontSize: 12, color: V3_GOLD, letterSpacing: 4, fontWeight: 600 }}>RACE No. 17 · MAY 09 · 2026</div>
          <div style={{ fontSize: 30, fontWeight: 400, color: V3_CREAM, letterSpacing: 2, lineHeight: 1.1 }}>
            TRADEFARM <span style={{ color: V3_GOLD_HI }}>STAKES</span>
          </div>
        </div>
      </div>
      <div style={{
        textAlign: 'center',
        border: `2px solid ${V3_GOLD}`, padding: '6px 24px',
        background: V3_GREEN_DARK, position: 'relative',
        boxShadow: `0 0 0 4px ${V3_GREEN}, 0 0 0 6px ${V3_GOLD}`,
      }}>
        <div style={{ fontSize: 10, color: V3_GOLD, letterSpacing: 4, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>TODAY'S PURSE</div>
        <div style={{ fontSize: 38, color: V3_GOLD_HI, fontWeight: 400, letterSpacing: 1 }}>
          ${Math.round(account.totalEquity).toLocaleString('en-US')}
        </div>
        <div style={{ fontSize: 13, color: account.pnl >= 0 ? '#86efac' : '#fb7185', fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>
          {fmtPct(account.pnlPct, 2)} · {(account.pnl >= 0 ? '+' : '−')}${Math.abs(account.pnl).toFixed(0)} TODAY
        </div>
      </div>
      <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 16 }}>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 11, color: V3_GOLD, letterSpacing: 3, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>POST TIME</div>
          <div style={{ fontSize: 30, color: V3_CREAM, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700 }}>
            <ETClock />
          </div>
          <div style={{ fontSize: 10, color: V3_GOLD, letterSpacing: 2, fontFamily: 'JetBrains Mono, monospace' }}>NYSE · ET</div>
        </div>
        <V3MarqueeBulbs />
      </div>
    </div>
  );
}

function V3MarqueeBulbs() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      {[0, 1, 2].map(row => (
        <div key={row} style={{ display: 'flex', gap: 4 }}>
          {[0, 1, 2, 3].map(col => (
            <span key={col} className={`v3-bulb v3-bulb-${(row + col) % 3}`} style={{
              width: 8, height: 8, borderRadius: 999,
              background: V3_GOLD_HI,
              boxShadow: `0 0 6px ${V3_GOLD}`,
            }} />
          ))}
        </div>
      ))}
    </div>
  );
}

function V3ToteBoard({ byStrategy }) {
  // Compute "odds" = weighted by inverse pnl rank → cheapest = winning fastest
  const items = STRATEGIES.map(s => ({
    s, label: STRATEGY_LABEL[s],
    pnl: byStrategy[s].pnl,
    pnlPct: byStrategy[s].pnlPct,
    winners: byStrategy[s].winners,
    n: byStrategy[s].agents.length,
  })).sort((a, b) => b.pnl - a.pnl);
  return (
    <div style={{
      background: V3_GREEN_DARK,
      border: `3px solid ${V3_GOLD}`,
      padding: 14,
      fontFamily: '"Yeseva One", Georgia, serif',
    }}>
      <div style={{
        textAlign: 'center', fontSize: 14, color: V3_GOLD, letterSpacing: 4, fontWeight: 700,
        borderBottom: `1px solid ${V3_GOLD}`, paddingBottom: 8, marginBottom: 12,
        fontFamily: 'JetBrains Mono, monospace',
      }}>STRATEGY · TOTE</div>
      {items.map((it, i) => {
        const odds = i === 0 ? '5/2' : i === 1 ? '7/2' : '8/1';
        return (
          <div key={it.s} style={{
            display: 'grid', gridTemplateColumns: '32px 1fr auto',
            alignItems: 'center', gap: 10,
            padding: '10px 0', borderBottom: i < 2 ? `1px dashed ${V3_GOLD}55` : 'none',
          }}>
            <div style={{
              width: 28, height: 28,
              background: stratColor(it.s),
              border: `2px solid ${V3_GOLD}`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 12, fontWeight: 800, color: '#000',
              fontFamily: 'JetBrains Mono, monospace',
            }}>{i + 1}</div>
            <div>
              <div style={{ fontSize: 16, color: V3_CREAM, fontWeight: 400, letterSpacing: 1 }}>{it.label}</div>
              <div style={{ fontSize: 10, color: V3_GOLD, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
                n={it.n} · {it.winners}W
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 22, color: V3_GOLD_HI, fontFamily: 'JetBrains Mono, monospace', fontWeight: 800 }}>{odds}</div>
              <div style={{ fontSize: 10, color: it.pnl >= 0 ? '#86efac' : '#fb7185', fontFamily: 'JetBrains Mono, monospace' }}>
                {fmtPct(it.pnlPct, 2)}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function V3FieldCount({ account }) {
  return (
    <div style={{
      background: '#000', border: `2px solid ${V3_GOLD}`,
      padding: 12, marginTop: 12,
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 4,
      fontFamily: 'JetBrains Mono, monospace',
    }}>
      {[
        ['IN MONEY', account.profit, '#86efac'],
        ['OUT', account.loss, '#fb7185'],
        ['SCRATCHED', account.waiting, '#a1a1aa'],
        ['ACTIVE', account.trading, V3_GOLD_HI],
      ].map(([l, v, c]) => (
        <div key={l} style={{ textAlign: 'center', borderRight: `1px solid ${V3_GOLD}33`, padding: '4px 0' }}>
          <div style={{ fontSize: 9, color: V3_GOLD, letterSpacing: 1.5 }}>{l}</div>
          <div style={{ fontSize: 22, fontWeight: 800, color: c, letterSpacing: -0.5 }}>{v}</div>
        </div>
      ))}
    </div>
  );
}

function V3Track({ agents }) {
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 12), [agents]);
  const allPnls = agents.map(a => a.pnl).sort((x, y) => x - y);
  const lo = allPnls[5], hi = allPnls[allPnls.length - 1];
  const range = hi - lo || 1;
  return (
    <div style={{
      flex: 1, background: `radial-gradient(ellipse at top, ${V3_TRACK_HI}, ${V3_TRACK})`,
      border: `4px solid ${V3_GOLD}`,
      padding: 18,
      display: 'flex', flexDirection: 'column',
      position: 'relative', overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        fontFamily: '"Yeseva One", Georgia, serif',
        marginBottom: 10,
      }}>
        <div style={{ fontSize: 22, color: V3_GOLD_HI, letterSpacing: 2 }}>THE FIELD · 12 RUNNERS</div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: V3_GOLD, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1.5, fontWeight: 700 }}>
          <span>POST</span>
          <span style={{ color: V3_CREAM, opacity: 0.5 }}>· · · · · · · · · · · ·</span>
          <span>FINISH</span>
        </div>
      </div>
      <div style={{ flex: 1, display: 'grid', gridTemplateRows: 'repeat(12, 1fr)', gap: 3 }}>
        {top.map((a, i) => {
          const t = Math.max(0.02, (a.pnl - lo) / range);
          return <V3Lane key={a.id} agent={a} progress={t} laneNo={i + 1} />;
        })}
      </div>
      {/* finish line shadow */}
      <div style={{
        position: 'absolute', right: 18, top: 50, bottom: 18, width: 14,
        background: 'repeating-linear-gradient(0deg, #fff 0 8px, #000 8px 16px)',
        opacity: 0.5,
      }} />
    </div>
  );
}

function V3Lane({ agent, progress, laneNo }) {
  const t = useAnimatedNumber(progress, 700);
  return (
    <div style={{
      position: 'relative', height: '100%',
      background: `linear-gradient(0deg, ${V3_TRACK} 50%, ${V3_TRACK_HI} 100%)`,
      borderTop: `1px solid ${V3_TRACK_HI}`,
      borderBottom: `1px solid ${V3_TRACK_HI}`,
    }}>
      {/* lane number */}
      <div style={{
        position: 'absolute', left: 4, top: '50%', transform: 'translateY(-50%)',
        width: 24, height: 24, background: V3_GOLD,
        color: '#000', display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontFamily: '"Yeseva One", Georgia, serif', fontSize: 14, fontWeight: 800,
        border: `1px solid ${V3_GREEN_DARK}`,
      }}>{laneNo}</div>
      {/* horse marker */}
      <div style={{
        position: 'absolute', left: `calc(34px + ${t * 88}%)`, top: 0, bottom: 0,
        display: 'flex', alignItems: 'center', gap: 6,
        transition: 'left 0.4s cubic-bezier(0.4, 0, 0.2, 1)',
      }}>
        <div style={{
          width: 36, height: 36, borderRadius: 999,
          background: stratColor(agent.strategy),
          border: `3px solid ${V3_GOLD}`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 12, fontWeight: 900, color: '#000',
          fontFamily: 'JetBrains Mono, monospace',
          boxShadow: '0 4px 8px rgba(0,0,0,0.6)',
        }}>{agent.initials}</div>
        <div style={{
          background: 'rgba(0,0,0,0.7)',
          padding: '2px 8px', borderRadius: 2,
          fontFamily: '"Yeseva One", Georgia, serif',
          color: V3_CREAM, fontSize: 13, whiteSpace: 'nowrap',
          letterSpacing: 0.5,
        }}>
          {agent.name} <span style={{ color: V3_GOLD_HI, fontFamily: 'JetBrains Mono, monospace', fontWeight: 800, fontSize: 11 }}>
            {fmtPct(agent.pnlPct, 1)}
          </span>
        </div>
      </div>
    </div>
  );
}

function V3RaceCalls({ fills, promotions }) {
  const calls = useMemo(() => {
    const fcalls = fills.slice(0, 8).map(f => ({
      key: f.id, t: f.t,
      text: `${f.agentName} ${f.side === 'buy' ? 'takes' : 'sheds'} ${f.qty} ${f.symbol} at $${f.price.toFixed(2)} —`,
      kind: 'call',
    }));
    const pcalls = promotions.slice(0, 3).map(p => ({
      key: p.id, t: p.t,
      text: `${p.agentName} ${p.direction === 'up' ? 'moves up to' : 'drops to'} ${p.toRank.toUpperCase()} class — ${p.reason}!`,
      kind: 'flag',
    }));
    return [...pcalls, ...fcalls].slice(0, 10);
  }, [fills, promotions]);
  return (
    <div style={{
      background: V3_GREEN_DARK,
      border: `3px solid ${V3_GOLD}`,
      padding: 14, flex: 1, minHeight: 0,
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        borderBottom: `1px solid ${V3_GOLD}`, paddingBottom: 8, marginBottom: 8,
      }}>
        <div style={{ fontSize: 14, color: V3_GOLD, letterSpacing: 4, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace' }}>
          THE CALL
        </div>
        <span style={{ flex: 1 }} />
        <span style={{
          padding: '2px 8px', background: V3_RED, color: V3_CREAM,
          fontSize: 9, fontWeight: 800, letterSpacing: 1.5,
          fontFamily: 'JetBrains Mono, monospace',
        }}>ON AIR</span>
      </div>
      <div style={{ flex: 1, overflow: 'hidden', fontFamily: '"Yeseva One", Georgia, serif' }}>
        {calls.map((c, i) => (
          <div key={c.key} style={{
            padding: '6px 0', display: 'flex', gap: 8,
            opacity: 1 - i * 0.07,
            borderBottom: `1px dashed ${V3_GOLD}22`,
          }}>
            <span style={{
              fontSize: 10, color: V3_GOLD, fontFamily: 'JetBrains Mono, monospace',
              letterSpacing: 0.5, minWidth: 56,
            }}>{new Date(c.t).toLocaleTimeString('en-US', { hour12: false }).slice(0, 8)}</span>
            <span style={{ fontSize: 13, color: c.kind === 'flag' ? V3_GOLD_HI : V3_CREAM, lineHeight: 1.35 }}>
              {c.kind === 'flag' && <span style={{ color: V3_RED, marginRight: 4 }}>★</span>}
              {c.text}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function V3Marquee({ fills, agents }) {
  const items = useMemo(() => {
    return fills.slice(0, 16).map(f => ({
      key: f.id,
      text: `${f.symbol} · ${f.side.toUpperCase()} ${f.qty} @ $${f.price.toFixed(2)} · ${f.agentName}`,
    }));
  }, [fills]);
  return (
    <div style={{
      height: 56, background: '#000',
      borderTop: `4px double ${V3_GOLD}`,
      borderBottom: `2px solid ${V3_GOLD}`,
      display: 'flex', overflow: 'hidden',
      position: 'relative',
    }}>
      <div style={{
        background: V3_GOLD, color: '#000',
        padding: '0 24px', display: 'flex', alignItems: 'center', gap: 8,
        fontFamily: '"Yeseva One", Georgia, serif',
        fontSize: 24, fontWeight: 400, letterSpacing: 2,
      }}>
        <span>TF</span>
        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 14, letterSpacing: 2, fontWeight: 800 }}>TAPE</span>
      </div>
      <div style={{ flex: 1, position: 'relative' }}>
        <div className="v3-marquee" style={{
          position: 'absolute', whiteSpace: 'nowrap',
          height: '100%', display: 'flex', alignItems: 'center',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 16,
          color: V3_GOLD_HI, fontWeight: 600, letterSpacing: 1,
        }}>
          {[...items, ...items].map((it, i) => (
            <span key={i} style={{ padding: '0 28px' }}>
              <span style={{ color: V3_RED, marginRight: 10 }}>★</span>
              {it.text}
            </span>
          ))}
        </div>
        {/* bulbs */}
        <div style={{
          position: 'absolute', left: 0, right: 0, top: 0, height: 4,
          background: 'repeating-linear-gradient(90deg, ' + V3_GOLD_HI + ' 0 6px, transparent 6px 14px)',
        }} />
        <div style={{
          position: 'absolute', left: 0, right: 0, bottom: 0, height: 4,
          background: 'repeating-linear-gradient(90deg, ' + V3_GOLD_HI + ' 0 6px, transparent 6px 14px)',
        }} />
      </div>
    </div>
  );
}

function V3FieldGrid({ agents }) {
  // Show full 100 as horse-numbered chips below — visual density
  const sorted = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl), [agents]);
  return (
    <div style={{
      background: V3_GREEN_DARK, border: `3px solid ${V3_GOLD}`,
      padding: 10, marginTop: 12, flex: 1, minHeight: 0,
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        fontSize: 12, color: V3_GOLD, letterSpacing: 3, fontWeight: 700,
        fontFamily: 'JetBrains Mono, monospace',
        borderBottom: `1px solid ${V3_GOLD}55`,
        paddingBottom: 6, marginBottom: 8,
      }}>FULL FIELD · 100 ENTRIES</div>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(20, 1fr)',
        gap: 2, flex: 1,
      }}>
        {sorted.slice(0, 100).map((a, i) => {
          const inMoney = a.pnl > 0;
          return (
            <div key={a.id} style={{
              background: inMoney ? `oklch(${0.4 + Math.min(0.4, a.pnl/200)} 0.14 145)` : `oklch(${0.4 + Math.min(0.4, Math.abs(a.pnl)/200)} 0.14 25)`,
              border: i < 12 ? `1px solid ${V3_GOLD}` : `1px solid #00000044`,
              fontSize: 9, fontWeight: 800, color: '#000',
              fontFamily: 'JetBrains Mono, monospace',
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              padding: '2px 0',
            }}>
              <span style={{ fontSize: 10, color: V3_CREAM }}>{a.id.toString().padStart(2, '0')}</span>
              <span style={{ fontSize: 8 }}>{a.pnl >= 0 ? '+' : '−'}{Math.abs(a.pnl).toFixed(0)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BroadcastV3({ stream }) {
  const { agents, account, fills, promotions, byStrategy } = stream;
  return (
    <div style={{
      width: 1920, height: 1080,
      background: `radial-gradient(ellipse at top, ${V3_GREEN}, ${V3_GREEN_DARK})`,
      color: V3_CREAM,
      fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
      display: 'flex', flexDirection: 'column', position: 'relative',
      overflow: 'hidden',
    }}>
      <V3Header account={account} />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '320px 1fr 360px', gap: 14, padding: 14, minHeight: 0 }}>
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <V3ToteBoard byStrategy={byStrategy} />
          <V3FieldCount account={account} />
          <div style={{ flex: 1, marginTop: 12, minHeight: 0 }}>
            <V3FieldGrid agents={agents} />
          </div>
        </div>
        <V3Track agents={agents} />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14, minHeight: 0 }}>
          <V3RaceCalls fills={fills} promotions={promotions} />
        </div>
      </div>
      <V3Marquee fills={fills} agents={agents} />
    </div>
  );
}

window.BroadcastV3 = BroadcastV3;
