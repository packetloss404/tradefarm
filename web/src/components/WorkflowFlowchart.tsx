import { useState } from "react";

/* ------------------------------------------------------------------ *
 * Agent workflow flowchart.
 *
 * Each agent inherits the same orchestrator-driven tick loop (bars →
 * decide → signals → risk → fills → journal), but the decide() body
 * differs by strategy. We render all three pipelines as side-by-side
 * SVG flow diagrams so a viewer can see exactly where the LSTM lives,
 * where the LLM cost-gate kicks in, and where retrieval is consulted.
 *
 * Pure SVG, no chart lib, no animation libs.
 * ------------------------------------------------------------------ */

type StrategyId =
  | "momentum_12_1"
  | "mean_reversion_bb"
  | "rsi2"
  | "donchian_breakout"
  | "pairs_zscore"
  | "lstm_v1"
  | "lstm_llm_v1";

type NodeKind =
  | "input"     // grey rounded-rect — data into the step
  | "compute"   // blue rounded-rect — deterministic computation
  | "model"     // purple — neural net inference
  | "llm"       // amber — external LLM call (costly)
  | "decision"  // diamond — branching gate
  | "action"    // emerald — outgoing trading signal
  | "skip"      // zinc — no-op terminal
  | "io";       // cyan — DB / journal

type FlowNode = {
  id: string;
  kind: NodeKind;
  label: string;
  sub?: string;
  x: number;
  y: number;
  w?: number;
};

type FlowEdge = {
  from: string;
  to: string;
  label?: string;
};

type Strategy = {
  id: StrategyId;
  title: string;
  blurb: string;
  nodes: FlowNode[];
  edges: FlowEdge[];
};

const NODE_W = 178;
const NODE_H = 46;
const DIAMOND_W = 200;
const DIAMOND_H = 84;

const KIND_STYLE: Record<NodeKind, { fill: string; stroke: string; text: string }> = {
  input:    { fill: "#27272a", stroke: "#52525b", text: "#e4e4e7" },
  compute:  { fill: "#1e3a8a", stroke: "#3b82f6", text: "#dbeafe" },
  model:    { fill: "#581c87", stroke: "#a855f7", text: "#f3e8ff" },
  llm:      { fill: "#78350f", stroke: "#f59e0b", text: "#fef3c7" },
  decision: { fill: "#0f172a", stroke: "#64748b", text: "#e2e8f0" },
  action:   { fill: "#064e3b", stroke: "#10b981", text: "#d1fae5" },
  skip:     { fill: "#18181b", stroke: "#3f3f46", text: "#a1a1aa" },
  io:       { fill: "#155e75", stroke: "#06b6d4", text: "#cffafe" },
};

// -- Strategy 1: momentum_12_1 --------------------------------------

const MOMENTUM_12_1: Strategy = {
  id: "momentum_12_1",
  title: "momentum_12_1",
  blurb:
    "Jegadeesh-Titman 12-month return, skipping the most-recent month. Buys when the 12-1m return is positive AND rising; sells when negative AND falling.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "mom",    kind: "compute",  label: "12-1m return", sub: "closes[t-21]/closes[t-273] - 1", x: 200, y: 100 },
    { id: "cross",  kind: "decision", label: "rising or falling?", sub: "current vs previous bar", x: 190, y: 180 },
    { id: "sign",   kind: "decision", label: "sign?", sub: "+ or -", x: 190, y: 320 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash", sub: "reason: mom12-1 rising …", x: 20,  y: 460 },
    { id: "sell",   kind: "action",   label: "SELL all qty", sub: "reason: mom12-1 falling …",  x: 380, y: 460 },
    { id: "wait",   kind: "skip",     label: "wait", x: 200, y: 460 },
  ],
  edges: [
    { from: "bars",  to: "mom" },
    { from: "mom",   to: "cross" },
    { from: "cross", to: "sign" },
    { from: "sign",  to: "buy",  label: "+ & rising" },
    { from: "sign",  to: "sell", label: "- & falling" },
    { from: "sign",  to: "wait", label: "otherwise" },
  ],
};

// -- Strategy 2: mean_reversion_bb ---------------------------------

const BB: Strategy = {
  id: "mean_reversion_bb",
  title: "mean_reversion_bb",
  blurb:
    "Bollinger Bands (20-period SMA ± 2σ). Fades extremes: buy on close < lower, sell on close > upper.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "bb",     kind: "compute",  label: "20d SMA + ±2σ", x: 200, y: 100 },
    { id: "ext",    kind: "decision", label: "close vs band?", x: 190, y: 180 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash", sub: "reason: bb oversold", x: 20,  y: 320 },
    { id: "sell",   kind: "action",   label: "SELL all qty", sub: "reason: bb overbought",  x: 380, y: 320 },
    { id: "wait",   kind: "skip",     label: "wait", x: 200, y: 320 },
  ],
  edges: [
    { from: "bars", to: "bb" },
    { from: "bb",   to: "ext" },
    { from: "ext",  to: "buy",  label: "< lower (flat)" },
    { from: "ext",  to: "sell", label: "> upper (long)" },
    { from: "ext",  to: "wait", label: "inside bands" },
  ],
};

// -- Strategy 3: rsi2 ----------------------------------------------

const RSI2: Strategy = {
  id: "rsi2",
  title: "rsi2",
  blurb:
    "Connors' 2-period RSI. Buy on deep-oversold (RSI(2) < 5), sell on deep-overbought (RSI(2) > 95). Fast-firing, low-compute.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "rsi",    kind: "compute",  label: "2-period RSI", sub: "avg gain / (avg gain + avg loss)", x: 200, y: 100 },
    { id: "level",  kind: "decision", label: "RSI(2) level?", x: 190, y: 180 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash", sub: "reason: rsi2 oversold", x: 20,  y: 320 },
    { id: "sell",   kind: "action",   label: "SELL all qty", sub: "reason: rsi2 overbought",  x: 380, y: 320 },
    { id: "wait",   kind: "skip",     label: "wait", x: 200, y: 320 },
  ],
  edges: [
    { from: "bars",  to: "rsi" },
    { from: "rsi",   to: "level" },
    { from: "level", to: "buy",  label: "< 5 (flat)" },
    { from: "level", to: "sell", label: "> 95 (long)" },
    { from: "level", to: "wait", label: "neutral" },
  ],
};

// -- Strategy 4: donchian_breakout ---------------------------------

const DONCHIAN: Strategy = {
  id: "donchian_breakout",
  title: "donchian_breakout",
  blurb:
    "Turtle-style 20-day channel breakout. Buy on close > 20d high, sell on close < 20d low.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "chan",   kind: "compute",  label: "20d high / 20d low", sub: "max / min over prior 20 bars", x: 200, y: 100 },
    { id: "break",  kind: "decision", label: "breakout?", x: 190, y: 180 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash", sub: "reason: upper break", x: 20,  y: 320 },
    { id: "sell",   kind: "action",   label: "SELL all qty", sub: "reason: lower break",  x: 380, y: 320 },
    { id: "wait",   kind: "skip",     label: "wait", x: 200, y: 320 },
  ],
  edges: [
    { from: "bars",  to: "chan" },
    { from: "chan",  to: "break" },
    { from: "break", to: "buy",  label: "> high (flat)" },
    { from: "break", to: "sell", label: "< low (long)" },
    { from: "break", to: "wait", label: "inside" },
  ],
};

// -- Strategy 5: pairs_zscore --------------------------------------

const PAIRS: Strategy = {
  id: "pairs_zscore",
  title: "pairs_zscore",
  blurb:
    "A-B dollar spread z-score. Buys A when spread is in the lower tail (z < -2), sells A when in the upper tail (z > +2). Long-only sandbox.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars (A+B)", sub: "EODHD cache", x: 200, y: 20 },
    { id: "spread", kind: "compute",  label: "spread = A - B", sub: "simple dollar spread", x: 200, y: 100 },
    { id: "z",      kind: "compute",  label: "60-bar z-score", sub: "(spread - μ) / σ", x: 200, y: 180 },
    { id: "level",  kind: "decision", label: "|z| vs entry?", sub: "default 2.0", x: 190, y: 260 },
    { id: "sign",   kind: "decision", label: "sign of z?", x: 190, y: 400 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash (A)", sub: "reason: pairs_zscore z<…", x: 20,  y: 540 },
    { id: "sell",   kind: "action",   label: "SELL all qty (A)", sub: "reason: pairs_zscore z>…",  x: 380, y: 540 },
    { id: "wait",   kind: "skip",     label: "wait", x: 200, y: 540 },
  ],
  edges: [
    { from: "bars",   to: "spread" },
    { from: "spread", to: "z" },
    { from: "z",      to: "level" },
    { from: "level",  to: "sign", label: "|z| ≥ entry" },
    { from: "level",  to: "wait", label: "|z| < entry" },
    { from: "sign",   to: "buy",  label: "z<0" },
    { from: "sign",   to: "sell", label: "z>0" },
  ],
};

// -- Strategy 2: lstm_v1 --------------------------------------------

const LSTM_V1: Strategy = {
  id: "lstm_v1",
  title: "lstm_v1",
  blurb:
    "19-feature window → trained per-symbol LSTM → directional probs gate trades.",
  nodes: [
    { id: "bars",   kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "feat",   kind: "compute",  label: "featurize()", sub: "19 features × seq_len", x: 200, y: 100 },
    { id: "lstm",   kind: "model",    label: "LSTM forward", sub: "PyTorch FittedModel.predict", x: 200, y: 180 },
    { id: "gate",   kind: "decision", label: "max_prob ≥ enter_conf\n(0.40)?", x: 190, y: 260 },
    { id: "dirq",   kind: "decision", label: "direction?", sub: "up / flat / down", x: 190, y: 400 },
    { id: "buy",    kind: "action",   label: "BUY 20% cash", sub: "reason: lstm up p=…", x: 20,  y: 540 },
    { id: "sell",   kind: "action",   label: "SELL all qty", sub: "reason: lstm down p=…", x: 380, y: 540 },
    { id: "skip",   kind: "skip",     label: "wait", x: 200, y: 540 },
  ],
  edges: [
    { from: "bars", to: "feat" },
    { from: "feat", to: "lstm" },
    { from: "lstm", to: "gate" },
    { from: "gate", to: "skip", label: "no" },
    { from: "gate", to: "dirq", label: "yes" },
    { from: "dirq", to: "buy",  label: "up + flat" },
    { from: "dirq", to: "sell", label: "down + long" },
    { from: "dirq", to: "skip", label: "flat" },
  ],
};

// -- Strategy 3: lstm_llm_v1 ----------------------------------------

const LSTM_LLM: Strategy = {
  id: "lstm_llm_v1",
  title: "lstm_llm_v1",
  blurb:
    "LSTM proposes, LLM disposes. Cost-gated to skip the LLM call when the LSTM signal is weak.",
  nodes: [
    { id: "bars",     kind: "input",    label: "Daily bars", sub: "EODHD cache", x: 200, y: 20 },
    { id: "feat",     kind: "compute",  label: "featurize() + window", x: 200, y: 100 },
    { id: "lstm",     kind: "model",    label: "LSTM forward", sub: "direction + probs", x: 200, y: 180 },
    { id: "costgate", kind: "decision", label: "cost gate", sub: "max_prob ≥ 0.40\n& direction ≠ flat", x: 190, y: 260 },
    { id: "skipllm",  kind: "skip",     label: "skip LLM", sub: "stance=wait, reason=…", x: 460, y: 280 },
    { id: "retrieve", kind: "io",       label: "retrieval.fetch()", sub: "k similar past setups", x: 200, y: 400 },
    { id: "llm",      kind: "llm",      label: "LLM overlay", sub: "Claude / MiniMax JSON", x: 200, y: 480 },
    { id: "stance",   kind: "decision", label: "stance + predictive?", x: 190, y: 580 },
    { id: "buy",      kind: "action",   label: "BUY size_pct cash", sub: "≤ 25%", x: 20,  y: 720 },
    { id: "sell",     kind: "action",   label: "SELL all qty", sub: "predictive flat/short", x: 380, y: 720 },
    { id: "wait",     kind: "skip",     label: "wait", x: 200, y: 720 },
  ],
  edges: [
    { from: "bars",     to: "feat" },
    { from: "feat",     to: "lstm" },
    { from: "lstm",     to: "costgate" },
    { from: "costgate", to: "skipllm",  label: "no (LLM_SKIPS+1)" },
    { from: "costgate", to: "retrieve", label: "yes" },
    { from: "retrieve", to: "llm" },
    { from: "llm",      to: "stance" },
    { from: "stance",   to: "buy",  label: "trade · long" },
    { from: "stance",   to: "sell", label: "predictive flat/short" },
    { from: "stance",   to: "wait", label: "wait" },
  ],
};

const STRATEGIES: Strategy[] = [MOMENTUM_12_1, BB, RSI2, DONCHIAN, PAIRS, LSTM_V1, LSTM_LLM];

// Optional shared "outer loop" diagram showing what the orchestrator does
// around every agent's decide() call. Rendered above the per-strategy panes.
const OUTER_LOOP: { nodes: FlowNode[]; edges: FlowEdge[] } = {
  nodes: [
    { id: "tick",   kind: "input",    label: "scheduler tick", sub: "auto every N sec", x: 20,   y: 30 },
    { id: "bars",   kind: "io",       label: "fetch bars + marks", sub: "EODHD / Alpaca", x: 230, y: 30 },
    { id: "decide", kind: "compute",  label: "agent.decide()", sub: "strategy-specific →", x: 440, y: 30 },
    { id: "risk",   kind: "decision", label: "RiskManager.check()", sub: "rank cap, exits", x: 650, y: 18, w: 200 },
    { id: "broker", kind: "compute",  label: "Broker.submit()", sub: "VirtualBook / Alpaca", x: 880, y: 30 },
    { id: "fill",   kind: "io",       label: "on_fill + journal", sub: "agent_notes outcome", x: 1090, y: 30 },
  ],
  edges: [
    { from: "tick",   to: "bars" },
    { from: "bars",   to: "decide" },
    { from: "decide", to: "risk",   label: "signals" },
    { from: "risk",   to: "broker", label: "passed" },
    { from: "broker", to: "fill" },
  ],
};

// ------------------------------------------------------------------ *

function TextInBox({
  x,
  y,
  w,
  h,
  label,
  sub,
  color,
}: {
  x: number;
  y: number;
  w: number;
  h: number;
  label: string;
  sub?: string;
  color: string;
}) {
  // Multi-line label support — split on \n.
  const lines = label.split("\n");
  const lineH = 14;
  const baseY = sub
    ? y + h / 2 - ((lines.length - 1) * lineH) / 2 - 4
    : y + h / 2 - ((lines.length - 1) * lineH) / 2 + 4;
  return (
    <>
      {lines.map((ln, i) => (
        <text
          key={i}
          x={x + w / 2}
          y={baseY + i * lineH}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={12}
          fontWeight={600}
          fill={color}
          fontFamily="ui-sans-serif, system-ui, sans-serif"
        >
          {ln}
        </text>
      ))}
      {sub && (
        <text
          x={x + w / 2}
          y={baseY + lines.length * lineH + 1}
          textAnchor="middle"
          dominantBaseline="middle"
          fontSize={9.5}
          fill={color}
          opacity={0.75}
          fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
        >
          {sub}
        </text>
      )}
    </>
  );
}

function FlowNodeShape({ node }: { node: FlowNode }) {
  const style = KIND_STYLE[node.kind];
  const w = node.w ?? (node.kind === "decision" ? DIAMOND_W : NODE_W);
  const h = node.kind === "decision" ? DIAMOND_H : NODE_H;

  if (node.kind === "decision") {
    const cx = node.x + w / 2;
    const cy = node.y + h / 2;
    const points = [
      [cx, node.y],
      [node.x + w, cy],
      [cx, node.y + h],
      [node.x, cy],
    ]
      .map((p) => p.join(","))
      .join(" ");
    return (
      <g>
        <polygon points={points} fill={style.fill} stroke={style.stroke} strokeWidth={1.5} />
        <TextInBox x={node.x} y={node.y} w={w} h={h} label={node.label} sub={node.sub} color={style.text} />
      </g>
    );
  }

  return (
    <g>
      <rect
        x={node.x}
        y={node.y}
        width={w}
        height={h}
        rx={8}
        ry={8}
        fill={style.fill}
        stroke={style.stroke}
        strokeWidth={1.5}
      />
      <TextInBox x={node.x} y={node.y} w={w} h={h} label={node.label} sub={node.sub} color={style.text} />
    </g>
  );
}

function nodeAnchor(node: FlowNode, side: "top" | "bottom" | "left" | "right"): { x: number; y: number } {
  const w = node.w ?? (node.kind === "decision" ? DIAMOND_W : NODE_W);
  const h = node.kind === "decision" ? DIAMOND_H : NODE_H;
  switch (side) {
    case "top":    return { x: node.x + w / 2, y: node.y };
    case "bottom": return { x: node.x + w / 2, y: node.y + h };
    case "left":   return { x: node.x,         y: node.y + h / 2 };
    case "right":  return { x: node.x + w,     y: node.y + h / 2 };
  }
}

function pickSides(from: FlowNode, to: FlowNode): { fromSide: "top"|"bottom"|"left"|"right"; toSide: "top"|"bottom"|"left"|"right" } {
  const fc = { x: from.x + (from.w ?? NODE_W) / 2, y: from.y + (from.kind === "decision" ? DIAMOND_H : NODE_H) / 2 };
  const tc = { x: to.x   + (to.w   ?? NODE_W) / 2, y: to.y   + (to.kind   === "decision" ? DIAMOND_H : NODE_H) / 2 };
  const dx = tc.x - fc.x;
  const dy = tc.y - fc.y;
  if (Math.abs(dy) >= Math.abs(dx)) {
    return dy > 0
      ? { fromSide: "bottom", toSide: "top" }
      : { fromSide: "top",    toSide: "bottom" };
  }
  return dx > 0
    ? { fromSide: "right", toSide: "left" }
    : { fromSide: "left",  toSide: "right" };
}

function Edge({ a, b, label }: { a: FlowNode; b: FlowNode; label?: string }) {
  const { fromSide, toSide } = pickSides(a, b);
  const p1 = nodeAnchor(a, fromSide);
  const p2 = nodeAnchor(b, toSide);
  const midX = (p1.x + p2.x) / 2;
  const midY = (p1.y + p2.y) / 2;
  const path = `M ${p1.x} ${p1.y} C ${p1.x} ${midY}, ${p2.x} ${midY}, ${p2.x} ${p2.y}`;
  return (
    <g>
      <path d={path} fill="none" stroke="#52525b" strokeWidth={1.4} markerEnd="url(#arrow-head)" />
      {label && (
        <g>
          <rect
            x={midX - label.length * 3.2 - 5}
            y={midY - 8}
            width={label.length * 6.4 + 10}
            height={16}
            rx={4}
            fill="#0a0a0a"
            stroke="#3f3f46"
            strokeWidth={0.8}
          />
          <text
            x={midX}
            y={midY + 1}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={10}
            fill="#a1a1aa"
            fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
          >
            {label}
          </text>
        </g>
      )}
    </g>
  );
}

function StrategyDiagram({ strat }: { strat: Strategy }) {
  const byId = new Map(strat.nodes.map((n) => [n.id, n]));
  const maxX = Math.max(...strat.nodes.map((n) => n.x + (n.w ?? NODE_W))) + 20;
  const maxY = Math.max(
    ...strat.nodes.map((n) => n.y + (n.kind === "decision" ? DIAMOND_H : NODE_H)),
  ) + 20;

  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="mb-2">
        <div className="font-mono text-sm font-semibold text-zinc-100">{strat.title}</div>
        <div className="text-[11px] text-zinc-500 leading-snug">{strat.blurb}</div>
      </div>
      <svg
        viewBox={`0 0 ${maxX} ${maxY}`}
        preserveAspectRatio="xMidYMin meet"
        className="w-full h-auto block"
        style={{ maxHeight: 640 }}
      >
        <defs>
          <marker id="arrow-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#71717a" />
          </marker>
        </defs>
        {strat.edges.map((e, i) => {
          const a = byId.get(e.from);
          const b = byId.get(e.to);
          if (!a || !b) return null;
          return <Edge key={i} a={a} b={b} label={e.label} />;
        })}
        {strat.nodes.map((n) => (
          <FlowNodeShape key={n.id} node={n} />
        ))}
      </svg>
    </div>
  );
}

function OuterLoopDiagram() {
  const { nodes, edges } = OUTER_LOOP;
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const maxX = Math.max(...nodes.map((n) => n.x + (n.w ?? NODE_W))) + 20;
  const maxY = Math.max(...nodes.map((n) => n.y + (n.kind === "decision" ? DIAMOND_H : NODE_H))) + 20;
  return (
    <div className="rounded-md border border-zinc-800 bg-zinc-950/40 p-3">
      <div className="mb-2">
        <div className="font-mono text-sm font-semibold text-zinc-100">Orchestrator tick loop</div>
        <div className="text-[11px] text-zinc-500 leading-snug">
          Shared outer loop. The strategy-specific decide() bodies below sit inside the middle node.
        </div>
      </div>
      <svg viewBox={`0 0 ${maxX} ${maxY}`} preserveAspectRatio="xMidYMin meet" className="w-full h-auto block" style={{ maxHeight: 130 }}>
        <defs>
          <marker id="arrow-head-outer" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#71717a" />
          </marker>
        </defs>
        {edges.map((e, i) => {
          const a = byId.get(e.from);
          const b = byId.get(e.to);
          if (!a || !b) return null;
          // Reuse Edge but pin to the outer arrow marker.
          const { fromSide, toSide } = pickSides(a, b);
          const p1 = nodeAnchor(a, fromSide);
          const p2 = nodeAnchor(b, toSide);
          const midX = (p1.x + p2.x) / 2;
          const path = `M ${p1.x} ${p1.y} C ${midX} ${p1.y}, ${midX} ${p2.y}, ${p2.x} ${p2.y}`;
          return (
            <g key={i}>
              <path d={path} fill="none" stroke="#52525b" strokeWidth={1.4} markerEnd="url(#arrow-head-outer)" />
              {e.label && (
                <text
                  x={midX}
                  y={p1.y - 6}
                  textAnchor="middle"
                  fontSize={10}
                  fill="#a1a1aa"
                  fontFamily="ui-monospace, SFMono-Regular, Consolas, monospace"
                >
                  {e.label}
                </text>
              )}
            </g>
          );
        })}
        {nodes.map((n) => (
          <FlowNodeShape key={n.id} node={n} />
        ))}
      </svg>
    </div>
  );
}

function Legend() {
  const items: { kind: NodeKind; label: string }[] = [
    { kind: "input",    label: "input" },
    { kind: "compute",  label: "compute" },
    { kind: "model",    label: "LSTM" },
    { kind: "llm",      label: "LLM call" },
    { kind: "decision", label: "decision" },
    { kind: "io",       label: "I/O" },
    { kind: "action",   label: "trade signal" },
    { kind: "skip",     label: "wait / skip" },
  ];
  return (
    <div className="flex flex-wrap items-center gap-3 px-1 py-2 text-[10px] text-zinc-400 font-mono">
      {items.map((it) => {
        const s = KIND_STYLE[it.kind];
        return (
          <span key={it.kind} className="inline-flex items-center gap-1.5">
            <span
              className="inline-block size-3 rounded-sm border"
              style={{ backgroundColor: s.fill, borderColor: s.stroke }}
            />
            {it.label}
          </span>
        );
      })}
    </div>
  );
}

export function WorkflowFlowchart() {
  const [active, setActive] = useState<StrategyId>("lstm_llm_v1");
  const strat = STRATEGIES.find((s) => s.id === active) ?? STRATEGIES[0]!;

  return (
    <div className="space-y-3">
      <OuterLoopDiagram />

      <div className="flex flex-wrap items-center gap-1.5 border-b border-zinc-800 pb-2">
        {STRATEGIES.map((s) => {
          const isActive = s.id === active;
          return (
            <button
              key={s.id}
              type="button"
              onClick={() => setActive(s.id)}
              aria-pressed={isActive}
              className={[
                "rounded-sm border px-2.5 py-1 text-[11px] font-mono transition-colors",
                isActive
                  ? "border-emerald-500/70 bg-emerald-500/10 text-emerald-300"
                  : "border-zinc-700 bg-zinc-800/60 text-zinc-400 hover:bg-zinc-800 hover:text-zinc-200",
              ].join(" ")}
            >
              {s.title}
            </button>
          );
        })}
        <span className="ml-auto text-[10px] text-zinc-500 font-mono">
          decide() body for the selected strategy
        </span>
      </div>

      <StrategyDiagram strat={strat} />
      <Legend />
    </div>
  );
}
