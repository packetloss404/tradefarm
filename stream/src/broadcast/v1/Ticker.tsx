import { useMemo } from "react";
import { FONT_MONO, RANK_LABEL, V1 } from "./tokens";
import type { V1Fill, V1Promotion } from "./adapter";

type Item = { type: "promo" | "fill"; key: string; text: string };

/**
 * FARMLINE ticker. 60px tall band along the bottom; amber bug on the left,
 * marquee on the right. Items: promotions first (up to 5), then fills (up to
 * 12). Marquee animation is in `index.css` (`v1-marquee` keyframes).
 */
export function Ticker({
  fills,
  promotions,
}: {
  fills: V1Fill[];
  promotions: V1Promotion[];
}) {
  const items = useMemo<Item[]>(() => {
    const f = fills.slice(0, 12).map<Item>((x) => ({
      type: "fill",
      key: x.id,
      text: `${x.symbol} · ${x.side.toUpperCase()} ${x.qty}@$${x.price.toFixed(2)} · ${x.agentName}`,
    }));
    const p = promotions.slice(0, 5).map<Item>((x) => ({
      type: "promo",
      key: x.id,
      text: `${x.direction === "up" ? "↑ PROMOTED" : "↓ DEMOTED"} ${x.agentName} → ${RANK_LABEL[x.toRank]} (${x.reason})`,
    }));
    return [...p, ...f];
  }, [fills, promotions]);

  return (
    <div
      style={{
        height: 60,
        background: "#000",
        borderTop: `2px solid ${V1.AMBER}`,
        display: "flex",
        alignItems: "stretch",
        overflow: "hidden",
      }}
    >
      <div
        style={{
          background: V1.AMBER,
          color: "#000",
          padding: "0 18px",
          display: "flex",
          alignItems: "center",
          fontSize: 14,
          fontWeight: 900,
          letterSpacing: 2,
          fontFamily: FONT_MONO,
        }}
      >
        FARMLINE
      </div>
      <div style={{ flex: 1, overflow: "hidden", position: "relative" }}>
        <div
          className="v1-marquee"
          style={{
            position: "absolute",
            whiteSpace: "nowrap",
            display: "flex",
            alignItems: "center",
            height: "100%",
            fontFamily: FONT_MONO,
            fontSize: 14,
          }}
        >
          {items.length === 0 ? (
            <span style={{ padding: "0 24px", color: V1.TEXT_FAINT }}>
              FARMLINE — waiting for the first fill…
            </span>
          ) : (
            [...items, ...items].map((it, i) => (
              <span
                key={`${it.key}-${i}`}
                style={{
                  padding: "0 24px",
                  color: it.type === "promo" ? V1.AMBER : "#e5e7eb",
                }}
              >
                <span style={{ color: V1.TEXT_FAINT, marginRight: 8 }}>●</span>
                {it.text}
              </span>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
