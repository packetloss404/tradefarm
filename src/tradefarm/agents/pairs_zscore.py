"""Pairs-trading z-score mean-reversion agent.

Classic pairs spread (Gatev, Goetzmann & Rouwenhorst 2006): the spread
``A - B`` between two cointegrated names drifts around a long-run mean;
when the spread's z-score is sufficiently negative we long A (the
underperformer) expecting the spread to revert, and when it is
sufficiently positive we close that long.

This sandbox is long-only — we never short B. The agent only trades
``symbol_a`` and uses ``symbol_b`` solely to compute the spread.

Decision rule:
- z < -z_entry AND no current long A → buy A
- z >  z_entry AND has long A        → sell A to flat
- otherwise wait

``z_exit`` is reserved for a future refinement (faster mean-reversion
exit around the mean); not used in this initial cut.
"""

from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.runtime.money import D, quantize_qty


class PairsZScoreAgent(Agent):
    strategy_name = "pairs_zscore"

    def __init__(
        self,
        state,
        risk,
        *,
        symbol_a: str,
        symbol_b: str,
        lookback: int = 60,
        z_entry: float = 2.0,
        z_exit: float = 0.5,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol_a = symbol_a
        self.symbol_b = symbol_b
        self.lookback = lookback
        self.z_entry = float(z_entry)
        self.z_exit = float(z_exit)
        self.size_pct = size_pct

    def _zscore(self, df_a: pd.DataFrame, df_b: pd.DataFrame) -> float | None:
        """Most-recent z-score of the A-B dollar spread over the lookback
        window, or None if either side lacks history or the window is
        degenerate (zero std). Population std (ddof=0).
        """
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            return None
        if len(df_a) < self.lookback or len(df_b) < self.lookback:
            return None
        closes_a = df_a["adjusted_close"].iloc[-self.lookback :]
        closes_b = df_b["adjusted_close"].iloc[-self.lookback :]
        spread = closes_a.to_numpy() - closes_b.to_numpy()
        mean = float(spread.mean())
        std = float(pd.Series(spread).std(ddof=0))
        if std == 0.0 or std != std:  # zero or NaN std → degenerate
            return None
        last = float(spread[-1])
        return (last - mean) / std

    async def decide(
        self, bars: dict[str, pd.DataFrame], marks: dict[str, float]
    ) -> list[Signal]:
        df_a = bars.get(self.symbol_a)
        df_b = bars.get(self.symbol_b)
        if df_a is None or df_b is None or df_a.empty or df_b.empty:
            return []
        z = self._zscore(df_a, df_b)
        if z is None:
            return []

        px_a = marks.get(self.symbol_a, float(df_a["adjusted_close"].iloc[-1]))
        pos = self.state.book.positions.get(self.symbol_a)
        has_long = pos is not None and pos.qty > 0

        if z < -self.z_entry and not has_long:
            target_notional = self.state.book.cash * D(str(self.size_pct))
            qty = quantize_qty(target_notional / D(str(px_a)))
            if qty <= 0:
                return []
            return [
                Signal(
                    self.symbol_a,
                    "buy",
                    qty,
                    reason=(
                        f"pairs z={z:+.2f}<-{self.z_entry:g} "
                        f"long {self.symbol_a} vs {self.symbol_b}"
                    ),
                )
            ]
        if z > self.z_entry and has_long and pos is not None:
            return [
                Signal(
                    self.symbol_a,
                    "sell",
                    quantize_qty(pos.qty),
                    reason=(
                        f"pairs z={z:+.2f}>{self.z_entry:g} "
                        f"close {self.symbol_a} vs {self.symbol_b}"
                    ),
                )
            ]
        return []
