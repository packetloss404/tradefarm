// Pipeline status board — operator's "what's running / stuck / done"
// view over all 10 subsystems in today's VOD pipeline. Cards on top,
// expanded detail (with log tail) for the selected subsystem on the
// bottom.

import { useState, type CSSProperties, type ReactNode } from "react";
import { T } from "./tokens";
import type { PipelineNode } from "./mockData";
import { fmtInt, fmtMoney, ProgressBar, StatusDot } from "./widgets";
import type { VodMock } from "./useVodMock";

function pipelineBtn(border: string = T.border, color: string = T.text): CSSProperties {
  return {
    fontFamily: T.mono,
    fontSize: 11,
    letterSpacing: 0.4,
    fontWeight: 600,
    padding: "8px 12px",
    border: `1px solid ${border}`,
    background: "transparent",
    color,
    borderRadius: 4,
    cursor: "pointer",
  };
}

function Stat({
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
      <div style={{ fontSize: 10, letterSpacing: 1.6, color: T.text3, marginBottom: 4 }}>
        {label}
      </div>
      <div
        style={{
          fontSize: 18,
          fontWeight: 600,
          color: color || T.text,
          fontFeatureSettings: '"tnum"',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function PipelineHeader({ vod }: { vod: VodMock }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 18,
        padding: "20px 28px",
        borderBottom: `1px solid ${T.border}`,
        background: T.panel,
        fontFamily: T.font,
      }}
    >
      <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
        <span style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: 2, color: T.text3 }}>
          EP
        </span>
        <span
          style={{
            fontFamily: T.mono,
            fontSize: 32,
            fontWeight: 700,
            color: T.text,
            letterSpacing: -1,
          }}
        >
          {String(vod.episodeNumber).padStart(3, "0")}
        </span>
      </div>
      <div style={{ width: 1, height: 36, background: T.border }} />
      <div>
        <div
          style={{
            fontFamily: T.font,
            fontSize: 18,
            fontWeight: 600,
            color: T.text,
            marginBottom: 2,
          }}
        >
          Today on TradeFarm
        </div>
        <div style={{ fontFamily: T.mono, fontSize: 11, color: T.text2 }}>{vod.sessionLabel}</div>
      </div>
      <div style={{ flex: 1 }} />
      <div style={{ display: "flex", gap: 28, fontFamily: T.mono }}>
        <Stat
          label="POOL P&L"
          value={fmtMoney(vod.summary.totalPnl, { signed: true, compact: true })}
          color={T.ok}
        />
        <Stat label="FILLS" value={fmtInt(vod.summary.fillCount)} />
        <Stat label="DECISIONS" value={fmtInt(vod.summary.decisionCount)} />
        <Stat label="LLM SPEND" value={"$" + vod.summary.llmSpend.toFixed(2)} />
      </div>
      <div style={{ width: 1, height: 36, background: T.border }} />
      <PipelineActions vod={vod} />
    </div>
  );
}

function PipelineActions({ vod }: { vod: VodMock }) {
  const queued = vod.pipeline.filter((p) => p.status === "queued").length;
  const running = vod.pipeline.filter((p) => p.status === "running").length;
  const done = vod.pipeline.filter((p) => p.status === "done").length;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <div style={{ display: "flex", gap: 8, fontFamily: T.mono, fontSize: 11, color: T.text2 }}>
        <span style={{ color: T.ok }}>● {done} done</span>
        <span style={{ color: T.accent }}>● {running} running</span>
        <span>● {queued} queued</span>
      </div>
      <button style={{ ...pipelineBtn(T.accent), background: T.accent, color: "#1a1408" }}>
        ▸ resume pipeline
      </button>
      <button style={pipelineBtn()}>open out/</button>
    </div>
  );
}

function SubsystemCard({
  node,
  vod,
  isSelected,
  onSelect,
}: {
  node: PipelineNode;
  vod: VodMock;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const isRunning = node.status === "running";
  const isDone = node.status === "done";
  const isQueued = node.status === "queued";
  const progress = isRunning ? vod.renderProgress : isDone ? 1 : 0;
  return (
    <div
      onClick={onSelect}
      style={{
        background: isSelected ? T.panel2 : T.panel,
        border: `1px solid ${isSelected ? T.borderHi : T.border}`,
        borderRadius: 6,
        padding: 14,
        cursor: "pointer",
        opacity: isQueued ? 0.6 : 1,
        transition: "background 120ms",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
        <StatusDot status={node.status} />
        <span style={{ fontFamily: T.font, fontSize: 13, fontWeight: 600, color: T.text, flex: 1 }}>
          {node.label}
        </span>
        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>{node.status}</span>
      </div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text3,
          marginBottom: 10,
          whiteSpace: "nowrap",
          overflow: "hidden",
          textOverflow: "ellipsis",
        }}
      >
        {node.cmd}
      </div>
      <ProgressBar progress={progress} color={isDone ? T.ok : T.accent} />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginTop: 8,
          fontFamily: T.mono,
          fontSize: 10,
          color: T.text2,
        }}
      >
        <span>{node.output}</span>
        <span>{node.durationSec != null ? `${node.durationSec}s` : "—"}</span>
      </div>
    </div>
  );
}

function SectionLabel({
  children,
  right,
}: {
  children: ReactNode;
  right?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "baseline",
        justifyContent: "space-between",
        marginBottom: 12,
      }}
    >
      <div style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1.8, color: T.text3 }}>
        {children}
      </div>
      {right && <div style={{ fontFamily: T.mono, fontSize: 10, color: T.text3 }}>{right}</div>}
    </div>
  );
}

function DetailField({
  label,
  value,
  mono,
}: {
  label: string;
  value: ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <div
        style={{
          fontFamily: T.mono,
          fontSize: 10,
          letterSpacing: 1.4,
          color: T.text3,
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: mono ? T.mono : T.font,
          fontSize: 13,
          fontWeight: 500,
          color: T.text,
        }}
      >
        {value}
      </div>
    </div>
  );
}

function PipelineGraph({
  vod,
  selected,
  setSelected,
}: {
  vod: VodMock;
  selected: string;
  setSelected: (id: string) => void;
}) {
  return (
    <div
      className="vod-no-scroll"
      style={{ padding: "20px 28px", flex: 1, overflow: "auto" }}
    >
      <SectionLabel>pipeline · 2026-05-19 16:00:04 ET</SectionLabel>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12 }}>
        {vod.pipeline.map((node) => (
          <SubsystemCard
            key={node.id}
            node={node}
            vod={vod}
            isSelected={selected === node.id}
            onSelect={() => setSelected(node.id)}
          />
        ))}
      </div>
    </div>
  );
}

function DetailPane({ vod, selectedId }: { vod: VodMock; selectedId: string }) {
  const node = vod.pipeline.find((p) => p.id === selectedId) ?? vod.pipeline[2];
  if (!node) return null;
  return (
    <div
      style={{
        flex: 1,
        display: "flex",
        flexDirection: "column",
        minHeight: 0,
        padding: "0 28px 28px",
      }}
    >
      <div
        style={{
          background: T.panel,
          border: `1px solid ${T.border}`,
          borderRadius: 6,
          padding: 18,
          display: "flex",
          flexDirection: "column",
          gap: 14,
          minHeight: 0,
          flex: 1,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          <StatusDot status={node.status} />
          <span style={{ fontFamily: T.font, fontSize: 16, fontWeight: 700, color: T.text }}>
            {node.label}
          </span>
          <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text3 }}>{node.cmd}</span>
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text2 }}>{node.summary}</span>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16 }}>
          <DetailField label="started" value={node.started ?? "—"} />
          <DetailField label="finished" value={node.finished ?? "—"} />
          <DetailField
            label="duration"
            value={
              node.durationSec != null
                ? `${node.durationSec}s${node.status === "running" ? " · running" : ""}`
                : "—"
            }
          />
          <DetailField
            label="output"
            value={`${node.output} · ${node.outputSize ?? "—"}`}
            mono
          />
        </div>
        {node.progressLabel && (
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                fontFamily: T.mono,
                fontSize: 10,
                color: T.text2,
                marginBottom: 6,
              }}
            >
              <span>progress</span>
              <span>{node.progressLabel}</span>
            </div>
            <ProgressBar progress={vod.renderProgress} />
          </div>
        )}
        <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
          <SectionLabel right="tail · log">stdout</SectionLabel>
          <div
            className="vod-no-scroll"
            style={{
              flex: 1,
              minHeight: 0,
              background: T.bg,
              border: `1px solid ${T.border}`,
              borderRadius: 4,
              padding: "10px 12px",
              overflow: "auto",
              fontFamily: T.mono,
              fontSize: 11,
              lineHeight: 1.6,
              color: T.text2,
            }}
          >
            {node.tail.map((line, i) => {
              const isLast = i === node.tail.length - 1;
              const live = isLast && node.status === "running";
              return (
                <div key={i} style={{ color: live ? T.text : T.text2 }}>
                  {line}
                  {live && (
                    <span className="vod-cursor-blink" style={{ color: T.accent, marginLeft: 4 }}>
                      ▌
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

export function PipelineBoard({ vod }: { vod: VodMock }) {
  const [selected, setSelected] = useState("render");
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
      <PipelineHeader vod={vod} />
      <PipelineGraph vod={vod} selected={selected} setSelected={setSelected} />
      <DetailPane vod={vod} selectedId={selected} />
    </div>
  );
}
