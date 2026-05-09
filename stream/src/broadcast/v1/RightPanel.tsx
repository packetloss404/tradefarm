import { useState } from "react";
import { FONT_MONO, V1, stratColor } from "./tokens";
import type { V1Fill } from "./adapter";

/**
 * Right column — "PLAYS / CHAT" tab switcher. Per scope decision (V1 ships
 * with PLAYS only), the CHAT tab is rendered disabled with a "coming soon"
 * placeholder. The tab state is local; switching is instant.
 */
export function RightPanel({ fills }: { fills: V1Fill[] }) {
  const [tab, setTab] = useState<"plays" | "chat">("plays");
  return (
    <div
      style={{
        background: V1.PANEL,
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr 1fr",
          borderBottom: `1px solid ${V1.LINE}`,
        }}
      >
        <Tab
          active={tab === "plays"}
          onClick={() => setTab("plays")}
          label="PLAYS"
          sub="fills"
          dotColor={V1.AMBER}
        />
        <Tab
          active={tab === "chat"}
          onClick={() => setTab("chat")}
          label="CHAT"
          sub="coming soon"
          dotColor="#a78bfa"
          disabled
        />
      </div>
      <div style={{ flex: 1, minHeight: 0, overflow: "hidden" }}>
        {tab === "plays" ? <Plays fills={fills} /> : <ChatPlaceholder />}
      </div>
    </div>
  );
}

function Tab({
  active,
  onClick,
  label,
  sub,
  dotColor,
  disabled = false,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  sub: string;
  dotColor: string;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      style={{
        all: "unset",
        cursor: disabled && !active ? "not-allowed" : "pointer",
        padding: "12px 14px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        borderBottom: active ? `2px solid ${V1.AMBER}` : "2px solid transparent",
        background: active ? V1.PANEL_HI : "transparent",
        opacity: disabled && !active ? 0.55 : 1,
        transition: "background 0.15s",
      }}
    >
      <div>
        <div
          style={{
            fontSize: 13,
            fontWeight: 800,
            letterSpacing: 1.6,
            color: active ? V1.TEXT : V1.TEXT_MUTED,
          }}
        >
          {label}
        </div>
        <div
          style={{
            fontSize: 9,
            color: V1.TEXT_HINT,
            letterSpacing: 1.2,
            marginTop: 2,
            fontFamily: FONT_MONO,
            fontWeight: 600,
          }}
        >
          {sub}
        </div>
      </div>
      <span
        className={active ? "v1-pulse-dot" : ""}
        style={{
          width: 8,
          height: 8,
          borderRadius: 999,
          background: active ? dotColor : "#3f3f46",
          boxShadow: active ? `0 0 8px ${dotColor}` : "none",
        }}
      />
    </button>
  );
}

function Plays({ fills }: { fills: V1Fill[] }) {
  return (
    <div
      style={{
        background: V1.PANEL,
        height: "100%",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ flex: 1, overflow: "hidden", display: "flex", flexDirection: "column" }}>
        {fills.length === 0 ? (
          <div style={{ color: V1.TEXT_FAINT, padding: 16, fontSize: 11 }}>
            Waiting for fills…
          </div>
        ) : (
          fills.slice(0, 7).map((f, i) => <FillCard key={f.id} fill={f} fresh={i === 0} />)
        )}
      </div>
    </div>
  );
}

function ChatPlaceholder() {
  return (
    <div
      style={{
        height: "100%",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 8,
        padding: 24,
        textAlign: "center",
        color: V1.TEXT_FAINT,
      }}
    >
      <div
        style={{
          fontSize: 11,
          fontFamily: FONT_MONO,
          letterSpacing: 1.6,
          fontWeight: 800,
          color: V1.TEXT_MUTED,
        }}
      >
        CHAT · COMING SOON
      </div>
      <div style={{ fontSize: 11, fontFamily: FONT_MONO, color: V1.TEXT_HINT, lineHeight: 1.5 }}>
        Live viewer chat will plug in via the Twitch IRC / YouTube live-chat
        feed. Until then, switch back to PLAYS for the live fill stream.
      </div>
    </div>
  );
}

function FillCard({ fill, fresh }: { fill: V1Fill; fresh: boolean }) {
  const isBuy = fill.side === "buy";
  return (
    <div
      style={{
        borderBottom: `1px solid ${V1.LINE}`,
        padding: "10px 12px",
        background: fresh ? `linear-gradient(90deg, ${V1.AMBER}22, transparent)` : "transparent",
        display: "grid",
        gridTemplateColumns: "32px 1fr auto",
        gap: 10,
        alignItems: "center",
      }}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: 4,
          background: stratColor(fill.strategy),
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          fontSize: 11,
          fontWeight: 800,
          color: "#000",
          fontFamily: FONT_MONO,
        }}
      >
        {fill.initials}
      </div>
      <div style={{ minWidth: 0 }}>
        <div
          style={{
            fontSize: 11,
            color: V1.TEXT_DIM,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {fill.agentName}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
          <span
            style={{
              fontSize: 9,
              padding: "1px 5px",
              background: isBuy ? "#10b98133" : "#f43f5e33",
              color: isBuy ? V1.PROFIT_HI : V1.LOSS_HI,
              fontWeight: 800,
              letterSpacing: 1,
              borderRadius: 2,
              fontFamily: FONT_MONO,
            }}
          >
            {fill.side.toUpperCase()}
          </span>
          <span
            style={{
              fontSize: 11,
              fontWeight: 700,
              color: "#fff",
              fontFamily: FONT_MONO,
            }}
          >
            {fill.qty} {fill.symbol}
          </span>
          <span style={{ fontSize: 10, color: V1.TEXT_HINT, fontFamily: FONT_MONO }}>
            @ ${fill.price.toFixed(2)}
          </span>
        </div>
      </div>
      <div
        style={{
          fontSize: 9,
          color: V1.TEXT_HINT,
          letterSpacing: 0.5,
          fontFamily: FONT_MONO,
          textAlign: "right",
        }}
      >
        {new Date(fill.t).toLocaleTimeString("en-US", { hour12: false }).slice(0, 8)}
      </div>
    </div>
  );
}
