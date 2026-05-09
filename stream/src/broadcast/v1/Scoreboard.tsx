import { useAnimatedNumber, useTickPulse } from "./hooks";
import { ETClock, LiveDot, MarketBadge } from "./primitives";
import { FONT_MONO, V1, fmtPct } from "./tokens";
import type { V1Account } from "./adapter";

/**
 * Top scoreboard band. 96px tall, brand-stripe bottom border. Equity / Day P&L
 * values animate between ticks via useAnimatedNumber and pulse a text-shadow
 * for ~250ms on each tick.
 */
export function Scoreboard({ account }: { account: V1Account }) {
  const equity = useAnimatedNumber(account.totalEquity, 400);
  const pnl = useAnimatedNumber(account.pnl, 400);
  const pulse = useTickPulse(account.tick);

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "320px 1fr auto",
        alignItems: "center",
        gap: 0,
        height: 96,
        padding: "0 32px",
        background: "linear-gradient(180deg, #0c0e14 0%, #060709 100%)",
        borderBottom: `2px solid ${V1.AMBER}`,
        position: "relative",
      }}
    >
      {/* Brand block */}
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <div
          style={{
            width: 52,
            height: 52,
            borderRadius: 6,
            background: V1.AMBER,
            color: "#000",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontWeight: 900,
            fontSize: 26,
            fontFamily: FONT_MONO,
            letterSpacing: -1,
            boxShadow: "0 0 24px rgba(251,191,36,0.35)",
          }}
        >
          TF
        </div>
        <div>
          <div style={{ fontSize: 22, fontWeight: 800, letterSpacing: 0.5 }}>TRADEFARM</div>
          <div
            style={{
              fontSize: 11,
              color: V1.TEXT_MUTED,
              letterSpacing: 2.4,
              fontWeight: 600,
            }}
          >
            100-AGENT LIVE BROADCAST
          </div>
        </div>
      </div>

      {/* Score cells */}
      <div style={{ display: "flex", alignItems: "center", gap: 32, justifyContent: "center" }}>
        <ScoreCell
          label="FUND EQUITY"
          value={"$" + equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}
          pulse={pulse}
        />
        <Divider />
        <ScoreCell
          label="DAY P&L"
          value={
            (pnl >= 0 ? "+" : "−") +
            "$" +
            Math.abs(pnl).toLocaleString("en-US", { maximumFractionDigits: 0 })
          }
          color={pnl >= 0 ? V1.PROFIT : V1.LOSS}
          pulse={pulse}
        />
        <Divider />
        <ScoreCell
          label="P&L %"
          value={fmtPct(account.pnlPct, 2)}
          color={account.pnlPct >= 0 ? V1.PROFIT : V1.LOSS}
        />
        <Divider />
        <ScoreCell label="PROFITABLE" value={`${account.profit}/100`} color={V1.AMBER} />
      </div>

      {/* Right block */}
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <MarketBadge />
        <div
          style={{
            fontSize: 28,
            fontFamily: FONT_MONO,
            fontWeight: 700,
            color: "#e5e7eb",
            letterSpacing: 1,
          }}
        >
          <ETClock />
        </div>
        <span
          style={{
            fontSize: 10,
            color: V1.TEXT_HINT,
            letterSpacing: 1.5,
            fontWeight: 700,
          }}
        >
          ET
        </span>
        <LiveDot />
      </div>
    </div>
  );
}

function Divider() {
  return <div style={{ width: 1, height: 56, background: V1.LINE }} />;
}

function ScoreCell({
  label,
  value,
  color = V1.TEXT,
  pulse,
}: {
  label: string;
  value: string;
  color?: string;
  pulse?: boolean;
}) {
  return (
    <div style={{ textAlign: "center", minWidth: 130 }}>
      <div
        style={{
          fontSize: 9,
          color: V1.TEXT_MUTED,
          letterSpacing: 2,
          fontWeight: 700,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: 30,
          fontWeight: 800,
          color,
          fontFamily: FONT_MONO,
          letterSpacing: -0.5,
          textShadow: pulse ? `0 0 12px ${color}55` : "none",
          transition: "text-shadow 0.25s",
        }}
      >
        {value}
      </div>
    </div>
  );
}
