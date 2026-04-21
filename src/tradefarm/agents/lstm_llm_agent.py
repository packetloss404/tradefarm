"""LSTM + LLM hybrid agent. The LSTM proposes; the LLM disposes."""
from __future__ import annotations

import pandas as pd
import structlog

from tradefarm.agents import retrieval
from tradefarm.agents.base import Agent, Signal
from tradefarm.agents.features import featurize, latest_window
from tradefarm.agents.llm_overlay import LlmContext, LlmDecision, LlmOverlay
from tradefarm.agents.lstm_model import FittedModel, load
from tradefarm.config import settings

log = structlog.get_logger()

# Count of LSTM->LLM calls short-circuited on low confidence, for dashboard display.
LLM_SKIPS = {"count": 0, "called": 0}

DIR_NAMES = ("down", "flat", "up")


def _feature_digest(df: pd.DataFrame) -> str:
    """Last 5 closes + a few headline indicators, in one line."""
    tail = df.sort_values("date").tail(5)
    closes = tail["adjusted_close"].tolist()
    pct = (closes[-1] / closes[0] - 1) * 100 if len(closes) >= 2 and closes[0] else 0
    last = tail.iloc[-1]
    return (
        f"5d close: {[round(c, 2) for c in closes]} "
        f"({pct:+.2f}% over window); "
        f"vol last={int(last['volume']):,}, range last="
        f"{(last['high'] - last['low']):.2f}"
    )


class LstmLlmAgent(Agent):
    strategy_name = "lstm_llm_v1"

    def __init__(
        self,
        state,
        risk,
        symbol: str,
        overlay: LlmOverlay | None = None,
    ) -> None:
        super().__init__(state, risk)
        self.symbol = symbol
        self._fitted: FittedModel | None = load(symbol)
        self._overlay = overlay
        self.last_lstm: dict | None = None
        self.last_decision: LlmDecision | None = None

    @property
    def has_model(self) -> bool:
        return self._fitted is not None

    async def decide(self, bars: dict[str, pd.DataFrame], marks: dict[str, float]) -> list[Signal]:
        if self._fitted is None or self._overlay is None:
            return []
        df = bars.get(self.symbol)
        if df is None or len(df) < self._fitted.model.cfg.seq_len + 1:
            return []
        X, _ = featurize(df)
        window = latest_window(X, seq_len=self._fitted.model.cfg.seq_len)
        if window is None:
            return []
        pred = self._fitted.predict(window)
        self.last_lstm = {
            "direction": DIR_NAMES[pred.direction],
            "probs": pred.direction_probs,
            "confidence": pred.confidence,
        }

        px = marks.get(self.symbol)
        if px is None:
            return []
        pos = self.state.book.positions.get(self.symbol)
        has_long = pos is not None and pos.qty > 0
        held_qty = pos.qty if pos else 0.0

        # Cost gate: skip the LLM call entirely when the LSTM signal is weak
        # (flat bias OR max class prob < threshold). Pre-empts a Claude call
        # that would almost certainly have returned stance=wait.
        max_prob = max(pred.direction_probs)
        if pred.direction == 1 or max_prob < settings.llm_min_confidence:
            LLM_SKIPS["count"] += 1
            self.last_decision = LlmDecision(
                bias="flat",
                predictive=DIR_NAMES[pred.direction],  # type: ignore[arg-type]
                stance="wait",
                size_pct=0.0,
                reason=(
                    f"skipped llm: lstm {DIR_NAMES[pred.direction]} max_prob="
                    f"{max_prob:.2f} < {settings.llm_min_confidence:.2f}"
                ),
            )
            return []

        equity = self.state.book.equity(marks)
        day_pnl_pct = (equity - settings.agent_starting_capital) / settings.agent_starting_capital * 100

        # Phase 3: pull the agent's own most-similar past stamped setups
        # after the cost gate (so a skipped LLM call also skips the DB hit)
        # and before building LlmContext. Errors degrade gracefully to [];
        # retrieval must never block a decision.
        try:
            examples = await retrieval.fetch(self.state.id, self.symbol)
            retrieved_examples = [ex.to_dict() for ex in examples]
        except Exception as e:  # pragma: no cover — fetch already swallows
            log.warning(
                "retrieval_unexpected_error",
                agent_id=self.state.id,
                symbol=self.symbol,
                error=str(e),
            )
            retrieved_examples = []

        ctx = LlmContext(
            symbol=self.symbol,
            feature_digest=_feature_digest(df),
            lstm_direction=DIR_NAMES[pred.direction],
            lstm_probs=pred.direction_probs,
            lstm_confidence=pred.confidence,
            has_long=has_long,
            held_qty=held_qty,
            day_pnl_pct=day_pnl_pct,
            retrieved_examples=retrieved_examples,
        )

        try:
            LLM_SKIPS["called"] += 1
            decision = await self._overlay.decide(ctx)
        except Exception:
            self.last_decision = None
            return []

        self.last_decision = decision

        if decision.stance == "wait" or decision.size_pct <= 0:
            return []
        if decision.predictive == "long" and not has_long:
            qty = round(self.state.book.cash * min(decision.size_pct, 0.25) / px, 4)
            if qty <= 0:
                return []
            return [Signal(self.symbol, "buy", qty, reason=f"llm:{decision.reason[:60]}")]
        if decision.predictive in ("short", "flat") and has_long:
            return [Signal(self.symbol, "sell", round(pos.qty, 4), reason=f"llm:{decision.reason[:60]}")]
        return []
