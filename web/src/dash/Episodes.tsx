// Episodes page — archive of past VODs. Featured latest, 6-week P&L
// heatmap, and a grid of cards. Each card carries a "day-shape"
// sparkline rendering the day's detected beats at scaled times +
// scores. All mocked — the episodes endpoint is net-new.

import { useTheme } from "./ThemeContext";
import { EPISODES, type Episode } from "./mockData";
import { fmtPct } from "../vod/widgets";

function DayShapeSpark({
  shape,
  width = 200,
  height = 32,
}: {
  shape: Episode["dayShape"];
  width?: number;
  height?: number;
}) {
  const { T } = useTheme();
  if (!shape || shape.length === 0) return null;
  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: "block" }}
    >
      <line x1="0" x2={width} y1={height - 1} y2={height - 1} stroke={T.border} strokeWidth="1" />
      {shape.map((b, i) => {
        const x = b.t * width;
        const h = b.score * (height - 4) + 2;
        const y = height - h;
        return (
          <rect
            key={i}
            x={x - 2}
            y={y}
            width="3"
            height={h}
            fill={`oklch(0.72 0.16 ${b.hue})`}
            opacity={0.85}
            rx="1"
          />
        );
      })}
    </svg>
  );
}

function EpisodeThumb({ ep, large }: { ep: Episode; large?: boolean }) {
  const { T } = useTheme();
  const isPositive = ep.pnlPct >= 0;
  const heroColor = isPositive ? T.ok : T.err;
  return (
    <div
      style={{
        aspectRatio: "16/9",
        borderRadius: 6,
        position: "relative",
        overflow: "hidden",
        background: `linear-gradient(135deg, oklch(0.2 0.05 ${ep.thumbHue}) 0%, ${T.bg} 100%)`,
        border: `1px solid ${T.border}`,
      }}
    >
      <svg
        viewBox="0 0 320 180"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      >
        {Array.from({ length: 5 }).map((_, i) => (
          <g key={i} transform={`translate(${60 + i * 30}, ${120 - i * 10})`}>
            <polygon
              points="0,0 26,15 0,30 -26,15"
              fill="none"
              stroke={T.accent}
              strokeOpacity="0.2"
              strokeWidth="1"
            />
          </g>
        ))}
        <polyline
          points="20,140 50,135 80,130 110,125 140,118 170,110 200,100 230,90 260,85 290,75"
          transform={`translate(0, ${isPositive ? 0 : 30})`}
          fill="none"
          stroke={heroColor}
          strokeOpacity="0.7"
          strokeWidth="2"
          strokeLinejoin="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: large ? 14 : 10,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: large ? 11 : 9,
              letterSpacing: 1.6,
              color: T.accent,
            }}
          >
            EP {String(ep.number).padStart(3, "0")}
          </span>
          {ep.status === "rendering" && (
            <span
              style={{
                fontFamily: "JetBrains Mono, monospace",
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: 1,
                padding: "2px 6px",
                borderRadius: 2,
                background: `${T.accent}22`,
                color: T.accent,
              }}
            >
              RENDERING
            </span>
          )}
        </div>
        <div
          style={{
            fontFamily: '"Helvetica Neue"',
            fontSize: large ? 22 : 14,
            fontWeight: 700,
            color: "#fff",
            lineHeight: 1.2,
            letterSpacing: -0.3,
            textShadow: "0 1px 4px rgba(0,0,0,0.7)",
          }}
        >
          {ep.title}
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          bottom: 8,
          right: 8,
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 10,
          color: "#fff",
          background: "rgba(0,0,0,0.7)",
          padding: "2px 6px",
          borderRadius: 2,
        }}
      >
        {Math.floor(ep.duration / 60)}:{String(ep.duration % 60).padStart(2, "0")}
      </div>
    </div>
  );
}

function EpisodeCard({ ep }: { ep: Episode }) {
  const { T } = useTheme();
  const isPositive = ep.pnlPct >= 0;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 14,
        display: "flex",
        flexDirection: "column",
        gap: 12,
        cursor: "pointer",
      }}
    >
      <EpisodeThumb ep={ep} />
      <div>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
          <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2 }}>
            {new Date(ep.date).toLocaleDateString("en-US", {
              weekday: "short",
              month: "short",
              day: "numeric",
            })}
          </span>
          <span
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 12,
              fontWeight: 700,
              color: isPositive ? T.ok : T.err,
            }}
          >
            {fmtPct(ep.pnlPct)}
          </span>
        </div>
        <div
          style={{
            fontFamily: '"Helvetica Neue"',
            fontSize: 13,
            fontWeight: 600,
            color: T.text,
            lineHeight: 1.35,
            marginBottom: 10,
            display: "-webkit-box",
            WebkitLineClamp: 2,
            WebkitBoxOrient: "vertical",
            overflow: "hidden",
            textOverflow: "ellipsis",
            height: 36,
          }}
        >
          {ep.title}
        </div>
        <DayShapeSpark shape={ep.dayShape} width={220} height={28} />
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 10,
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            color: T.text3,
          }}
        >
          <span>
            {ep.beats} beats · {ep.fills} fills
          </span>
          <span>{ep.views == null ? "—" : `${ep.views.toLocaleString()} views`}</span>
        </div>
      </div>
    </div>
  );
}

function KV({ label, value, color }: { label: string; value: string; color?: string }) {
  const { T } = useTheme();
  return (
    <div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.4,
          color: T.text3,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 15,
          fontWeight: 600,
          color: color || T.text,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function FeaturedEpisode({ ep }: { ep: Episode }) {
  const { T } = useTheme();
  const isPositive = ep.pnlPct >= 0;
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.borderHi}`,
        borderRadius: 12,
        padding: 24,
        display: "grid",
        gridTemplateColumns: "1.4fr 1fr",
        gap: 24,
      }}
    >
      <EpisodeThumb ep={ep} large />
      <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div>
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9,
              letterSpacing: 1.8,
              color: T.accent,
              marginBottom: 6,
            }}
          >
            FEATURED · LATEST
          </div>
          <h2
            style={{
              fontFamily: '"Helvetica Neue"',
              fontSize: 26,
              fontWeight: 700,
              color: T.text,
              margin: 0,
              letterSpacing: -0.5,
              lineHeight: 1.2,
            }}
          >
            {ep.title}
          </h2>
          <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 12, color: T.text2, marginTop: 8 }}>
            {new Date(ep.date).toLocaleDateString("en-US", {
              weekday: "long",
              month: "long",
              day: "numeric",
              year: "numeric",
            })}{" "}
            · EP {String(ep.number).padStart(3, "0")}
          </div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
          <KV label="DAY P&L" value={fmtPct(ep.pnlPct)} color={isPositive ? T.ok : T.err} />
          <KV
            label="DURATION"
            value={`${Math.floor(ep.duration / 60)}:${String(ep.duration % 60).padStart(2, "0")}`}
          />
          <KV label="BEATS" value={`${ep.beats}`} />
          <KV label="STATUS" value={ep.status} color={ep.status === "published" ? T.ok : T.accent} />
        </div>
        <div>
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9,
              letterSpacing: 1.6,
              color: T.text3,
              marginBottom: 6,
            }}
          >
            DAY SHAPE
          </div>
          <DayShapeSpark shape={ep.dayShape} width={400} height={40} />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button
            style={{
              flex: 1,
              padding: "12px",
              borderRadius: 4,
              cursor: "pointer",
              background: T.accent,
              color: "#1a1408",
              border: "none",
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 12,
              fontWeight: 700,
              letterSpacing: 0.5,
            }}
          >
            ▸ watch on youtube
          </button>
          <a
            href="#vod-studio/beats"
            style={{
              padding: "12px 16px",
              borderRadius: 4,
              cursor: "pointer",
              background: "transparent",
              color: T.text,
              border: `1px solid ${T.border}`,
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 12,
              fontWeight: 600,
              textDecoration: "none",
            }}
          >
            open beats
          </a>
        </div>
      </div>
    </div>
  );
}

function CalendarHeatmap({ episodes }: { episodes: Episode[] }) {
  const { T } = useTheme();
  const byDate: Record<string, Episode> = Object.fromEntries(episodes.map((e) => [e.date, e]));
  const today = new Date("2026-05-19");
  const cells: { date: string; ep: Episode | undefined }[] = [];
  for (let w = 5; w >= 0; w--) {
    for (let d = 0; d < 5; d++) {
      const date = new Date(today);
      date.setDate(date.getDate() - w * 7 - (4 - d));
      const iso = date.toISOString().slice(0, 10);
      cells.push({ date: iso, ep: byDate[iso] });
    }
  }
  const max = Math.max(...episodes.map((e) => Math.abs(e.pnlPct)));
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        padding: 18,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 12,
        }}
      >
        <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.6, color: T.text3 }}>
          P&L HEATMAP · LAST 6 WEEKS
        </span>
        <div
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            color: T.text2,
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}
        >
          <span>−</span>
          <div style={{ display: "flex", gap: 1 }}>
            {[0.2, 0.45, 0.7, 1].map((o) => (
              <div key={"l" + o} style={{ width: 10, height: 10, background: T.err, opacity: o }} />
            ))}
            <div style={{ width: 10, height: 10, background: T.panel3 }} />
            {[0.2, 0.45, 0.7, 1].map((o) => (
              <div key={"r" + o} style={{ width: 10, height: 10, background: T.ok, opacity: o }} />
            ))}
          </div>
          <span>+</span>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 4,
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 9,
            color: T.text3,
            paddingTop: 2,
          }}
        >
          {["Mon", "Tue", "Wed", "Thu", "Fri"].map((d) => (
            <span key={d} style={{ height: 32, lineHeight: "32px" }}>
              {d}
            </span>
          ))}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(6, 1fr)",
            gridAutoFlow: "column",
            gap: 4,
            flex: 1,
          }}
        >
          {cells.map((c) => {
            const e = c.ep;
            if (!e) {
              return (
                <div
                  key={c.date}
                  title={c.date}
                  style={{ height: 32, background: T.panel2, borderRadius: 3, opacity: 0.5 }}
                />
              );
            }
            const intensity = max === 0 ? 0 : Math.min(1, Math.abs(e.pnlPct) / max);
            const color = e.pnlPct >= 0 ? T.ok : T.err;
            return (
              <div
                key={c.date}
                title={`${c.date} · ${fmtPct(e.pnlPct)}`}
                style={{
                  height: 32,
                  background: color,
                  opacity: 0.3 + intensity * 0.7,
                  borderRadius: 3,
                  cursor: "pointer",
                  border: c.date === "2026-05-19" ? `2px solid ${T.text}` : "none",
                  position: "relative",
                }}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}

function EpisodesHeader({ episodes }: { episodes: Episode[] }) {
  const { T } = useTheme();
  const published = episodes.filter((e) => e.status === "published");
  const positive = published.filter((e) => e.pnlPct >= 0).length;
  const totalViews = published.reduce((s, e) => s + (e.views || 0), 0);
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        padding: "24px 24px 18px",
      }}
    >
      <div>
        <h1
          style={{
            fontFamily: '"Helvetica Neue"',
            fontSize: 28,
            fontWeight: 700,
            color: T.text,
            margin: 0,
            letterSpacing: -0.5,
          }}
        >
          Episodes
        </h1>
        <div style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2, marginTop: 6 }}>
          {episodes.length} episodes · {positive} green days · {(totalViews / 1000).toFixed(1)}k total views
        </div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <DummyMenu label="sort: newest" />
        <DummyMenu label="filter: all" />
      </div>
    </div>
  );
}

function DummyMenu({ label }: { label: string }) {
  const { T } = useTheme();
  return (
    <button
      style={{
        fontFamily: "JetBrains Mono, monospace",
        fontSize: 11,
        fontWeight: 600,
        padding: "8px 12px",
        borderRadius: 4,
        cursor: "pointer",
        background: T.panel,
        border: `1px solid ${T.border}`,
        color: T.text,
        display: "flex",
        alignItems: "center",
        gap: 8,
      }}
    >
      {label} <span style={{ color: T.text3 }}>▾</span>
    </button>
  );
}

export function EpisodesPage() {
  const { T } = useTheme();
  const episodes = EPISODES;
  const latest = episodes[0];
  const rest = episodes.slice(1);
  if (!latest) return null;
  return (
    <div>
      <EpisodesHeader episodes={episodes} />
      <div style={{ padding: "0 24px 24px", display: "flex", flexDirection: "column", gap: 18 }}>
        <FeaturedEpisode ep={latest} />
        <CalendarHeatmap episodes={episodes} />
        <div>
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 9,
              letterSpacing: 1.6,
              color: T.text3,
              marginBottom: 12,
            }}
          >
            ALL EPISODES
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
              gap: 16,
            }}
          >
            {rest.map((ep) => (
              <EpisodeCard key={ep.number} ep={ep} />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
