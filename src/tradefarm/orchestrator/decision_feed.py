"""Pure helpers that translate per-agent state into a stream-friendly
``agent_decision`` payload.

The orchestrator's tick loop calls :func:`build_decision_payload` once per
agent right after ``agent.decide(...)`` so the broadcast app can render
*every* agent's reasoning each tick — including the (common) case where the
agent decided to WAIT. This is what turns "flat day, zero fills" from a
silent stream into an audible inner monologue.

Kept dependency-free and synchronous so it's trivially unit-testable; the
orchestrator wraps the resulting dicts into a single ``agent_decisions_batch``
event per tick (see :mod:`tradefarm.orchestrator.scheduler`).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from tradefarm.agents.base import Agent, Signal

# Map LSTM class index -> human-readable direction. Mirrors the agents'
# ``DIR_NAMES`` tuple so any drift here will surface in the same place.
_DIR_FROM_INDEX = ("down", "flat", "up")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lstm_snapshot(agent: Agent) -> dict[str, Any] | None:
    """Return the most-recent LSTM dict for this agent, regardless of which
    strategy class produced it.

    - :class:`LstmAgent` stores its prediction under ``last_prediction``.
    - :class:`LstmLlmAgent` stores it under ``last_lstm``.

    Both shapes are ``{"direction": str, "probs": tuple, "confidence": float}``.
    Returns ``None`` for momentum agents (no LSTM in their loop).
    """
    snap = getattr(agent, "last_lstm", None)
    if snap is None:
        snap = getattr(agent, "last_prediction", None)
    if snap is None:
        return None
    # Normalize: probs may arrive as a tuple from the model layer.
    probs = snap.get("probs") if isinstance(snap, dict) else None
    if probs is None:
        return None
    return {
        "direction": snap.get("direction"),
        "probs": [float(p) for p in probs],
        "confidence": float(snap.get("confidence") or 0.0),
    }


def _lstm_max_prob(probs: list[float] | None) -> tuple[float | None, str | None]:
    if not probs or len(probs) != 3:
        # _DIR_FROM_INDEX is keyed 0/1/2 (down/flat/up). A non-3-length
        # probs array means the upstream snapshot is malformed; refuse
        # to make up a direction rather than indexing into nothing.
        return None, None
    idx = max(range(3), key=lambda i: probs[i])
    return float(probs[idx]), _DIR_FROM_INDEX[idx]


def _short_reason_momentum(verdict: str, signals: list[Signal]) -> str:
    """Reason string for momentum agents.

    On a trade we surface the underlying ``Signal.reason`` (which is already a
    short phrase like "golden cross"). On a wait we say so explicitly — the
    audience-facing copy is the *whole point* of this module.
    """
    if verdict == "trade" and signals:
        return signals[0].reason or "cross — trade"
    return "no cross — wait"


def _short_reason_lstm(
    verdict: str,
    lstm: dict[str, Any] | None,
    enter_conf: float = 0.40,
) -> str:
    """Reason string for the LSTM-only strategy.

    Distinguishes three wait modes that show up in the stream caption:
    - LSTM picked ``flat`` → "lstm flat 0.42 — wait"
    - LSTM picked a direction but below the entry threshold → "...below 0.40 thresh"
    - LSTM picked a direction above threshold → "lstm up 0.62 — buy" / "sell"
    """
    if lstm is None:
        return "no lstm snapshot — wait"
    direction = lstm.get("direction") or "?"
    max_prob, _ = _lstm_max_prob(lstm.get("probs"))
    prob_str = f"{max_prob:.2f}" if max_prob is not None else "?"
    if verdict == "trade":
        # The trade side (buy/sell) is implied by the signal; just label the
        # direction the LSTM saw.
        return f"lstm {direction} {prob_str} — trade"
    # WAIT branches.
    if direction == "flat":
        return f"lstm flat {prob_str} — wait"
    if max_prob is not None and max_prob < enter_conf:
        return f"lstm {direction} {prob_str} — below {enter_conf:.2f} thresh"
    return f"lstm {direction} {prob_str} — wait"


def _short_reason_lstm_llm(
    verdict: str,
    lstm: dict[str, Any] | None,
    last_decision: Any | None,
) -> str:
    """Reason string for the LSTM+LLM hybrid.

    Prefers the LLM's own one-liner when present (it's already capped at ~80
    chars per the LLM schema). Falls back to the LSTM-shape reason when the
    LLM call was skipped (cost-gated) or failed.
    """
    if last_decision is not None:
        llm_reason = getattr(last_decision, "reason", None)
        llm_stance = getattr(last_decision, "stance", None)
        if llm_reason:
            # Prefix the stance so listeners get the verdict before the rationale.
            verdict_str = (llm_stance or verdict or "?").upper()
            # Cap the surfaced reason so it doesn't blow out a ticker row;
            # the LLM schema already promises ≤80 chars but be defensive.
            return f"llm {verdict_str}: {llm_reason[:120]}"
    return _short_reason_lstm(verdict, lstm)


def _build_reason(
    strategy: str,
    verdict: str,
    lstm: dict[str, Any] | None,
    last_decision: Any | None,
    signals: list[Signal],
) -> str:
    if strategy == "momentum_sma20":
        return _short_reason_momentum(verdict, signals)
    if strategy == "lstm_v1":
        return _short_reason_lstm(verdict, lstm)
    if strategy == "lstm_llm_v1":
        return _short_reason_lstm_llm(verdict, lstm, last_decision)
    # Unknown strategy — degrade gracefully rather than raise on a hot path.
    return f"{strategy} — {verdict}"


def build_decision_payload(
    agent: Agent,
    signals: Iterable[Signal],
    marks: dict[str, float],
) -> dict[str, Any]:
    """Build a single ``agent_decision`` payload from an agent's current state.

    Parameters
    ----------
    agent:
        The agent whose decision is being surfaced. Reads ``state``,
        ``last_lstm`` / ``last_prediction``, and ``last_decision`` — none of
        which are mutated.
    signals:
        The list returned by ``agent.decide(...)`` for this tick. Empty list
        is interpreted as ``verdict="wait"``; non-empty as ``"trade"``.
    marks:
        The current marks dict — currently unused but reserved so future
        reasons can mention the symbol's mark without changing the signature.

    Returns
    -------
    A plain ``dict`` matching the ``agent_decision`` wire schema documented in
    the Decision Lab spec. Always JSON-serializable.
    """
    del marks  # reserved for future use, kept in the signature on purpose
    sig_list = list(signals)
    verdict = "trade" if sig_list else "wait"

    lstm = _lstm_snapshot(agent)
    lstm_probs = lstm["probs"] if lstm else None
    lstm_max_prob, lstm_direction_from_probs = _lstm_max_prob(lstm_probs)
    # Prefer the agent-published direction string (already normalized); fall
    # back to whichever class index has the max prob.
    lstm_direction = (lstm.get("direction") if lstm else None) or lstm_direction_from_probs

    last_decision = getattr(agent, "last_decision", None)
    llm_bias = getattr(last_decision, "bias", None) if last_decision is not None else None
    llm_stance = getattr(last_decision, "stance", None) if last_decision is not None else None

    reason = _build_reason(agent.state.strategy, verdict, lstm, last_decision, sig_list)

    return {
        "agent_id": agent.state.id,
        "agent_name": agent.state.name,
        "strategy": agent.state.strategy,
        "symbol": getattr(agent, "symbol", None),
        "verdict": verdict,
        "lstm_probs": lstm_probs,
        "lstm_max_prob": lstm_max_prob,
        "lstm_direction": lstm_direction,
        "llm_bias": llm_bias,
        "llm_stance": llm_stance,
        "reason": reason,
        "at": _now_iso(),
    }


def build_decisions_batch(
    results: Iterable[tuple[Agent, list[Signal]]],
    marks: dict[str, float],
    tick_id: str,
) -> dict[str, Any]:
    """Wrap ``build_decision_payload`` for every (agent, signals) pair into a
    single ``agent_decisions_batch`` envelope.

    One WS event per tick keeps the fan-out cheap at 100 agents/tick.
    """
    at = _now_iso()
    decisions = [build_decision_payload(a, sigs, marks) for a, sigs in results]
    return {"at": at, "tick_id": tick_id, "decisions": decisions}
