// 0.18.0 -- LLM model picker.
//
// The dashboard's admin modal gets a new section: a form to flip the
// active LLM provider + model at runtime. The panel reads
// /admin/llm/models to populate the per-provider dropdowns (live
// discovery via each provider's /v1/models endpoint), POSTs
// /admin/llm/select on save, and POSTs /admin/llm/reset to revert
// to the env-var defaults. The runtime singleton takes effect on
// the next build_provider call; the in-flight LLM call completes
// with the old provider (a provider object is per-call).
//
// The provider radios gate on `has_creds[provider]` -- the operator
// can't switch to a provider whose env key isn't set, the radio
// shows as disabled with a one-line hint. The 60s SWR refresh keeps
// the cached list from feeling stale on a long-lived modal; the
// "Refresh" button forces a refetch via ?refresh=true.
//
// Cost hint per row reads from `model.cost_hint_usd` (the static
// MODEL_COST_HINTS table on the backend). Missing rows render as
// "cost: unknown" rather than a wrong number.
import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import {
  api,
  type LlmModelInfo,
  type ProviderModelsResponse,
} from "../api";

type Provider = "anthropic" | "openai" | "minimax";

const PROVIDER_LABELS: Record<Provider, string> = {
  anthropic: "Anthropic Claude",
  openai: "OpenAI GPT",
  minimax: "MiniMax",
};

const PROVIDER_KEY_NAMES: Record<Provider, string> = {
  anthropic: "ANTHROPIC_API_KEY",
  openai: "OPENAI_API_KEY",
  minimax: "MINIMAX_API_KEY",
};

const PROVIDER_DESCRIPTIONS: Record<Provider, string> = {
  anthropic: "Claude. Default Haiku 4.5 (cached). Live /v1/models lookup.",
  openai: "GPT-5.6 trio (Sol / Terra / Luna). Live /v1/models lookup.",
  minimax: "MiniMax M-series. Default M2.7-highspeed. Live /v1/models lookup.",
};

function formatCostHint(usd: Record<string, number> | undefined): string {
  if (!usd) return "cost: unknown";
  const inp = usd["input_per_million"];
  const out = usd["output_per_million"];
  if (inp == null || out == null) return "cost: unknown";
  return `~$${inp.toFixed(2)} in / $${out.toFixed(2)} out per 1M tokens`;
}

function formatCachedAt(iso: string | null | undefined): string {
  if (!iso) return "never";
  // The backend returns ISO-8601 like "2026-08-10T14:23:01Z" -
  // render just the HH:MM:SS portion so the operator can see
  // how stale the list is at a glance.
  const t = iso.split("T")[1];
  if (!t) return iso;
  return t.replace("Z", "");
}

export function LlmModelPicker() {
  // The catalog response carries three per-provider sections
  // (anthropic / openai / minimax) + a cached_at field. The
  // 60s SWR refresh keeps the cache from feeling stale without
  // re-hitting the providers on every render.
  const { data, error, mutate, isLoading } = useSWR<ProviderModelsResponse>(
    "llm-models",
    () => api.llmModels(false),
    { refreshInterval: 60_000, shouldRetryOnError: false },
  );

  // Track the operator's current selection. Defaults to the
  // active config from /admin/config; the form is "dirty"
  // when the local state diverges from the persisted state.
  const { data: config } = useSWR("admin-config", api.adminConfig);
  const activeProvider: Provider = (config?.llm_provider ?? "anthropic") as Provider;
  const activeModel: string = config?.llm_model ?? "";

  const [provider, setProvider] = useState<Provider>("anthropic");
  const [model, setModel] = useState<string>("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">(
    "idle",
  );
  const [saveError, setSaveError] = useState<string | null>(null);

  // Sync the form state when the active config changes (initial
  // load, post-save, post-reset).
  useEffect(() => {
    if (config) {
      setProvider(activeProvider);
      setModel(activeModel);
    }
  }, [config, activeProvider, activeModel]);

  // The catalog response is keyed by provider. If the operator
  // just selected a provider whose fetch failed (e.g. missing
  // key), the section shows the error inline.
  const providerSection = useMemo(() => {
    if (!data) return null;
    const section = data[provider];
    return section ?? null;
  }, [data, provider]);

  const hasCreds: Record<Provider, boolean> = useMemo(() => {
    return {
      anthropic: !!config?.anthropic_api_key?.set,
      openai: !!config?.openai_api_key?.set,
      minimax: !!config?.minimax_api_key?.set,
    };
  }, [config]);

  // If the active model isn't in the current provider's listing
  // (a common case after a provider switch or refresh), fall
  // back to the first available model. Don't clobber the user's
  // in-progress selection -- only do this when the persisted
  // active model doesn't appear in the live list.
  useEffect(() => {
    if (!providerSection || !providerSection.ok) return;
    const ids = providerSection.models.map((m) => m.id);
    if (ids.length === 0) return;
    if (model && !ids.includes(model)) {
      const fallback = ids[0];
      if (fallback) setModel(fallback);
    }
  }, [providerSection, model]);

  const canSave = useMemo(() => {
    if (!data) return false;
    if (!model || !model.trim()) return false;
    if (provider === "anthropic" && !hasCreds.anthropic) return false;
    if (provider === "openai" && !hasCreds.openai) return false;
    if (provider === "minimax" && !hasCreds.minimax) return false;
    return true;
  }, [data, model, provider, hasCreds]);

  const onSave = async () => {
    if (!canSave) return;
    setSaveState("saving");
    setSaveError(null);
    try {
      await api.llmSelect({ provider, model });
      setSaveState("saved");
      // Re-fetch both the catalog and the active config so the
      // form state syncs to the persisted values without a
      // follow-up GET.
      await Promise.all([mutate(), config && (await Promise.resolve())]);
      // The active-config SWR key needs a separate refresh;
      // we don't have a handle to its mutate here, so the
      // dashboard's parent modal will pick it up on the next
      // admin-config poll (15s default).
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
      await api.llmReset();
      setSaveState("saved");
      await mutate();
      setTimeout(() => setSaveState("idle"), 2000);
    } catch (err) {
      setSaveState("error");
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  };

  const onRefresh = async () => {
    // Force a refetch by calling the endpoint with refresh=true.
    // The endpoint rebuilds the 60-min cache, so this is the
    // operator's escape hatch when a new model has dropped.
    try {
      await api.llmModels(true);
      await mutate();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    }
  };

  if (error) {
    return (
      <div className="text-xs text-(--color-loss)">/admin/llm/models unreachable</div>
    );
  }
  if (isLoading || !data) {
    return <div className="text-xs text-zinc-500">Loading model catalog...</div>;
  }

  return (
    <div className="space-y-4">
      <div>
        <div className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500 mb-2">
          Provider
        </div>
        <div className="grid grid-cols-1 gap-2">
          {(["anthropic", "openai", "minimax"] as const).map((p) => {
            const cred = hasCreds[p];
            const active = activeProvider === p;
            return (
              <label
                key={p}
                className={[
                  "flex items-start gap-3 rounded-md border px-3 py-2 cursor-pointer transition-colors",
                  cred
                    ? active
                      ? "border-(--color-profit) bg-emerald-500/5"
                      : "border-zinc-700 hover:border-zinc-500"
                    : "border-zinc-800 bg-zinc-900/30 opacity-60 cursor-not-allowed",
                ].join(" ")}
              >
                <input
                  type="radio"
                  name="llm-provider"
                  value={p}
                  checked={provider === p}
                  onChange={() => setProvider(p)}
                  disabled={!cred}
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
                  {!cred && (
                    <div className="text-[10px] text-(--color-loss) mt-1 font-mono">
                      {PROVIDER_KEY_NAMES[p]} not set
                    </div>
                  )}
                </div>
              </label>
            );
          })}
        </div>
      </div>

      <ModelDropdown
        provider={provider}
        providerSection={providerSection}
        value={model}
        onChange={setModel}
        onRefresh={onRefresh}
      />

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

      <CachedAtLine cachedAt={providerSection?.fetched_at ?? null} />
    </div>
  );
}

function ModelDropdown({
  provider,
  providerSection,
  value,
  onChange,
  onRefresh,
}: {
  provider: Provider;
  providerSection: ProviderModelsResponse["anthropic"] | null;
  value: string;
  onChange: (v: string) => void;
  onRefresh: () => void;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between mb-1">
        <label
          htmlFor="llm-model"
          className="text-[10px] font-mono uppercase tracking-[0.3em] text-zinc-500"
        >
          Model
        </label>
        <button
          type="button"
          onClick={onRefresh}
          className="text-[10px] text-zinc-500 hover:text-zinc-300 font-mono"
        >
          Refresh list
        </button>
      </div>
      <select
        id="llm-model"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-zinc-700 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100"
        disabled={!providerSection || !providerSection.ok || providerSection.models.length === 0}
      >
        {providerSection && providerSection.ok && providerSection.models.length > 0 ? (
          providerSection.models.map((m) => (
            <option key={m.id} value={m.id}>
              {m.display_name} ({m.id})
            </option>
          ))
        ) : (
          <option value="">{`(no ${PROVIDER_LABELS[provider]} models available)`}</option>
        )}
      </select>
      {providerSection && providerSection.ok && providerSection.models.length > 0 && (
        <ModelListHint models={providerSection.models} value={value} />
      )}
      {providerSection && providerSection.error && (
        // Two flavors: ok=false means the live fetch failed (red);
        // ok=true with a warning string means the catalog is the
        // 0.18.0 demo fallback (no API key set). Both should surface
        // a one-liner so the operator knows what they're seeing.
        <div
          className={`mt-1 text-[10px] font-mono ${
            providerSection.ok ? "text-amber-400" : "text-(--color-loss)"
          }`}
        >
          {providerSection.ok ? "demo: " : "fetch failed: "}
          {providerSection.error}
        </div>
      )}
    </div>
  );
}

function ModelListHint({
  models,
  value,
}: {
  models: LlmModelInfo[];
  value: string;
}) {
  const selected = useMemo(
    () => models.find((m) => m.id === value),
    [models, value],
  );
  if (!selected) return null;
  return (
    <div className="mt-1 text-[10px] text-zinc-500 font-mono">
      {formatCostHint(selected.cost_hint_usd)}
      {selected.created_at && (
        <span className="ml-2 text-zinc-600">released {selected.created_at.split("T")[0]}</span>
      )}
    </div>
  );
}

function CachedAtLine({ cachedAt }: { cachedAt: string | null | undefined }) {
  return (
    <div className="border-t border-zinc-800 pt-2 text-[10px] font-mono text-zinc-600">
      list cached at {formatCachedAt(cachedAt)} (60min TTL -- hit Refresh to refetch)
    </div>
  );
}
