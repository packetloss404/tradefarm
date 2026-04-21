import { useEffect, useState } from "react";
import useSWR from "swr";
import { api, type AdminConfig, type AdminPatch } from "../api";
import { BacktestModal } from "./BacktestModal";

export function AdminModal({ onClose }: { onClose: () => void }) {
  const [backtestOpen, setBacktestOpen] = useState(false);
  const { data, error, mutate } = useSWR<AdminConfig>("admin-config", api.adminConfig);
  const [draft, setDraft] = useState<AdminPatch>({});
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string>("");
  const [curriculumBusy, setCurriculumBusy] = useState(false);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (error) {
    return (
      <Shell onClose={onClose}>
        <div className="p-5 text-sm text-(--color-loss)">Failed to load admin config: {(error as Error).message}</div>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell onClose={onClose}>
        <div className="p-5 text-sm text-zinc-500">Loading…</div>
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
      setMsg(changed.length ? `saved: ${changed.join(", ")}${res.overlay ? ` · brain → ${res.overlay.provider}/${res.overlay.model}` : ""}` : "nothing changed");
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
    try {
      const next = !d.ai_enabled;
      await api.adminToggleAi(next);
      setField("ai_enabled", next);
      await mutate();
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

  const anthropicPlaceholder = data.anthropic_api_key.set ? data.anthropic_api_key.masked : "sk-ant-…";
  const minimaxPlaceholder = data.minimax_api_key.set ? data.minimax_api_key.masked : "paste key";
  const modelPlaceholder = data._meta.model_defaults[d.llm_provider] ?? "";

  return (
    <Shell onClose={onClose}>
      <header className="flex items-center justify-between border-b border-zinc-800 px-5 py-3">
        <div>
          <div className="text-lg font-semibold">Admin</div>
          <div className="text-[11px] uppercase tracking-wider text-zinc-500">runtime config · persists to .env</div>
        </div>
        <button onClick={onClose} className="rounded border border-zinc-700 bg-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-700">esc</button>
      </header>

      <div className="space-y-5 p-5">
        {/* AI Kill switch */}
        <Section label="AI Control">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm">Scheduled ticks</div>
              <div className="text-[11px] text-zinc-500">When off, agents freeze but dashboard keeps running.</div>
            </div>
            <Toggle value={!!d.ai_enabled} onChange={toggleAi} disabled={busy} />
          </div>
        </Section>

        {/* Brain provider */}
        <Section label="Brain Provider">
          <div className="space-y-3">
            <div className="flex gap-2">
              {(["anthropic", "minimax"] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => setField("llm_provider", p)}
                  className={`flex-1 rounded border px-3 py-2 text-xs ${
                    d.llm_provider === p
                      ? "border-emerald-500 bg-emerald-950/40 text-emerald-300"
                      : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                  }`}
                >
                  <div className="font-mono font-semibold uppercase">{p}</div>
                  <div className="text-[10px] text-zinc-500 normal-case">
                    default: {data._meta.model_defaults[p]}
                  </div>
                </button>
              ))}
            </div>

            <Row label="Model override">
              <input
                type="text"
                value={d.llm_model ?? ""}
                onChange={(e) => setField("llm_model", e.target.value)}
                placeholder={modelPlaceholder}
                className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
              />
            </Row>

            {d.llm_provider === "anthropic" && (
              <Row label="Anthropic API key" hint={data.anthropic_api_key.set ? "set — paste a new one to replace" : "not set"}>
                <input
                  type="password"
                  value={d.anthropic_api_key ?? ""}
                  onChange={(e) => setField("anthropic_api_key", e.target.value)}
                  placeholder={anthropicPlaceholder}
                  className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
                />
              </Row>
            )}

            {d.llm_provider === "minimax" && (
              <>
                <Row label="MiniMax API key" hint={data.minimax_api_key.set ? "set — paste a new one to replace" : "not set"}>
                  <input
                    type="password"
                    value={d.minimax_api_key ?? ""}
                    onChange={(e) => setField("minimax_api_key", e.target.value)}
                    placeholder={minimaxPlaceholder}
                    className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
                  />
                </Row>
                <Row label="Base URL">
                  <input
                    type="text"
                    value={d.minimax_base_url ?? ""}
                    onChange={(e) => setField("minimax_base_url", e.target.value)}
                    placeholder="https://api.minimax.io/v1"
                    className="w-full rounded border border-zinc-700 bg-zinc-950 px-2 py-1 font-mono text-xs text-zinc-100"
                  />
                </Row>
              </>
            )}
          </div>
        </Section>

        {/* Tuning */}
        <Section label="Tuning">
          <div className="grid grid-cols-2 gap-3">
            <Row label={`Min LSTM confidence (${(d.llm_min_confidence ?? 0.4).toFixed(2)})`} hint="below this, skip the LLM entirely">
              <input
                type="range" min={0} max={0.9} step={0.05}
                value={d.llm_min_confidence ?? 0.4}
                onChange={(e) => setField("llm_min_confidence", parseFloat(e.target.value))}
                className="w-full"
              />
            </Row>
            <Row label={`Tick every ${d.auto_tick_interval_sec ?? 0}s`} hint="0 disables the scheduler">
              <input
                type="number" min={0} step={30}
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
            <Toggle value={!!d.tick_outside_rth} onChange={(v) => setField("tick_outside_rth", v)} />
          </div>
        </Section>

        {/* Execution */}
        <Section label="Execution">
          <div className="flex gap-2">
            {(["simulated", "alpaca_paper"] as const).map((m) => (
              <button
                key={m}
                onClick={() => setField("execution_mode", m)}
                className={`flex-1 rounded border px-3 py-2 text-xs font-mono ${
                  d.execution_mode === m
                    ? "border-emerald-500 bg-emerald-950/40 text-emerald-300"
                    : "border-zinc-700 bg-zinc-800 text-zinc-300 hover:bg-zinc-700"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
          <div className="mt-2 text-[11px] text-zinc-500">
            simulated = local self-fills. alpaca_paper = real orders to Alpaca paper + reconciler loop.
          </div>
        </Section>

        {/* Strategies */}
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
                  <Toggle value={!disabled} onChange={toggle} />
                </div>
              );
            })}
            <div className="text-[11px] text-zinc-500">
              Disabled strategies keep existing positions but skip all new decisions until re-enabled.
            </div>
          </div>
        </Section>

        {/* Backtest */}
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
              Launch →
            </button>
          </div>
        </Section>

        {/* Curriculum — Phase 4 */}
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
              {curriculumBusy ? "running…" : "Run curriculum pass"}
            </button>
          </div>
        </Section>

        {/* Future — placeholder for growth */}
        <Section label="Coming soon">
          <ul className="space-y-1 text-xs text-zinc-500">
            <li>· Per-strategy enable/disable toggles</li>
            <li>· Symbol universe editor</li>
            <li>· Agent rebuild (reset all books)</li>
          </ul>
        </Section>

        {backtestOpen && <BacktestModal onClose={() => setBacktestOpen(false)} />}

        <footer className="sticky bottom-0 -mx-5 -mb-5 flex items-center justify-between gap-3 border-t border-zinc-800 bg-zinc-900/95 px-5 py-3 backdrop-blur">
          <div className="text-[11px] text-zinc-500 truncate">{msg}</div>
          <div className="flex gap-2">
            <button onClick={onClose} className="rounded border border-zinc-700 bg-zinc-800 px-3 py-1.5 text-xs text-zinc-300 hover:bg-zinc-700">cancel</button>
            <button
              onClick={save}
              disabled={busy || Object.keys(draft).length === 0}
              className="rounded border border-emerald-600 bg-emerald-600/20 px-3 py-1.5 text-xs font-semibold text-emerald-300 hover:bg-emerald-600/30 disabled:opacity-40"
            >
              {busy ? "saving…" : `save${Object.keys(draft).length ? ` (${Object.keys(draft).length})` : ""}`}
            </button>
          </div>
        </footer>
      </div>
    </Shell>
  );
}

function Shell({ children, onClose }: { children: React.ReactNode; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div
        className="w-[640px] max-w-[92vw] max-h-[88vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl"
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

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="mb-1 flex items-baseline justify-between">
        <span className="text-[11px] uppercase tracking-wider text-zinc-500">{label}</span>
        {hint && <span className="text-[10px] text-zinc-600">{hint}</span>}
      </div>
      {children}
    </label>
  );
}

function Toggle({ value, onChange, disabled }: { value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      disabled={disabled}
      role="switch"
      aria-checked={value}
      className={`relative inline-flex h-6 w-11 items-center rounded-full transition disabled:opacity-50 ${value ? "bg-emerald-500" : "bg-zinc-700"}`}
    >
      <span className={`inline-block size-4 rounded-full bg-white transition ${value ? "translate-x-6" : "translate-x-1"}`} />
    </button>
  );
}
