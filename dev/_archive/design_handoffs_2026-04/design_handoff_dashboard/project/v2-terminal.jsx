// V2 — Cyberpunk Bloomberg Terminal
// 1920×1080: phosphor green + amber, scanlines, 6-pane grid.

const V2_BG = '#04060a';
const V2_PANEL = '#080c11';
const V2_LINE = '#0e1a18';
const V2_GREEN = '#5eead4';
const V2_GREEN_HI = '#86efac';
const V2_AMBER = '#fbbf24';
const V2_DIM = '#3f3f46';
const V2_TEXT = '#a7f3d0';
const V2_TEXT_DIM = '#4d7c6e';
const V2_LOSS = '#f43f5e';

function V2Frame({ title, code, accent = V2_GREEN, children, style = {} }) {
  return (
    <div style={{
      background: V2_PANEL,
      border: `1px solid ${V2_LINE}`,
      display: 'flex', flexDirection: 'column',
      minHeight: 0, position: 'relative',
      ...style,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '4px 10px',
        borderBottom: `1px solid ${V2_LINE}`,
        background: 'linear-gradient(180deg, rgba(94,234,212,0.05), transparent)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ color: accent, fontSize: 9, fontFamily: 'JetBrains Mono, monospace' }}>{code}</span>
          <span style={{ fontSize: 10, color: V2_GREEN_HI, letterSpacing: 1.6, fontWeight: 700 }}>{title}</span>
        </div>
        <span style={{ display: 'flex', gap: 4 }}>
          <span style={{ width: 6, height: 6, borderRadius: 999, background: accent, boxShadow: `0 0 6px ${accent}` }} />
          <span style={{ width: 6, height: 6, borderRadius: 999, background: V2_DIM }} />
          <span style={{ width: 6, height: 6, borderRadius: 999, background: V2_DIM }} />
        </span>
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>{children}</div>
    </div>
  );
}

function V2HeaderBar({ account }) {
  const now = useNow(500);
  const t = now.toLocaleTimeString('en-US', { hour12: false, timeZone: 'America/New_York' });
  return (
    <div style={{
      height: 36, background: '#000',
      borderBottom: `1px solid ${V2_LINE}`,
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 16px',
      fontFamily: 'JetBrains Mono, monospace', fontSize: 12,
      color: V2_GREEN_HI,
    }}>
      <span style={{ color: V2_AMBER, fontWeight: 800 }}>tradefarm@stream</span>
      <span style={{ color: V2_DIM }}>:</span>
      <span style={{ color: V2_GREEN }}>~/live</span>
      <span style={{ color: V2_DIM }}>$</span>
      <span style={{ color: V2_TEXT }}>broadcast --tick={account.tick.toString().padStart(5, '0')} --agents=100 --strategies=mom,lstm,llm</span>
      <span className="cursor-blink" style={{ color: V2_GREEN, marginLeft: -4 }}>▌</span>
      <span style={{ flex: 1 }} />
      <span style={{ color: V2_AMBER }}>{t} ET</span>
      <span style={{ color: V2_DIM }}>·</span>
      <span style={{ color: V2_GREEN }}>RTH</span>
      <span style={{ color: V2_DIM }}>·</span>
      <LiveDot color={V2_LOSS} label="REC" />
    </div>
  );
}

function V2BigStats({ account }) {
  const eq = useAnimatedNumber(account.totalEquity, 400);
  const pn = useAnimatedNumber(account.pnl, 400);
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)',
      borderBottom: `1px solid ${V2_LINE}`,
      background: '#06090d',
    }}>
      <V2Stat label="EQUITY" value={'$' + eq.toLocaleString('en-US', { maximumFractionDigits: 0 })} />
      <V2Stat label="DAY P&L" value={(pn >= 0 ? '+' : '−') + '$' + Math.abs(pn).toFixed(0)} color={pn >= 0 ? V2_GREEN_HI : V2_LOSS} />
      <V2Stat label="P&L %" value={fmtPct(account.pnlPct, 2)} color={account.pnlPct >= 0 ? V2_GREEN_HI : V2_LOSS} />
      <V2Stat label="PROFIT/LOSS" value={`${account.profit}/${account.loss}`} color={V2_AMBER} />
      <V2Stat label="ACTIVE" value={`${account.trading}`} color={V2_GREEN} />
      <V2Stat label="TICK" value={`#${account.tick}`} color={V2_GREEN_HI} />
    </div>
  );
}

function V2Stat({ label, value, color = V2_GREEN_HI }) {
  return (
    <div style={{ padding: '10px 14px', borderRight: `1px solid ${V2_LINE}` }}>
      <div style={{ fontSize: 9, letterSpacing: 1.6, color: V2_TEXT_DIM, fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
        {label}
      </div>
      <div style={{
        fontSize: 22, fontWeight: 800, color, fontFamily: 'JetBrains Mono, monospace',
        textShadow: `0 0 8px ${color}55`, marginTop: 2, letterSpacing: -0.5,
      }}>{value}</div>
    </div>
  );
}

// 10x10 agent matrix heatmap
function V2Matrix({ agents }) {
  return (
    <div style={{ padding: 8, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(10, 1fr)', gap: 2,
        flex: 1,
      }}>
        {agents.map((a, i) => {
          const norm = Math.max(-1, Math.min(1, a.pnl / 100));
          const bg = norm > 0
            ? `oklch(${0.35 + norm * 0.4} 0.18 145)`
            : norm < 0
              ? `oklch(${0.35 + Math.abs(norm) * 0.4} 0.18 25)`
              : '#0e1a18';
          return (
            <div key={a.id} title={`${a.name} ${fmtPct(a.pnlPct,1)}`} style={{
              background: bg, position: 'relative', overflow: 'hidden',
              border: a.status === 'trading' ? `1px solid ${V2_AMBER}aa` : `1px solid #00000044`,
            }}>
              <div style={{
                position: 'absolute', left: 2, top: 1,
                fontSize: 8, fontFamily: 'JetBrains Mono, monospace',
                color: '#000', fontWeight: 800, opacity: 0.7,
              }}>{(i + 1).toString().padStart(2, '0')}</div>
              <div style={{
                position: 'absolute', right: 2, bottom: 0,
                fontSize: 9, fontFamily: 'JetBrains Mono, monospace',
                color: '#000', fontWeight: 800, opacity: 0.85,
              }}>{a.pnl >= 0 ? '+' : '−'}{Math.abs(a.pnl).toFixed(0)}</div>
            </div>
          );
        })}
      </div>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginTop: 6, fontSize: 9, fontFamily: 'JetBrains Mono, monospace',
        color: V2_TEXT_DIM, letterSpacing: 1,
      }}>
        <span>−$100</span>
        <span style={{ display: 'flex', flex: 1, height: 6, margin: '0 8px',
          background: 'linear-gradient(90deg, oklch(0.6 0.18 25), #0e1a18, oklch(0.6 0.18 145))' }} />
        <span>+$100</span>
      </div>
    </div>
  );
}

function V2StrategyPane({ byStrategy }) {
  return (
    <div style={{ padding: 12, height: '100%', display: 'flex', flexDirection: 'column', gap: 10 }}>
      {STRATEGIES.map(s => {
        const st = byStrategy[s];
        const color = stratColor(s);
        return (
          <div key={s} style={{
            border: `1px solid ${V2_LINE}`,
            padding: '8px 10px', display: 'grid',
            gridTemplateColumns: '70px 1fr auto', gap: 10, alignItems: 'center',
          }}>
            <div>
              <div style={{ fontSize: 10, fontWeight: 800, color, letterSpacing: 1.5, fontFamily: 'JetBrains Mono, monospace' }}>
                {STRATEGY_LABEL[s]}
              </div>
              <div style={{ fontSize: 9, color: V2_TEXT_DIM, fontFamily: 'JetBrains Mono, monospace' }}>
                n={st.agents.length}
              </div>
            </div>
            <Sparkline
              data={st.agents.slice(0, 8).flatMap(a => a.sparkline.slice(-8))}
              color={color} width={220} height={36} strokeWidth={1.2} fillBelow
            />
            <div style={{ textAlign: 'right' }}>
              <div style={{
                fontSize: 16, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
                color: st.pnl >= 0 ? V2_GREEN_HI : V2_LOSS,
              }}>{fmtPct(st.pnlPct, 2)}</div>
              <div style={{ fontSize: 10, color: V2_TEXT_DIM, fontFamily: 'JetBrains Mono, monospace' }}>
                {st.winners}/{st.agents.length} W
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}

function V2MarketFeed({ agents }) {
  const symbols = useMemo(() => {
    const counts = {};
    agents.forEach(a => { if (a.symbol) counts[a.symbol] = (counts[a.symbol] || 0) + 1; });
    return Object.entries(counts).sort((a,b) => b[1] - a[1]).slice(0, 14);
  }, [agents]);
  return (
    <div style={{ padding: 8, height: '100%', overflow: 'hidden' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr', gap: 1,
        fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
      }}>
        <div style={{
          display: 'grid', gridTemplateColumns: '60px 1fr 60px 50px',
          padding: '3px 8px',
          borderBottom: `1px solid ${V2_LINE}`,
          color: V2_TEXT_DIM, fontSize: 9, letterSpacing: 1.4,
        }}>
          <span>SYM</span><span>LAST · TAPE</span><span style={{ textAlign: 'right' }}>%CHG</span><span style={{ textAlign: 'right' }}>HOLD</span>
        </div>
        {symbols.map(([sym, n], i) => {
          const r = (Math.sin(account_seed(sym) + n) + 1) / 2;
          const chg = (r - 0.5) * 6;
          const last = 50 + r * 850;
          return (
            <div key={sym} style={{
              display: 'grid', gridTemplateColumns: '60px 1fr 60px 50px',
              padding: '4px 8px', alignItems: 'center',
              background: i % 2 === 0 ? 'transparent' : 'rgba(94,234,212,0.02)',
            }}>
              <span style={{ color: V2_AMBER, fontWeight: 800 }}>{sym}</span>
              <span style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{ color: V2_GREEN_HI }}>{last.toFixed(2)}</span>
                <V2Tape n={(i + n) % 8} />
              </span>
              <span style={{ textAlign: 'right', color: chg >= 0 ? V2_GREEN_HI : V2_LOSS }}>{fmtPct(chg, 2)}</span>
              <span style={{ textAlign: 'right', color: V2_TEXT }}>{n}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
function account_seed(s) {
  let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) | 0;
  return h;
}
function V2Tape({ n }) {
  return (
    <span style={{ display: 'inline-flex', gap: 1 }}>
      {Array.from({ length: 6 }).map((_, i) => (
        <span key={i} style={{
          width: 4, height: 8,
          background: i < n ? V2_GREEN : V2_LINE,
        }} />
      ))}
    </span>
  );
}

function V2Console({ fills }) {
  return (
    <div style={{ padding: 8, height: '100%', overflow: 'hidden', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>
      {fills.slice(0, 16).map((f, i) => {
        const time = new Date(f.t).toLocaleTimeString('en-US', { hour12: false }).slice(0, 8);
        return (
          <div key={f.id} style={{
            padding: '2px 4px', borderLeft: `2px solid ${i === 0 ? V2_AMBER : 'transparent'}`,
            background: i === 0 ? 'rgba(251,191,36,0.06)' : 'transparent',
            display: 'flex', gap: 8, opacity: 1 - i * 0.04,
          }}>
            <span style={{ color: V2_TEXT_DIM }}>{time}</span>
            <span style={{ color: V2_GREEN, width: 32 }}>a{f.agentId.toString().padStart(3, '0')}</span>
            <span style={{
              color: f.side === 'buy' ? V2_GREEN_HI : V2_LOSS,
              fontWeight: 800, width: 28,
            }}>{f.side.toUpperCase()}</span>
            <span style={{ color: V2_AMBER, width: 56 }}>{f.symbol}</span>
            <span style={{ color: V2_TEXT, width: 36 }}>x{f.qty}</span>
            <span style={{ color: V2_GREEN_HI }}>${f.price.toFixed(2)}</span>
            <span style={{ color: V2_TEXT_DIM, marginLeft: 'auto' }}>FILL</span>
          </div>
        );
      })}
      {fills.length === 0 && <div style={{ color: V2_TEXT_DIM }}>// awaiting fills…</div>}
    </div>
  );
}

function V2LSTM({ agents }) {
  const samples = useMemo(() => agents.filter(a => a.strategy !== 'momentum').slice(0, 8), [agents]);
  return (
    <div style={{ padding: 10, height: '100%', overflow: 'hidden' }}>
      {samples.map(a => (
        <div key={a.id} style={{ marginBottom: 8 }}>
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
            fontFamily: 'JetBrains Mono, monospace', fontSize: 10, color: V2_TEXT_DIM,
            marginBottom: 3,
          }}>
            <span style={{ color: V2_GREEN_HI, fontWeight: 700 }}>a{a.id.toString().padStart(3, '0')} · {a.name}</span>
            <span style={{ color: V2_AMBER }}>p={a.lstmConf.toFixed(2)}</span>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 2, height: 14 }}>
            {['up','flat','down'].map((d, i) => {
              const probs = [a.lstmConf, (1 - a.lstmConf) * 0.6, (1 - a.lstmConf) * 0.4];
              const p = a.lstmDir === d ? probs[0] : probs[1 + (i % 2)];
              const c = d === 'up' ? V2_GREEN_HI : d === 'down' ? V2_LOSS : V2_DIM;
              return (
                <div key={d} style={{ background: V2_PANEL, position: 'relative', border: `1px solid ${V2_LINE}` }}>
                  <div style={{
                    position: 'absolute', left: 0, top: 0, bottom: 0,
                    width: `${p * 100}%`, background: c, opacity: 0.6,
                  }} />
                  <div style={{
                    position: 'absolute', inset: 0, display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    fontSize: 9, fontWeight: 800, color: '#000',
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>{d.toUpperCase()} {(p * 100).toFixed(0)}</div>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

function V2LLM({ agents, fills }) {
  const sample = useMemo(() => {
    const llm = agents.filter(a => a.strategy === 'llm');
    return llm.slice(0, 3);
  }, [agents]);
  return (
    <div style={{ padding: 10, height: '100%', fontFamily: 'JetBrains Mono, monospace', fontSize: 10, overflow: 'hidden' }}>
      {sample.map(a => (
        <div key={a.id} style={{ marginBottom: 10, borderLeft: `2px solid ${V2_AMBER}`, paddingLeft: 8 }}>
          <div style={{ color: V2_AMBER, fontWeight: 800 }}>POST /llm/decide a{a.id.toString().padStart(3,'0')}</div>
          <div style={{ color: V2_TEXT_DIM }}>{'{'}</div>
          <div style={{ color: V2_TEXT, paddingLeft: 8 }}>
            "agent": "<span style={{ color: V2_GREEN_HI }}>{a.name}</span>",
          </div>
          <div style={{ color: V2_TEXT, paddingLeft: 8 }}>
            "bias": "<span style={{ color: a.lstmDir === 'up' ? V2_GREEN_HI : a.lstmDir === 'down' ? V2_LOSS : V2_AMBER }}>{a.lstmDir === 'up' ? 'long' : a.lstmDir === 'down' ? 'short' : 'flat'}</span>",
          </div>
          <div style={{ color: V2_TEXT, paddingLeft: 8 }}>
            "stance": "<span style={{ color: V2_GREEN_HI }}>{a.llmStance}</span>",
          </div>
          <div style={{ color: V2_TEXT, paddingLeft: 8 }}>
            "size": <span style={{ color: V2_AMBER }}>{(a.lstmConf * 0.4).toFixed(2)}</span>
          </div>
          <div style={{ color: V2_TEXT_DIM }}>{'}'}</div>
        </div>
      ))}
    </div>
  );
}

function V2Footer({ account }) {
  return (
    <div style={{
      height: 28, background: '#000',
      borderTop: `1px solid ${V2_LINE}`,
      display: 'flex', alignItems: 'center', gap: 16,
      padding: '0 16px',
      fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
      color: V2_TEXT_DIM,
    }}>
      <span>● <span style={{ color: V2_GREEN_HI }}>DB</span> 4.2ms</span>
      <span>● <span style={{ color: V2_GREEN_HI }}>WS</span> ok</span>
      <span>● <span style={{ color: V2_GREEN_HI }}>BROKER</span> alpaca_paper</span>
      <span>● <span style={{ color: V2_AMBER }}>LLM</span> claude-haiku-4.5</span>
      <span style={{ flex: 1 }} />
      <span>tick interval: 600ms</span>
      <span>uptime: 14:23:51</span>
      <span>mem 412mb / 8gb</span>
    </div>
  );
}

function BroadcastV2({ stream }) {
  const { agents, account, fills, byStrategy } = stream;
  return (
    <div className="v2-crt" style={{
      width: 1920, height: 1080, background: V2_BG, color: V2_TEXT,
      fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
      display: 'flex', flexDirection: 'column', position: 'relative',
      overflow: 'hidden',
    }}>
      <V2HeaderBar account={account} />
      <V2BigStats account={account} />

      <div style={{
        flex: 1, display: 'grid',
        gridTemplateColumns: '1.2fr 1fr 1fr',
        gridTemplateRows: '1fr 1fr',
        gap: 6, padding: 6,
        minHeight: 0,
      }}>
        <V2Frame title="AGENT MATRIX · 100×PNL" code="A0" accent={V2_GREEN}>
          <V2Matrix agents={agents} />
        </V2Frame>
        <V2Frame title="STRATEGY EQUITY · 30T" code="B0" accent={V2_AMBER}>
          <V2StrategyPane byStrategy={byStrategy} />
        </V2Frame>
        <V2Frame title="TAPE · TOP HOLDINGS" code="C0" accent={V2_GREEN}>
          <V2MarketFeed agents={agents} />
        </V2Frame>
        <V2Frame title="ORDERS · LIVE LOG" code="D0" accent={V2_AMBER} style={{ gridColumn: 'span 1' }}>
          <V2Console fills={fills} />
        </V2Frame>
        <V2Frame title="LSTM · DIRECTION PROBS" code="E0" accent={V2_GREEN}>
          <V2LSTM agents={agents} />
        </V2Frame>
        <V2Frame title="LLM · DECISION TRACE" code="F0" accent={V2_AMBER}>
          <V2LLM agents={agents} fills={fills} />
        </V2Frame>
      </div>

      <V2Footer account={account} />

      {/* CRT scanline overlay */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: 'repeating-linear-gradient(0deg, transparent 0 2px, rgba(0,0,0,0.18) 2px 3px)',
        mixBlendMode: 'multiply', opacity: 0.5,
      }} />
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        background: 'radial-gradient(ellipse at center, transparent 60%, rgba(0,0,0,0.4) 100%)',
      }} />
    </div>
  );
}

window.BroadcastV2 = BroadcastV2;
