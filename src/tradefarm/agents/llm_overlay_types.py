"""Shared types + prompt constants for LLM providers.

Pulled out of `llm_overlay.py` so `llm_providers.py` can import them without
a cycle (overlay imports providers; providers need LlmContext/LlmDecision).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Bias = Literal["long", "short", "flat"]
Stance = Literal["trade", "wait"]

SYSTEM_PROMPT = """You are a disciplined trading agent for a US equities paper-trading sandbox.

Inputs you'll receive each turn:
- A short feature digest for one ticker (last few days, indicators)
- An LSTM model's directional probabilities and confidence
- Risk context: current position, day P&L vs the 5% daily-loss limit

Your job: respond with a JSON object describing your decision. Be honest about uncertainty — when the LSTM is weak (confidence < 0.55) or signals conflict, the right answer is `wait`.

Schema (no extra keys, no prose):
{
  "bias":       "long" | "short" | "flat",   // your directional read
  "predictive": "long" | "short" | "flat",   // what you think the next move is
  "stance":     "trade" | "wait",            // whether to act now
  "size_pct":   number,                      // 0..0.25, fraction of agent capital to risk if trading
  "reason":     "\u226480 char rationale"
}

Rules:
- If stance=wait, size_pct must be 0.
- Default size_pct around 0.15-0.20 when conviction is normal; reduce when confidence is borderline.
- Never short if the agent already holds a long (close first); never go long if already long with size > 0.20.
- If day P&L is below -3% of starting capital, prefer stance=wait."""


@dataclass
class LlmDecision:
    bias: Bias
    predictive: Bias
    stance: Stance
    size_pct: float
    reason: str


@dataclass
class LlmContext:
    symbol: str
    feature_digest: str
    lstm_direction: str
    lstm_probs: tuple[float, float, float]
    lstm_confidence: float
    has_long: bool
    held_qty: float
    day_pnl_pct: float


def user_message(ctx: LlmContext) -> str:
    return (
        f"Ticker: {ctx.symbol}\n"
        f"Feature digest: {ctx.feature_digest}\n"
        f"LSTM: bias={ctx.lstm_direction} probs(down/flat/up)="
        f"({ctx.lstm_probs[0]:.2f}/{ctx.lstm_probs[1]:.2f}/{ctx.lstm_probs[2]:.2f}) "
        f"confidence={ctx.lstm_confidence:.2f}\n"
        f"Position: {'long ' + str(ctx.held_qty) if ctx.has_long else 'flat'}\n"
        f"Day P&L vs starting capital: {ctx.day_pnl_pct:+.2f}%\n"
        f"\nReturn the decision JSON now."
    )
