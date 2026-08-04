"""Cross-sectional momentum agent: 12-month return skip-the-most-recent-month.

Classic academic momentum factor (Jegadeesh & Titman 1993). Computes the
trailing 12-month (252 trading days) return, **skipping the most recent
21 trading days** to avoid the well-documented 1-month mean-reversion
bounce that contaminates naive 12m momentum.

Decision rule (deliberately simple — overlays tighten later):
- If the 12-1m return is **positive and rising** vs the prior bar's value
  AND no current long → buy
- If the 12-1m return is **negative and falling** vs the prior bar's value
  AND has long → sell to flat
- Otherwise wait

Replaces the original ``momentum_sma20`` placeholder. The new
``strategy_name`` is ``momentum_12_1``; old ``momentum_sma20`` rows in
existing SQLite dev DBs are inert (no agent class with that name exists
anymore). Wipe ``tradefarm.db`` to start clean, or leave the orphans.
"""

from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.runtime.money import D, quantize_qty


class MomentumAgent(Agent):
    strategy_name = "momentum_12_1"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        *,
        lookback: int = 252,
        skip: int = 21,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.lookback = lookback
        self.skip = skip
        self.size_pct = size_pct

    def _momentum(self, closes: pd.Series) -> tuple[float | None, float | None]:
        """Return (current, previous) 12-1m momentum values, or (None, None)
        if there isn't enough history.
        """
        # Need lookback + skip + 1 extra bar to compute the *previous* value.
        if len(closes) < self.lookback + self.skip + 2:
            return None, None
        # Current: return over [t-lookback-skip, t-skip].
        cur = float(
            closes.iloc[-1 - self.skip] / closes.iloc[-self.lookback - self.skip] - 1.0
        )
        # Previous bar's value: shifted by one.
        prev = float(
            closes.iloc[-2 - self.skip] / closes.iloc[-self.lookback - 1 - self.skip] - 1.0
        )
        return cur, prev

    async def decide(
        self, bars: dict[str, pd.DataFrame], marks: dict[str, float]
    ) -> list[Signal]:
        df = bars.get(self.symbol)
        if df is None or df.empty:
            return []
        cur, prev = self._momentum(df["adjusted_close"])
        if cur is None or prev is None:
            return []

        px = marks.get(self.symbol, float(df["adjusted_close"].iloc[-1]))
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        # Enter long when momentum turns positive AND is rising.
        if cur > 0 and cur > prev and not has_long:
            target_notional = self.state.book.cash * D(str(self.size_pct))
            qty = quantize_qty(target_notional / D(str(px)))
            if qty <= 0:
                return []
            return [
                Signal(
                    self.symbol,
                    "buy",
                    qty,
                    reason=f"mom12-1 rising {cur:+.2%}>{prev:+.2%}",
                )
            ]
        # Exit long when momentum turns negative AND is falling.
        if cur < 0 and cur < prev and has_long and pos is not None:
            return [
                Signal(
                    self.symbol,
                    "sell",
                    quantize_qty(pos.qty),
                    reason=f"mom12-1 falling {cur:+.2%}<{prev:+.2%}",
                )
            ]
        return []
