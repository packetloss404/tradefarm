// TradeFarm 0.18.0 admin modal — "McLove" pass.
//
// Operator-facing surface for runtime config + every live action that
// isn't reachable from the main dashboard (AI kill switch, provider /
// model swap, backtest launcher, curriculum pass, TTS settings). The
// modal is a `role="dialog"` with a focus trap (see `useFocusTrap`),
// an Esc-to-close handler, and a labelled close button.
//
// Section ordering (top to bottom, McLove 0.18.0):
//   1. AI Control       — master kill switch
//   2. Brain Provider   — API key fields for all 3 providers (no radio;
//                         the LLM Model section owns the provider switch)
//   3. LLM Model        — model picker: 3-provider radio + per-provider
//                         model dropdown + save (single source of truth)
//   4. Tuning           — min-confidence slider, daily budget, tick cadence
//   5. Execution        — simulated vs alpaca_paper (read-only-ish; flip
//                         still hits the config but backend comment
//                         notes this is intended to require a restart
//                         in the audited fix)
//   6. Strategies       — per-strategy enable / disable toggles
//   7. Backtest         — launch the LSTM walk-forward job
//   8. Curriculum       — run an evaluation pass
//   9. TTS              — embedded TtsSettingsPanel
//
// The "Coming soon" placeholder from 0.17.0 is removed in 0.18.0 —
// the McLove pass drops dead UI rather than label it.

import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, type AdminConfig, type AdminPatch } from "../api";
import { BacktestModal } from "./BacktestModal";
import { LlmModelPicker } from "./LlmModelPicker";
import { TtsSettingsPanel } from "./TtsSettingsPanel";
import { useFocusTrap } from "../lib/useFocusTrap";

const ADMIN_TITLE_ID = "admin-modal-title";

export function AdminModal({ onClose }: { onClose: () => void }) {
  const [backtestOpen, setBacktestOpen] = useState(false);
  const { data, error, mutate } = useSWR<AdminConfig>("admin-config", api.adminConfig);
  const [draft, setDraft] = useState<AdminPatch>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const [curriculumBusy, setCurriculumBusy] = useState(false);
  const dialogRef = useFocusTrap<HTMLDivElement>(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (error) {
    return (
      <Shell onClose={onClose} titleId={ADMIN_TITLE_ID} dialogRef={dialogRef}>
        <div className="p-5 text-sm text-rose-400">Failed to load admin config: {(error as Error).message}</div>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell onClose={onClose} titleId={ADMIN_TITLE_ID} dialogRef={dialogRef}>
        <div className="p-5 text-sm text-zinc-500">Loading...</div>
      </Shell>
    );
  }

  const d = { ...data, ...draft } as AdminConfig & AdminPatch;
  const setField = <K extends keyof AdminPatch>(k: K, v: AdminPatch[K]) =>
    setDraft((prev) => ({ ...prev, [k]: v }));

  const save = async () => {
    setBusy(true);
    setMsg("");
    try {
      const res = await api.adminPatch({ ...draft, persist: true });
      const changed = Object.keys(res.changed);
      setMsg(
        changed.length
          ? `saved: ${changed.join(", ")}${res.overlay ? ` · brain -> ${res.overlay.provider}/${res.overlay.model}` : ""}`
          : "nothing changed",
      );
      setDraft({});
      await mutate();
    } catch (e) {
      setMsg(`error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const toggleAi = async () => {
    setBusy(true);
    setMsg("");
    try {
      const next = !d.ai_enabled;
      await api.adminToggleAi(next);
      setField("ai_enabled", next);
      await mutate();
    } catch (e) {
      setMsg(`error: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const runCurriculum = async () => {
    setCurriculumBusy(true);
    setMsg("");
    try {
      const res = await api.runCurriculum();
      const total = res.promoted.length + res.demoted.length + res.unchanged;
      setMsg(
        `evaluated ${total} agents · ${res.promoted.length} promoted · ${res.demoted.length} demoted`,
      );
    } catch (e) {
      setMsg(`error: ${(e as Error).message}`);
    } finally {
      setCurriculumBusy(false);
    }
  };

  const anthropicPlaceholder = data.anthropic_api_key.set ? data.anthropic_api_key.masked : "sk-ant-...";
  const minimaxPlaceholder = data.minimax_api_key.set ? data.minimax_api_key.masked : "paste key";

  return (
    <Shell onClose={onClose} titleId={ADMIN_TITLE_ID} dialogRef={dialogRef}>
      <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
        <div>
          <div id={ADMIN_TITLE_ID} className="text-lg font-semibold">Admin</div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">runtime config · persists to .env</div>
        </div>
        <button
          onClick={onClose}
          aria-label="Close admin modal"
          className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700"
        >
          esc
        </button>
      </header>

      <div className="space-y-5 p-5">
        {/* 1. AI Control */}
        <Section label="AI Control">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm">Scheduled ticks</div>
              <div className="text-[11px] text-zinc-500">When off, agents freeze but dashboard keeps running.</div>
            </div>
            <Toggle
              value={!!d.ai_enabled}
              onChange={toggleAi}
              disabled={busy}
              label="Scheduled ticks on/off"
            />
          </div>
        </Section>

        {/* 2. Brain Provider — API key fields for all 3 providers. No
            provider radio here; the LLM Model section owns provider +
            model as a single source of truth. The operator can paste a
            key for any provider regardless of which is active, so all
            three Rows render unconditionally. */}
        <Section label="Brain Provider">
          <div className="space-y-3">
            <Row
              htmlFor="anthropic-api-key"
              label="Anthropic API key"
              hint={data.anthropic_api_key.set ? "set — paste a new one to replace" : "not set"}
              badge={data.anthropic_api_key.set ? "set" : null}
            >
              <input
                id="anthropic-api-key"
                type="password"
                value={d.anthropic_api_key ?? ""}
                onChange={(e) => setField("anthropic_api_key", e.target.value)}
                placeholder={anthropicPlaceholder}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>

            <Row
              htmlFor="openai-api-key"
              label="OpenAI API key"
              hint={data.openai_api_key?.set ? "set — paste a new one to replace" : "not set"}
              badge={data.openai_api_key?.set ? "set" : null}
            >
              <input
                id="openai-api-key"
                type="password"
                value={d.openai_api_key ?? ""}
                onChange={(e) => setField("openai_api_key", e.target.value)}
                placeholder="sk-..."
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>

            <Row
              htmlFor="minimax-api-key"
              label="MiniMax API key"
              hint={data.minimax_api_key.set ? "set — paste a new one to replace" : "not set"}
              badge={data.minimax_api_key.set ? "set" : null}
            >
              <input
                id="minimax-api-key"
                type="password"
                value={d.minimax_api_key ?? ""}
                onChange={(e) => setField("minimax_api_key", e.target.value)}
                placeholder={minimaxPlaceholder}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>
            <Row htmlFor="minimax-base-url" label="MiniMax base URL">
              <input
                id="minimax-base-url"
                type="text"
                value={d.minimax_base_url ?? ""}
                onChange={(e) => setField("minimax_base_url", e.target.value)}
                placeholder="https://api.minimax.io/v1"
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>
          </div>
        </Section>

        {/* 3. LLM Model — the picker owns provider + model as a single
            source of truth. The picker reads the AdminConfig for the
            current provider/model and writes back via /admin/llm/select. */}
        <Section label="LLM Model">
          <LlmModelPicker />
        </Section>

        {/* 4. Tuning */}
        <Section label="Tuning">
          <div className="grid grid-cols-2 gap-3">
            <Row
              htmlFor="llm-min-confidence"
              label={`Min LSTM confidence (${(d.llm_min_confidence ?? 0.4).toFixed(2)})`}
              hint="below this, skip the LLM entirely"
            >
              <input
                id="llm-min-confidence"
                type="range"
                min={0}
                max={0.9}
                step={0.05}
                value={d.llm_min_confidence ?? 0.4}
                onChange={(e) => setField("llm_min_confidence", parseFloat(e.target.value))}
                className="w-full"
              />
            </Row>
            <Row
              htmlFor="llm-daily-budget"
              label={`Daily LLM budget ($${d.llm_daily_budget_usd ?? 0}/day)`}
              hint="0 disables the cap; backend will keep spending"
            >
              <input
                id="llm-daily-budget"
                type="number"
                min={0}
                step={0.5}
                value={d.llm_daily_budget_usd ?? 0}
                onChange={(e) => setField("llm_daily_budget_usd", parseFloat(e.target.value) || 0)}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>
            <Row
              htmlFor="auto-tick-interval"
              label={`Tick every ${d.auto_tick_interval_sec ?? 0}s`}
              hint="0 disables the scheduler"
            >
              <input
                id="auto-tick-interval"
                type="number"
                min={0}
                step={30}
                value={d.auto_tick_interval_sec ?? 0}
                onChange={(e) => setField("auto_tick_interval_sec", parseInt(e.target.value, 10) || 0)}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div className="text-xs">
              <div>Tick outside RTH</div>
              <div className="text-[11px] text-zinc-500">Useful for demos; wastes calls in prod.</div>
            </div>
            <Toggle
              value={!!d.tick_outside_rth}
              onChange={(v) => setField("tick_outside_rth", v)}
              label="Tick outside RTH"
            />
          </div>
        </Section>

        {/* 5. Execution */}
        <Section label="Execution">
          <div role="radiogroup" aria-label="Execution mode" className="flex gap-2">
            {(["simulated", "alpaca_paper"] as const).map((m) => {
              const active = d.execution_mode === m;
              return (
                <label
                  key={m}
                  className={`flex-1 cursor-pointer rounded border px-3 py-2 text-xs font-mono text-center transition-colors ${
                    active
                      ? "border-emerald-500 bg-emerald-950/40 text-emerald-300"
                      : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                  }`}
                >
                  <input
                    type="radio"
                    name="execution-mode"
                    value={m}
                    checked={active}
                    onChange={() => setField("execution_mode", m)}
                    className="sr-only"
                  />
                  {m}
                </label>
              );
            })}
          </div>
          <div className="mt-2 text-[11px] text-zinc-500">
            simulated = local self-fills. alpaca_paper = real orders to Alpaca paper + reconciler loop.
          </div>
        </Section>

        {/* 6. Strategies */}
        <Section label="Strategies">
          <div className="space-y-2">
            {data._meta.known_strategies.map((strat) => {
              const disabled = (d.disabled_strategies ?? []).includes(strat);
              const count = data._meta.strategy_agent_counts[strat] ?? 0;
              const toggle = () => {
                const current = new Set(d.disabled_strategies ?? []);
                if (current.has(strat)) current.delete(strat);
                else current.add(strat);
                setField("disabled_strategies", Array.from(current).sort());
              };
              return (
                <div key={strat} className="flex items-center justify-between rounded border border-zinc-800 bg-zinc-900 px-3 py-2">
                  <div>
                    <div className="font-mono text-sm">{strat}</div>
                    <div className="text-[11px] text-zinc-500">
                      {count} agent{count === 1 ? "" : "s"} · {disabled ? "frozen — no new decisions" : "active"}
                    </div>
                  </div>
                  <Toggle
                    value={!disabled}
                    onChange={toggle}
                    label={`${strat} strategy on/off`}
                  />
                </div>
              );
            })}
            <div className="text-[11px] text-zinc-500">
              Disabled strategies keep existing positions but skip all new decisions until re-enabled.
            </div>
          </div>
        </Section>

        {/* 7. Backtest */}
        <Section label="Backtest">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm">Walk-forward LSTM backtest</div>
              <div className="text-[11px] text-zinc-500">
                Replay ~2y of EOD bars with the LstmAgent decision rule and compare symbols by Sharpe, return, drawdown.
              </div>
            </div>
            <button
              onClick={() => setBacktestOpen(true)}
              className="rounded border border-emerald-600 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/30"
            >
              Launch
            </button>
          </div>
        </Section>

        {/* 8. Curriculum */}
        <Section label="Curriculum">
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="text-sm">Run curriculum pass</div>
              <div className="text-[11px] text-zinc-500">
                Re-scores every agent and applies promotions/demotions per the current thresholds.
              </div>
            </div>
            <button
              onClick={runCurriculum}
              disabled={curriculumBusy}
              className="rounded border border-emerald-600 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40"
            >
              {curriculumBusy ? "running..." : "Run curriculum pass"}
            </button>
          </div>
        </Section>

        {/* 9. TTS */}
        <Section label="TTS">
          <TtsSettingsPanel />
        </Section>

        {backtestOpen && <BacktestModal onClose={() => setBacktestOpen(false)} />}

        <footer className="sticky bottom-0 -mx-5 -mb-5 flex items-center justify-between gap-3 border-t border-zinc-800 bg-zinc-900/95 px-5 py-3 backdrop-blur">
          <div className="text-[11px] text-zinc-500 truncate">{msg}</div>
          <div className="flex gap-2">
            <button
              onClick={onClose}
              className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700"
            >
              cancel
            </button>
            <button
              onClick={save}
              disabled={busy || Object.keys(draft).length === 0}
              className="rounded border border-emerald-600 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40"
            >
              {busy ? "saving..." : `save${Object.keys(draft).length ? ` (${Object.keys(draft).length})` : ""}`}
            </button>
          </div>
        </footer>
      </div>
    </Shell>
  );
}

function Shell({
  children,
  onClose,
  titleId,
  dialogRef,
}: {
  children: React.ReactNode;
  onClose: () => void;
  titleId?: string;
  dialogRef?: React.RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        className="w-[640px] max-w-[92vw] max-h-[88vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl focus:outline-none"
        onClick={(e) => e.stopPropagation()}
      >
        {children}
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section className="rounded-md border border-zinc-800 bg-zinc-950/50 p-4">
      <div className="mb-3 text-[10px] uppercase tracking-wider text-zinc-400">{label}</div>
      {children}
    </section>
  );
}

function Row({
  label,
  hint,
  htmlFor,
  badge,
  children,
}: {
  label: string;
  hint?: string;
  htmlFor?: string;
  badge?: string | null;
  children: React.ReactNode;
}) {
  return (
    <div className="block">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <label
          htmlFor={htmlFor}
          className="text-[11px] uppercase tracking-wider text-zinc-500"
        >
          {label}
        </label>
        <div className="flex items-baseline gap-2">
          {badge && (
            <span
              className={`rounded px-1.5 py-0.5 text-[9px] font-mono uppercase tracking-wider ${
                badge === "set"
                  ? "border border-emerald-700/50 bg-emerald-950/40 text-emerald-300"
                  : "border border-zinc-700 bg-zinc-900 text-zinc-400"
              }`}
            >
              {badge}
            </span>
          )}
          {hint && <span className="text-[10px] text-zinc-600">{hint}</span>}
        </div>
      </div>
      {children}
    </div>
  );
}

function Toggle({
  value,
  onChange,
  disabled,
  label,
}: {
  value: boolean;
  onChange: (v: boolean) => void;
  disabled?: boolean;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      disabled={disabled}
      role="switch"
      aria-checked={value}
      aria-label={label}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-50 ${value ? "bg-emerald-500" : "bg-zinc-700"}`}
    >
      <span className={`inline-block size-4 rounded-full bg-white transition ${value ? "translate-x-6" : "translate-x-1"}`} />
    </button>
  );
}
