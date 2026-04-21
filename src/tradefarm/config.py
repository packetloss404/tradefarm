from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # Background scheduler: 0 disables auto-tick (manual /tick only).
    # During RTH it ticks every interval; outside RTH it sleeps unless tick_outside_rth=True.
    auto_tick_interval_sec: int = Field(default=0, ge=0)
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

    # CSV of strategy names to freeze (e.g. "momentum_sma20,lstm_v1"). Agents
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
