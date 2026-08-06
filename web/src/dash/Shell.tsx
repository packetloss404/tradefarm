// Top nav, status group, tweaks panel, generic Panel primitive.
// Shared across all four dashboard pages.

import type { CSSProperties, ReactNode } from "react";
import { useTheme } from "./ThemeContext";
import { ETClock, fmtMoney, fmtPct } from "../vod/widgets";
import type { VodSessionLive } from "../vod/useVodSessionLive";
import type { DashRoute, DashRouteState } from "./useHashRoute";
import type { DashTweaks } from "./useDashTweaks";

const ROUTES: { id: DashRoute; label: string }[] = [
  { id: "today", label: "Today" },
  { id: "episodes", label: "Episodes" },
  { id: "research", label: "Research" },
  { id: "admin", label: "Admin" },
];

export function DashNav({
  vod,
  route,
  go,
}: {
  vod: VodSessionLive;
  route: DashRouteState;
  go: (id: DashRouteState) => void;
}) {
  const { T } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 16,
        padding: "0 24px",
        height: 56,
        borderBottom: `1px solid ${T.border}`,
        background: T.panel,
        flexShrink: 0,
        position: "sticky",
        top: 0,
        zIndex: 20,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: `linear-gradient(135deg, ${T.accent}, ${T.accent2})`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 13,
            fontWeight: 800,
            color: "#000",
          }}
        >
          tf
        </div>
        <span
          style={{
            fontFamily: '"Helvetica Neue", sans-serif',
            fontSize: 15,
            fontWeight: 700,
            color: T.text,
          }}
        >
          tradefarm
        </span>
      </div>
      <div style={{ width: 1, height: 22, background: T.border }} />
      <div style={{ display: "flex", gap: 4 }}>
        {ROUTES.map((r) => (
          <button
            key={r.id}
            onClick={() => go({ route: r.id, param: null } as DashRouteState)}
            style={{
              fontFamily: '"Helvetica Neue", sans-serif',
              fontSize: 13,
              fontWeight: route.route === r.id ? 600 : 500,
              padding: "8px 14px",
              borderRadius: 4,
              border: "none",
              cursor: "pointer",
              background: route.route === r.id ? T.panel2 : "transparent",
              color: route.route === r.id ? T.text : T.text2,
              transition: "background 120ms",
            }}
          >
            {r.label}
          </button>
        ))}
        <a
          href="#vod-studio/beats"
          title="Open VOD Studio (separate post-production app)"
          style={{
            fontFamily: '"Helvetica Neue", sans-serif',
            fontSize: 13,
            fontWeight: 500,
            padding: "8px 14px",
            borderRadius: 4,
            border: "none",
            color: T.text2,
            textDecoration: "none",
            background: "transparent",
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
          }}
        >
          VOD Studio ↗
        </a>
      </div>
      <div style={{ flex: 1 }} />
      <NavStatusGroup vod={vod} />
    </div>
  );
}

function NavStatusGroup({ vod }: { vod: VodSessionLive }) {
  const { T } = useTheme();
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
      <NavStat label="POOL" value={fmtMoney(vod.summary.totalEquity, { compact: true })} mono />
      <NavStat label="DAY" value={fmtPct(vod.summary.pnlPct)} color={vod.summary.pnlPct >= 0 ? T.ok : T.err} mono />
      <NavStat label="EP" value={`#${vod.episodeNumber}`} mono />
      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
        <span
          className="vod-pulse-dot"
          style={{ width: 8, height: 8, borderRadius: 999, background: T.rec, boxShadow: `0 0 8px ${T.rec}` }}
        />
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            fontWeight: 700,
            letterSpacing: 1.4,
            color: T.rec,
          }}
        >
          REC
        </span>
      </div>
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 11, color: T.text2 }}>
        <ETClock /> ET
      </span>
    </div>
  );
}

function NavStat({
  label,
  value,
  color,
  mono,
}: {
  label: string;
  value: string;
  color?: string;
  mono?: boolean;
}) {
  const { T } = useTheme();
  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 60 }}>
      <span style={{ fontFamily: "JetBrains Mono, monospace", fontSize: 9, letterSpacing: 1.4, color: T.text3 }}>
        {label}
      </span>
      <span
        style={{
          fontFamily: mono ? "JetBrains Mono, monospace" : "inherit",
          fontSize: 13,
          fontWeight: 600,
          color: color || T.text,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </span>
    </div>
  );
}

// --- Tweaks panel ------------------------------------------------------

export function TweaksButton({ onClick }: { onClick: () => void }) {
  const { T } = useTheme();
  return (
    <button
      onClick={onClick}
      title="Theme, density, layout toggles"
      style={{
        position: "fixed",
        bottom: 18,
        right: 18,
        zIndex: 49,
        width: 40,
        height: 40,
        borderRadius: 999,
        background: T.panel,
        border: `1px solid ${T.borderHi}`,
        color: T.text,
        cursor: "pointer",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        boxShadow: "0 6px 20px rgba(0,0,0,0.3)",
      }}
    >
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="2" stroke="currentColor" strokeWidth="1.5" />
        <path
          d="M8 2v2M8 12v2M14 8h-2M4 8H2M12.2 3.8l-1.4 1.4M5.2 10.8l-1.4 1.4M12.2 12.2l-1.4-1.4M5.2 5.2L3.8 3.8"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
        />
      </svg>
    </button>
  );
}

export function TweaksPanel({
  tweaks,
  setTweak,
  open,
  onClose,
}: {
  tweaks: DashTweaks;
  setTweak: <K extends keyof DashTweaks>(k: K, v: DashTweaks[K]) => void;
  open: boolean;
  onClose: () => void;
}) {
  const { T } = useTheme();
  if (!open) return null;
  return (
    <div
      style={{
        position: "fixed",
        bottom: 18,
        right: 18,
        zIndex: 50,
        width: 280,
        background: T.panel,
        border: `1px solid ${T.borderHi}`,
        borderRadius: 8,
        padding: 16,
        boxShadow: "0 12px 48px rgba(0,0,0,0.4)",
        fontFamily: '"Helvetica Neue", sans-serif',
        color: T.text,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
        <span
          style={{
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 10,
            letterSpacing: 1.8,
            color: T.text3,
            flex: 1,
          }}
        >
          TWEAKS
        </span>
        <button
          onClick={onClose}
          style={{ background: "transparent", border: "none", color: T.text2, cursor: "pointer", fontSize: 16 }}
        >
          ×
        </button>
      </div>

      <TwSection label="Theme">
        <TwSegment
          value={tweaks.theme}
          onChange={(v) => setTweak("theme", v as DashTweaks["theme"])}
          options={[
            { value: "studio-dark", label: "Dark" },
            { value: "studio-light", label: "Light" },
            { value: "amber-crt", label: "Amber" },
          ]}
        />
      </TwSection>

      <TwSection label="Density">
        <TwSegment
          value={tweaks.density}
          onChange={(v) => setTweak("density", v as DashTweaks["density"])}
          options={[
            { value: "compact", label: "Compact" },
            { value: "comfortable", label: "Cozy" },
            { value: "cozy", label: "Roomy" },
          ]}
        />
      </TwSection>

      <TwSection label="Today layout">
        <TwToggle
          label="Pipeline panel"
          value={tweaks.showPipelinePanel}
          onChange={(v) => setTweak("showPipelinePanel", v)}
        />
        <TwToggle
          label="Cost rail"
          value={tweaks.showCostRail}
          onChange={(v) => setTweak("showCostRail", v)}
        />
      </TwSection>
    </div>
  );
}

function TwSection({ label, children }: { label: string; children: ReactNode }) {
  const { T } = useTheme();
  return (
    <div style={{ marginBottom: 14 }}>
      <div
        style={{
          fontFamily: "JetBrains Mono, monospace",
          fontSize: 9,
          letterSpacing: 1.6,
          color: T.text3,
          marginBottom: 6,
        }}
      >
        {label}
      </div>
      {children}
    </div>
  );
}

function TwSegment({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  const { T } = useTheme();
  return (
    <div
      style={{
        display: "flex",
        background: T.bg,
        border: `1px solid ${T.border}`,
        borderRadius: 4,
        padding: 2,
      }}
    >
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          style={{
            flex: 1,
            padding: "6px 8px",
            border: "none",
            cursor: "pointer",
            fontFamily: "JetBrains Mono, monospace",
            fontSize: 11,
            fontWeight: 600,
            background: value === o.value ? T.panel2 : "transparent",
            color: value === o.value ? T.text : T.text2,
            borderRadius: 3,
          }}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function TwToggle({
  label,
  value,
  onChange,
}: {
  label: string;
  value: boolean;
  onChange: (v: boolean) => void;
}) {
  const { T } = useTheme();
  return (
    <div style={{ display: "flex", alignItems: "center", padding: "4px 0" }}>
      <span style={{ flex: 1, fontFamily: '"Helvetica Neue"', fontSize: 12, color: T.text2 }}>{label}</span>
      <button
        onClick={() => onChange(!value)}
        style={{
          width: 32,
          height: 18,
          borderRadius: 999,
          border: `1px solid ${value ? T.accent : T.border}`,
          background: value ? T.accent : T.bg,
          position: "relative",
          cursor: "pointer",
          transition: "background 120ms",
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 1,
            left: value ? 15 : 1,
            width: 14,
            height: 14,
            borderRadius: 999,
            background: value ? "#1a1408" : T.text2,
            transition: "left 120ms",
          }}
        />
      </button>
    </div>
  );
}

// --- Reusable atoms used by every page ---------------------------------

export function Panel({
  title,
  children,
  right,
  padded = true,
  style,
}: {
  title?: ReactNode;
  children: ReactNode;
  right?: ReactNode;
  padded?: boolean;
  style?: CSSProperties;
}) {
  const { T } = useTheme();
  return (
    <div
      style={{
        background: T.panel,
        border: `1px solid ${T.border}`,
        borderRadius: 8,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        ...style,
      }}
    >
      {title && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            padding: "12px 16px",
            borderBottom: `1px solid ${T.border}`,
          }}
        >
          <div
            style={{
              fontFamily: "JetBrains Mono, monospace",
              fontSize: 10,
              letterSpacing: 1.6,
              color: T.text3,
            }}
          >
            {title}
          </div>
          {right}
        </div>
      )}
      <div style={{ padding: padded ? 16 : 0, flex: 1, minHeight: 0, overflow: "auto" }}>
        {children}
      </div>
    </div>
  );
}

export function MicroBar({ pct, color }: { pct: number; color?: string }) {
  const { T } = useTheme();
  return (
    <div style={{ height: 4, background: T.panel2, borderRadius: 2, overflow: "hidden" }}>
      <div
        style={{
          width: `${Math.min(100, Math.max(0, pct * 100))}%`,
          height: "100%",
          background: color || T.accent,
          transition: "width 200ms",
        }}
      />
    </div>
  );
}
