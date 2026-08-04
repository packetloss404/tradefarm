"""Donchian channel breakout agent.

Classic turtle-style trend-following (Donchian 1960s, popularized by the
Turtles experiment in the 1980s). The 20-period Donchian channel marks
the recent range: the upper band is the highest close over the lookback
window and the lower band is the lowest. Breakouts above the upper
band are treated as fresh strength (buy); breakdowns below the lower
band are treated as a failed trend (sell to flat).

The strategy is long-only in this sandbox — short-side breakouts are
ignored. In a 100-agent paper-trading fleet, this is the trend leg
to the Bollinger mean-reversion and RSI(2) entries: those fade
extremes, this one rides them.

Decision rule:
- close > upper_band AND no current long → buy
- close < lower_band AND has long → sell to flat
- otherwise wait
"""

from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.runtime.money import D, quantize_qty


class DonchianBreakoutAgent(Agent):
    strategy_name = "donchian_breakout"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        *,
        period: int = 20,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.period = period
        self.size_pct = size_pct

    def _channel(self, closes: pd.Series) -> tuple[float | None, float | None]:
        """Return (upper, lower) for the ``period``-bar window *ending at
        the prior bar*, or (None, None) if there's not enough history.

        The current bar is excluded from the channel — a breakout is defined
        by the current close exceeding the prior N-bar extreme, not the
        rolling window that includes the current bar (which would make
        ``close > upper`` a no-op since the current close is the window's
        max by construction).
        """
        if len(closes) < self.period + 1:
            return None, None
        window = closes.iloc[-(self.period + 1) : -1]
        return float(window.max()), float(window.min())

    async def decide(
        self, bars: dict[str, pd.DataFrame], marks: dict[str, float]
    ) -> list[Signal]:
        df = bars.get(self.symbol)
        if df is None or df.empty:
            return []
        upper, lower = self._channel(df["adjusted_close"])
        if upper is None or lower is None:
            return []

        px = marks.get(self.symbol, float(df["adjusted_close"].iloc[-1]))
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        if px > upper and not has_long:
            target_notional = self.state.book.cash * D(str(self.size_pct))
            qty = quantize_qty(target_notional / D(str(px)))
            if qty <= 0:
                return []
            return [
                Signal(
                    self.symbol,
                    "buy",
                    qty,
                    reason=f"donchian breakout px={px:.2f}>upper={upper:.2f}",
                )
            ]
        if px < lower and has_long and pos is not None:
            return [
                Signal(
                    self.symbol,
                    "sell",
                    quantize_qty(pos.qty),
                    reason=f"donchian breakdown px={px:.2f}<lower={lower:.2f}",
                )
            ]
        return []
