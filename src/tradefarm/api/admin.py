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
KNOWN_STRATEGIES = ("momentum_sma20", "lstm_v1", "lstm_llm_v1")

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
    "execution_mode": str,
    "disabled_strategies": list,  # accepted as list on POST, stored as CSV
    # Phase 2 (Agent Academy) — thresholds are accepted here so the admin
    # panel can tune them in Phase 4. No UI field yet; the shape is enough.
    "academy_rank_multipliers": str,
    "academy_min_trades_junior": int,
    "academy_min_trades_senior": int,
    "academy_min_trades_principal": int,
    "academy_min_win_rate_senior": float,
    "academy_min_sharpe_principal": float,
}
SECRET_KEYS = {"anthropic_api_key", "minimax_api_key"}
VALID_PROVIDERS = {"anthropic", "minimax"}
VALID_EXECUTION = {"simulated", "alpaca_paper"}

ENV_PATH = Path(".env")


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
        # Range / enum checks the pydantic patch didn't already enforce.
        if key == "llm_min_confidence":
            val = float(val)
            if not 0.0 <= val <= 1.0:
                raise HTTPException(400, "llm_min_confidence out of range")
        if key == "auto_tick_interval_sec" and int(val) < 0:
            raise HTTPException(400, "auto_tick_interval_sec must be >= 0")
        if key == "disabled_strategies":
            unknown = [s for s in val if s not in KNOWN_STRATEGIES]
            if unknown:
                raise HTTPException(400, f"unknown strategies: {unknown}")
            # Store as CSV internally; API shows as list.
            setattr(settings, key, ",".join(sorted(set(val))))
            changes[key] = sorted(set(val))
            continue

        setattr(settings, key, val)
        changes[key] = val

    if not changes:
        return {"changed": {}, "overlay": None}

    # Swap the shared LLM overlay if any provider-related field moved.
    overlay_info: dict[str, str | None] | None = None
    if any(k in changes for k in ("llm_provider", "llm_model", "anthropic_api_key", "minimax_api_key", "minimax_base_url")):
        orch = request.app.state.orchestrator
        overlay_info = orch.reload_llm_overlay()

    # Persist to .env for next boot.
    if patch.persist and ENV_PATH.exists():
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
            except Exception:
                # Non-fatal — in-memory change still stands.
                pass

    return {"changed": {k: v if k not in SECRET_KEYS else _mask(str(v)) for k, v in changes.items()},
            "overlay": overlay_info}


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
