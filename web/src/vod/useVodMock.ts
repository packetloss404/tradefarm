import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BEATS,
  DAY_SUMMARY,
  PIPELINE,
  SESSION_DATE,
  SESSION_EP_NUMBER,
  SESSION_ID,
  SESSION_LABEL,
  VOD_AGENTS,
  type Agent,
  type Beat,
  type DaySummary,
  type PipelineNode,
} from "./mockData";

export type VodMock = {
  sessionDate: string;
  sessionLabel: string;
  sessionId: string;
  episodeNumber: number;
  agents: Agent[];
  beats: Beat[];
  selectedBeats: Set<string>;
  toggleBeat: (id: string) => void;
  totalDuration: number;
  pipeline: PipelineNode[];
  renderProgress: number;
  renderTick: number;
  summary: DaySummary;
};

export function useVodMock(): VodMock {
  // Light "render is progressing" tick so the pipeline view animates.
  const [renderTick, setRenderTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setRenderTick((t) => t + 1), 800);
    return () => window.clearInterval(id);
  }, []);

  const [selectedBeats, setSelectedBeats] = useState<Set<string>>(
    () => new Set(BEATS.filter((b) => b.selected).map((b) => b.id)),
  );
  const toggleBeat = useCallback((id: string) => {
    setSelectedBeats((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const totalDuration = useMemo(
    () => BEATS.filter((b) => selectedBeats.has(b.id)).reduce((s, b) => s + b.duration, 0),
    [selectedBeats],
  );

  // Synthesize a creeping "current render progress" off renderTick so the
  // headless-renderer card looks alive even though it's a mock.
  const renderProgress = Math.min(1, 0.62 + (renderTick % 30) * 0.001);

  return {
    sessionDate: SESSION_DATE,
    sessionLabel: SESSION_LABEL,
    sessionId: SESSION_ID,
    episodeNumber: SESSION_EP_NUMBER,
    agents: VOD_AGENTS,
    beats: BEATS,
    selectedBeats,
    toggleBeat,
    totalDuration,
    pipeline: PIPELINE,
    renderProgress,
    renderTick,
    summary: DAY_SUMMARY,
  };
}
