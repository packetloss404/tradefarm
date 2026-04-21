"""Agent that converts LSTM directional predictions into trading signals.

Decision rule (deliberately simple — LLM overlay tightens it later):
- if prediction = up AND confidence ≥ enter_conf AND no current long → buy
- if prediction = down AND confidence ≥ enter_conf AND has long → sell to flat
- otherwise wait
"""
from __future__ import annotations

import pandas as pd

from tradefarm.agents.base import Agent, Signal
from tradefarm.agents.features import featurize, latest_window
from tradefarm.agents.lstm_model import FittedModel, load

DIR_NAMES = ("down", "flat", "up")


class LstmAgent(Agent):
    strategy_name = "lstm_v1"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        *,
        enter_conf: float = 0.40,  # honest threshold given current LSTM calibration
        exit_conf: float = 0.35,
        size_pct: float = 0.20,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self.enter_conf = enter_conf
        self.exit_conf = exit_conf
        self.size_pct = size_pct
        self._fitted: FittedModel | None = load(symbol)
        self.last_prediction: dict | None = None

    @property
    def has_model(self) -> bool:
        return self._fitted is not None

    async def decide(self, bars: dict[str, pd.DataFrame], marks: dict[str, float]) -> list[Signal]:
        if self._fitted is None:
            return []
        df = bars.get(self.symbol)
        if df is None or len(df) < self._fitted.model.cfg.seq_len + 1:
            return []

        X, _ = featurize(df)
        window = latest_window(X, seq_len=self._fitted.model.cfg.seq_len)
        if window is None:
            return []
        pred = self._fitted.predict(window)
        self.last_prediction = {
            "direction": DIR_NAMES[pred.direction],
            "probs": pred.direction_probs,
            "confidence": pred.confidence,
        }

        px = marks.get(self.symbol)
        if px is None:
            return []
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0

        # Use max class prob as the trigger; confidence head is a noisy auxiliary.
        max_prob = max(pred.direction_probs)
        if pred.direction == 2 and max_prob >= self.enter_conf and not has_long:
            qty = round(self.state.book.cash * self.size_pct / px, 4)
            if qty <= 0:
                return []
            return [Signal(self.symbol, "buy", qty, reason=f"lstm up p={pred.direction_probs[2]:.2f}")]
        if pred.direction == 0 and max_prob >= self.exit_conf and has_long:
            return [Signal(self.symbol, "sell", round(pos.qty, 4), reason=f"lstm down p={pred.direction_probs[0]:.2f}")]
        return []
