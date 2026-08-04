"""Connors' RSI(2) mean-reversion agent.

Short-horizon mean reversion via a 2-period RSI (Connors & Alvarez,
2014). The 2-day RSI oscillates between 0 and 100; the strategy buys
when RSI(2) drops below a deep-oversold threshold (default 5) and
sells when it rises above a deep-overbought threshold (default 95).

Very fast compute, fires more often than the cross-sectional
strategies — pairs naturally with the 5-minute tick rate. The 0.05/95
thresholds are intentionally extreme; the average RSI(2) sits ~50 and
the tails fire rarely. Tuning them tighter/lighter trades frequency
for win rate.

Decision rule:
- RSI(2) < oversold (default 5) AND no current long → buy
- RSI(2) > overbought (default 95) AND has long → sell to flat
- otherwise wait
"""

from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.runtime.money import D, quantize_qty


class Rsi2Agent(Agent):
    strategy_name = "rsi2"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        *,
        period: int = 2,
        oversold: float = 5.0,
        overbought: float = 95.0,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.period = period
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.size_pct = size_pct

    def _rsi(self, closes: pd.Series) -> float | None:
        """Most-recent 2-period RSI on a 0..100 scale, or None if there's
        not enough history."""
        # Need period + 1 bars (period diffs to compute gains/losses).
        if len(closes) < self.period + 1:
            return None
        delta = closes.diff().iloc[-self.period :]
        gains = delta.clip(lower=0.0)
        losses = (-delta.clip(upper=0.0))
        avg_gain = float(gains.mean())
        avg_loss = float(losses.mean())
        if avg_gain == 0.0 and avg_loss == 0.0:
            # No movement at all in the window — treat as the neutral midpoint.
            return 50.0
        if avg_loss == 0.0:
            # All-up bar(s) → maxed RSI.
            return 100.0
        rs = avg_gain / avg_loss
        return float(100.0 - 100.0 / (1.0 + rs))

    async def decide(
        self, bars: dict[str, pd.DataFrame], marks: dict[str, float]
    ) -> list[Signal]:
        df = bars.get(self.symbol)
        if df is None or df.empty:
            return []
        rsi = self._rsi(df["adjusted_close"])
        if rsi is None:
            return []

        px = marks.get(self.symbol, float(df["adjusted_close"].iloc[-1]))
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        if rsi < self.oversold and not has_long:
            target_notional = self.state.book.cash * D(str(self.size_pct))
            qty = quantize_qty(target_notional / D(str(px)))
            if qty <= 0:
                return []
            return [
                Signal(
                    self.symbol,
                    "buy",
                    qty,
                    reason=f"rsi2 oversold {rsi:.1f}<{self.oversold:g}",
                )
            ]
        if rsi > self.overbought and has_long and pos is not None:
            return [
                Signal(
                    self.symbol,
                    "sell",
                    quantize_qty(pos.qty),
                    reason=f"rsi2 overbought {rsi:.1f}>{self.overbought:g}",
                )
            ]
        return []
