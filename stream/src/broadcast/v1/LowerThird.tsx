import { FONT_MONO, RANK_LABEL, V1, stratColor } from "./tokens";
import type { V1Account, V1Promotion } from "./adapter";

/**
 * Lower-third banner — absolute, anchored 76px above the ticker. Two states:
 * promotion/demotion call-out when a promotion is fresh, or a "STORYLINE"
 * fallback summarizing the broader fund state.
 *
 * `pointerEvents: none` so it doesn't intercept hover/click on whatever it
 * floats over.
 */
export function LowerThird({
  promotions,
  account,
}: {
  promotions: V1Promotion[];
  account: V1Account;
}) {
  const latest = promotions[0];
  return (
    <div
      style={{
        position: "absolute",
        left: 32,
        right: 32,
        bottom: 76,
        height: 64,
        background: "linear-gradient(90deg, rgba(8,9,13,0.95) 0%, rgba(8,9,13,0.6) 100%)",
        borderLeft: `4px solid ${V1.AMBER}`,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        padding: "0 20px",
        gap: 16,
        pointerEvents: "none",
      }}
    >
      {latest ? (
        <>
          <div
            style={{
              padding: "6px 10px",
              background: V1.AMBER,
              color: "#000",
              fontSize: 11,
              fontWeight: 900,
              letterSpacing: 1.5,
              fontFamily: FONT_MONO,
            }}
          >
            {latest.direction === "up" ? "PROMOTION" : "DEMOTION"}
          </div>
          <div
            style={{
              width: 44,
              height: 44,
              borderRadius: 6,
              background: stratColor("lstm"),
              color: "#000",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontWeight: 900,
              fontSize: 14,
              fontFamily: FONT_MONO,
            }}
          >
            {latest.initials}
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 18, fontWeight: 800 }}>{latest.agentName}</div>
            <div
              style={{
                fontSize: 12,
                color: V1.TEXT_MUTED,
                fontFamily: FONT_MONO,
                letterSpacing: 1,
              }}
            >
              {RANK_LABEL[latest.fromRank]} → {RANK_LABEL[latest.toRank]} · {latest.reason}
            </div>
          </div>
          <div
            style={{
              fontSize: 22,
              fontFamily: FONT_MONO,
              fontWeight: 800,
              color: latest.direction === "up" ? V1.PROFIT : V1.LOSS,
            }}
          >
            {latest.direction === "up" ? "↑" : "↓"}
          </div>
        </>
      ) : (
        <>
          <div
            style={{
              padding: "6px 10px",
              background: V1.AMBER,
              color: "#000",
              fontSize: 11,
              fontWeight: 900,
              letterSpacing: 1.5,
              fontFamily: FONT_MONO,
            }}
          >
            STORYLINE
          </div>
          <div style={{ flex: 1, fontSize: 16, fontWeight: 600 }}>
            {account.profit} agents in profit · {account.trading} actively trading
          </div>
        </>
      )}
    </div>
  );
}
