from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Round-6 audit fix (H14): env-var shadowing. pydantic-settings loads from
# the shell environment FIRST and from ``.env`` only on top of that. If
# the operator started the backend with ``ANTHROPIC_API_KEY=...`` in the
# shell, the admin panel's later ``.env`` write is invisible on the
# next restart. Log a warning at boot when an env-prefixed field is
# set BOTH in the shell AND in ``.env`` so the operator can tell at a
# glance that their ``.env`` edit was swallowed.


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    eodhd_api_key: str = ""
    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    anthropic_api_key: str = ""

    database_url: str = "sqlite+aiosqlite:///./tradefarm.db"
    log_level: str = "INFO"

    agent_count: int = Field(default=100, ge=1, le=1000)
    agent_starting_capital: float = Field(default=1000.0, gt=0)

    # "simulated" fills locally at last close; "alpaca_paper" routes to Alpaca
    execution_mode: Literal["simulated", "alpaca_paper"] = "simulated"

    # Round-5 audit fix (BB): daily LLM spend ceiling (USD). When
    # set to a positive value, agents stop calling the LLM once the
    # day's tally crosses this number — the LSTM-only fallback path
    # keeps running. 0 (default) disables the ceiling, preserving
    # historical behavior. Pricing assumed Haiku 4.5; operators using
    # a different model should override the per-million-token rates
    # below.
    llm_daily_budget_usd: float = Field(default=0.0, ge=0)
    llm_input_per_million: float = Field(default=0.80, ge=0)
    llm_output_per_million: float = Field(default=4.00, ge=0)
    llm_cache_read_per_million: float = Field(default=0.08, ge=0)

    # Audit fix (H28): optional shared-secret for state-mutating endpoints.
    # When non-empty, every POST/PUT/PATCH/DELETE requires the header
    # X-TradeFarm-Token: <value>. Empty (default) = open, preserves
    # current behaviour. Lets the operator lock the broadcast VM's
    # 0.0.0.0:8000 bind without breaking the read-only dashboard polling.
    api_shared_secret: str = ""

    # Issue #3 (security): the host the API is bound to. Used by the
    # fail-fast startup guard in api/main.py — if this is a non-loopback
    # interface (0.0.0.0 or a LAN IP) AND api_shared_secret is empty, the
    # server refuses to start so an operator can't expose the
    # secret-rewriting endpoints to the LAN unauthenticated. The guard
    # prefers the `--host` value actually passed to uvicorn on sys.argv;
    # this setting is the fallback (and the testable/overridable knob).
    api_bind_host: str = "127.0.0.1"

    # Issue #4 (security): CORS allow-list is default-safe. By default only
    # loopback origins (localhost / 127.0.0.1 on any port, http or https) plus
    # the packaged Tauri webview origins are permitted. The broad RFC-1918 LAN
    # ranges (10.x / 192.168.x / 172.16-31.x) — needed for the split-machine
    # broadcast topology — are OPT-IN via `cors_allow_lan` so a malicious page
    # on an arbitrary LAN host can't be a permitted origin on a default bind.
    # `cors_allow_origins` is an optional CSV of extra exact origins merged into
    # the allow-list (e.g. "https://dash.example.com").
    cors_allow_lan: bool = False
    cors_allow_origins: str = ""

    # Background scheduler cadence in seconds. Default 300 (5 min) matches
    # the production cadence documented in CLAUDE.md. 0 disables auto-tick
    # so /tick is the only entrypoint — useful for backtesting / local
    # dev, but easy to forget; the previous default of 0 was responsible
    # for a real "I started the backend and no data collected" incident.
    # During RTH it ticks every interval; outside RTH it sleeps unless
    # tick_outside_rth=True.
    auto_tick_interval_sec: int = Field(default=300, ge=0)
    tick_outside_rth: bool = False

    # LLM cost gate: if LSTM max_prob is below this OR predicts flat, the
    # LSTM+LLM agent skips the Claude call entirely and records a synthetic
    # "wait" decision. Cuts API spend dramatically on weak signals.
    llm_min_confidence: float = Field(default=0.40, ge=0.0, le=1.0)

    # Master kill switch — when False, the scheduled tick loop skips all
    # decisions (agents freeze in place, dashboard keeps working).
    ai_enabled: bool = True

    # LLM provider dispatch.
    # anthropic: Claude (Haiku 4.5 default, prompt caching)
    # minimax:   OpenAI-compatible MiniMax API (M2.7-highspeed default)
    llm_provider: Literal["anthropic", "minimax"] = "anthropic"
    llm_model: str = ""  # empty → provider default

    minimax_api_key: str = ""
    minimax_base_url: str = "https://api.minimax.io/v1"

    # CSV of strategy names to freeze (e.g. "momentum_12_1,lstm_v1"). Agents
    # in a frozen strategy keep existing positions but skip all decisions.
    disabled_strategies: str = ""

    # -------------------------------------------------------------------------
    # Academy (Phase 2) — rank-gated capital.
    #
    # `academy_rank_multipliers` is a CSV of `rank=multiplier` pairs that scale
    # `RiskManager.limits.max_position_notional_pct` per rank. If empty, every
    # rank resolves to 1.0× so legacy behavior is preserved until the operator
    # opts in. Malformed entries fall back to 1.0.
    # -------------------------------------------------------------------------
    academy_rank_multipliers: str = ""
    academy_min_trades_junior: int = Field(default=5, ge=0)
    academy_min_trades_senior: int = Field(default=15, ge=0)
    academy_min_trades_principal: int = Field(default=40, ge=0)
    academy_min_win_rate_senior: float = Field(default=0.52, ge=0.0, le=1.0)
    academy_min_sharpe_principal: float = Field(default=0.5)

    # -------------------------------------------------------------------------
    # Academy (Phase 3) — retrieval-augmented prompt.
    #
    # `academy_retrieval_k` caps how many past stamped setups are pulled per
    # decision; hard-limited to 0..10 (the canonical plan fixes v1 at 3).
    # `academy_retrieval_enabled` is the kill switch — when False the
    # LSTM+LLM agent's prompt is byte-identical to pre-Phase-3 output.
    # -------------------------------------------------------------------------
    academy_retrieval_k: int = Field(default=3, ge=0, le=10)
    academy_retrieval_enabled: bool = True

    # -------------------------------------------------------------------------
    # Academy (Phase 4) — curriculum / auto-promote-demote.
    #
    # `academy_eval_interval_sec`: 0 disables the background curriculum loop
    # (Phase 4 is opt-in until the operator flips this). Positive values run
    # `curriculum.evaluate_all()` every N seconds between ticks.
    # `academy_demote_drawdown_pct`: realized-PnL drawdown threshold (fraction
    # of starting capital) that triggers a demotion. Absolute value.
    # `academy_demote_consecutive_losses`: a run of this many losing stamped
    # outcomes in a row also triggers demotion.
    # `academy_demote_cap_pct`: max fraction of the total agent population that
    # can be demoted in a single pass (demote-cascade guard).
    # -------------------------------------------------------------------------
    academy_eval_interval_sec: int = Field(default=0, ge=0)
    academy_demote_drawdown_pct: float = Field(default=0.08, ge=0.0, le=1.0)
    academy_demote_consecutive_losses: int = Field(default=5, ge=1)
    academy_demote_cap_pct: float = Field(default=0.10, ge=0.0, le=1.0)

    # -------------------------------------------------------------------------
    # VOD autonomy — daily pipeline scheduler + webhook notifications.
    #
    # `vod_pipeline_enabled`: master switch. When False (default), the
    # orchestrator's `run_vod_scheduler()` loop sleeps forever, so the
    # operator can ship this code dark and flip the switch without a
    # restart. When True, the scheduler loop fires the render pipeline
    # once per trading day, after the post-close cool-off.
    #
    # `vod_market_close_offset_min`: minutes after today's RTH close to
    # wait before firing. Lets data settle (4pm close + 5 min for the
    # broker feeds to flush). Mirrors what the operator would do
    # manually — `sleep 16:05 && uv run python -m tradefarm.render.pipeline`.
    #
    # `vod_publish_at_et`: "HH:MM" ET clock time used as the YouTube
    # `publish_at` for private uploads. The chain's `yt.metadata` already
    # reads this; the scheduler's job is to fire the run so the upload
    # step lands with the right publish_at. Default 16:30 = 30 min
    # after close, matches the existing `default_publish_at()` default.
    #
    # `vod_notify_webhook`: URL to POST a JSON notification to when a
    # run reaches a terminal state. Empty (default) disables
    # notifications. Compatible with Discord/Slack incoming webhooks,
    # ntfy.sh topics, or any json-post endpoint.
    # -------------------------------------------------------------------------
    vod_pipeline_enabled: bool = False
    vod_market_close_offset_min: int = Field(default=5, ge=0, le=120)
    vod_publish_at_et: str = "16:30"
    vod_notify_webhook: str = ""

    # -------------------------------------------------------------------------
    # YouTube Live Chat — poll the active broadcast's live chat via the
    # YouTube Data API v3 and republish new messages on the WS as
    # ``chat_message`` events. Credentials live in `.env` only (NOT exposed in
    # the admin panel allowlist). Use ``uv run python -m tradefarm.tools.youtube_auth``
    # to perform the one-time OAuth dance and capture a refresh token.
    # -------------------------------------------------------------------------
    youtube_chat_enabled: bool = False
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_refresh_token: str = ""
    # Optional: pin to a specific live broadcast. When empty, the poller
    # auto-detects via liveBroadcasts.list?broadcastStatus=active.
    youtube_channel_id: str = ""

    # -------------------------------------------------------------------------
    # Risk-based exits — apply to every open long regardless of brain.
    # First match fires a synthetic sell each tick: stop-loss, take-profit,
    # time-stop, trailing-stop (in that order).
    # -------------------------------------------------------------------------
    risk_stop_loss_pct: float = Field(default=0.03, ge=0.0, le=1.0)
    risk_take_profit_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    risk_trailing_stop_pct: float = Field(default=0.02, ge=0.0, le=1.0)
    risk_max_hold_days: int = Field(default=10, ge=1)

    @property
    def disabled_strategies_set(self) -> set[str]:
        return {s.strip() for s in self.disabled_strategies.split(",") if s.strip()}

    @property
    def rank_multiplier_map(self) -> dict[str, float]:
        """Parse `academy_rank_multipliers` into a dict. Empty or malformed
        entries silently fall back to 1.0 for that rank (or all ranks if the
        CSV is empty entirely).
        """
        out: dict[str, float] = {}
        raw = (self.academy_rank_multipliers or "").strip()
        if not raw:
            return out
        for token in raw.split(","):
            token = token.strip()
            if not token or "=" not in token:
                continue
            key, _, val = token.partition("=")
            key = key.strip().lower()
            try:
                out[key] = float(val.strip())
            except ValueError:
                # Malformed → leave unset; rank_multiplier() falls back to 1.0.
                continue
        return out

    def rank_multiplier(self, rank: str) -> float:
        """Multiplier for ``rank``. Empty/unconfigured settings → 1.0 for every
        rank (backwards-compat: the feature is only 'live' once operators set
        the CSV). Unknown ranks also → 1.0.
        """
        return self.rank_multiplier_map.get(rank.lower(), 1.0)


settings = Settings()


def _check_env_shadows() -> None:
    """Log a warning for each env-var whose shell value disagrees with
    the file-resolved value.

    Runs at module-import time. Each pydantic-settings field has a
    matching env-var name (uppercase). We compare
    ``os.environ[FIELD]`` (the shell value) to ``getattr(settings,
    field)`` (the .env-resolved value, which ``pydantic-settings``
    applies on top of the shell). If they differ, the shell wins on
    restart — and the operator's ``.env`` edit is invisible.

    This is a warning, not an error: some operators intentionally set
    the shell env to override ``.env`` (e.g. for a one-off experiment).
    """
    import logging as _logging
    import os as _os

    log = _logging.getLogger(__name__)
    for fname in type(settings).model_fields:
        env_key = fname.upper()
        shell_val = _os.environ.get(env_key)
        if shell_val is None:
            continue
        file_val = getattr(settings, fname)
        if file_val is None:
            continue
        # Compare as strings — pydantic-settings stores both sides as
        # their typed-coerced value, so str() of the two should match
        # when the operator's ``.env`` value is actually applied.
        if str(file_val) != shell_val and str(shell_val) != str(file_val):
            log.warning(
                "env_shadow: %s is set in both shell and .env; shell wins on restart",
                env_key,
            )


_check_env_shadows()
