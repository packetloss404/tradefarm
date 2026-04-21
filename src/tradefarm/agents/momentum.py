"""Placeholder baseline: 20-day SMA crossover on a randomly-assigned symbol.

Replace with LSTM+LLM hybrid once the data + broker + orchestrator loop is
proven. Keeping the logic trivial here on purpose — the point of the MVP is
to get 100 agents ticking end-to-end, not to make money with SMA."""
from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal


class MomentumAgent(Agent):
    strategy_name = "momentum_sma20"

    def __init__(self, state, risk, symbol: str, fast: int = 5, slow: int = 20) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.fast = fast
        self.slow = slow

    async def decide(self, bars: dict[str, pd.DataFrame], marks: dict[str, float]) -> list[Signal]:
        df = bars.get(self.symbol)
        if df is None or len(df) < self.slow + 1:
            return []
        closes = df["adjusted_close"]
        fast_ma = closes.rolling(self.fast).mean().iloc[-1]
        slow_ma = closes.rolling(self.slow).mean().iloc[-1]
        prev_fast = closes.rolling(self.fast).mean().iloc[-2]
        prev_slow = closes.rolling(self.slow).mean().iloc[-2]

        px = marks.get(self.symbol, closes.iloc[-1])
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        if fast_ma > slow_ma and prev_fast <= prev_slow and not has_long:
            target_notional = self.state.book.cash * 0.2
            qty = round(target_notional / px, 4)
            if qty <= 0:
                return []
            return [Signal(self.symbol, "buy", qty, reason="golden cross")]
        if fast_ma < slow_ma and prev_fast >= prev_slow and has_long:
            return [Signal(self.symbol, "sell", round(pos.qty, 4), reason="death cross")]
        return []
