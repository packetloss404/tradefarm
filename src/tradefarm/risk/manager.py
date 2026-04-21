from dataclasses import dataclass

from tradefarm.execution.virtual_book import VirtualBook

# Base (pre-multiplier) position-size cap. Phase 2 scales this by the rank
# multiplier. Kept as a module-level constant so Phase 2 tests (and Phase 4's
# curriculum) can reason about "base * multiplier" without reading the
# dataclass default directly.
BASE_MAX_POSITION_NOTIONAL_PCT = 0.25


@dataclass
class RiskLimits:
    max_position_notional_pct: float = BASE_MAX_POSITION_NOTIONAL_PCT  # of starting capital per symbol
    stop_loss_pct: float = 0.03
    trailing_stop_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05


@dataclass
class RiskDecision:
    allow: bool
    reason: str = ""


class RiskManager:
    def __init__(
        self,
        starting_capital: float,
        limits: RiskLimits | None = None,
        rank: str = "intern",
    ) -> None:
        self.starting_capital = starting_capital
        self.limits = limits or RiskLimits()
        self.rank = rank
        # Apply the rank multiplier to the base cap. When `academy_rank_multipliers`
        # is unset, `rank_multiplier()` returns 1.0 for every rank so existing
        # behavior is preserved (see backwards-compat contract in PROJECT_PLAN.md).
        self._apply_rank_multiplier()
        self._peak: dict[str, float] = {}

    def _apply_rank_multiplier(self) -> None:
        # Lazy import keeps `risk.manager` import-safe during config bootstrap.
        from tradefarm.config import settings
        multiplier = settings.rank_multiplier(self.rank)
        # Recompute from the *base* cap each call so repeated rank changes
        # don't compound. `limits.max_position_notional_pct` stores the
        # effective (post-multiplier) cap.
        self.limits.max_position_notional_pct = BASE_MAX_POSITION_NOTIONAL_PCT * multiplier

    def check_entry(self, book: VirtualBook, symbol: str, qty: float, price: float) -> RiskDecision:
        notional = abs(qty * price)
        cap = self.starting_capital * self.limits.max_position_notional_pct
        if notional > cap:
            return RiskDecision(False, f"size {notional:.0f} exceeds per-symbol cap {cap:.0f}")
        if book.cash - notional < 0:
            return RiskDecision(False, "insufficient cash")
        return RiskDecision(True)

    def check_daily_loss(self, book: VirtualBook, marks: dict[str, float]) -> RiskDecision:
        equity = book.equity(marks)
        dd = (equity - self.starting_capital) / self.starting_capital
        if dd <= -self.limits.daily_loss_limit_pct:
            return RiskDecision(False, f"daily loss {dd:.2%} breached")
        return RiskDecision(True)

    def should_stop_out(self, symbol: str, entry: float, current: float, side: str) -> RiskDecision:
        edge = (current - entry) / entry if side == "long" else (entry - current) / entry
        if edge <= -self.limits.stop_loss_pct:
            return RiskDecision(False, f"stop-loss hit ({edge:.2%})")

        peak = self._peak.get(symbol, entry)
        peak = max(peak, current) if side == "long" else min(peak, current)
        self._peak[symbol] = peak
        trail = (current - peak) / peak if side == "long" else (peak - current) / peak
        if trail <= -self.limits.trailing_stop_pct:
            return RiskDecision(False, f"trailing stop hit ({trail:.2%})")
        return RiskDecision(True)
