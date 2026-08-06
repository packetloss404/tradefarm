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
from tradefarm.storage import repo

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
    "donchian_breakout",  # 20-period Donchian channel, upper/lower breakouts
    "pairs_zscore",  # A-B dollar spread z-score mean reversion (long-only)
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


# ---------------------------------------------------------------------------
# Per-agent disable controls.
#
# Companion to the per-strategy `disabled_strategies` set: instead of freezing
# every agent running a given strategy, the operator can flip a single agent
# off (and back on) from the admin UI. Disabled agents are fully frozen — the
# scheduler skips them in gather() so they emit no signals and the risk-exit
# loop in `_tick_once_inner` doesn't run against their positions either.
# This is intentionally conservative: a "disable" is "leave it alone", not
# "force-close my position". The operator must re-enable to exit a trade.
# ---------------------------------------------------------------------------


@router.get("/agents")
async def list_agents() -> list[dict[str, Any]]:
    """Return all agents with their per-agent disable flag + cash.

    Slim response (5 fields per agent × 100 agents ≈ 5KB JSON) so the
    admin UI can poll every few seconds without bloating the network.
    The `cash` column is the agent's current virtual-book cash (Decimal)
    coerced to float at this boundary.
    """
    return await repo.get_all_agents_with_disabled()


class _AgentDisabledBody(BaseModel):
    disabled: bool


class _AgentBulkDisabledBody(BaseModel):
    agent_ids: list[int]
    disabled: bool


def _validate_agent_id(agent_id: int) -> None:
    """Reject agent ids outside the configured population range.

    The runtime guarantees 0..settings.agent_count-1; anything else is
    either a stale UI, a typo, or an attacker's probe. 400 keeps the
    response code aligned with FastAPI's other "client supplied bad data"
    responses — 404 would be defensible but a crafty attacker could
    use 200/404 deltas to enumerate id ranges.
    """
    n = int(getattr(settings, "agent_count", 0))
    if agent_id < 0 or (n and agent_id >= n):
        raise HTTPException(
            status_code=400,
            detail=f"agent_id {agent_id} out of range [0, {n})",
        )


@router.post("/agents/{agent_id}/disabled")
async def set_agent_disabled(agent_id: int, body: _AgentDisabledBody) -> dict[str, Any]:
    """Flip a single agent's `disabled` flag.

    Disabled agents skip ``decide()`` in the next tick (the orchestrator
    reads `repo.get_disabled_agent_ids()` once per tick). The flag is
    durable in `agents.disabled`; on a process restart the same agent
    comes back disabled.
    """
    _validate_agent_id(agent_id)
    await repo.set_agent_disabled(agent_id, body.disabled)
    return {"agent_id": int(agent_id), "disabled": bool(body.disabled)}


@router.post("/agents/bulk-disabled")
async def bulk_set_agents_disabled(body: _AgentBulkDisabledBody) -> dict[str, Any]:
    """Flip the disable flag on a batch of agents in one request.

    All ids in ``agent_ids`` are validated against the configured range
    up front; the whole batch is rejected if any id is out of range (no
    partial updates). Useful for the UI's "disable all in strategy" /
    "enable all in strategy" affordances.
    """
    n = int(getattr(settings, "agent_count", 0))
    bad = [aid for aid in body.agent_ids if aid < 0 or (n and aid >= n)]
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"agent_ids out of range [0, {n}): {sorted(set(bad))[:10]}"
            + (" ..." if len(set(bad)) > 10 else ""),
        )
    updated = await repo.set_agents_disabled_bulk(body.agent_ids, body.disabled)
    return {"updated": [int(i) for i in updated]}


# ---------------------------------------------------------------------------
# 0.16.0 — manual 4pm recap push.
#
# The dashboard's BroadcastPanel gets a "Push 4pm recap" button that hits
# this endpoint when the operator wants to re-show the live recap during
# the last few minutes of a stream (e.g. after a 4:30pm big fill). The
# endpoint publishes the same canonical ``BroadcastMoment`` the scheduler
# fires, but DOES NOT write to ``daily_recap_fired`` — the operator's
# push is unconditional, the next 4pm still fires. Operators who want to
# skip a given day should set ``daily_recap_enabled=False`` instead of
# relying on this endpoint.
# ---------------------------------------------------------------------------


class _RecapPushBody(BaseModel):
    """Optional override for the published moment's ``date`` field.

    ``date`` is purely diagnostic — it lands in the moment's ``metadata``
    and is read by the stream's ``LiveRecapScene`` to label the frame.
    Default: today (ET). We don't validate the format here; the scheduler
    uses the same field with the same semantics.
    """

    date: str | None = None


@router.post("/recap/push")
async def push_recap(body: _RecapPushBody | None = None) -> dict[str, Any]:
    """Manually publish the 4pm recap moment. Operator-only.

    Constructs the same ``BroadcastMoment`` the scheduler's poll loop
    fires (via the suite's shared ``_build_daily_recap_moment`` helper)
    and publishes it via ``publish_broadcast_moment``. The
    ``daily_recap_fired`` idempotency row is NOT written — a manual
    push is unconditional, the next 4pm still fires.

    Returns the moment id + a tiny summary so the dashboard can show
    a "pushed at HH:MM:SS" toast without a follow-up GET.
    """
    import uuid as _uuid

    from tradefarm.market.hours import ET as _ET
    from tradefarm.orchestrator.broadcast_os import publish_broadcast_moment
    from tradefarm.orchestrator.broadcast_suite import (
        _build_daily_recap_moment as _build_moment,
    )
    from tradefarm.runtime.clock import now_utc as _now_utc
    from tradefarm.session.weekly_rollup import week_id_for as _week_id_for

    now = _now_utc()
    et_now = now.astimezone(_ET)
    date_str = body.date if body and body.date else et_now.date().isoformat()
    week_id = _week_id_for(et_now.date())
    moment_id = f"daily-recap-{date_str}-{_uuid.uuid4().hex[:8]}"
    moment = _build_moment(date_str, moment_id=moment_id, week_id=week_id)
    await publish_broadcast_moment(moment, emit_legacy=False)
    import structlog

    structlog.get_logger().info(
        "admin_recap_push_fired", moment_id=moment_id, date=date_str
    )
    return {
        "moment_id": moment_id,
        "date": date_str,
        "week_id": week_id,
        "pushed_at": now.isoformat(),
    }
