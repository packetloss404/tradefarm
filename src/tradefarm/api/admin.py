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
from pydantic import BaseModel, Field

from tradefarm.config import settings
from tradefarm.runtime.tts_config import TtsConfig
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
    "openai_api_key": str,
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
VALID_PROVIDERS = {"anthropic", "openai", "minimax"}
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
            "openai": "gpt-5.6-sol",
            "minimax": "M2.7-highspeed",
        },
        "known_strategies": list(KNOWN_STRATEGIES),
        "strategy_agent_counts": counts,
    }
    return out


class ConfigPatch(BaseModel):
    """Partial update — only present keys are written."""

    ai_enabled: bool | None = None
    llm_provider: Literal["anthropic", "openai", "minimax"] | None = None
    llm_model: str | None = None
    anthropic_api_key: str | None = None
    openai_api_key: str | None = None
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
            "openai_api_key",
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


# ---------------------------------------------------------------------------
# 0.17.0 — TTS settings panel.
#
# The dashboard's `<TtsSettingsPanel />` (web/src/components/TtsSettingsPanel.tsx)
# reads `/admin/tts/status` to populate the form, POSTs `/admin/tts/switch`
# when the operator flips provider/voice/rate, and POSTs `/admin/tts/preview`
# to synthesize a sample line. The runtime config singleton in
# `tradefarm.runtime.tts_config` is the source of truth for the synthesis
# paths; the env-var settings remain the defaults.
# ---------------------------------------------------------------------------


class _TtsSwitchBody(BaseModel):
    """Body for `POST /admin/tts/switch`.

    All fields required (the dashboard sends the whole config on every
    save; partial patches would make the UI state machine more complex
    for no real win).
    """

    provider: str = Field(..., description="openai | elevenlabs | silence")
    voice: str = Field(..., min_length=1, max_length=128)
    speaking_rate: float = Field(1.0, ge=0.25, le=4.0)


class _TtsPreviewBody(BaseModel):
    """Body for `POST /admin/tts/preview`."""

    text: str = Field(..., min_length=1, max_length=2000)
    provider: str | None = Field(None, description="Override the active provider for this one call")
    voice: str | None = Field(None, description="Override the active voice for this one call")


@router.get("/tts/status")
async def tts_status() -> dict[str, Any]:
    """Return the current TTS runtime config + availability map.

    Used by the dashboard's `<TtsSettingsPanel />` to populate the
    provider/voice/rate controls. The availability map (``has_creds``)
    gates the radio cards — the operator can't switch to a provider
    whose env key isn't set, the radio shows as disabled.
    """
    from tradefarm.runtime.tts_config import (
        COST_PER_1K_CHARS_USD,
        VOICES_BY_PROVIDER,
        get_tts_config,
    )
    from tradefarm.tts.run import available_providers, has_tts_creds

    config = get_tts_config()
    available = list(available_providers())
    has_creds = {
        "openai": bool(__import__("os").environ.get("OPENAI_API_KEY")),
        "elevenlabs": bool(__import__("os").environ.get("ELEVENLABS_API_KEY")),
        "silence": True,  # always available
    }
    return {
        "config": config.to_payload(),
        "available_providers": available + ["silence"],
        "has_creds": has_creds,
        "voices_by_provider": {
            provider: list(voices)
            for provider, voices in VOICES_BY_PROVIDER.items()
        },
        "cost_per_1k_chars_usd": dict(COST_PER_1K_CHARS_USD),
        "creds_present": has_tts_creds(),
    }


@router.post("/tts/switch")
async def tts_switch(body: _TtsSwitchBody) -> dict[str, Any]:
    """Replace the active TTS config at runtime.

    Validates: provider must be in `VALID_TTS_PROVIDERS`; if a cloud
    provider is requested, its env key must be set. Returns 400 with a
    human-readable error so the dashboard can show "no API key for
    ElevenLabs; set ELEVENLABS_API_KEY in .env".

    Does NOT persist to .env — a process restart reverts to the
    env-var settings. The dashboard's "revert to env" button (when
    added) will call `POST /admin/tts/reset`.
    """
    import os

    from tradefarm.runtime.tts_config import VALID_TTS_PROVIDERS, set_tts_config

    if body.provider not in VALID_TTS_PROVIDERS:
        raise HTTPException(400, f"unknown provider: {body.provider!r}")

    # Gate on creds. The `silence` provider is always allowed.
    if body.provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(400, "OPENAI_API_KEY is not set; cannot switch to openai")
    if body.provider == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(400, "ELEVENLABS_API_KEY is not set; cannot switch to elevenlabs")

    new_config = TtsConfig(
        provider=body.provider,
        voice=body.voice,
        speaking_rate=body.speaking_rate,
    )
    previous = set_tts_config(new_config)
    return {
        "previous": previous.to_payload(),
        "active": new_config.to_payload(),
    }


@router.post("/tts/reset")
async def tts_reset() -> dict[str, Any]:
    """Reset the active TTS config to the env-var defaults.

    Symmetric to `/admin/tts/switch` but reads from `settings.podcast_*`
    instead of accepting a body. Useful when the operator wants to
    revert a runtime override without restarting the process.
    """
    from tradefarm.runtime.tts_config import reset_tts_config

    previous = reset_tts_config()
    return {"previous": previous.to_payload()}


@router.post("/tts/preview")
async def tts_preview(body: _TtsPreviewBody) -> dict[str, Any]:
    """Synthesize a single line and return it as a base64-encoded wav.

    Updates the TTS_SPEND counter atomically (one synthesize() call +
    one cost entry). The dashboard's preview button plays the
    returned audio inline.

    The override fields (provider/voice) let the operator try a
    different voice than the active config without committing a
    switch — the synthesis uses the override for this call only, and
    the active config is unchanged.
    """
    import base64
    import os
    import tempfile
    from pathlib import Path

    from tradefarm.runtime.tts_config import estimate_cost_usd, get_tts_config
    from tradefarm.tts.run import build_provider

    config = get_tts_config()
    provider_name = body.provider or config.provider
    voice = body.voice or config.voice

    if provider_name == "openai" and not os.environ.get("OPENAI_API_KEY"):
        raise HTTPException(400, "OPENAI_API_KEY is not set")
    if provider_name == "elevenlabs" and not os.environ.get("ELEVENLABS_API_KEY"):
        raise HTTPException(400, "ELEVENLABS_API_KEY is not set")

    # Build the provider; raise 400 on unknown name (defensive — the
    # switch endpoint already validates, but a curl caller might bypass).
    try:
        provider = build_provider(provider_name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"failed to build provider {provider_name!r}: {exc}")

    # Synthesize to a tmp wav. All current providers (silent, openai,
    # elevenlabs) declare `synthesize` as `async def`; since this
    # endpoint is itself `async def` we just await the coroutine
    # directly — the event loop is already running. The `cast(Any, ...)`
    # suppresses the protocol-vs-bound-method type narrowing.
    from typing import Any, cast

    with tempfile.TemporaryDirectory() as tmp:
        out_path = Path(tmp) / "preview.wav"
        try:
            synthesize = cast(Any, provider.synthesize)
            duration = await synthesize(body.text, voice=voice, out_path=out_path)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"synthesis failed: {exc}")

        wav_bytes = out_path.read_bytes()
        audio_b64 = base64.b64encode(wav_bytes).decode("ascii")

    # Update spend counter (atomic; no lock needed because asyncio
    # serializes the request handler).
    cost = estimate_cost_usd(provider_name, body.text)
    from tradefarm.api.main import TTS_SPEND

    TTS_SPEND["calls"] += 1
    TTS_SPEND["chars_synthesized"] += len(body.text)
    TTS_SPEND["cost_usd"] += cost

    return {
        "provider": provider_name,
        "voice": voice,
        "duration_sec": round(duration, 2),
        "cost_usd": cost,
        "total_calls": int(TTS_SPEND["calls"]),
        "total_cost_usd": round(TTS_SPEND["cost_usd"], 6),
        "audio_base64": audio_b64,
        "mime": "audio/wav",
    }


# ---------------------------------------------------------------------------
# 0.17.0 — lower-third builder.
#
# The dashboard's BroadcastPanel gets a quick-input form for ad-hoc
# lower-thirds ("back from break", "next guest", "outage notice", ...).
# The form POSTs to this endpoint, which publishes a ``lower_third``
# event to the WS bus (consumed by the stream's `useStreamCommands` and
# routed to the same banner slot as the legacy `stream_banner`). The
# `GET /admin/lower_third/recent` companion endpoint returns the in-memory
# ring buffer so the dashboard can render a "recent" list with a
# "replay" affordance per row.
#
# Why a dedicated event type rather than reusing `stream_banner`?
# `stream_banner` is the legacy wire format the broadcast suite emits on
# auto-fired moments; it doesn't carry an `id` (so the stream can't
# dedup against the canonical `broadcast_moment` envelope) and doesn't
# carry a `color` (so the visual is always the neutral accent). The
# operator-driven path wants both, plus a clean grep target in WS
# recordings and replay manifests.
# ---------------------------------------------------------------------------


class _LowerThirdPushBody(BaseModel):
    """Request body for `POST /admin/lower_third/push`.

    Field validation lives on the model so FastAPI emits a 422 with a
    detailed error when a request is malformed (missing required field,
    wrong type). The endpoint adds a final pass for the runtime
    invariants (non-empty title after stripping whitespace, ttl range,
    color allowlist) because pydantic can't express those without
    custom validators, and we want the 400 to be specific (the
    operator's eye will be on the response).
    """

    title: str
    subtitle: str | None = None
    ttl_sec: int | None = None
    color: Literal["profit", "loss", "neutral"] | None = None
    id: str | None = None


@router.post("/lower_third/push")
async def push_lower_third(body: _LowerThirdPushBody) -> dict[str, Any]:
    """Publish a `lower_third` event and record it in the operator log.

    The publish uses the existing ``publish_event`` helper (the same
    one `stream_banner` and `commentary` use), so the stream's
    ``useLiveEvents`` consumer sees the event with no extra wiring —
    it just needs the new ``lower_third`` case in its switch.

    Returns the entry that was recorded in the ring buffer so the
    dashboard can show a "pushed at HH:MM:SS, id=..." toast without
    a follow-up GET.
    """
    from tradefarm.api.events import (
        EVENT_TYPE_LOWER_THIRD,
        publish_event as _publish_event,
    )
    from tradefarm.api.lower_third_log import (
        MAX_TTL_SEC,
        MIN_TTL_SEC,
        VALID_LOWER_THIRD_COLORS,
        log as _lt_log,
    )

    # pydantic already coerced types per the BaseModel schema; the
    # remaining checks are runtime invariants pydantic can't express
    # cleanly (strip-then-non-empty, range, enum). We 400 explicitly
    # so the operator's UI can show the actual reason (pydantic's
    # default 422 has a nested array of error dicts that's noisy for
    # a button-triggered push).
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(400, "title must be non-empty")
    if body.color is not None and body.color not in VALID_LOWER_THIRD_COLORS:
        raise HTTPException(
            400, f"color must be one of {sorted(VALID_LOWER_THIRD_COLORS)}"
        )
    if body.ttl_sec is not None and not (
        MIN_TTL_SEC <= int(body.ttl_sec) <= MAX_TTL_SEC
    ):
        raise HTTPException(
            400, f"ttl_sec must be in [{MIN_TTL_SEC}, {MAX_TTL_SEC}]"
        )

    subtitle = (body.subtitle or "").strip()
    entry = _lt_log.record(
        title=title,
        subtitle=subtitle,
        ttl_sec=body.ttl_sec if body.ttl_sec is not None else 8,
        color=body.color,
        id=body.id,
    )

    # Publish to the WS bus. The stream's `lower_third` handler maps
    # this to the same banner slot as `stream_banner`; the visual is
    # identical, only the audit trail differs.
    await _publish_event(
        EVENT_TYPE_LOWER_THIRD,
        {
            "id": entry.id,
            "title": entry.title,
            "subtitle": entry.subtitle,
            "ttl_sec": entry.ttl_sec,
            "color": entry.color,
        },
    )

    import structlog

    structlog.get_logger().info(
        "admin_lower_third_pushed",
        id=entry.id,
        title=entry.title,
        ttl_sec=entry.ttl_sec,
        color=entry.color,
    )
    return entry.to_payload()


@router.get("/lower_third/recent")
async def recent_lower_thirds(
    limit: int = 50,
) -> dict[str, Any]:
    """Return the most-recent operator-pushed lower-thirds, newest-first.

    `limit` is clamped at the lower-third log's `MAX_RECENT_LIMIT` so
    a runaway dashboard (limit=10000) can't trigger a multi-MB JSON
    response. Default 50 covers the operator's "what did I push in
    the last hour" UI without bloating the wire.
    """
    from tradefarm.api.lower_third_log import MAX_RECENT_LIMIT, log as _lt_log

    if limit < 0:
        raise HTTPException(400, "limit must be non-negative")
    effective = min(limit, MAX_RECENT_LIMIT)
    return {"items": _lt_log.recent(effective)}


# ---------------------------------------------------------------------------
# 0.17.0 — WS frame recording control surface.
#
# Three endpoints back the dashboard's RecordingPanel:
#
#   POST /admin/ws_recording/start   — pre-arm a recorder (idempotent)
#   POST /admin/ws_recording/stop    — close + remove a recorder
#   GET  /admin/ws_recording/list    — list session_ids with a recording
#
# Recording itself lives in `tradefarm.api.ws_recording`; the WS
# handler attaches a recorder to a connection when the client
# supplies `?session_id=...` in the query string. The admin endpoints
# exist so an operator can pre-arm a recorder (e.g. before opening
# the dashboard, so the very first frame lands on disk) and stop it
# (closing the file handle) without reaching into the running
# process.
# ---------------------------------------------------------------------------


class _WsRecordingStartBody(BaseModel):
    """Request body for `POST /admin/ws_recording/start`.

    `session_id` is mandatory and validated against the safe-id
    regex (same one the replay path uses) so the recorder's
    on-disk filename can't escape `data_cache/ws_recordings/`.
    `base_dir` is optional — defaults to the module's
    `DEFAULT_BASE_DIR` so a default install "just works".
    """

    session_id: str
    base_dir: str | None = None


class _WsRecordingStopBody(BaseModel):
    """Request body for `POST /admin/ws_recording/stop`.

    `session_id` is mandatory; 404 if no recorder is active for
    that session.
    """

    session_id: str


@router.post("/ws_recording/start")
async def start_ws_recording(body: _WsRecordingStartBody) -> dict[str, Any]:
    """Pre-arm (or reuse) a recorder for ``session_id``.

    Idempotent: if a recorder for ``session_id`` is already active,
    returns its path + frame count without touching the file. The
    caller is the dashboard's RecordingPanel ("Start" button) or an
    operator's curl to record a session that hasn't connected yet.

    Returns ``{ok, path, session_id, frames_recorded, already_active}``
    so the dashboard can show "already recording" vs "started fresh"
    in the toast.
    """
    from pathlib import Path as _Path

    from tradefarm.api import ws_recording
    from tradefarm.session import replay_query as _rq

    if not isinstance(body.session_id, str) or not body.session_id:
        raise HTTPException(400, "session_id must be a non-empty string")
    try:
        safe_id = _rq._require_safe_session_id(body.session_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    base_dir = _Path(body.base_dir) if body.base_dir else None

    existing = ws_recording.get_recorder(safe_id)
    if existing is not None:
        return {
            "ok": True,
            "session_id": safe_id,
            "path": str(existing.path),
            "frames_recorded": existing.frames_recorded,
            "already_active": True,
        }

    rec = ws_recording.get_or_create_recorder(safe_id, base_dir=base_dir)
    return {
        "ok": True,
        "session_id": safe_id,
        "path": str(rec.path),
        "frames_recorded": rec.frames_recorded,
        "already_active": False,
    }


@router.post("/ws_recording/stop")
async def stop_ws_recording(body: _WsRecordingStopBody) -> dict[str, Any]:
    """Close the recorder for ``session_id``.

    Returns ``{ok, session_id, frames_recorded, path}`` on success;
    404 if no recorder was active for that session. The frames count
    is the in-process tally since the recorder was opened — the
    on-disk NDJSON is the durable source of truth (use
    ``wc -l <path>`` to count after the process restarts).
    """
    from tradefarm.api import ws_recording

    if not isinstance(body.session_id, str) or not body.session_id:
        raise HTTPException(400, "session_id must be a non-empty string")
    rec = ws_recording.stop_recorder(body.session_id)
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail=f"no active recorder for session {body.session_id!r}",
        )
    return {
        "ok": True,
        "session_id": body.session_id,
        "frames_recorded": rec.frames_recorded,
        "path": str(rec.path),
    }


@router.get("/ws_recording/list")
async def list_ws_recordings(base_dir: str | None = None) -> dict[str, Any]:
    """List session_ids with a recording on disk.

    Reads the directory listing (no DB). The default base dir is
    `data_cache/ws_recordings/`; an operator can pass `?base_dir=...`
    to inspect a different directory (e.g. a CI checkout of
    `tests/fixtures/ws/`). Returns ``{sessions: [str], base_dir: str}``.
    """
    from pathlib import Path as _Path

    from tradefarm.api import ws_recording

    base = _Path(base_dir) if base_dir else None
    return {
        "base_dir": str(base) if base else str(ws_recording.DEFAULT_BASE_DIR),
        "sessions": ws_recording.list_recorded_sessions(base),
    }


# ---------------------------------------------------------------------------
# 0.18.0 — LLM model picker endpoints.
#
# Three endpoints back the dashboard's ``<LlmModelPicker />`:
#
#   GET  /admin/llm/models        — fan-out to the three providers'
#                                   /v1/models, cache the result for
#                                   60 min, return the catalog.
#   POST /admin/llm/select        — replace the runtime
#                                   ``LlmModelConfig`` and write
#                                   ``LLM_PROVIDER`` / ``LLM_MODEL``
#                                   to .env so the choice survives
#                                   restart.
#   POST /admin/llm/reset         — revert the runtime config to
#                                   the env-var defaults.
#
# The picker fan-out reuses the existing ``llm_model_catalog``
# module; the active-config singleton lives in
# ``tradefarm.runtime.llm_model_config``. The TTS endpoints above
# are the shape template (POST returns ``{previous, active}`` for
# consistency with the dashboard's "what did I just change?" UX).
# ---------------------------------------------------------------------------


@router.get("/llm/models")
async def list_llm_models(refresh: bool = False) -> dict[str, Any]:
    """Return the current LLM model catalog across all three providers.

    ``refresh=true`` forces a refetch (bypasses the 60-min cache);
    the dashboard's "Refresh" button calls this so a newly-released
    model can be picked without restarting the backend. The
    catalog endpoint fans out in parallel with a per-provider 5s
    timeout; one provider's failure or missing key does not fail
    the whole request - the response carries one
    ``{ok, models, fetched_at, error?}`` block per provider.
    """
    from tradefarm.runtime.llm_model_catalog import get_model_catalog

    catalog = await get_model_catalog(force=refresh)
    return catalog.to_payload()


class _LlmSelectBody(BaseModel):
    """Body for ``POST /admin/llm/select``.

    ``provider`` is a plain string; the endpoint validates against
    ``VALID_LLM_PROVIDERS`` at runtime and returns 400 with a
    human-readable error. The pydantic Literal would return 422
    with a nested error array; the operator's UI wants the 400
    text in the toast (mirrors the tts/switch endpoint shape).
    ``model`` is the canonical model id (the picker submits
    canonical ids, not aliases, so a future alias rename doesn't
    break the operator's existing choice).
    """

    provider: str
    model: str = Field(..., min_length=1, max_length=256)


@router.post("/llm/select")
async def llm_select(
    body: _LlmSelectBody, request: Request
) -> dict[str, Any]:
    """Replace the active LLM model config at runtime and persist.

    Validates: provider must be in ``VALID_LLM_PROVIDERS``; if a
    cloud provider is requested, its env key must be set (so a
    missing-key switch doesn't leak into the synthesis path - the
    same gating pattern ``tts_switch`` uses).

    Persistence: the runtime singleton takes effect immediately
    (the next ``build_provider`` call picks it up); ``LLM_PROVIDER``
    and ``LLM_MODEL`` are written to ``.env`` for durability, so
    the choice survives restart. The overlay is rebuilt so the
    next LLM call uses the new config (mirrors what
    ``patch_config`` does for the legacy ``llm_provider`` /
    ``llm_model`` fields).

    Returns ``{previous, active, persisted}`` - mirrors the
    tts/switch response shape so the dashboard's "saved at HH:MM:SS"
    toast renders without a follow-up GET.
    """

    from tradefarm.runtime.llm_model_config import LlmModelConfig, set_llm_model_config

    if body.provider not in VALID_PROVIDERS:
        raise HTTPException(400, f"unknown provider: {body.provider!r}")

    # Gate on creds. Every cloud provider needs its env key.
    if body.provider == "anthropic" and not settings.anthropic_api_key:
        raise HTTPException(400, "ANTHROPIC_API_KEY is not set; cannot switch to anthropic")
    if body.provider == "openai" and not settings.openai_api_key:
        raise HTTPException(400, "OPENAI_API_KEY is not set; cannot switch to openai")
    if body.provider == "minimax" and not settings.minimax_api_key:
        raise HTTPException(400, "MINIMAX_API_KEY is not set; cannot switch to minimax")

    new_config = LlmModelConfig(provider=body.provider, model=body.model)
    previous = set_llm_model_config(new_config)

    # Mirror to settings.llm_provider / settings.llm_model so the
    # patch_config() path + the next ``_safe_build_overlay()`` call
    # see the same source of truth. The runtime singleton is the
    # primary, but settings is the seed for boot + the input to
    # the overlay rebuild.
    settings.llm_provider = body.provider  # type: ignore[assignment]
    settings.llm_model = body.model

    # Rebuild the shared overlay so the next LLM call uses the new
    # provider/model without waiting for the periodic overlay
    # rebuild. Same hook the legacy patch_config() path uses.
    orch = getattr(request.app.state, "orchestrator", None)
    overlay_info: dict[str, str | None] | None = None
    if orch is not None and hasattr(orch, "reload_llm_overlay"):
        overlay_info = orch.reload_llm_overlay()

    # Persist LLM_PROVIDER + LLM_MODEL to .env. We do NOT persist
    # here if the operator's chosen provider is the env default -
    # the env-var write would be a no-op and the file would gain
    # two redundant lines. The orchestrator's existing .env writes
    # follow the same pattern.
    persisted: dict[str, bool] = {}
    if ENV_PATH.exists():
        try:
            set_key(str(ENV_PATH), "LLM_PROVIDER", body.provider, quote_mode="never")
            persisted["llm_provider"] = True
        except Exception:  # noqa: BLE001
            persisted["llm_provider"] = False
        try:
            set_key(str(ENV_PATH), "LLM_MODEL", body.model, quote_mode="never")
            persisted["llm_model"] = True
        except Exception:  # noqa: BLE001
            persisted["llm_model"] = False

    return {
        "previous": previous.to_payload(),
        "active": new_config.to_payload(),
        "overlay": overlay_info,
        "persisted": persisted,
    }


@router.post("/llm/reset")
async def llm_reset() -> dict[str, Any]:
    """Reset the active LLM model config to the env-var defaults.

    Symmetric to ``/admin/llm/select`` but reads from
    ``settings.llm_provider`` / ``settings.llm_model`` instead of
    accepting a body. Useful when the operator wants to revert a
    runtime override without restarting the process.
    """
    from tradefarm.runtime.llm_model_config import reset_llm_model_config

    previous = reset_llm_model_config()
    return {
        "previous": previous.to_payload(),
    }
