// 0.17.0 — TTS settings panel.
//
// The dashboard's admin modal gets a new section: a form to flip the
// active TTS provider at runtime, pick a voice, set the speaking rate,
// and preview a sample line. The panel reads /admin/tts/status to
// populate the controls + availability map, POSTs /admin/tts/switch on
// save, and POSTs /admin/tts/preview on the synthesize button. The
// active config takes effect on the next TTS synthesis call; in-flight
// synthesis completes with the old config (a provider is per-call).
//
// The provider radios gate on `has_creds[provider]` — the operator
// can't switch to a provider whose env key isn't set, the radio shows
// as disabled with a one-line hint. The preview button always works
// for the active provider (even if it's silence).
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { api } from "../api";

type Provider = "openai" | "elevenlabs" | "silence";

type TtsStatusPayload = {
  config: { provider: Provider; voice: string; speaking_rate: number };
  available_providers: Provider[];
  has_creds: Record<Provider, boolean>;
  voices_by_provider: Record<Provider, string[]>;
  cost_per_1k_chars_usd: Record<Provider, number>;
  creds_present: boolean;
};

type PreviewPayload = {
  provider: Provider;
  voice: string;
  duration_sec: number;
  cost_usd: number;
  total_calls: number;
  total_cost_usd: number;
  audio_base64: string;
  mime: string;
};

const PROVIDER_LABELS: Record<Provider, string> = {
  openai: "OpenAI TTS",
  elevenlabs: "ElevenLabs",
  silence: "Silence (CI / dev)",
};

const PROVIDER_DESCRIPTIONS: Record<Provider, string> = {
  openai: "tts-1-hd. $0.015 per 1k chars. Cloud.",
  elevenlabs: "ElevenLabs flash v2.5. $0.30 per 1k chars. Cloud.",
  silence: "No audio. Wav filled with silence at the right duration. Free, no creds.",
};

export function TtsSettingsPanel() {
  const { data, error, mutate } = useSWR<TtsStatusPayload>(
    "tts-status",
    api.ttsStatus,
    { refreshInterval: 15_000, shouldRetryOnError: false },
  );

  const [provider, setProvider] = useState<Provider>("silence");
  const [voice, setVoice] = useState<string>("silent");
  const [speakingRate, setSpeakingRate] = useState<number>(1.0);
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [saveError, setSaveError] = useState<string | null>(null);

  // Sync the form state to the active config when the status payload
  // arrives or changes. The dashboard's "revert to env" button (when
  // added) calls mutate() which fires this effect.
  useEffect(() => {
    if (data) {
      setProvider(data.config.provider);
      setVoice(data.config.voice);
      setSpeakingRate(data.config.speaking_rate);
    }
  }, [data]);

  const voicesForProvider = useMemo<string[]>(
    () => data?.voices_by_provider[provider] ?? [],
    [data, provider],
  );

  // If the active voice isn't in the selected provider's list (a
  // common case after a provider switch), fall back to the first
  // available voice. Don't clobber the user's in-progress voice
  // selection — only do this when the active config changed.
  useEffect(() => {
    if (voicesForProvider.length === 0) return;
    if (!voicesForProvider.includes(voice)) {
      setVoice(voicesForProvider[0] ?? "");
    }
  }, [voicesForProvider, voice]);

  const canSave = useMemo(() => {
    if (!data) return false;
    if (!voice || !voice.trim()) return false;
    if (provider === "openai" && !data.has_creds.openai) return false;
    if (provider === "elevenlabs" && !data.has_creds.elevenlabs) return false;
    return true;
  }, [data, provider, voice]);

  const onSave = async () => {
    if (!canSave) return;
    setSaveState("saving");
    setSaveError(null);
    try {
      await api.ttsSwitch({ provider, voice, speaking_rate: speakingRate });
      setSaveState("saved");
      await mutate();
      // Reset the "saved" badge after 2s so the operator gets a
      // visible confirmation without it lingering.
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("error");
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  };

  const onReset = async () => {
    setSaveState("saving");
    setSaveError(null);
    try {
      await api.ttsReset();
      setSaveState("saved");
      await mutate();
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("error");
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  };

  if (error) {
    return (
      <div className="text-xs text-(--color-loss)">/admin/tts/status unreachable</div>
    );
  }
  if (!data) {
    return <div className="text-xs text-zinc-500">Loading TTS config...</div>;
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500 mb-2">
          Provider
        </div>
        <div className="grid grid-cols-1 gap-2">
          {(["silence", "openai", "elevenlabs"] as const).map((p) => {
            const hasCreds = data.has_creds[p];
            const active = data.config.provider === p;
            return (
              <label
                key={p}
                className={[
                  "flex items-start gap-3 rounded-md border px-3 py-2 cursor-pointer transition-colors",
                  hasCreds
                    ? active
                      ? "border-(--color-profit) bg-emerald-500/5"
                      : "border-zinc-700 hover:border-zinc-500"
                    : "border-zinc-800 bg-zinc-900/30 opacity-60 cursor-not-allowed",
                ].join(" ")}
              >
                <input
                  type="radio"
                  name="tts-provider"
                  value={p}
                  checked={provider === p}
                  onChange={() => setProvider(p)}
                  disabled={!hasCreds}
                  className="mt-1"
                />
                <div className="flex-1 min-w-0">
                  <div className="text-sm font-semibold text-zinc-100">
                    {PROVIDER_LABELS[p]}
                    {active && (
                      <span className="ml-2 text-[9px] uppercase tracking-[0.3em] text-(--color-profit)">
                        Active
                      </span>
                    )}
                  </div>
                  <div className="text-[11px] text-zinc-500 mt-0.5">
                    {PROVIDER_DESCRIPTIONS[p]}
                  </div>
                  {!hasCreds && p !== "silence" && (
                    <div className="text-[10px] text-(--color-loss) mt-1 font-mono">
                      {p === "openai" ? "OPENAI_API_KEY" : "ELEVENLABS_API_KEY"} not set
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <div>
        <label
          htmlFor="tts-voice"
          className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500 mb-1 block"
        >
          Voice
        </label>
        <select
          id="tts-voice"
          value={voice}
          onChange={(e) => setVoice(e.target.value)}
          className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100"
          disabled={voicesForProvider.length === 0}
        >
          {voicesForProvider.map((v) => (
            <option key={v} value={v}>
              {v}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label
          htmlFor="tts-rate"
          className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500 mb-1 block"
        >
          Speaking rate ({speakingRate.toFixed(2)}x)
        </label>
        <input
          id="tts-rate"
          type="range"
          min={0.25}
          max={4.0}
          step={0.05}
          value={speakingRate}
          onChange={(e) => setSpeakingRate(Number(e.target.value))}
          className="w-full"
        />
        <div className="flex justify-between text-[10px] text-zinc-600 font-mono mt-0.5">
          <span>0.25x (slow)</span>
          <span>1.0x</span>
          <span>4.0x (fast)</span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={onSave}
          disabled={!canSave || saveState === "saving"}
          className="px-3 py-1.5 rounded-md bg-(--color-profit) text-zinc-950 text-sm font-semibold disabled:opacity-40 disabled:cursor-not-allowed hover:opacity-90 transition-opacity"
        >
          {saveState === "saving" ? "Saving..." : "Save"}
        </button>
        <button
          type="button"
          onClick={onReset}
          disabled={saveState === "saving"}
          className="px-3 py-1.5 rounded-md border border-zinc-700 text-zinc-300 text-sm hover:bg-zinc-800 transition-colors"
        >
          Revert to env defaults
        </button>
        {saveState === "saved" && (
          <span className="text-xs text-(--color-profit) font-mono">Saved</span>
        )}
        {saveState === "error" && saveError && (
          <span className="text-xs text-(--color-loss) font-mono">{saveError}</span>
        )}
      </div>

      <PreviewSection provider={provider} voice={voice} hasCreds={data.has_creds} />

      <TtsSpendWidget />
    </div>
  );
}

function PreviewSection({
  provider,
  voice,
  hasCreds,
}: {
  provider: Provider;
  voice: string;
  hasCreds: Record<Provider, boolean>;
}) {
  const [text, setText] = useState("Hello from TradeFarm.");
  const [previewing, setPreviewing] = useState(false);
  const [result, setResult] = useState<PreviewPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canPreview = useMemo(() => {
    if (!text.trim()) return false;
    if (provider === "openai" && !hasCreds.openai) return false;
    if (provider === "elevenlabs" && !hasCreds.elevenlabs) return false;
    return true;
  }, [text, provider, hasCreds]);

  const onPreview = async () => {
    if (!canPreview) return;
    setPreviewing(true);
    setError(null);
    setResult(null);
    try {
      const payload = await api.ttsPreview({ text, provider, voice });
      setResult(payload);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPreviewing(false);
    }
  };

  return (
    <div className="border-t border-zinc-800 pt-3">
      <div className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500 mb-1">
        Preview
      </div>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 resize-y"
        placeholder="Type a line to preview..."
      />
      <div className="flex items-center gap-2 mt-2">
        <button
          type="button"
          onClick={onPreview}
          disabled={!canPreview || previewing}
          className="px-3 py-1.5 rounded-md border border-zinc-700 text-zinc-200 text-sm hover:bg-zinc-800 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {previewing ? "Synthesizing..." : "Synthesize"}
        </button>
        {!canPreview && provider !== "silence" && (
          <span className="text-[10px] text-(--color-loss) font-mono">
            {provider === "openai" ? "OPENAI_API_KEY" : "ELEVENLABS_API_KEY"} not set
          </span>
        )}
      </div>
      {error && (
        <div className="mt-2 text-xs text-(--color-loss) font-mono">{error}</div>
      )}
      {result && (
        <div className="mt-2 space-y-1">
          <div className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500">
            {result.provider} / {result.voice} · {result.duration_sec}s · ${result.cost_usd.toFixed(4)}
          </div>
          <audio controls src={`data:${result.mime};base64,${result.audio_base64}`} className="w-full h-8" />
        </div>
      )}
    </div>
  );
}

function TtsSpendWidget() {
  const { data } = useSWR<{ chars_synthesized: number; cost_usd: number; calls: number; active_provider: Provider }>(
    "tts-stats",
    api.ttsStats,
    { refreshInterval: 5_000, shouldRetryOnError: false },
  );
  if (!data) return null;
  return (
    <div className="border-t border-zinc-800 pt-2 text-[10px] font-mono text-zinc-500">
      Today: {data.calls} calls · {data.chars_synthesized} chars · ${data.cost_usd.toFixed(4)} · active: {data.active_provider}
    </div>
  );
}
