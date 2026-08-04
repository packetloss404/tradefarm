// Episode page — finished VOD card. Thumbnail, editable title and
// description, auto chapters, tags, schedule, upload strip.
// Operator's "review before publish" view.
//
// The preview area + download button used to be all-mock. They now
// read live render output from out/sessions/<id>/ via the
// `/vod/{session_id}/reel.mp4` and `/vod/{session_id}/thumb.jpg`
// backend endpoints. When no rendered session exists (the common case
// before the operator has run a render), the page falls back to the
// static SVG thumbnail so the layout is still demoable.

import { useEffect, useState } from "react";
import type { CSSProperties, ReactNode } from "react";
import { T } from "./tokens";
import { fmtInt, fmtPct } from "./widgets";
import type { VodMock } from "./useVodMock";

// Backend response shape — must stay in sync with
// `src/tradefarm/api/vod.list_sessions`.
type VodSession = {
  session_id: string;
  date: number;
  has_reel: boolean;
  has_thumb: boolean;
  reel_bytes: number;
  thumb_bytes: number;
};

const EMPTY_SESSIONS: VodSession[] = [];

function epBtn(color?: string): CSSProperties {
  return {
    fontFamily: T.mono,
    fontSize: 11,
    letterSpacing: 0.4,
    fontWeight: 600,
    padding: "8px 12px",
    border: `1px solid ${color || T.border}`,
    background: "transparent",
    color: color || T.text,
    borderRadius: 4,
    cursor: "pointer",
  };
}

function EpisodeHeader({
  vod,
  downloadHref,
  pickedSessionId,
  onPickedSessionChange,
  sessions,
}: {
  vod: VodMock;
  downloadHref: string | null;
  pickedSessionId: string;
  onPickedSessionChange: (id: string) => void;
  sessions: VodSession[];
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "16px 24px",
        borderBottom: `1px solid ${T.border}`,
        background: T.panel,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
        <span style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 2, color: T.text3 }}>
          EP
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 22,
            fontWeight: 700,
            color: T.text,
            letterSpacing: -0.5,
          }}
        >
          {String(vod.episodeNumber).padStart(3, "0")}
        </span>
      </div>
      <div style={{ width: 1, height: 24, background: T.border }} />
      <div>
        <div style={{ fontFamily: T.font, fontSize: 14, fontWeight: 600, color: T.text }}>
          Episode review
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text2 }}>
          ready · upload window 16:30–16:45 ET · auto-publish ON
        </div>
      </div>
      <div style={{ flex: 1 }} />
      <SessionPicker
        sessions={sessions}
        value={pickedSessionId}
        onChange={onPickedSessionChange}
      />
      <button style={epBtn()}>← back to beats</button>
      {downloadHref ? (
        // The download attribute hints the browser to save the file
        // rather than navigate to the URL. Server already sets
        // Content-Disposition via FileResponse; the attribute makes
        // the file name match on the client too.
        <a
          href={downloadHref}
          download={`${pickedSessionId}-reel.mp4`}
          style={{
            ...epBtn(),
            textDecoration: "none",
            display: "inline-block",
          }}
        >
          ↓ download mp4
        </a>
      ) : (
        <button style={{ ...epBtn(), opacity: 0.4, cursor: "not-allowed" }} disabled>
          ↓ download mp4
        </button>
      )}
      <button style={{ ...epBtn(T.yt), background: T.yt, color: "#fff" }}>
        ▲ upload to YouTube
      </button>
    </div>
  );
}

function Thumbnail({ vod }: { vod: VodMock }) {
  return (
    <div
      style={{
        position: "relative",
        aspectRatio: "16/9",
        width: "100%",
        background: "linear-gradient(135deg, #1a1f2e 0%, #0a0a0d 100%)",
        borderRadius: 8,
        overflow: "hidden",
        border: `1px solid ${T.border}`,
      }}
    >
      <svg
        viewBox="0 0 1280 720"
        preserveAspectRatio="xMidYMid slice"
        style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }}
      >
        <defs>
          <linearGradient id="vod-thumb-bg" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#1d2440" />
            <stop offset="100%" stopColor="#08080d" />
          </linearGradient>
          <radialGradient id="vod-thumb-glow" cx="0.78" cy="0.42" r="0.6">
            <stop offset="0%" stopColor={T.ok} stopOpacity="0.5" />
            <stop offset="100%" stopColor={T.ok} stopOpacity="0" />
          </radialGradient>
        </defs>
        <rect width="1280" height="720" fill="url(#vod-thumb-bg)" />
        <rect width="1280" height="720" fill="url(#vod-thumb-glow)" />
        {Array.from({ length: 10 }).map((_, i) => (
          <g key={i} transform={`translate(${260 + i * 70}, ${480 - i * 18})`}>
            <polygon
              points="0,0 64,38 0,76 -64,38"
              fill="none"
              stroke={T.accent}
              strokeOpacity="0.18"
              strokeWidth="1.5"
            />
          </g>
        ))}
        <polyline
          points="60,540 100,520 140,530 180,500 220,480 260,490 300,460 340,440 380,450 420,420 460,400 500,380 540,360"
          fill="none"
          stroke={T.ok}
          strokeWidth="4"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      </svg>
      <div
        style={{
          position: "absolute",
          inset: 0,
          padding: "36px 40px",
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between" }}>
          <div>
            <div
              style={{
                fontFamily: T.mono,
                fontSize: 12,
                letterSpacing: 3,
                color: T.accent,
                marginBottom: 8,
              }}
            >
              TODAY ON TRADEFARM · EP {String(vod.episodeNumber).padStart(3, "0")}
            </div>
            <div
              style={{
                fontFamily: T.font,
                fontSize: 60,
                fontWeight: 800,
                color: "#fff",
                letterSpacing: -1.5,
                lineHeight: 1,
                maxWidth: 600,
              }}
            >
              Mei takes #1
              <br />
              after 47 days
            </div>
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 13, color: "#fff8" }}>tue · may 19</div>
        </div>
        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between" }}>
          <div
            style={{
              fontFamily: T.font,
              fontSize: 22,
              fontWeight: 600,
              color: "#cdd1da",
              maxWidth: 540,
            }}
          >
            <span style={{ color: T.ok, fontWeight: 800 }}>+1.84%</span> day · biggest rivalry yet ·
            1 promotion
          </div>
          <div style={{ fontFamily: T.mono, fontSize: 13, color: "#fff8", textAlign: "right" }}>
            100 agents · 312 fills · {String(Math.floor(vod.totalDuration / 60)).padStart(2, "0")}:
            {String(vod.totalDuration % 60).padStart(2, "0")}
          </div>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          bottom: 12,
          right: 14,
          fontFamily: T.mono,
          fontSize: 11,
          color: "#fff",
          background: "rgba(0,0,0,0.7)",
          padding: "3px 7px",
          borderRadius: 3,
        }}
      >
        {String(Math.floor(vod.totalDuration / 60)).padStart(2, "0")}:
        {String(vod.totalDuration % 60).padStart(2, "0")}
      </div>
    </div>
  );
}

function MetaField({
  label,
  children,
  mono,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: 1.8,
          color: T.text3,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? T.mono : T.font,
          fontSize: 13,
          color: T.text,
          lineHeight: 1.5,
        }}
      >
        {children}
      </div>
    </div>
  );
}

function ChapterList({ vod }: { vod: VodMock }) {
  const selected = vod.beats.filter((b) => vod.selectedBeats.has(b.id));
  let cumulative = 0;
  const rows = selected.map((b) => {
    const start = cumulative;
    cumulative += b.duration;
    return { ...b, start };
  });
  const fmtStamp = (s: number) => {
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  };
  return (
    <div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 9,
          letterSpacing: 1.8,
          color: T.text3,
          marginBottom: 8,
        }}
      >
        chapters · auto · {rows.length}
      </div>
      <div
        className="vod-no-scroll"
        style={{
          background: T.bg,
          border: `1px solid ${T.border}`,
          borderRadius: 4,
          padding: 12,
          fontFamily: T.mono,
          fontSize: 12,
          lineHeight: 1.9,
          color: T.text2,
          maxHeight: 240,
          overflow: "auto",
        }}
      >
        {rows.map((r) => (
          <div key={r.id} style={{ display: "flex", gap: 12 }}>
            <span style={{ color: T.accent, width: 52, flexShrink: 0 }}>{fmtStamp(r.start)}</span>
            <span
              style={{
                color: T.text,
                flex: 1,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {r.headline}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

function UploadStrip() {
  const steps = [
    { label: "reel.mp4", sub: "1080p · 47.2 MB", ok: true, pending: false },
    { label: "thumbnail", sub: "1280×720 · 184 KB", ok: true, pending: false },
    { label: "metadata", sub: "title · desc · 13 chapters", ok: true, pending: false },
    { label: "YT upload", sub: "queued · 16:30 ET", ok: false, pending: true },
  ];
  return (
    <div
      style={{
        display: "flex",
        gap: 10,
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 6,
        padding: 14,
      }}
    >
      {steps.map((s, i) => (
        <div
          key={s.label}
          style={{
            flex: 1,
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "6px 8px",
            borderRight: i < steps.length - 1 ? `1px solid ${T.border}` : "none",
          }}
        >
          <span
            className={s.pending ? "vod-pulse-dot" : undefined}
            style={{
              width: 22,
              height: 22,
              borderRadius: 999,
              background: s.ok ? `${T.ok}22` : `${T.accent}22`,
              border: `1px solid ${s.ok ? T.ok : T.accent}`,
              color: s.ok ? T.ok : T.accent,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              fontFamily: T.mono,
              fontSize: 11,
              fontWeight: 700,
            }}
          >
            {s.ok ? "✓" : "⋯"}
          </span>
          <div>
            <div style={{ fontFamily: T.font, fontSize: 12, color: T.text, fontWeight: 600 }}>
              {s.label}
            </div>
            <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>{s.sub}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function Stat2({
  label,
  value,
  color,
}: {
  label: string;
  value: ReactNode;
  color?: string;
}) {
  return (
    <div>
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.4, color: T.text3, marginBottom: 4 }}>
        {label}
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 14,
          color: color || T.text,
          fontWeight: 600,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// ReelPreview — live preview of the rendered MP4 for a chosen session.
//
// Pulls /vod/sessions on mount, then renders:
//   - <video> with native controls if the chosen session has a reel
//   - the static Thumbnail mock if nothing has been rendered yet
//   - a "no reel" empty state if the session exists but reel.mp4 is missing
//
// The poster is the real thumb.jpg when present, so the player shows the
// generated thumbnail before the user hits play. Range requests are
// handled by FileResponse on the backend, so the browser can scrub
// without buffering the whole file.
// ---------------------------------------------------------------------------

function useVodSessions(): { sessions: VodSession[]; loaded: boolean } {
  const [sessions, setSessions] = useState<VodSession[]>(EMPTY_SESSIONS);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch("/vod/sessions")
      .then((r) => (r.ok ? r.json() : []))
      .then((rows: VodSession[]) => {
        if (!cancelled) setSessions(Array.isArray(rows) ? rows : []);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { sessions, loaded };
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

function ReelPreview({
  vod,
  sessionId,
  sessions,
  loaded,
}: {
  vod: VodMock;
  sessionId: string;
  sessions: VodSession[];
  loaded: boolean;
}) {
  // The chosen session wins if it has a reel; otherwise the most
  // recent rendered session takes over. Both let the operator preview
  // older episodes without having to re-render.
  const active =
    sessions.find((s) => s.session_id === sessionId && s.has_reel) ??
    sessions.find((s) => s.session_id === sessionId) ??
    sessions.find((s) => s.has_reel);

  if (!active) {
    // No rendered session on disk yet. Show the static mock thumbnail
    // with a "not rendered" badge so the layout is still demoable.
    if (!loaded) {
      // Initial fetch in flight — show a quiet placeholder rather than
      // a hard "no reel" message, otherwise the badge would flash on
      // every page load.
      return (
        <div
          style={{
            position: "relative",
            aspectRatio: "16/9",
            width: "100%",
            background: T.bg,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: T.text3,
            fontFamily: T.mono,
            fontSize: 11,
          }}
        >
          checking for rendered sessions…
        </div>
      );
    }
    return (
      <div style={{ position: "relative" }}>
        <Thumbnail vod={vod} />
        <div
          style={{
            position: "absolute",
            top: 12,
            left: 12,
            background: "rgba(0,0,0,0.75)",
            color: T.text,
            fontFamily: T.mono,
            fontSize: 10,
            letterSpacing: 1.4,
            padding: "4px 8px",
            borderRadius: 3,
            border: `1px solid ${T.border}`,
          }}
        >
          no reel rendered yet — run the VOD pipeline to populate out/sessions/
        </div>
      </div>
    );
  }

  if (!active.has_reel) {
    return (
      <div
        style={{
          aspectRatio: "16/9",
          width: "100%",
          background: T.bg,
          border: `1px solid ${T.border}`,
          borderRadius: 8,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: 6,
          color: T.text2,
          fontFamily: T.mono,
          fontSize: 12,
        }}
      >
        <div style={{ color: T.text, fontWeight: 600 }}>
          session {active.session_id} — reel not rendered
        </div>
        <div style={{ color: T.text3, fontSize: 10 }}>
          render.stitch + render.mix produce reel.mp4 under this session dir
        </div>
      </div>
    );
  }

  // Real preview. The <video> element streams the file with native
  // controls (play / pause / scrub / volume / fullscreen) and uses the
  // generated thumbnail as the poster image.
  return (
    <div>
      <video
        controls
        preload="metadata"
        poster={active.has_thumb ? `/vod/${active.session_id}/thumb.jpg` : undefined}
        src={`/vod/${active.session_id}/reel.mp4`}
        style={{
          display: "block",
          width: "100%",
          aspectRatio: "16/9",
          background: "#000",
          borderRadius: 8,
          border: `1px solid ${T.border}`,
        }}
      >
        Your browser does not support embedded video.
      </video>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginTop: 6,
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text3,
          letterSpacing: 0.5,
        }}
      >
        <span>
          {active.session_id} · {fmtBytes(active.reel_bytes)} · {active.has_thumb ? "thumb.jpg present" : "no thumb"}
        </span>
        <span>1080p · h264</span>
      </div>
    </div>
  );
}

function SessionPicker({
  sessions,
  value,
  onChange,
}: {
  sessions: VodSession[];
  value: string;
  onChange: (id: string) => void;
}) {
  if (sessions.length === 0) return null;
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        fontFamily: T.mono,
        fontSize: 11,
        background: T.bg,
        color: T.text,
        border: `1px solid ${T.border}`,
        borderRadius: 4,
        padding: "6px 8px",
        cursor: "pointer",
        minWidth: 200,
      }}
      title="Pick a rendered session to preview"
    >
      {sessions.map((s) => (
        <option key={s.session_id} value={s.session_id}>
          {s.session_id}
          {s.has_reel ? "" : " (no reel)"}
        </option>
      ))}
    </select>
  );
}

export function EpisodePage({ vod }: { vod: VodMock }) {
  // The chosen session drives the preview + download button. Defaults
  // to the mock's hard-coded sessionId, but the operator can switch
  // to any rendered session via the picker.
  const { sessions, loaded } = useVodSessions();
  const [pickedSession, setPickedSession] = useState<string>(vod.sessionId);
  // Fall back to the most recent rendered session if the mock's
  // sessionId doesn't have a reel yet — the mock's id is decorative.
  const picked =
    sessions.find((s) => s.session_id === pickedSession && s.has_reel) ??
    sessions.find((s) => s.session_id === pickedSession) ??
    sessions.find((s) => s.has_reel);
  const downloadSessionId = picked?.session_id ?? null;
  const downloadHref = downloadSessionId ? `/vod/${downloadSessionId}/reel.mp4` : null;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: T.bg,
        color: T.text,
        fontFamily: T.font,
        display: "flex",
        flexDirection: "column",
        overflow: "hidden",
      }}
    >
      <EpisodeHeader
        vod={vod}
        downloadHref={downloadHref}
        pickedSessionId={pickedSession}
        onPickedSessionChange={setPickedSession}
        sessions={sessions}
      />
      <div
        className="vod-no-scroll"
        style={{ flex: 1, minHeight: 0, overflow: "auto", padding: 20 }}
      >
        <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 20 }}>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <ReelPreview
              vod={vod}
              sessionId={pickedSession}
              sessions={sessions}
              loaded={loaded}
            />
            <UploadStrip />
            <div
              style={{
                background: T.panel,
                border: `1px solid ${T.border}`,
                borderRadius: 6,
                padding: 16,
              }}
            >
              <div
                style={{
                  fontFamily: T.mono,
                  fontSize: 9,
                  letterSpacing: 1.8,
                  color: T.text3,
                  marginBottom: 8,
                }}
              >
                episode stats
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14 }}>
                <Stat2
                  label="duration"
                  value={`${Math.floor(vod.totalDuration / 60)}:${String(
                    vod.totalDuration % 60,
                  ).padStart(2, "0")}`}
                />
                <Stat2
                  label="beats"
                  value={`${vod.selectedBeats.size} / ${vod.beats.length}`}
                />
                <Stat2
                  label="cost (LLM + TTS)"
                  value={`$${(vod.summary.llmSpend + 1.42).toFixed(2)}`}
                />
                <Stat2 label="render time" value="8m 14s" />
                <Stat2 label="pool P&L" value={fmtPct(vod.summary.pnlPct)} color={T.ok} />
                <Stat2 label="fills" value={fmtInt(vod.summary.fillCount)} />
                <Stat2 label="promotions" value="1 ↑ · 0 ↓" />
                <Stat2 label="biggest mover" value="Mei Patel +$284" />
              </div>
            </div>
          </div>
          <div
            style={{
              background: T.panel,
              border: `1px solid ${T.border}`,
              borderRadius: 6,
              padding: 18,
              display: "flex",
              flexDirection: "column",
              gap: 18,
            }}
          >
            <MetaField label="title · editable">
              <div
                contentEditable
                suppressContentEditableWarning
                style={{
                  fontSize: 18,
                  fontWeight: 700,
                  color: T.text,
                  lineHeight: 1.3,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  borderRadius: 4,
                  padding: "10px 12px",
                  outline: "none",
                }}
              >
                Mei takes #1 after 47 days · TradeFarm Day {vod.episodeNumber}
              </div>
            </MetaField>

            <MetaField label="description · auto-generated">
              <div
                contentEditable
                suppressContentEditableWarning
                style={{
                  color: T.text2,
                  lineHeight: 1.6,
                  background: T.bg,
                  border: `1px solid ${T.border}`,
                  borderRadius: 4,
                  padding: "10px 12px",
                  minHeight: 120,
                  fontSize: 12.5,
                  outline: "none",
                }}
              >
                100 paper-trading AI agents had their best day since April 24. Mei Patel overtook a
                47-day reign at #1, Marcus Wagner went big on NVDA, and a four-time rivalry
                between Brian Anderson and Lisa Garcia finally tipped.
                <br />
                <br />
                Pool finished +1.84% with 1 promotion (Henry Bennett to senior). Watch through to
                the close — the last nine minutes had 18 fills.
              </div>
            </MetaField>

            <ChapterList vod={vod} />

            <MetaField label="tags · auto" mono>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                {[
                  "tradefarm", "ai trading", "paper trading", "llm", "lstm",
                  "daily recap", "agent academy", "autonomous", "vod",
                ].map((t) => (
                  <span
                    key={t}
                    style={{
                      fontSize: 11,
                      padding: "3px 8px",
                      background: T.bg,
                      border: `1px solid ${T.border}`,
                      borderRadius: 3,
                      color: T.text2,
                    }}
                  >
                    {t}
                  </span>
                ))}
              </div>
            </MetaField>

            <MetaField label="schedule · YT" mono>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <input
                  type="text"
                  defaultValue="2026-05-19 16:30 ET"
                  readOnly
                  style={{
                    flex: 1,
                    fontFamily: T.mono,
                    fontSize: 12,
                    padding: "8px 10px",
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    borderRadius: 4,
                    color: T.text,
                  }}
                />
                <select
                  defaultValue="unlisted"
                  style={{
                    fontFamily: T.mono,
                    fontSize: 12,
                    padding: "8px 10px",
                    background: T.bg,
                    border: `1px solid ${T.border}`,
                    borderRadius: 4,
                    color: T.text,
                  }}
                >
                  <option>public</option>
                  <option>unlisted</option>
                  <option>private</option>
                </select>
              </div>
            </MetaField>
          </div>
        </div>
      </div>
    </div>
  );
}
