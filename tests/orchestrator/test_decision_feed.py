"""Tests for ``tradefarm.orchestrator.decision_feed``.

Uses light-weight stand-ins for the Agent / AgentState / LlmDecision shapes
so the tests don't depend on the broker, DB, or LSTM model files.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from tradefarm.agents.base import Signal
from tradefarm.orchestrator.decision_feed import (
    build_decision_payload,
    build_decisions_batch,
)


# ---------------------------------------------------------------------------
# Stubs — mirror just the attributes ``build_decision_payload`` reads.
# ---------------------------------------------------------------------------


@dataclass
class _StubState:
    id: int
    name: str
    strategy: str


class _StubAgent:
    """Minimal stand-in matching the surface the helper reads.

    The helper only touches ``state``, ``symbol`` (optional), ``last_lstm``
    or ``last_prediction``, and ``last_decision`` — not the full Agent ABC.
    """

    def __init__(
        self,
        *,
        agent_id: int,
        name: str,
        strategy: str,
        symbol: str | None = None,
        last_lstm: dict[str, Any] | None = None,
        last_prediction: dict[str, Any] | None = None,
        last_decision: Any | None = None,
    ) -> None:
        self.state = _StubState(id=agent_id, name=name, strategy=strategy)
        self.symbol = symbol
        # Both attribute names exist on different strategy classes; mirror that.
        if last_lstm is not None:
            self.last_lstm = last_lstm
        if last_prediction is not None:
            self.last_prediction = last_prediction
        self.last_decision = last_decision


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_momentum_wait_payload() -> None:
    """Momentum agent with no signals → verdict=wait, reason mentions the cross."""
    agent = _StubAgent(
        agent_id=1,
        name="agent-001",
        strategy="momentum_sma20",
        symbol="SPY",
    )
    payload = build_decision_payload(agent, signals=[], marks={"SPY": 500.0})

    assert payload["agent_id"] == 1
    assert payload["agent_name"] == "agent-001"
    assert payload["strategy"] == "momentum_sma20"
    assert payload["symbol"] == "SPY"
    assert payload["verdict"] == "wait"
    assert payload["lstm_probs"] is None
    assert payload["lstm_max_prob"] is None
    assert payload["lstm_direction"] is None
    assert payload["llm_bias"] is None
    assert payload["llm_stance"] is None
    assert "cross" in payload["reason"]
    assert "wait" in payload["reason"]
    # ISO timestamp shape (we don't assert exact value).
    assert isinstance(payload["at"], str) and "T" in payload["at"]


def test_momentum_trade_payload_uses_signal_reason() -> None:
    """A momentum trade surfaces the signal's own reason text."""
    agent = _StubAgent(
        agent_id=2,
        name="agent-002",
        strategy="momentum_sma20",
        symbol="QQQ",
    )
    payload = build_decision_payload(
        agent,
        signals=[Signal("QQQ", "buy", 1.0, reason="golden cross")],
        marks={},
    )
    assert payload["verdict"] == "trade"
    assert payload["reason"] == "golden cross"


def test_lstm_flat_wait_reason() -> None:
    """LSTM with flat-direction probs + no signals → "lstm flat 0.45 — wait"."""
    agent = _StubAgent(
        agent_id=3,
        name="agent-003",
        strategy="lstm_v1",
        symbol="AAPL",
        last_prediction={
            "direction": "flat",
            "probs": (0.20, 0.45, 0.35),
            "confidence": 0.45,
        },
    )
    payload = build_decision_payload(agent, signals=[], marks={})

    assert payload["verdict"] == "wait"
    assert payload["lstm_probs"] == [0.20, 0.45, 0.35]
    assert payload["lstm_max_prob"] == pytest.approx(0.45)
    assert payload["lstm_direction"] == "flat"
    assert payload["reason"] == "lstm flat 0.45 — wait"


def test_lstm_below_threshold_reason() -> None:
    """LSTM picks a direction but the max prob is below the 0.40 entry thresh."""
    agent = _StubAgent(
        agent_id=4,
        name="agent-004",
        strategy="lstm_v1",
        symbol="MSFT",
        last_prediction={
            "direction": "up",
            "probs": (0.30, 0.32, 0.38),
            "confidence": 0.38,
        },
    )
    payload = build_decision_payload(agent, signals=[], marks={})
    assert payload["verdict"] == "wait"
    # Threshold copy is specific: "below 0.40 thresh".
    assert "below 0.40 thresh" in payload["reason"]
    assert "lstm up 0.38" in payload["reason"]


def test_lstm_trade_payload() -> None:
    """LSTM with non-empty signals → verdict=trade."""
    agent = _StubAgent(
        agent_id=5,
        name="agent-005",
        strategy="lstm_v1",
        symbol="NVDA",
        last_prediction={
            "direction": "up",
            "probs": (0.10, 0.20, 0.70),
            "confidence": 0.70,
        },
    )
    payload = build_decision_payload(
        agent,
        signals=[Signal("NVDA", "buy", 0.5, reason="lstm up p=0.70")],
        marks={},
    )
    assert payload["verdict"] == "trade"
    assert payload["lstm_direction"] == "up"
    assert payload["lstm_max_prob"] == pytest.approx(0.70)
    assert "trade" in payload["reason"].lower()


def test_lstm_llm_wait_includes_llm_verdict_and_reason() -> None:
    """LSTM+LLM agent with ``last_decision.stance="wait"`` surfaces the LLM's
    own reason text and its verdict in the reason string."""
    last_decision = SimpleNamespace(
        bias="flat",
        predictive="flat",
        stance="wait",
        size_pct=0.0,
        reason="weak signal, sit out",
    )
    agent = _StubAgent(
        agent_id=6,
        name="agent-006",
        strategy="lstm_llm_v1",
        symbol="TSLA",
        last_lstm={
            "direction": "up",
            "probs": (0.25, 0.30, 0.45),
            "confidence": 0.45,
        },
        last_decision=last_decision,
    )
    payload = build_decision_payload(agent, signals=[], marks={})

    assert payload["verdict"] == "wait"
    assert payload["llm_stance"] == "wait"
    assert payload["llm_bias"] == "flat"
    assert "WAIT" in payload["reason"]
    assert "weak signal" in payload["reason"]


def test_lstm_llm_skipped_call_falls_back_to_lstm_shape() -> None:
    """When the LLM was cost-gated (last_decision present but reason is the
    skip message), the LSTM-shape reason still gives audience-useful context.
    """
    last_decision = SimpleNamespace(
        bias="flat",
        predictive="flat",
        stance="wait",
        size_pct=0.0,
        reason="skipped llm: lstm flat max_prob=0.39 < 0.40",
    )
    agent = _StubAgent(
        agent_id=7,
        name="agent-007",
        strategy="lstm_llm_v1",
        symbol="META",
        last_lstm={
            "direction": "flat",
            "probs": (0.30, 0.39, 0.31),
            "confidence": 0.39,
        },
        last_decision=last_decision,
    )
    payload = build_decision_payload(agent, signals=[], marks={})
    # Still surfaces the LLM reason (which itself describes the skip).
    assert "skipped llm" in payload["reason"]
    assert payload["llm_stance"] == "wait"


def test_build_decisions_batch_envelope() -> None:
    """The batch helper wraps per-agent payloads into the documented envelope."""
    a1 = _StubAgent(agent_id=10, name="a-010", strategy="momentum_sma20", symbol="SPY")
    a2 = _StubAgent(
        agent_id=11,
        name="a-011",
        strategy="lstm_v1",
        symbol="QQQ",
        last_prediction={
            "direction": "up",
            "probs": (0.20, 0.30, 0.50),
            "confidence": 0.50,
        },
    )
    results = [
        (a1, []),
        (a2, [Signal("QQQ", "buy", 1.0, reason="lstm up p=0.50")]),
    ]
    batch = build_decisions_batch(results, marks={}, tick_id="abc123")

    assert batch["tick_id"] == "abc123"
    assert isinstance(batch["at"], str)
    assert len(batch["decisions"]) == 2
    assert {d["agent_id"] for d in batch["decisions"]} == {10, 11}
    # Verdicts line up.
    by_id = {d["agent_id"]: d for d in batch["decisions"]}
    assert by_id[10]["verdict"] == "wait"
    assert by_id[11]["verdict"] == "trade"
