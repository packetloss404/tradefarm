from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from tradefarm.execution.virtual_book import VirtualBook, VirtualPosition
from tradefarm.runtime.clock import now_utc

# Base (pre-multiplier) position-size cap. Phase 2 scales this by the rank
# multiplier. Kept as a module-level constant so Phase 2 tests (and Phase 4's
# curriculum) can reason about "base * multiplier" without reading the
# dataclass default directly.
BASE_MAX_POSITION_NOTIONAL_PCT = 0.25


@dataclass
class RiskLimits:
    max_position_notional_pct: float = (
        BASE_MAX_POSITION_NOTIONAL_PCT  # of starting capital per symbol
    )
    stop_loss_pct: float = 0.03
    trailing_stop_pct: float = 0.02
    daily_loss_limit_pct: float = 0.05
    # Phase 2.5 (risk-based exits): these apply regardless of which brain the
    # agent uses, so positions actually close on some schedule rather than
    # relying on the LSTM to flip "down" (which it rarely does).
    take_profit_pct: float = 0.05
    max_hold_days: int = 10


@dataclass
class RiskDecision:
    allow: bool
    reason: str = ""


@dataclass
class ExitTrigger:
    """Why the RiskManager says an open position should close now."""

    kind: str  # "stop-loss" | "take-profit" | "time-stop" | "trailing-stop"
    reason: str  # human-readable detail with the actual numbers


def _utcnow() -> datetime:
    return now_utc()


class RiskManager:
    def __init__(
        self,
        starting_capital: float,
        limits: RiskLimits | None = None,
        rank: str = "intern",
    ) -> None:
        self.starting_capital = starting_capital
        # Track whether the caller passed explicit limits. If they did, those
        # are authoritative (tests rely on this). If not, `should_exit` will
        # read thresholds from live settings so admin changes take effect
        # without a restart.
        self._limits_explicit = limits is not None
        self.limits = limits or self._limits_from_settings()
        self.rank = rank
        self._apply_rank_multiplier()
        self._peak: dict[str, float] = {}
        # Audit fix (H19): when a position reopens after being closed,
        # the previous peak is stale. Track when each peak was seeded so
        # `should_exit` can detect a fresh `opened_at` > seeded_at and
        # reset rather than dragging the old peak forward.
        self._peak_seeded_at: dict[str, datetime] = {}

    @staticmethod
    def _limits_from_settings() -> RiskLimits:
        """Build RiskLimits from the live settings. Lazy-imported so the
        module stays import-safe during config bootstrap."""
        from tradefarm.config import settings

        return RiskLimits(
            max_position_notional_pct=BASE_MAX_POSITION_NOTIONAL_PCT,
            stop_loss_pct=settings.risk_stop_loss_pct,
            trailing_stop_pct=settings.risk_trailing_stop_pct,
            daily_loss_limit_pct=0.05,
            take_profit_pct=settings.risk_take_profit_pct,
            max_hold_days=settings.risk_max_hold_days,
        )

    def _apply_rank_multiplier(self) -> None:
        # Lazy import keeps `risk.manager` import-safe during config bootstrap.
        from tradefarm.config import settings

        multiplier = settings.rank_multiplier(self.rank)
        # Audit fix (H21): when the caller passed an explicit RiskLimits
        # the position cap they supplied is authoritative — DO NOT
        # overwrite it with the base × multiplier. Previously this
        # silently clobbered tests / call sites that injected a tighter
        # or looser cap. Only recompute from BASE for the implicit path.
        if not self._limits_explicit:
            self.limits.max_position_notional_pct = BASE_MAX_POSITION_NOTIONAL_PCT * multiplier

    def check_entry(
        self,
        book: VirtualBook,
        symbol: str,
        qty: float | Decimal,
        price: float,
        marks: dict[str, float] | None = None,
    ) -> RiskDecision:
        # Audit fix: reject zero / negative inputs at the boundary so a
        # bad signal can't reach the broker. ``qty`` may arrive as Decimal
        # (signal sizing); risk math is float-based, so coerce here.
        qty = float(qty)
        if qty <= 0 or price <= 0:
            return RiskDecision(False, "invalid order qty/price")
        notional = abs(qty * price)

        # Audit fix (H17): per-symbol cap was per-trade, so an agent that
        # added to an existing position repeatedly could bypass the cap
        # entirely. Cap is now against the *total* notional including the
        # current position at mark.
        existing = book.positions.get(symbol)
        existing_notional = abs(float(existing.qty)) * price if existing is not None else 0.0
        total_notional = notional + existing_notional

        # Audit fix (H18): cap was anchored to starting_capital, so a
        # losing agent's cap stayed at 25% of starting (= 50%+ of current
        # equity at drawdown). Clamp by min(starting, current_equity).
        # Book money is Decimal; risk math is %-based on floats, so convert
        # at this boundary (the book's exactness isn't load-bearing for a
        # threshold comparison).
        cash = float(book.cash)
        equity = (
            float(book.equity(marks or {}))
            if marks
            else cash + (existing_notional if existing else 0.0)
        )
        cap_anchor = min(self.starting_capital, max(0.0, equity))
        cap = cap_anchor * self.limits.max_position_notional_pct
        if total_notional > cap:
            return RiskDecision(
                False,
                f"size {total_notional:.0f} (incl. existing {existing_notional:.0f}) "
                f"exceeds per-symbol cap {cap:.0f}",
            )
        if cash - notional < 0:
            return RiskDecision(False, "insufficient cash")
        return RiskDecision(True)

    def should_exit(
        self,
        symbol: str,
        pos: VirtualPosition,
        mark: float,
        now: datetime | None = None,
    ) -> ExitTrigger | None:
        """Decide whether this open long should close based on risk alone.

        Reads thresholds from ``self.limits``; if the caller passed explicit
        limits at construction they're authoritative. Otherwise the thresholds
        come from the live `settings` object (so admin-panel changes take
        effect on the next tick without restarting).

        Checks in order: stop-loss, take-profit, time-stop, trailing-stop.
        Returns None if no rule fires. Shorts aren't supported in v1 — we
        don't open them — so qty <= 0 always returns None.
        """
        if pos.qty <= 0 or pos.avg_price <= 0:
            return None
        now = now or _utcnow()

        sl_pct, tp_pct, trail_pct_threshold, max_hold_days = self._effective_thresholds()

        # Book money is Decimal; risk is %-based on float marks. Convert
        # avg_price here so the trailing-peak dict (also float, shared with
        # should_stop_out) stays homogeneous.
        avg_price = float(pos.avg_price)
        unrealized_pct = (mark - avg_price) / avg_price

        if unrealized_pct <= -sl_pct:
            return ExitTrigger("stop-loss", f"stop-loss {unrealized_pct:+.2%}")

        if unrealized_pct >= tp_pct:
            return ExitTrigger("take-profit", f"take-profit {unrealized_pct:+.2%}")

        if pos.opened_at is not None:
            # Audit fix (H20): days-held uses trading days, not wall-clock
            # days. A position opened Friday hitting "10 days" Monday-
            # after-next was wrong — most of those "days" were closures.
            from tradefarm.market.hours import trading_days_between

            try:
                days = trading_days_between(pos.opened_at, now)
            except Exception:  # pragma: no cover — best-effort
                # If the calendar lookup ever throws, fall back to wall
                # clock — closing too aggressively is safer than not
                # closing at all.
                days = (now - pos.opened_at).total_seconds() / 86400.0
            if days >= max_hold_days:
                return ExitTrigger(
                    "time-stop",
                    f"held {days:.1f} trading days >= {max_hold_days}d",
                )

        # Audit fix (H19): if `opened_at` is later than the cached peak's
        # timestamp, the position has been closed + reopened since we
        # last tracked a peak. Reset the peak to the new entry's avg_price
        # so a stale-peak doesn't instantly trip the trailing-stop on
        # the new position.
        peak_seeded_at = self._peak_seeded_at.get(symbol)
        if peak_seeded_at is None or (pos.opened_at is not None and pos.opened_at > peak_seeded_at):
            self._peak[symbol] = avg_price
            self._peak_seeded_at[symbol] = pos.opened_at or now

        peak = max(self._peak.get(symbol, avg_price), mark)
        self._peak[symbol] = peak
        if peak > 0:
            trail_pct = (mark - peak) / peak
            if trail_pct <= -trail_pct_threshold:
                return ExitTrigger(
                    "trailing-stop", f"trailing {trail_pct:+.2%} off peak {peak:.2f}"
                )

        return None

    def clear_peak(self, symbol: str) -> None:
        """Reset the trailing peak for a symbol — called when the position
        has been fully closed so a re-entry starts fresh. The seeded-at
        check in should_exit covers the case automatically too, but
        explicit callers can shed the entry early."""
        self._peak.pop(symbol, None)
        self._peak_seeded_at.pop(symbol, None)

    def _effective_thresholds(self) -> tuple[float, float, float, int]:
        """If the caller injected explicit RiskLimits (tests), use those.
        Otherwise read live settings so admin tweaks take effect immediately
        on the next tick without restarting the backend."""
        if self._limits_explicit:
            return (
                self.limits.stop_loss_pct,
                self.limits.take_profit_pct,
                self.limits.trailing_stop_pct,
                self.limits.max_hold_days,
            )
        from tradefarm.config import settings

        return (
            settings.risk_stop_loss_pct,
            settings.risk_take_profit_pct,
            settings.risk_trailing_stop_pct,
            settings.risk_max_hold_days,
        )

    # Legacy API — kept so any external caller still works. New code should
    # use `should_exit(...)`.
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

    def check_daily_loss(self, book: VirtualBook, marks: dict[str, float]) -> RiskDecision:
        equity = float(book.equity(marks))
        dd = (equity - self.starting_capital) / self.starting_capital
        if dd <= -self.limits.daily_loss_limit_pct:
            return RiskDecision(False, f"daily loss {dd:.2%} breached")
        return RiskDecision(True)
