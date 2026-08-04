// V4 — Twitch Streamer Overlay
// 1920×1080: 10×10 agent grid hero, chat-style fill feed, featured agent rotator,
// sub-style alerts, mood meter. Electric blue accent.

const V4_BG = '#0a0a0e';
const V4_PANEL = '#11131a';
const V4_PANEL_HI = '#1a1d27';
const V4_LINE = '#272a35';
const V4_BLUE = '#3b82f6';
const V4_BLUE_HI = '#60a5fa';
const V4_PINK = '#ec4899';
const V4_PURPLE = '#a78bfa';

function V4TopBar({ account, promotions }) {
  const latest = promotions[0];
  return (
    <div style={{
      height: 60, background: '#000',
      borderBottom: `2px solid ${V4_BLUE}`,
      display: 'grid', gridTemplateColumns: '280px 1fr auto',
      alignItems: 'center', gap: 16, padding: '0 20px',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <div style={{
          width: 40, height: 40, borderRadius: 6,
          background: `linear-gradient(135deg, ${V4_BLUE}, ${V4_PURPLE})`,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          color: '#fff', fontWeight: 900, fontSize: 18,
          fontFamily: 'JetBrains Mono, monospace',
          boxShadow: `0 0 20px ${V4_BLUE}66`,
        }}>TF</div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16, fontWeight: 800 }}>tradefarm</span>
            <span style={{
              padding: '1px 6px', background: '#ef4444', color: '#fff',
              fontSize: 9, fontWeight: 800, letterSpacing: 1,
              borderRadius: 2,
            }}>LIVE</span>
          </div>
          <div style={{ fontSize: 10, color: '#9ca3af', display: 'flex', gap: 8, fontFamily: 'JetBrains Mono, monospace' }}>
            <span>👁 12.4K</span>
            <span>· Trading IRL · English</span>
          </div>
        </div>
      </div>
      {/* alert ribbon */}
      <div style={{
        display: 'flex', justifyContent: 'center',
      }}>
        {latest ? (
          <div style={{
            display: 'inline-flex', alignItems: 'center', gap: 12,
            padding: '6px 18px',
            background: `linear-gradient(90deg, ${V4_BLUE}, ${V4_PURPLE})`,
            border: `1px solid ${V4_BLUE_HI}`,
            borderRadius: 4,
            boxShadow: `0 0 24px ${V4_BLUE}55`,
          }}>
            <span style={{ fontSize: 18 }}>🎉</span>
            <span style={{ fontSize: 11, fontWeight: 800, letterSpacing: 1.5, color: '#dbeafe' }}>
              {latest.direction === 'up' ? 'NEW PROMOTION!' : 'DEMOTED'}
            </span>
            <span style={{ fontSize: 14, fontWeight: 700, color: '#fff' }}>{latest.agentName}</span>
            <span style={{
              fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#dbeafe',
              padding: '2px 8px', background: 'rgba(0,0,0,0.3)', borderRadius: 2,
            }}>
              → {RANK_LABEL[latest.toRank]}
            </span>
          </div>
        ) : (
          <div style={{ fontSize: 12, color: '#71717a', letterSpacing: 1.5 }}>
            ⚡ tradefarm · 100 AI agents · 3 strategies · live paper trading
          </div>
        )}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <V4StatPill label="EQUITY" value={'$' + Math.round(account.totalEquity).toLocaleString()} />
        <V4StatPill label="P&L" value={fmtPct(account.pnlPct, 2)} color={account.pnlPct >= 0 ? '#34d399' : '#fb7185'} />
        <V4StatPill label="WINNERS" value={`${account.profit}/100`} color={V4_BLUE_HI} />
      </div>
    </div>
  );
}

function V4StatPill({ label, value, color = '#fff' }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 12px',
      background: V4_PANEL_HI,
      border: `1px solid ${V4_LINE}`,
      borderRadius: 6,
    }}>
      <span style={{ fontSize: 9, color: '#9ca3af', letterSpacing: 1.5, fontWeight: 700 }}>{label}</span>
      <span style={{ fontSize: 16, fontWeight: 800, color, fontFamily: 'JetBrains Mono, monospace' }}>{value}</span>
    </div>
  );
}

function V4Chat({ fills, promotions }) {
  const items = useMemo(() => {
    const f = fills.slice(0, 30).map(x => ({ ...x, kind: 'fill' }));
    const p = promotions.slice(0, 8).map(x => ({ ...x, kind: 'promo' }));
    return [...p, ...f].sort((a, b) => b.t - a.t).slice(0, 24);
  }, [fills, promotions]);
  return (
    <div style={{
      background: V4_PANEL, height: '100%',
      display: 'flex', flexDirection: 'column',
      borderRight: `1px solid ${V4_LINE}`,
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: `1px solid ${V4_LINE}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        background: V4_PANEL_HI,
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 0.5 }}>STREAM CHAT</div>
        <div style={{ display: 'flex', gap: 4 }}>
          <span style={{ width: 8, height: 8, borderRadius: 999, background: V4_BLUE, boxShadow: `0 0 6px ${V4_BLUE}` }} />
          <span style={{ fontSize: 9, color: '#9ca3af', letterSpacing: 1.5, fontWeight: 700 }}>FILLS · PROMOS</span>
        </div>
      </div>
      <div style={{ flex: 1, overflow: 'hidden', padding: '4px 0', display: 'flex', flexDirection: 'column-reverse' }}>
        <div>
          {items.map((it, i) => (
            <V4ChatRow key={it.id || it.key} item={it} fresh={i === 0} />
          ))}
        </div>
      </div>
      {/* fake input */}
      <div style={{
        padding: '10px 12px', borderTop: `1px solid ${V4_LINE}`,
        background: V4_PANEL_HI,
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          fontSize: 11, color: '#9ca3af',
          padding: '6px 10px', flex: 1, background: '#000',
          border: `1px solid ${V4_LINE}`, borderRadius: 4,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          gg <span style={{ animation: 'cursor-blink 1s step-end infinite' }}>▌</span>
        </span>
        <span style={{
          padding: '6px 14px', background: V4_BLUE, color: '#fff',
          fontSize: 12, fontWeight: 800, borderRadius: 4,
        }}>Chat</span>
      </div>
    </div>
  );
}

function V4ChatRow({ item, fresh }) {
  if (item.kind === 'promo') {
    return (
      <div style={{
        padding: '6px 14px', display: 'flex', gap: 8,
        background: `linear-gradient(90deg, ${V4_PURPLE}22, transparent)`,
        borderLeft: `3px solid ${V4_PURPLE}`,
        marginBottom: 2,
      }}>
        <span style={{ fontSize: 14 }}>{item.direction === 'up' ? '🎉' : '💀'}</span>
        <div style={{ flex: 1, fontSize: 12, lineHeight: 1.4 }}>
          <span style={{ color: V4_PURPLE, fontWeight: 800 }}>SYSTEM</span>{' '}
          <span style={{ color: '#d4d4d8' }}>
            {item.agentName} {item.direction === 'up' ? 'promoted to' : 'demoted to'} {' '}
            <span style={{ color: V4_BLUE_HI, fontWeight: 800 }}>{RANK_LABEL[item.toRank]}</span>
            {' '}<span style={{ color: '#71717a', fontSize: 11 }}>· {item.reason}</span>
          </span>
        </div>
      </div>
    );
  }
  const sc = stratColor(item.strategy);
  const isBuy = item.side === 'buy';
  return (
    <div style={{
      padding: '4px 14px', display: 'flex', gap: 8, alignItems: 'flex-start',
      background: fresh ? `${V4_BLUE}11` : 'transparent',
      transition: 'background 0.4s',
    }}>
      <span style={{
        width: 22, height: 22, borderRadius: 4,
        background: sc, color: '#000',
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 9, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
        flexShrink: 0,
      }}>{item.initials}</span>
      <div style={{ flex: 1, fontSize: 12, lineHeight: 1.4, minWidth: 0 }}>
        <div>
          <span style={{ color: sc, fontWeight: 700 }}>{item.agentName}</span>
          <span style={{
            display: 'inline-block', marginLeft: 4,
            fontSize: 8, padding: '1px 4px', borderRadius: 2,
            background: 'rgba(255,255,255,0.08)', color: '#9ca3af',
            fontFamily: 'JetBrains Mono, monospace', fontWeight: 700,
            letterSpacing: 0.5,
          }}>{RANK_LABEL[item.rank]}</span>
          <span style={{ color: '#52525b' }}>: </span>
          <span style={{ color: '#e5e7eb' }}>
            {isBuy ? 'going long ' : 'cutting '}
            <span style={{ color: isBuy ? '#34d399' : '#fb7185', fontWeight: 800 }}>{item.qty} {item.symbol}</span>
            {' '}<span style={{ color: '#71717a', fontFamily: 'JetBrains Mono, monospace', fontSize: 11 }}>@ ${item.price.toFixed(2)}</span>
            {fresh && <span style={{ marginLeft: 6 }}>{isBuy ? '🚀' : '🔻'}</span>}
          </span>
        </div>
      </div>
    </div>
  );
}

function V4Hero({ agents }) {
  return (
    <div style={{
      flex: 1, padding: 16, minHeight: 0,
      display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
        marginBottom: 10,
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14 }}>
          <div style={{ fontSize: 20, fontWeight: 800, letterSpacing: 0.5 }}>THE FARM</div>
          <div style={{ fontSize: 11, color: '#71717a', letterSpacing: 1.4, fontFamily: 'JetBrains Mono, monospace' }}>
            100 AGENTS · LIVE · TICK #
            <span style={{ color: V4_BLUE_HI, fontWeight: 800 }}>{agents.length > 0 ? '∞' : '0'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 14, fontSize: 11, fontFamily: 'JetBrains Mono, monospace', color: '#9ca3af' }}>
          {STRATEGIES.map(s => (
            <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ width: 10, height: 10, borderRadius: 2, background: stratColor(s) }} />
              <span style={{ letterSpacing: 1, fontWeight: 700 }}>{STRATEGY_LABEL[s]}</span>
            </span>
          ))}
        </div>
      </div>
      <div style={{
        flex: 1, display: 'grid',
        gridTemplateColumns: 'repeat(10, 1fr)',
        gridTemplateRows: 'repeat(10, 1fr)',
        gap: 6,
      }}>
        {agents.map(a => <V4Tile key={a.id} agent={a} />)}
      </div>
    </div>
  );
}

function V4Tile({ agent }) {
  const sc = stratColor(agent.strategy);
  const pnl = agent.pnl;
  const norm = Math.max(-1, Math.min(1, pnl / 100));
  const fillH = 45 + norm * 35; // 10–80%
  const isProfit = pnl >= 0;
  const glow = Math.abs(norm) > 0.5 ? `0 0 12px ${isProfit ? '#10b98155' : '#f43f5e55'}` : 'none';
  return (
    <div style={{
      position: 'relative',
      background: V4_PANEL,
      border: `1px solid ${agent.status === 'trading' ? V4_BLUE : V4_LINE}`,
      borderRadius: 4,
      overflow: 'hidden',
      boxShadow: glow,
    }}>
      {/* equity bar */}
      <div style={{
        position: 'absolute', left: 0, right: 0, bottom: 0,
        height: `${fillH}%`,
        background: `linear-gradient(0deg, ${isProfit ? '#10b98144' : '#f43f5e44'}, transparent)`,
        transition: 'height 0.4s',
      }} />
      {/* strategy stripe */}
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0, width: 3,
        background: sc,
      }} />
      {/* content */}
      <div style={{
        position: 'absolute', inset: 0, padding: '4px 6px 4px 9px',
        display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <span style={{
            fontSize: 9, fontWeight: 800, color: '#9ca3af',
            fontFamily: 'JetBrains Mono, monospace', letterSpacing: 0.5,
          }}>#{agent.id.toString().padStart(3, '0')}</span>
          {agent.status === 'trading' && (
            <span style={{ width: 5, height: 5, borderRadius: 999, background: V4_BLUE, boxShadow: `0 0 4px ${V4_BLUE}` }} />
          )}
        </div>
        <div>
          <div style={{
            fontSize: 9, color: '#d4d4d8',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          }}>{agent.name.split(' ')[0]}</div>
          <div style={{
            fontSize: 11, fontWeight: 800,
            color: isProfit ? '#34d399' : '#fb7185',
            fontFamily: 'JetBrains Mono, monospace', letterSpacing: -0.3,
          }}>{fmtPct(agent.pnlPct, 1)}</div>
        </div>
      </div>
    </div>
  );
}

function V4Featured({ agents, byStrategy }) {
  // Cycle the spotlighted agent every few seconds
  const [idx, setIdx] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setIdx(i => i + 1), 5000);
    return () => clearInterval(id);
  }, []);
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 6), [agents]);
  const featured = top[idx % Math.max(1, top.length)] || agents[0];
  if (!featured) return null;
  const sc = stratColor(featured.strategy);
  const isProfit = featured.pnl >= 0;
  return (
    <div style={{
      background: V4_PANEL, borderLeft: `1px solid ${V4_LINE}`,
      height: '100%', display: 'flex', flexDirection: 'column',
    }}>
      <div style={{
        padding: '10px 14px', borderBottom: `1px solid ${V4_LINE}`,
        background: V4_PANEL_HI,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 0.5 }}>SPOTLIGHT</div>
        <div style={{ fontSize: 9, color: '#9ca3af', letterSpacing: 1.4, fontWeight: 700 }}>
          AUTO · {((idx % top.length) + 1)}/{top.length}
        </div>
      </div>
      <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 64, height: 64, borderRadius: 8,
            background: sc, color: '#000',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 22, fontWeight: 900,
            fontFamily: 'JetBrains Mono, monospace',
            boxShadow: `0 0 20px ${sc}55`,
          }}>{featured.initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 18, fontWeight: 800, lineHeight: 1.1 }}>{featured.name}</div>
            <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1, marginTop: 4 }}>
              <span style={{ color: sc, fontWeight: 800 }}>{STRATEGY_LABEL[featured.strategy]}</span>
              {' · '}{RANK_LABEL[featured.rank]}{featured.symbol ? ` · ${featured.symbol}` : ''}
            </div>
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: '#71717a', letterSpacing: 1.5, fontWeight: 700 }}>EQUITY · DAY</div>
          <div style={{
            fontSize: 32, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
            color: isProfit ? '#34d399' : '#fb7185', letterSpacing: -0.5,
          }}>{fmtPct(featured.pnlPct, 2)}</div>
          <div style={{ fontSize: 12, color: '#9ca3af', fontFamily: 'JetBrains Mono, monospace' }}>
            ${featured.equity.toFixed(2)} · {featured.pnl >= 0 ? '+' : '−'}${Math.abs(featured.pnl).toFixed(2)}
          </div>
        </div>
        <div style={{
          height: 96,
          border: `1px solid ${V4_LINE}`, borderRadius: 4,
          padding: 8,
          background: '#000',
        }}>
          <Sparkline
            data={featured.sparkline}
            color={isProfit ? '#34d399' : '#fb7185'}
            width={300} height={80} strokeWidth={2} fillBelow
          />
        </div>
        <div style={{
          background: V4_PANEL_HI, border: `1px solid ${V4_LINE}`, borderRadius: 4,
          padding: 10,
        }}>
          <div style={{ fontSize: 9, color: '#71717a', letterSpacing: 1.5, fontWeight: 700, marginBottom: 6 }}>
            LSTM · LAST INFERENCE
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 4 }}>
            {['up','flat','down'].map(d => {
              const probs = [featured.lstmConf, (1 - featured.lstmConf) * 0.6, (1 - featured.lstmConf) * 0.4];
              const i = ['up','flat','down'].indexOf(d);
              const p = featured.lstmDir === d ? probs[0] : probs[1 + (i % 2)];
              const c = d === 'up' ? '#34d399' : d === 'down' ? '#fb7185' : '#9ca3af';
              return (
                <div key={d} style={{
                  background: '#000', height: 36, position: 'relative',
                  border: featured.lstmDir === d ? `2px solid ${V4_BLUE}` : `1px solid ${V4_LINE}`,
                }}>
                  <div style={{
                    position: 'absolute', left: 0, bottom: 0, right: 0,
                    height: `${p * 100}%`, background: c, opacity: 0.4,
                  }} />
                  <div style={{
                    position: 'absolute', inset: 0, display: 'flex',
                    flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                    fontFamily: 'JetBrains Mono, monospace',
                  }}>
                    <span style={{ fontSize: 9, color: c, fontWeight: 800, letterSpacing: 1 }}>{d.toUpperCase()}</span>
                    <span style={{ fontSize: 13, color: '#fff', fontWeight: 800 }}>{(p * 100).toFixed(0)}%</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div style={{
          background: V4_PANEL_HI, border: `1px solid ${V4_LINE}`, borderRadius: 4,
          padding: 10,
        }}>
          <div style={{ fontSize: 9, color: '#71717a', letterSpacing: 1.5, fontWeight: 700, marginBottom: 6 }}>
            LLM · STANCE
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{
              padding: '4px 10px',
              background: featured.llmStance === 'trade' ? V4_BLUE : '#3f3f46',
              color: '#fff', fontSize: 11, fontWeight: 800, letterSpacing: 1,
              fontFamily: 'JetBrains Mono, monospace', borderRadius: 2,
            }}>{featured.llmStance.toUpperCase()}</span>
            <span style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'JetBrains Mono, monospace' }}>
              size={(featured.lstmConf * 0.4).toFixed(2)} · bias={featured.lstmDir}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

function V4MoodMeter({ account, agents }) {
  // Oscilloscope-like — average pnl velocity
  const [hist, setHist] = useState(() => Array(60).fill(0));
  useEffect(() => {
    setHist(prev => [...prev.slice(1), account.pnlPct]);
  }, [account.tick]);
  const lo = Math.min(...hist), hi = Math.max(...hist);
  const range = (hi - lo) || 1;
  const w = 240, h = 60;
  const pts = hist.map((v, i) => {
    const x = (i / (hist.length - 1)) * w;
    const y = h - ((v - lo) / range) * (h - 6) - 3;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <div style={{
      position: 'absolute', right: 16, bottom: 16,
      width: 280, padding: 10,
      background: V4_PANEL,
      border: `1px solid ${V4_BLUE}`,
      borderRadius: 6,
      boxShadow: `0 0 24px ${V4_BLUE}33`,
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6,
      }}>
        <span style={{ fontSize: 10, fontWeight: 800, letterSpacing: 1.5, color: V4_BLUE_HI }}>MARKET MOOD · 60T</span>
        <span style={{
          fontSize: 11, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
          color: account.pnlPct >= 0 ? '#34d399' : '#fb7185',
        }}>{fmtPct(account.pnlPct, 2)}</span>
      </div>
      <svg width={w} height={h} style={{ background: '#000', borderRadius: 2 }}>
        <line x1="0" y1={h/2} x2={w} y2={h/2} stroke={V4_LINE} strokeDasharray="2 4" />
        <polyline points={pts} fill="none" stroke={V4_BLUE_HI} strokeWidth="1.5" />
      </svg>
      <div style={{
        display: 'flex', justifyContent: 'space-between', marginTop: 6,
        fontSize: 9, fontFamily: 'JetBrains Mono, monospace', color: '#71717a',
      }}>
        <span>BULLS {account.profit}</span>
        <span>NEUTRAL {account.waiting}</span>
        <span>BEARS {account.loss}</span>
      </div>
    </div>
  );
}

function V4LowerThird({ fills }) {
  const lastFill = fills[0];
  if (!lastFill) return null;
  return (
    <div style={{
      position: 'absolute', left: 16, bottom: 16, width: 460,
      background: 'rgba(10,10,14,0.92)',
      backdropFilter: 'blur(8px)',
      border: `1px solid ${V4_LINE}`, borderLeft: `4px solid ${V4_BLUE}`,
      borderRadius: 4,
      padding: 12,
      display: 'flex', alignItems: 'center', gap: 12,
    }}>
      <div style={{
        width: 40, height: 40, borderRadius: 4,
        background: stratColor(lastFill.strategy), color: '#000',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 14, fontWeight: 900, fontFamily: 'JetBrains Mono, monospace',
      }}>{lastFill.symbol.slice(0,3)}</div>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 9, color: V4_BLUE_HI, letterSpacing: 1.6, fontWeight: 800 }}>
          NOW TRADING
        </div>
        <div style={{ fontSize: 16, fontWeight: 800, marginTop: 2 }}>
          {lastFill.symbol} <span style={{
            color: lastFill.side === 'buy' ? '#34d399' : '#fb7185',
            fontFamily: 'JetBrains Mono, monospace',
          }}>{lastFill.side.toUpperCase()} {lastFill.qty}</span>
        </div>
        <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'JetBrains Mono, monospace' }}>
          ${lastFill.price.toFixed(2)} · {lastFill.agentName}
        </div>
      </div>
    </div>
  );
}

function BroadcastV4({ stream }) {
  const { agents, account, fills, promotions, byStrategy } = stream;
  return (
    <div style={{
      width: 1920, height: 1080, background: V4_BG, color: '#fafafa',
      fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
      display: 'flex', flexDirection: 'column', position: 'relative',
      overflow: 'hidden',
    }}>
      <V4TopBar account={account} promotions={promotions} />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '340px 1fr 360px', minHeight: 0 }}>
        <V4Chat fills={fills} promotions={promotions} />
        <div style={{ position: 'relative', display: 'flex', flexDirection: 'column' }}>
          <V4Hero agents={agents} />
          <V4LowerThird fills={fills} />
          <V4MoodMeter account={account} agents={agents} />
        </div>
        <V4Featured agents={agents} byStrategy={byStrategy} />
      </div>
    </div>
  );
}

window.BroadcastV4 = BroadcastV4;
