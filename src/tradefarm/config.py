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

    @property
    def disabled_strategies_set(self) -> set[str]:
        return {s.strip() for s in self.disabled_strategies.split(",") if s.strip()}


settings = Settings()
