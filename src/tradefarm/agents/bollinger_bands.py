"""Bollinger Bands mean-reversion agent.

Classic Bollinger Bands setup (Bollinger 1992): a 20-period simple
moving average with bands at ±2 standard deviations. The strategy
fades extremes — when the close is *below* the lower band the move is
treated as oversold (buy); when it's *above* the upper band the move
is treated as overbought (sell the long). Flat closes inside the bands
are no-ops.

Natural complement to the cross-sectional momentum agent: momentum
trends, this reverts. Backtest the two side-by-side and the
mean-reversion regime should dominate in sideways tapes while
momentum leads in trending tapes.

Decision rule:
- close < lower_band AND no current long → buy
- close > upper_band AND has long → sell to flat
- otherwise wait
"""

from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.runtime.money import D, quantize_qty


class BollingerBandsAgent(Agent):
    strategy_name = "mean_reversion_bb"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        *,
        period: int = 20,
        num_std: float = 2.0,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.period = period
        self.num_std = float(num_std)
        self.size_pct = size_pct

    def _bands(self, closes: pd.Series) -> tuple[float | None, float | None, float | None]:
        """Return (mid, upper, lower) for the most-recent bar, or (None,*,*)
        if there isn't enough history."""
        if len(closes) < self.period:
            return None, None, None
        window = closes.iloc[-self.period :]
        mid = float(window.mean())
        std = float(window.std(ddof=0))  # population std, matches Bollinger's formula
        if std == 0.0 or std != std:  # zero or NaN std → degenerate
            return None, None, None
        return mid, mid + self.num_std * std, mid - self.num_std * std

    async def decide(
        self, bars: dict[str, pd.DataFrame], marks: dict[str, float]
    ) -> list[Signal]:
        df = bars.get(self.symbol)
        if df is None or df.empty:
            return []
        mid, upper, lower = self._bands(df["adjusted_close"])
        if mid is None or upper is None or lower is None:
            return []

        px = marks.get(self.symbol, float(df["adjusted_close"].iloc[-1]))
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        if px < lower and not has_long:
            target_notional = self.state.book.cash * D(str(self.size_pct))
            qty = quantize_qty(target_notional / D(str(px)))
            if qty <= 0:
                return []
            return [
                Signal(
                    self.symbol,
                    "buy",
                    qty,
                    reason=f"bb oversold px={px:.2f}<lower={lower:.2f}",
                )
            ]
        if px > upper and has_long and pos is not None:
            return [
                Signal(
                    self.symbol,
                    "sell",
                    quantize_qty(pos.qty),
                    reason=f"bb overbought px={px:.2f}>upper={upper:.2f}",
                )
            ]
        return []
