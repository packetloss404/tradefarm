// V1 — Sports Broadcast
// 1920×1080 layout: top scoreboard, left leaderboard, center race lanes + grid,
// right plays-of-the-game feed, lower third banner, bottom ticker.

const V1_AMBER = '#fbbf24';
const V1_BG = '#08090d';
const V1_PANEL = '#10131a';
const V1_PANEL_HI = '#171b25';
const V1_LINE = '#22262f';

function V1Scoreboard({ account }) {
  const equity = useAnimatedNumber(account.totalEquity, 400);
  const pnl = useAnimatedNumber(account.pnl, 400);
  const pulse = useTickPulse([account.tick]);
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '320px 1fr auto',
      alignItems: 'center', gap: 0,
      height: 96, padding: '0 32px',
      background: 'linear-gradient(180deg, #0c0e14 0%, #060709 100%)',
      borderBottom: `2px solid ${V1_AMBER}`,
      position: 'relative',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
        <div style={{
          width: 52, height: 52, borderRadius: 6,
          background: V1_AMBER, color: '#000',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontWeight: 900, fontSize: 26, fontFamily: 'JetBrains Mono, monospace',
          letterSpacing: -1, boxShadow: '0 0 24px rgba(251,191,36,0.35)',
        }}>TF</div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 0.5 }}>TRADEFARM</div>
          <div style={{ fontSize: 11, color: '#9ca3af', letterSpacing: 2.4, fontWeight: 600 }}>100-AGENT LIVE BROADCAST</div>
        </div>
      </div>

      {/* Massive scoreboard */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 32, justifyContent: 'center' }}>
        <ScoreCell label="FUND EQUITY" value={'$' + equity.toLocaleString('en-US', { maximumFractionDigits: 0 })} pulse={pulse} />
        <div style={{ width: 1, height: 56, background: V1_LINE }} />
        <ScoreCell
          label="DAY P&L"
          value={(pnl >= 0 ? '+' : '−') + '$' + Math.abs(pnl).toLocaleString('en-US', { maximumFractionDigits: 0 })}
          color={pnl >= 0 ? '#10b981' : '#f43f5e'}
          pulse={pulse}
        />
        <div style={{ width: 1, height: 56, background: V1_LINE }} />
        <ScoreCell
          label="P&L %"
          value={fmtPct(account.pnlPct, 2)}
          color={account.pnlPct >= 0 ? '#10b981' : '#f43f5e'}
        />
        <div style={{ width: 1, height: 56, background: V1_LINE }} />
        <ScoreCell label="PROFITABLE" value={`${account.profit}/100`} color={V1_AMBER} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <MarketBadge />
        <div style={{ fontSize: 28, fontFamily: 'JetBrains Mono, monospace', fontWeight: 700, color: '#e5e7eb', letterSpacing: 1 }}>
          <ETClock />
        </div>
        <span style={{ fontSize: 10, color: '#71717a', letterSpacing: 1.5, fontWeight: 700 }}>ET</span>
        <LiveDot />
      </div>
    </div>
  );
}

function ScoreCell({ label, value, color = '#fafafa', pulse }) {
  return (
    <div style={{ textAlign: 'center', minWidth: 130 }}>
      <div style={{ fontSize: 9, color: '#9ca3af', letterSpacing: 2, fontWeight: 700, marginBottom: 4 }}>{label}</div>
      <div style={{
        fontSize: 30, fontWeight: 800, color, fontFamily: 'JetBrains Mono, monospace',
        letterSpacing: -0.5,
        textShadow: pulse ? `0 0 12px ${color}55` : 'none',
        transition: 'text-shadow 0.3s',
      }}>{value}</div>
    </div>
  );
}

function V1Leaderboard({ agents }) {
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 12), [agents]);
  return (
    <div style={{ background: V1_PANEL, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        padding: '12px 16px', borderBottom: `1px solid ${V1_LINE}`,
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      }}>
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.6 }}>TOP 12 · ALPHA</div>
        <span style={{
          fontSize: 9, padding: '2px 6px', background: V1_AMBER, color: '#000',
          fontWeight: 800, letterSpacing: 1, borderRadius: 2,
        }}>LEADERS</span>
      </div>
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {top.map((a, i) => (
          <V1LeaderRow key={a.id} agent={a} rank={i + 1} />
        ))}
      </div>
    </div>
  );
}

function V1LeaderRow({ agent, rank }) {
  const pnlColr = agent.pnl >= 0 ? '#10b981' : '#f43f5e';
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '24px 1fr 80px 56px',
      alignItems: 'center', gap: 8,
      padding: '8px 12px',
      borderBottom: `1px solid ${V1_LINE}`,
      background: rank <= 3 ? 'linear-gradient(90deg, rgba(251,191,36,0.08), transparent)' : 'transparent',
    }}>
      <div style={{
        fontSize: 14, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
        color: rank === 1 ? V1_AMBER : rank <= 3 ? '#fde68a' : '#9ca3af',
        textAlign: 'center',
      }}>{rank}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <div style={{
            width: 18, height: 18, borderRadius: 3,
            background: stratColor(agent.strategy),
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 9, fontWeight: 800, color: '#000',
            fontFamily: 'JetBrains Mono, monospace',
          }}>{agent.initials}</div>
          <div style={{ fontSize: 12, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {agent.name}
          </div>
        </div>
        <div style={{ fontSize: 9, color: '#71717a', letterSpacing: 1, marginTop: 1, fontFamily: 'JetBrains Mono, monospace' }}>
          {STRATEGY_LABEL[agent.strategy]} · {RANK_LABEL[agent.rank]} {agent.symbol ? `· ${agent.symbol}` : ''}
        </div>
      </div>
      <Sparkline data={agent.sparkline.slice(-20)} color={pnlColr} width={70} height={22} strokeWidth={1.5} fillBelow />
      <div style={{
        fontSize: 13, fontWeight: 800, color: pnlColr, textAlign: 'right',
        fontFamily: 'JetBrains Mono, monospace',
      }}>{fmtPct(agent.pnlPct, 1)}</div>
    </div>
  );
}

function V1RaceLanes({ agents }) {
  const top = useMemo(() => [...agents].sort((a, b) => b.pnl - a.pnl).slice(0, 6), [agents]);
  // map pnl percentile of full set into 0..1 lane progress
  const allPnls = agents.map(a => a.pnl).sort((x, y) => x - y);
  const lo = allPnls[0], hi = allPnls[allPnls.length - 1];
  const range = hi - lo || 1;
  return (
    <div style={{ background: V1_PANEL, padding: 16, borderBottom: `1px solid ${V1_LINE}` }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontSize: 16, fontWeight: 800, letterSpacing: 2 }}>
          RACE TO ALPHA <span style={{ color: V1_AMBER, fontSize: 12 }}>· LIVE</span>
        </div>
        <div style={{ fontSize: 10, color: '#71717a', letterSpacing: 1.5, fontFamily: 'JetBrains Mono, monospace' }}>
          POSITION · 24h P&L NORMALIZED
        </div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {top.map((a, i) => {
          const t = (a.pnl - lo) / range;
          return <V1Lane key={a.id} agent={a} progress={t} laneNo={i + 1} />;
        })}
      </div>
    </div>
  );
}

function V1Lane({ agent, progress, laneNo }) {
  const pnlColr = agent.pnl >= 0 ? '#10b981' : '#f43f5e';
  const t = useAnimatedNumber(progress, 600);
  return (
    <div style={{
      position: 'relative',
      height: 36,
      background: 'repeating-linear-gradient(90deg, transparent 0 36px, rgba(255,255,255,0.025) 36px 38px)',
      borderRadius: 4,
      border: `1px solid ${V1_LINE}`,
      overflow: 'hidden',
    }}>
      <div style={{
        position: 'absolute', left: 0, top: 0, bottom: 0,
        width: `${Math.max(2, t * 100)}%`,
        background: `linear-gradient(90deg, ${stratColorDim(agent.strategy)} 0%, ${stratColor(agent.strategy)} 100%)`,
        opacity: 0.45,
      }} />
      <div style={{ position: 'absolute', right: 8, top: 0, bottom: 0, width: 12, background: 'repeating-linear-gradient(0deg, #fff 0 6px, #000 6px 12px)', opacity: 0.7 }} />
      <div style={{
        position: 'absolute', left: `calc(${t * 100}% - 18px)`, top: 4, bottom: 4,
        width: 32, borderRadius: 4,
        background: stratColor(agent.strategy),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 900, color: '#000',
        fontFamily: 'JetBrains Mono, monospace',
        boxShadow: `0 0 10px ${stratColor(agent.strategy)}`,
        transition: 'left 0.3s ease-out',
      }}>{agent.initials}</div>
      <div style={{
        position: 'absolute', left: 8, top: 0, bottom: 0,
        display: 'flex', alignItems: 'center',
        fontSize: 10, fontWeight: 800, color: '#fff', letterSpacing: 1.5,
        fontFamily: 'JetBrains Mono, monospace',
        textShadow: '0 0 4px #000',
      }}>L{laneNo}</div>
      <div style={{
        position: 'absolute', right: 28, top: 0, bottom: 0,
        display: 'flex', alignItems: 'center', gap: 8,
        fontSize: 11, fontWeight: 700, color: pnlColr,
        fontFamily: 'JetBrains Mono, monospace',
        textShadow: '0 0 6px rgba(0,0,0,0.8)',
      }}>
        <span style={{ color: '#e5e7eb' }}>{agent.name}</span>
        <span>{fmtPct(agent.pnlPct, 1)}</span>
      </div>
    </div>
  );
}

function V1Grid({ agents }) {
  // 32 active agents — pick top trading or unique
  const grid = useMemo(() => {
    const ranked = [...agents].sort((a, b) => Math.abs(b.pnl) - Math.abs(a.pnl));
    return ranked.slice(0, 64);
  }, [agents]);
  return (
    <div style={{ flex: 1, padding: 16, overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', marginBottom: 10 }}>
        <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: 2 }}>
          THE FARM <span style={{ color: '#71717a', fontWeight: 600 }}>· 64 ACTIVE</span>
        </div>
        <div style={{ display: 'flex', gap: 12, fontSize: 10, fontFamily: 'JetBrains Mono, monospace', color: '#9ca3af' }}>
          <LegendChip color={stratColor('momentum')} label="MOM" />
          <LegendChip color={stratColor('lstm')} label="LSTM" />
          <LegendChip color={stratColor('llm')} label="LSTM+LLM" />
        </div>
      </div>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)',
        gridAutoRows: '46px', gap: 4,
      }}>
        {grid.map(a => <V1MiniCard key={a.id} agent={a} />)}
      </div>
    </div>
  );
}

function LegendChip({ color, label }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
      <span style={{ width: 8, height: 8, borderRadius: 2, background: color }} />
      <span style={{ letterSpacing: 1.5 }}>{label}</span>
    </span>
  );
}

function V1MiniCard({ agent }) {
  const pnlColr = agent.pnl >= 0 ? '#10b981' : '#f43f5e';
  return (
    <div style={{
      background: V1_PANEL_HI,
      borderLeft: `3px solid ${stratColor(agent.strategy)}`,
      borderRadius: 2,
      padding: '4px 6px',
      display: 'flex', flexDirection: 'column', justifyContent: 'space-between',
      overflow: 'hidden',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
        <span style={{
          fontSize: 9, fontWeight: 800, fontFamily: 'JetBrains Mono, monospace',
          color: '#9ca3af', minWidth: 18,
        }}>#{agent.id.toString().padStart(3, '0')}</span>
        <span style={{ fontSize: 9, color: '#d4d4d8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{agent.name}</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <Sparkline data={agent.sparkline.slice(-12)} color={pnlColr} width={50} height={14} strokeWidth={1} />
        <span style={{ fontSize: 10, fontWeight: 800, color: pnlColr, fontFamily: 'JetBrains Mono, monospace' }}>
          {fmtPct(agent.pnlPct, 1)}
        </span>
      </div>
    </div>
  );
}

// Streamer chat — simulated viewer messages, with reactions to fills/promotions.
const V1_CHATTERS = [
  { name: 'tape_reader_99', color: '#fbbf24', badges: ['SUB'] },
  { name: 'pyx_holder', color: '#22d3ee', badges: ['VIP'] },
  { name: 'midcurve_mike', color: '#a78bfa', badges: [] },
  { name: 'queen_of_carry', color: '#f472b6', badges: ['SUB','MOD'] },
  { name: 'lstm_skeptic', color: '#34d399', badges: [] },
  { name: 'theta_gang_42', color: '#fb923c', badges: ['SUB'] },
  { name: 'liquidity_dad', color: '#60a5fa', badges: ['MOD'] },
  { name: 'volatility_vince', color: '#facc15', badges: [] },
  { name: 'ada_in_drawdown', color: '#fbcfe8', badges: ['SUB'] },
  { name: 'bagholdr_supreme', color: '#86efac', badges: [] },
  { name: 'principal_hopium', color: '#c4b5fd', badges: ['SUB'] },
  { name: 'momo_maximalist', color: '#fda4af', badges: [] },
  { name: 'farm_to_table', color: '#5eead4', badges: ['VIP'] },
  { name: 'risk_off_rita', color: '#fde68a', badges: [] },
];
const V1_AMBIENT = [
  'momentum eating today fr',
  'who pumped MOM this morning',
  'lstm_v1 absolutely cooking 🔥',
  'BREAKING: principal_hopium pumping LSTM again',
  'waiting room is half the field rip',
  'when is the next promotion happening',
  'top 5 agents are all LSTM+LLM nuts',
  'is the LLM cheating again',
  'someone tell intern #047 to stop averaging down',
  'I had Tickbelinda in my fantasy farm 😭',
  'green dust everywhere',
  'agent #003 to the moon 🚀',
  'whoever sized that AAPL fill thank u',
  'paper trades only, not financial advice',
  'JR class is cooking SR class today',
  'buy the dip fade the rip',
  'MOM/LSTM/LLM pick em',
  'imagine being demoted on a green day',
  'this is better than mlb gamecast',
  'tradefarm > coffeezilla',
  'KEKW the carry desk',
  'no posted size is real size',
  'tape is choppy today',
  'when does intern grad to junior tho',
  'where is my agent at',
  'first time watching, what are we doing',
  'farm equity ATH lets gooo',
  'F in chat for the demoted',
  'someone sub principal_hopium plz',
  'pog promotion incoming',
];

function makeChatter() {
  return V1_CHATTERS[Math.floor(Math.random() * V1_CHATTERS.length)];
}

function useStreamerChat({ fills, promotions }) {
  const [messages, setMessages] = useState(() => {
    return Array.from({ length: 12 }).map((_, i) => ({
      id: 'seed-' + i,
      kind: 'chat',
      user: makeChatter(),
      text: V1_AMBIENT[Math.floor(Math.random() * V1_AMBIENT.length)],
      t: Date.now() - (12 - i) * 1000,
    }));
  });

  // Ambient chatter
  useEffect(() => {
    const id = setInterval(() => {
      const count = 1 + Math.floor(Math.random() * 3); // burst of 1-3
      const fresh = [];
      for (let i = 0; i < count; i++) {
        fresh.push({
          id: 'a-' + Math.random().toString(36).slice(2, 9) + Date.now(),
          kind: 'chat',
          user: makeChatter(),
          text: V1_AMBIENT[Math.floor(Math.random() * V1_AMBIENT.length)],
          t: Date.now(),
        });
      }
      setMessages(prev => [...prev, ...fresh].slice(-50));
    }, 1100);
    return () => clearInterval(id);
  }, []);

  // React to fills (sample, not every one)
  const lastFillRef = useRef(null);
  useEffect(() => {
    const f = fills[0];
    if (!f || f.id === lastFillRef.current) return;
    lastFillRef.current = f.id;
    if (Math.random() < 0.55) {
      const rxns = [
        `${f.agentName.split(' ')[0]} sending it 🚀`,
        `${f.symbol} ${f.side} ${f.qty}, bold`,
        `pog ${f.symbol}`,
        `${f.side === 'buy' ? 'long' : 'short'} ${f.symbol} let it cook`,
        `that's a chunky ${f.symbol} ticket`,
        `${f.agentName.split(' ')[0]} cooking again`,
      ];
      setMessages(prev => [...prev, {
        id: 'r-' + f.id,
        kind: 'chat',
        user: makeChatter(),
        text: rxns[Math.floor(Math.random() * rxns.length)],
        t: Date.now(),
      }].slice(-50));
    }
  }, [fills]);

  // System messages for promotions
  const lastPromoRef = useRef(null);
  useEffect(() => {
    const p = promotions[0];
    if (!p || p.id === lastPromoRef.current) return;
    lastPromoRef.current = p.id;
    setMessages(prev => [...prev, {
      id: 'sys-' + p.id,
      kind: 'system',
      promo: p,
      t: Date.now(),
    }].slice(-50));
  }, [promotions]);

  return messages;
}

function V1RightPanel({ fills, promotions }) {
  const [tab, setTab] = useState('plays');
  return (
    <div style={{ background: V1_PANEL, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{
        display: 'grid', gridTemplateColumns: '1fr 1fr',
        borderBottom: `1px solid ${V1_LINE}`,
      }}>
        <V1Tab active={tab === 'plays'} onClick={() => setTab('plays')} label="PLAYS" sub="fills" dotColor={V1_AMBER} />
        <V1Tab active={tab === 'chat'} onClick={() => setTab('chat')} label="CHAT" sub="live · 12.4K" dotColor="#a78bfa" />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
        {tab === 'plays' ? <V1Plays fills={fills} /> : <V1Chat fills={fills} promotions={promotions} />}
      </div>
    </div>
  );
}

function V1Tab({ active, onClick, label, sub, dotColor }) {
  return (
    <button onClick={onClick} style={{
      all: 'unset', cursor: 'pointer',
      padding: '12px 14px',
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      borderBottom: active ? `2px solid ${V1_AMBER}` : '2px solid transparent',
      background: active ? V1_PANEL_HI : 'transparent',
      transition: 'background 0.15s',
    }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 800, letterSpacing: 1.6, color: active ? '#fafafa' : '#9ca3af' }}>{label}</div>
        <div style={{ fontSize: 9, color: '#71717a', letterSpacing: 1.2, marginTop: 2, fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>
          {sub}
        </div>
      </div>
      <span className={active ? 'pulse-dot' : ''} style={{
        width: 8, height: 8, borderRadius: 999,
        background: active ? dotColor : '#3f3f46',
        boxShadow: active ? `0 0 8px ${dotColor}` : 'none',
      }} />
    </button>
  );
}

function V1Plays({ fills }) {
  return (
    <div style={{ background: V1_PANEL, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {fills.slice(0, 7).map((f, i) => (
          <V1FillCard key={f.id} fill={f} fresh={i === 0} />
        ))}
        {fills.length === 0 && <div style={{ color: '#52525b', padding: 16, fontSize: 11 }}>Waiting for fills…</div>}
      </div>
    </div>
  );
}

function V1Chat({ fills, promotions }) {
  const messages = useStreamerChat({ fills, promotions });
  const scrollRef = useRef(null);
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages]);
  return (
    <div style={{ background: V1_PANEL, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div ref={scrollRef} style={{
        flex: 1, overflow: 'hidden',
        padding: '6px 0',
        display: 'flex', flexDirection: 'column',
      }}>
        {messages.slice(-22).map((m, i, arr) => (
          <V1ChatRow key={m.id} msg={m} fresh={i === arr.length - 1} />
        ))}
      </div>
      <div style={{
        padding: '8px 12px', borderTop: `1px solid ${V1_LINE}`,
        background: '#0a0c12',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        <span style={{
          flex: 1, fontSize: 11, color: '#71717a',
          padding: '7px 10px', background: '#000',
          border: `1px solid ${V1_LINE}`, borderRadius: 3,
          fontFamily: 'JetBrains Mono, monospace',
        }}>
          Send a message <span className="cursor-blink" style={{ color: V1_AMBER }}>▌</span>
        </span>
        <span style={{
          padding: '7px 12px', background: V1_AMBER, color: '#000',
          fontSize: 11, fontWeight: 800, letterSpacing: 1, borderRadius: 3,
          fontFamily: 'JetBrains Mono, monospace',
        }}>CHAT</span>
      </div>
    </div>
  );
}

function V1ChatRow({ msg, fresh }) {
  if (msg.kind === 'system') {
    const p = msg.promo;
    return (
      <div style={{
        padding: '6px 12px', display: 'flex', gap: 8, alignItems: 'flex-start',
        background: `linear-gradient(90deg, ${V1_AMBER}22, transparent)`,
        borderLeft: `3px solid ${V1_AMBER}`,
        marginBottom: 1,
      }}>
        <span style={{ fontSize: 12, color: V1_AMBER, fontWeight: 900, fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
          {p.direction === 'up' ? '↑' : '↓'}
        </span>
        <div style={{ fontSize: 11, color: '#fde68a', lineHeight: 1.4, flex: 1 }}>
          <span style={{ fontWeight: 800, letterSpacing: 1, fontFamily: 'JetBrains Mono, monospace' }}>
            {p.direction === 'up' ? 'PROMOTION' : 'DEMOTION'}
          </span>
          <span style={{ color: '#fafafa' }}> · {p.agentName}</span>
          <span style={{ color: '#a1a1aa' }}> {RANK_LABEL[p.fromRank]}→{RANK_LABEL[p.toRank]}</span>
          <span style={{ color: '#71717a' }}> · {p.reason}</span>
        </div>
      </div>
    );
  }
  return (
    <div style={{
      padding: '3px 12px', display: 'flex', gap: 5, alignItems: 'baseline',
      lineHeight: 1.45,
      background: fresh ? 'rgba(251,191,36,0.04)' : 'transparent',
      transition: 'background 0.4s',
    }}>
      {msg.user.badges.map(b => (
        <span key={b} style={{
          display: 'inline-block',
          fontSize: 8, padding: '1px 4px',
          background: b === 'MOD' ? '#10b981' : b === 'VIP' ? '#ec4899' : V1_AMBER,
          color: '#000', fontWeight: 800, letterSpacing: 0.6,
          fontFamily: 'JetBrains Mono, monospace',
          borderRadius: 2, transform: 'translateY(-1px)',
        }}>{b}</span>
      ))}
      <span style={{
        fontSize: 12, fontWeight: 800, color: msg.user.color,
        fontFamily: 'JetBrains Mono, monospace',
      }}>{msg.user.name}</span>
      <span style={{ color: '#52525b' }}>:</span>
      <span style={{ fontSize: 12, color: '#e5e7eb', flex: 1, wordBreak: 'break-word' }}>{msg.text}</span>
    </div>
  );
}

function V1FillCard({ fill, fresh }) {
  const isBuy = fill.side === 'buy';
  return (
    <div style={{
      borderBottom: `1px solid ${V1_LINE}`,
      padding: '10px 12px',
      background: fresh ? `linear-gradient(90deg, ${V1_AMBER}22, transparent)` : 'transparent',
      display: 'grid', gridTemplateColumns: '32px 1fr auto', gap: 10,
      alignItems: 'center',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 4,
        background: stratColor(fill.strategy),
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        fontSize: 11, fontWeight: 800, color: '#000',
        fontFamily: 'JetBrains Mono, monospace',
      }}>{fill.initials}</div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 11, color: '#d4d4d8', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {fill.agentName}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 2 }}>
          <span style={{
            fontSize: 9, padding: '1px 5px',
            background: isBuy ? '#10b98133' : '#f43f5e33',
            color: isBuy ? '#34d399' : '#fb7185',
            fontWeight: 800, letterSpacing: 1, borderRadius: 2,
            fontFamily: 'JetBrains Mono, monospace',
          }}>{fill.side.toUpperCase()}</span>
          <span style={{ fontSize: 11, fontWeight: 700, color: '#fff', fontFamily: 'JetBrains Mono, monospace' }}>
            {fill.qty} {fill.symbol}
          </span>
          <span style={{ fontSize: 10, color: '#71717a', fontFamily: 'JetBrains Mono, monospace' }}>
            @ ${fill.price.toFixed(2)}
          </span>
        </div>
      </div>
      <div style={{
        fontSize: 9, color: '#71717a', letterSpacing: 0.5,
        fontFamily: 'JetBrains Mono, monospace', textAlign: 'right',
      }}>
        {new Date(fill.t).toLocaleTimeString('en-US', { hour12: false }).slice(0, 8)}
      </div>
    </div>
  );
}

function V1LowerThird({ promotions, account }) {
  const latest = promotions[0];
  return (
    <div style={{
      position: 'absolute', left: 32, right: 32, bottom: 76, height: 64,
      background: 'linear-gradient(90deg, rgba(8,9,13,0.95) 0%, rgba(8,9,13,0.6) 100%)',
      borderLeft: `4px solid ${V1_AMBER}`,
      backdropFilter: 'blur(8px)',
      display: 'flex', alignItems: 'center', padding: '0 20px', gap: 16,
      pointerEvents: 'none',
    }}>
      {latest ? (
        <>
          <div style={{
            padding: '6px 10px', background: V1_AMBER, color: '#000',
            fontSize: 11, fontWeight: 900, letterSpacing: 1.5,
            fontFamily: 'JetBrains Mono, monospace',
          }}>{latest.direction === 'up' ? 'PROMOTION' : 'DEMOTION'}</div>
          <div style={{
            width: 44, height: 44, borderRadius: 6,
            background: stratColor('lstm'), color: '#000',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontWeight: 900, fontSize: 14, fontFamily: 'JetBrains Mono, monospace',
          }}>{latest.initials}</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{latest.agentName}</div>
            <div style={{ fontSize: 12, color: '#9ca3af', fontFamily: 'JetBrains Mono, monospace', letterSpacing: 1 }}>
              {RANK_LABEL[latest.fromRank]} → {RANK_LABEL[latest.toRank]} · {latest.reason}
            </div>
          </div>
          <div style={{ fontSize: 22, fontFamily: 'JetBrains Mono, monospace', fontWeight: 800, color: latest.direction === 'up' ? '#10b981' : '#f43f5e' }}>
            {latest.direction === 'up' ? '↑' : '↓'}
          </div>
        </>
      ) : (
        <>
          <div style={{
            padding: '6px 10px', background: V1_AMBER, color: '#000',
            fontSize: 11, fontWeight: 900, letterSpacing: 1.5,
            fontFamily: 'JetBrains Mono, monospace',
          }}>STORYLINE</div>
          <div style={{ flex: 1, fontSize: 16, fontWeight: 600 }}>
            {account.profit} agents in profit · {account.trading} actively trading
          </div>
        </>
      )}
    </div>
  );
}

function V1Ticker({ fills, promotions }) {
  const items = useMemo(() => {
    const f = fills.slice(0, 12).map(x => ({
      type: 'fill', key: x.id,
      text: `${x.symbol} · ${x.side.toUpperCase()} ${x.qty}@$${x.price.toFixed(2)} · ${x.agentName}`,
    }));
    const p = promotions.slice(0, 5).map(x => ({
      type: 'promo', key: x.id,
      text: `${x.direction === 'up' ? '↑ PROMOTED' : '↓ DEMOTED'} ${x.agentName} → ${RANK_LABEL[x.toRank]} (${x.reason})`,
    }));
    return [...p, ...f];
  }, [fills, promotions]);

  return (
    <div style={{
      height: 60, background: '#000', borderTop: `2px solid ${V1_AMBER}`,
      display: 'flex', alignItems: 'stretch', overflow: 'hidden',
    }}>
      <div style={{
        background: V1_AMBER, color: '#000',
        padding: '0 18px', display: 'flex', alignItems: 'center',
        fontSize: 14, fontWeight: 900, letterSpacing: 2,
        fontFamily: 'JetBrains Mono, monospace',
      }}>FARMLINE</div>
      <div style={{ flex: 1, overflow: 'hidden', position: 'relative' }}>
        <div className="v1-marquee" style={{
          position: 'absolute', whiteSpace: 'nowrap',
          display: 'flex', alignItems: 'center', height: '100%',
          fontFamily: 'JetBrains Mono, monospace', fontSize: 14,
        }}>
          {[...items, ...items].map((it, i) => (
            <span key={i} style={{ padding: '0 24px', color: it.type === 'promo' ? V1_AMBER : '#e5e7eb' }}>
              <span style={{ color: '#52525b', marginRight: 8 }}>●</span>
              {it.text}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

function BroadcastV1({ stream }) {
  const { agents, account, fills, promotions } = stream;
  return (
    <div style={{
      width: 1920, height: 1080, background: V1_BG, color: '#fafafa',
      fontFamily: 'Helvetica Neue, Helvetica, Arial, sans-serif',
      display: 'flex', flexDirection: 'column', position: 'relative',
      overflow: 'hidden',
    }}>
      <V1Scoreboard account={account} />
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '380px 1fr 360px', minHeight: 0 }}>
        <V1Leaderboard agents={agents} />
        <div style={{ display: 'flex', flexDirection: 'column', minHeight: 0, borderLeft: `1px solid ${V1_LINE}`, borderRight: `1px solid ${V1_LINE}` }}>
          <V1RaceLanes agents={agents} />
          <V1Grid agents={agents} />
        </div>
        <V1RightPanel fills={fills} promotions={promotions} />
      </div>
      <V1LowerThird promotions={promotions} account={account} />
      <V1Ticker fills={fills} promotions={promotions} />
    </div>
  );
}

window.BroadcastV1 = BroadcastV1;
