"""Admin router — runtime-editable settings + master AI kill switch.

Security posture: the backend binds to 127.0.0.1 only, so this is assumed to
be local-dev only. If you expose the port externally, put an auth layer in
front (reverse proxy, API key, etc.). The allowlist below is NOT a substitute
for that — it's scope control, not access control.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from dotenv import set_key
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from tradefarm.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])

# Canonical list of strategy names currently in the codebase. Orchestrator uses
# these when building agents. Surface them here so the admin UI can render
# one toggle per strategy without having to query the orchestrator.
#
# `momentum_sma20` is kept as a known (but legacy) name so existing SQLite
# dev DBs with rows referencing the placeholder strategy don't trip the
# "unknown strategy" guard in the per-strategy toggle endpoint. The
# orchestrator no longer assigns that name; new agents get `momentum_12_1`.
KNOWN_STRATEGIES = (
    "momentum_sma20",  # legacy placeholder — pre-0.7.0; orchestrator no longer assigns
    "momentum_12_1",  # cross-sectional 12-1 month momentum (default since 0.7.0)
    "mean_reversion_bb",  # 20-period Bollinger Bands, ±2σ extremes
    "rsi2",  # Connors' 2-period RSI, deep-oversold/overbought
    "lstm_v1",
    "lstm_llm_v1",
)

# Keys the admin panel is allowed to mutate. Secrets are masked on GET.
EDITABLE: dict[str, type] = {
    "ai_enabled": bool,
    "llm_provider": str,
    "llm_model": str,
    "anthropic_api_key": str,
    "minimax_api_key": str,
    "minimax_base_url": str,
    "llm_min_confidence": float,
    "auto_tick_interval_sec": int,
    "tick_outside_rth": bool,
    # Audit fix (round 4 HIGH-3): `execution_mode` was operator-mutable
    # via the admin panel, but flipping `simulated` → `alpaca_paper`
    # mid-run never starts the reconciler (only `start_background()`
    # does, gated on the boot-time value). The result was a mode where
    # fills hit Alpaca with no reconciliation. Removed from EDITABLE;
    # operator must change `.env` and restart.
    # "execution_mode": str,    # ← REMOVED — requires restart
    "disabled_strategies": list,  # accepted as list on POST, stored as CSV
    # Phase 2 (Agent Academy) — thresholds are accepted here so the admin
    # panel can tune them in Phase 4. No UI field yet; the shape is enough.
    "academy_rank_multipliers": str,
    "academy_min_trades_junior": int,
    "academy_min_trades_senior": int,
    "academy_min_trades_principal": int,
    "academy_min_win_rate_senior": float,
    "academy_min_sharpe_principal": float,
    # Phase 3 — retrieval-augmented prompt.
    "academy_retrieval_k": int,
    "academy_retrieval_enabled": bool,
    # Phase 4 — curriculum / auto-promote-demote.
    "academy_eval_interval_sec": int,
    "academy_demote_drawdown_pct": float,
    "academy_demote_consecutive_losses": int,
    "academy_demote_cap_pct": float,
    # Phase 2.5 — risk-based exits.
    "risk_stop_loss_pct": float,
    "risk_take_profit_pct": float,
    "risk_trailing_stop_pct": float,
    "risk_max_hold_days": int,
}
# Audit fix (round 4 MED-6): derive secret-bearing keys by suffix so
# any future field added to Settings (alpaca_api_key, api_shared_secret,
# youtube_refresh_token, …) is masked by default instead of relying on
# this hardcoded list. The explicit base set covers fields that don't
# fit the suffix rule but should still be masked on GET.
_SECRET_SUFFIXES = ("_api_key", "_secret", "_token", "_refresh_token")


def _is_secret_key(key: str) -> bool:
    return any(key.endswith(suf) for suf in _SECRET_SUFFIXES)


def _all_secret_keys() -> set[str]:
    """Cross-reference EDITABLE + Settings fields to build the masked-on-GET set."""
    from tradefarm.config import Settings

    declared = set(Settings.model_fields.keys())
    return {k for k in (set(EDITABLE) | declared) if _is_secret_key(k)}


SECRET_KEYS = _all_secret_keys()
VALID_PROVIDERS = {"anthropic", "minimax"}
VALID_EXECUTION = {"simulated", "alpaca_paper"}

ENV_PATH = Path(".env")

# Characters that corrupt `.env` when written via dotenv.set_key(quote_mode="never").
# A literal newline lets an operator inject arbitrary KEY=VAL lines (incl.
# DATABASE_URL, AI_ENABLED, etc.) on the next restart. `\r` and NUL are
# equally hostile. `#` is benign as a *value* but only when nothing later
# tries to re-read the file as comments — we reject it defensively.
_FORBIDDEN_ENV_VALUE_CHARS = ("\n", "\r", "\x00")


def _reject_envfile_injection(key: str, val: object) -> None:
    if isinstance(val, str) and any(c in val for c in _FORBIDDEN_ENV_VALUE_CHARS):
        raise HTTPException(400, f"{key}: control characters not allowed in value")


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}…{value[-4:]}"


@router.get("/config")
async def get_config(request: Request) -> dict[str, Any]:
    """Return the current editable config. Secrets are masked."""
    out: dict[str, Any] = {}
    for key in EDITABLE:
        v = getattr(settings, key)
        if key in SECRET_KEYS and isinstance(v, str):
            out[key] = {"set": bool(v), "masked": _mask(v)}
        elif key == "disabled_strategies":
            out[key] = sorted(settings.disabled_strategies_set)
        else:
            out[key] = v

    # Per-strategy agent counts — handy for the toggle UI.
    orch = getattr(request.app.state, "orchestrator", None)
    counts: dict[str, int] = {s: 0 for s in KNOWN_STRATEGIES}
    if orch is not None:
        for a in orch.agents:
            counts[a.state.strategy] = counts.get(a.state.strategy, 0) + 1

    # Preflight 5/26: surface read-only operational fields that
    # operators want to see but shouldn't mutate via the panel.
    # execution_mode was removed from EDITABLE (round-4 HIGH-3 —
    # mid-run flip leaves the reconciler in the wrong state);
    # llm_daily_budget_usd is shown so the operator can monitor
    # without editing .env.
    out["_runtime"] = {
        "execution_mode": settings.execution_mode,
        "llm_daily_budget_usd": settings.llm_daily_budget_usd,
    }

    out["_meta"] = {
        "secret_keys": sorted(SECRET_KEYS),
        "valid_providers": sorted(VALID_PROVIDERS),
        "valid_execution": sorted(VALID_EXECUTION),
        "model_defaults": {
            "anthropic": "claude-haiku-4-5-20251001",
            "minimax": "M2.7-highspeed",
        },
        "known_strategies": list(KNOWN_STRATEGIES),
        "strategy_agent_counts": counts,
    }
    return out


class ConfigPatch(BaseModel):
    """Partial update — only present keys are written."""

    ai_enabled: bool | None = None
    llm_provider: Literal["anthropic", "minimax"] | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    minimax_api_key: str | None = None
    minimax_base_url: str | None = None
    llm_min_confidence: float | None = None
    auto_tick_interval_sec: int | None = None
    tick_outside_rth: bool | None = None
    execution_mode: Literal["simulated", "alpaca_paper"] | None = None
    disabled_strategies: list[str] | None = None
    # Phase 2 (Agent Academy) — see EDITABLE notes above.
    academy_rank_multipliers: str | None = None
    academy_min_trades_junior: int | None = None
    academy_min_trades_senior: int | None = None
    academy_min_trades_principal: int | None = None
    academy_min_win_rate_senior: float | None = None
    academy_min_sharpe_principal: float | None = None
    # Phase 3 — retrieval-augmented prompt.
    academy_retrieval_k: int | None = None
    academy_retrieval_enabled: bool | None = None
    # Phase 4 — curriculum / auto-promote-demote.
    academy_eval_interval_sec: int | None = None
    academy_demote_drawdown_pct: float | None = None
    academy_demote_consecutive_losses: int | None = None
    academy_demote_cap_pct: float | None = None
    # Phase 2.5 — risk-based exits.
    risk_stop_loss_pct: float | None = None
    risk_take_profit_pct: float | None = None
    risk_trailing_stop_pct: float | None = None
    risk_max_hold_days: int | None = None

    # If True, also write each changed key into .env so it survives restart.
    persist: bool = True


@router.post("/config")
async def patch_config(patch: ConfigPatch, request: Request) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    for key in EDITABLE:
        val = getattr(patch, key, None)
        if val is None:
            continue
        # For secret fields, empty string or the masked sentinel ("***" / "…")
        # means "don't change" — let the existing value stand.
        if key in SECRET_KEYS and isinstance(val, str):
            if val == "" or "…" in val or val == "***":
                continue
        # Reject newlines / NULs that would corrupt `.env` on persist.
        _reject_envfile_injection(key, val)
        # Range / enum checks the pydantic patch didn't already enforce.
        if key == "llm_min_confidence":
            val = float(val)
            if not 0.0 <= val <= 1.0:
                raise HTTPException(400, "llm_min_confidence out of range")
        if key == "auto_tick_interval_sec" and int(val) < 0:
            raise HTTPException(400, "auto_tick_interval_sec must be >= 0")
        if key == "academy_retrieval_k":
            val = int(val)
            if not 0 <= val <= 10:
                raise HTTPException(400, "academy_retrieval_k out of range (0..10)")
        if key == "disabled_strategies":
            strategies = list(val) if isinstance(val, (list, tuple, set)) else []
            unknown = [s for s in strategies if s not in KNOWN_STRATEGIES]
            if unknown:
                raise HTTPException(400, f"unknown strategies: {unknown}")
            # Store as CSV internally; API shows as list.
            setattr(settings, key, ",".join(sorted(set(strategies))))
            changes[key] = sorted(set(strategies))
            continue

        setattr(settings, key, val)
        changes[key] = val

    if not changes:
        return {"changed": {}, "overlay": None}

    # Swap the shared LLM overlay if any provider-related field moved.
    overlay_info: dict[str, str | None] | None = None
    if any(
        k in changes
        for k in (
            "llm_provider",
            "llm_model",
            "anthropic_api_key",
            "minimax_api_key",
            "minimax_base_url",
        )
    ):
        orch = request.app.state.orchestrator
        overlay_info = orch.reload_llm_overlay()

    # Persist to .env for next boot.
    # Audit fix (round 4 S1): surface per-key persist failures so the
    # operator can tell which fields will survive restart. Previously
    # `except Exception: pass` silently dropped persistence — operator
    # would type a new API key, see "saved", restart, watch it
    # disappear, and have no breadcrumb.
    persisted: dict[str, bool] = {}
    persist_errors: dict[str, str] = {}
    if patch.persist and ENV_PATH.exists():
        import structlog

        log = structlog.get_logger()
        for key, val in changes.items():
            env_key = key.upper()
            if isinstance(val, bool):
                env_val = str(val).lower()
            elif isinstance(val, list):
                env_val = ",".join(str(x) for x in val)
            else:
                env_val = str(val)
            try:
                set_key(str(ENV_PATH), env_key, env_val, quote_mode="never")
                persisted[key] = True
            except Exception as e:  # noqa: BLE001
                persisted[key] = False
                persist_errors[key] = f"{type(e).__name__}: {str(e)[:120]}"
                log.warning(
                    "env_persist_failed",
                    key=env_key,
                    err_type=type(e).__name__,
                    err=str(e)[:200],
                )

    return {
        "changed": {k: v if k not in SECRET_KEYS else _mask(str(v)) for k, v in changes.items()},
        "overlay": overlay_info,
        "persisted": persisted,
        "persist_errors": persist_errors,
    }


@router.post("/toggle-ai")
async def toggle_ai(enabled: bool) -> dict[str, bool]:
    """Convenience endpoint for the big on/off switch."""
    settings.ai_enabled = enabled
    if ENV_PATH.exists():
        try:
            set_key(str(ENV_PATH), "AI_ENABLED", str(enabled).lower(), quote_mode="never")
        except Exception:
            pass
    return {"ai_enabled": enabled}
