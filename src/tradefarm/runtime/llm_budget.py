"""Daily LLM spend ceiling — protects the operator from runaway cost.

Round-5 audit fix (BB). Each agent's LSTM+LLM tick can fire a Claude
call; cost is hard to predict without a ceiling. The previous gate
was only the LSTM `max_prob < 0.40` confidence threshold — fine for
the average day, but a noisy / high-confidence regime could exhaust
the entire daily budget in minutes.

API surface:

    register_call(input_tokens, output_tokens, cache_read_tokens=0)
        Bookkeep a completed call.
    is_over_budget() -> bool
        True once today's spend exceeds ``settings.llm_daily_budget_usd``.
    today_usd() -> float
        Current spend (UTC day).
    reset_for_test()
        Wipe state (tests).

Counters reset automatically on the first call of a new UTC day.

Pricing is approximated for the default model only (Haiku 4.5 per
Anthropic's public table); operators using other models can override
via ``settings.llm_input_per_million / llm_output_per_million``.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date, datetime, timezone

from tradefarm.config import settings

# Haiku 4.5 default pricing (USD per 1M tokens).
DEFAULT_INPUT_USD_PER_MTOK = 0.80
DEFAULT_OUTPUT_USD_PER_MTOK = 4.00
DEFAULT_CACHE_READ_USD_PER_MTOK = 0.08  # 90% off

_lock = threading.Lock()


@dataclass
class _DailyTally:
    date_utc: date
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    calls: int = 0
    blocked: int = 0  # calls refused because budget exhausted

    def usd(self) -> float:
        in_per = getattr(settings, "llm_input_per_million", DEFAULT_INPUT_USD_PER_MTOK)
        out_per = getattr(settings, "llm_output_per_million", DEFAULT_OUTPUT_USD_PER_MTOK)
        cr_per = getattr(settings, "llm_cache_read_per_million", DEFAULT_CACHE_READ_USD_PER_MTOK)
        return (
            self.input_tokens * in_per / 1_000_000
            + self.output_tokens * out_per / 1_000_000
            + self.cache_read_tokens * cr_per / 1_000_000
        )


_tally: _DailyTally = _DailyTally(date_utc=datetime.now(timezone.utc).date())


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _rollover_if_needed() -> None:
    """Reset counters when the UTC day rolls over."""
    global _tally
    today = _today()
    if _tally.date_utc != today:
        _tally = _DailyTally(date_utc=today)


def register_call(
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> None:
    """Bookkeep a completed LLM call."""
    with _lock:
        _rollover_if_needed()
        _tally.input_tokens += int(input_tokens)
        _tally.output_tokens += int(output_tokens)
        _tally.cache_read_tokens += int(cache_read_tokens)
        _tally.calls += 1


def register_blocked() -> None:
    """Bookkeep a call that was refused because the budget was exhausted."""
    with _lock:
        _rollover_if_needed()
        _tally.blocked += 1


def is_over_budget() -> bool:
    """True if today's spend exceeds the configured ceiling.

    Budget = ``settings.llm_daily_budget_usd``; 0 (default) disables
    the ceiling. Returns False when disabled."""
    budget = float(getattr(settings, "llm_daily_budget_usd", 0.0) or 0.0)
    if budget <= 0:
        return False
    with _lock:
        _rollover_if_needed()
        return _tally.usd() >= budget


def today_usd() -> float:
    with _lock:
        _rollover_if_needed()
        return _tally.usd()


def snapshot() -> dict:
    """For /llm/stats and /metrics."""
    with _lock:
        _rollover_if_needed()
        return {
            "date_utc": _tally.date_utc.isoformat(),
            "input_tokens": _tally.input_tokens,
            "output_tokens": _tally.output_tokens,
            "cache_read_tokens": _tally.cache_read_tokens,
            "calls": _tally.calls,
            "blocked": _tally.blocked,
            "usd": round(_tally.usd(), 4),
            "budget_usd": float(getattr(settings, "llm_daily_budget_usd", 0.0) or 0.0),
        }


def reset_for_test() -> None:
    """Wipe state (tests only)."""
    global _tally
    with _lock:
        _tally = _DailyTally(date_utc=_today())
