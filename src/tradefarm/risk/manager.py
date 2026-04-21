from dataclasses import dataclass

from tradefarm.execution.virtual_book import VirtualBook


@dataclass
class RiskLimits:
    max_position_notional_pct: float = 0.25  # of starting capital per symbol
    stop_loss_pct: float = 0.03
    trailing_stop_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05


@dataclass
class RiskDecision:
    allow: bool
    reason: str = ""


class RiskManager:
    def __init__(self, starting_capital: float, limits: RiskLimits | None = None) -> None:
        self.starting_capital = starting_capital
        self.limits = limits or RiskLimits()
        self._peak: dict[str, float] = {}

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
