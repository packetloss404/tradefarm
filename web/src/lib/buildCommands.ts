import type { AgentRow } from "../api";
import { MACROS, runMacro } from "../components/broadcast/BroadcastMacrosSection";
import type { Command } from "./commands";

const TOP_SYMBOLS = [
  "SPY",
  "QQQ",
  "IWM",
  "AAPL",
  "MSFT",
  "NVDA",
  "AMZN",
  "META",
  "GOOGL",
  "TSLA",
] as const;

const STREAM_SCENES: { id: string; pretty: string }[] = [
  { id: "hero", pretty: "Hero" },
  { id: "leaderboard", pretty: "Leaderboard" },
  { id: "showdown", pretty: "Showdown" },
  { id: "brain", pretty: "Brain" },
  { id: "strategy", pretty: "Strategy" },
  { id: "recap", pretty: "Recap" },
];

async function postStreamCmd(type: string, payload: Record<string, unknown>): Promise<void> {
  try {
    const r = await fetch("/api/stream/cmd", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, payload }),
    });
    if (!r.ok) {
      console.warn(`stream/cmd ${type} -> ${r.status} ${r.statusText}`);
    }
  } catch (e) {
    console.warn(`stream/cmd ${type} failed`, e);
  }
}

export type BuildCommandsDeps = {
  agents: AgentRow[];
  onSelectAgent: (id: number) => void;
  onManualTick: () => Promise<void>;
  onOpenAdmin: () => void;
  onOpenBacktest?: () => void;
};

export function buildCommands(deps: BuildCommandsDeps): Command[] {
  const cmds: Command[] = [];

  for (const a of deps.agents) {
    cmds.push({
      id: `agent-${a.id}`,
      label: `Go to ${a.name}`,
      hint: `${a.strategy} · rank ${a.rank ?? "intern"}`,
      section: "Navigation",
      action: () => deps.onSelectAgent(a.id),
    });
  }

  for (const sym of TOP_SYMBOLS) {
    cmds.push({
      id: `symbol-${sym}`,
      label: `Find ${sym}`,
      hint: "Filter agent grid by symbol",
      section: "Navigation",
      // TODO: wire to a real symbol filter on the agent grid.
      action: () => {},
    });
  }

  for (const scene of STREAM_SCENES) {
    cmds.push({
      id: `stream-scene-${scene.id}`,
      label: `Force scene: ${scene.pretty}`,
      section: "Stream",
      action: () => postStreamCmd("stream_scene", { scene_id: scene.id }),
    });
  }

  cmds.push({
    id: "stream-preroll",
    label: "Replay pre-roll opener",
    section: "Stream",
    action: () => postStreamCmd("stream_preroll", {}),
  });

  cmds.push({
    id: "stream-audio-toggle",
    label: "Toggle stream audio mute",
    section: "Stream",
    action: () => postStreamCmd("stream_audio", { enabled: false, volume: 0 }),
  });

  for (const macro of MACROS) {
    cmds.push({
      id: `macro-${macro.id}`,
      label: `Macro: ${macro.label}`,
      section: "Macros",
      action: () => runMacro(macro, ""),
    });
  }

  cmds.push({
    id: "open-admin",
    label: "Open Admin Panel",
    section: "Admin",
    action: () => deps.onOpenAdmin(),
  });

  cmds.push({
    id: "manual-tick",
    label: "Manual Tick",
    section: "Tick",
    action: () => deps.onManualTick(),
  });

  cmds.push({
    id: "run-backtest",
    label: "Run Backtest",
    section: "Admin",
    action: () => {
      if (deps.onOpenBacktest) deps.onOpenBacktest();
      else alert("backtest opener not wired");
    },
  });

  return cmds;
}
