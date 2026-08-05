// Derive the 10-subsystem pipeline card state from the active run
// (when one is in flight) or fall back to the mock fixture.
//
// Why this exists
// ---------------
// The VOD studio's pipeline surface is a 10-card grid that was
// designed against the original prototype, which had two prototype-only
// steps (script writer, thumbnail generator) and labelled the headless
// renderer card as "render" / "Headless renderer". The real
// `tradefarm.render.pipeline` runner ships 8 steps keyed differently:
//
//   mock id   step key      label
//   -------   ---------     ----------------------------------
//   session   session       session.run
//   beats     beats         session.beats
//   render    headless      render.headless
//   stitch    stitch        render.stitch
//   script    (none)        prototype-only, no runner step
//   tts       tts           tts.run
//   mix       mix           render.mix
//   thumb     (none)        prototype-only, no runner step
//   meta      metadata      yt.metadata
//   upload    upload        yt.upload
//
// When the operator hits "run pipeline" we want the cards to reflect
// the real run state — not the mock. This helper takes the mock array
// (so the prototype-only script/thumb cards still appear in the grid)
// and overlays the run's `last_lines` tail to compute per-card
// status, started/finished, and a focused log tail.
//
// Pure function — no React, no fetch. Trivially testable with
// canned `last_lines` strings; the runner's banner format lives in
// `src/tradefarm/render/pipeline.py:run_pipeline` and is the single
// source of truth this file mirrors.

import type { PipelineNode, PipelineStatus } from "./types";
import type { PipelineRunRow } from "../api";

// Mock card id -> real step key. `null` means the card is a
// prototype-only artifact with no matching step in the runner.
const MOCK_ID_TO_STEP_KEY: Record<string, string | null> = {
  session: "session",
  beats: "beats",
  render: "headless",
  stitch: "stitch",
  script: null,
  tts: "tts",
  mix: "mix",
  thumb: null,
  meta: "metadata",
  upload: "upload",
};

// Canonical step label (matches the suffix of the runner's
// "step N/M: {label}" banner). Kept narrow so a regex match is
// unambiguous against the runner's many colons.
const STEP_LABEL_BY_KEY: Record<string, string> = {
  session: "session.run",
  beats: "session.beats",
  headless: "render.headless",
  stitch: "render.stitch",
  tts: "tts.run",
  mix: "render.mix",
  metadata: "yt.metadata",
  upload: "yt.upload",
};

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") as string;
}

interface Derived {
  status: PipelineStatus;
  started: string | null;
  finished: string | null;
  durationSec: number | null;
  tail: string[];
}

function deriveOne(_mock: PipelineNode, stepKey: string, activeRun: PipelineRunRow): Derived {
  // `stepKey` is always one of the 8 known pipeline keys; the lookup
  // is total. The `!` is to satisfy `noUncheckedIndexedAccess`.
  const label = STEP_LABEL_BY_KEY[stepKey]!;
  const startRe = new RegExp(`^step\\s+\\d+/\\d+:\\s+${escapeRegex(label)}(?:\\s|$)`);
  const anyStartRe = /^step\s+\d+\/\d+:\s+/;
  const doneRe = /^DONE:/;

  const startIdx = activeRun.last_lines.findIndex((ln) => startRe.test(ln));
  if (startIdx < 0) {
    return {
      status: "queued",
      started: null,
      finished: null,
      durationSec: null,
      tail: ["[—] waiting for prior steps"],
    };
  }

  const startLine = activeRun.last_lines[startIdx];
  if (startLine === undefined) {
    // Defensive: findIndex matched but the value is gone (race in
    // the polling path). Treat as queued.
    return {
      status: "queued",
      started: null,
      finished: null,
      durationSec: null,
      tail: ["[—] waiting for prior steps"],
    };
  }

  // "step 1/8: session.run  [skipped — ...]" — the runner didn't
  // execute this step, but it's effectively "done" from the
  // operator's POV (output already on disk, or the step was filtered).
  if (/\[skipped/.test(startLine)) {
    return {
      status: "done",
      started: "—",
      finished: "—",
      durationSec: null,
      tail: [startLine],
    };
  }

  const after = activeRun.last_lines.slice(startIdx + 1);
  const nextStart = after.findIndex((ln) => anyStartRe.test(ln));
  const doneIdx = after.findIndex((ln) => doneRe.test(ln));

  // No later step + no DONE banner -> still running. If the run as a
  // whole failed, mark this step as failed too (we can't know which
  // step blew up; the runner fails fast on the first exception).
  if (nextStart < 0 && doneIdx < 0) {
    const failed = activeRun.status === "failed";
    const tail = after.slice(-5);
    return {
      status: failed ? "failed" : "running",
      started: "—",
      finished: null,
      durationSec: null,
      tail: tail.length > 0 ? tail : [startLine],
    };
  }

  const endIdx = nextStart >= 0 ? nextStart : doneIdx;
  const tailSlice = after.slice(0, endIdx);
  return {
    status: "done",
    started: "—",
    finished: "—",
    durationSec: null,
    tail: tailSlice.length > 0 ? tailSlice : [startLine],
  };
}

export function deriveNodesFromRun(
  mockNodes: PipelineNode[],
  activeRun: PipelineRunRow,
): PipelineNode[] {
  return mockNodes.map((mock) => {
    const stepKey = MOCK_ID_TO_STEP_KEY[mock.id];

    // Prototype-only card (script, thumb) — the real pipeline doesn't
    // touch these. Keep it in the grid so the 10-card layout stays
    // stable, but mark as queued with an honest note.
    if (!stepKey) {
      return {
        ...mock,
        status: "queued" as PipelineStatus,
        started: null,
        finished: null,
        durationSec: null,
        tail: [
          "[—] prototype-only — no matching step in tradefarm.render.pipeline",
        ],
      };
    }

    // Step exists in the runner but wasn't enabled for this run
    // (filtered by --include-tts/--include-upload, or excluded by
    // skip_headless, or skipped when resuming a session). Show as
    // queued with a "not in --include" note.
    if (!activeRun.enabled.includes(stepKey)) {
      return {
        ...mock,
        status: "queued" as PipelineStatus,
        started: null,
        finished: null,
        durationSec: null,
        tail: [
          `[—] step "${stepKey}" not in --include set; not run for this run`,
        ],
      };
    }

    // Step is enabled. Compute the live state from the run's log tail.
    const d = deriveOne(mock, stepKey, activeRun);
    return {
      ...mock,
      status: d.status,
      started: d.started,
      finished: d.finished,
      durationSec: d.durationSec,
      tail: d.tail,
    };
  });
}
