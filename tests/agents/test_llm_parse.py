"""Validation tests for the LLM response parser.

Guards Issue #9: a malformed model reply must raise a distinct
:class:`LlmParseError` (so it is logged as a parse error, not conflated with a
network "call failed"), enum values must be in range, and ``size_pct`` must be
clamped into the advertised 0..0.25 band.
"""

from __future__ import annotations

import json

import pytest

from tradefarm.agents.llm_overlay_types import (
    SIZE_PCT_CAP,
    LlmDecision,
    LlmParseError,
    parse_decision,
)
from tradefarm.agents.llm_providers import _parse_decision_json


def _valid() -> dict:
    return {
        "bias": "long",
        "predictive": "long",
        "stance": "trade",
        "size_pct": 0.15,
        "reason": "lstm up, normal conviction",
    }


def test_valid_response_parses() -> None:
    d = parse_decision(json.dumps(_valid()))
    assert isinstance(d, LlmDecision)
    assert d.bias == "long"
    assert d.predictive == "long"
    assert d.stance == "trade"
    assert d.size_pct == pytest.approx(0.15)
    assert d.reason == "lstm up, normal conviction"


def test_valid_response_with_code_fence() -> None:
    fenced = "```json\n" + json.dumps(_valid()) + "\n```"
    d = parse_decision(fenced)
    assert d.bias == "long"


def test_missing_key_raises_parse_error() -> None:
    payload = _valid()
    del payload["bias"]
    with pytest.raises(LlmParseError):
        parse_decision(json.dumps(payload))


def test_out_of_enum_bias_rejected() -> None:
    payload = _valid()
    payload["bias"] = "garbage"
    with pytest.raises(LlmParseError):
        parse_decision(json.dumps(payload))


def test_out_of_enum_stance_rejected() -> None:
    payload = _valid()
    payload["stance"] = "yolo"
    with pytest.raises(LlmParseError):
        parse_decision(json.dumps(payload))


def test_size_pct_over_cap_is_clamped() -> None:
    payload = _valid()
    payload["size_pct"] = 5.0
    d = parse_decision(json.dumps(payload))
    assert d.size_pct == pytest.approx(SIZE_PCT_CAP)


def test_size_pct_negative_is_clamped_to_zero() -> None:
    payload = _valid()
    payload["size_pct"] = -3.0
    d = parse_decision(json.dumps(payload))
    assert d.size_pct == 0.0


def test_size_pct_non_numeric_raises_parse_error() -> None:
    payload = _valid()
    payload["size_pct"] = "lots"
    with pytest.raises(LlmParseError):
        parse_decision(json.dumps(payload))


def test_size_pct_defaults_to_zero_when_missing() -> None:
    payload = _valid()
    del payload["size_pct"]
    d = parse_decision(json.dumps(payload))
    assert d.size_pct == 0.0


def test_invalid_json_raises_parse_error() -> None:
    with pytest.raises(LlmParseError):
        parse_decision("not json at all {")


def test_non_object_json_raises_parse_error() -> None:
    with pytest.raises(LlmParseError):
        parse_decision("[1, 2, 3]")


def test_reason_is_truncated() -> None:
    payload = _valid()
    payload["reason"] = "x" * 500
    d = parse_decision(json.dumps(payload))
    assert len(d.reason) == 120


def test_extra_keys_ignored() -> None:
    payload = _valid()
    payload["unexpected"] = "value"
    d = parse_decision(json.dumps(payload))
    assert d.bias == "long"


def test_provider_wrapper_raises_parse_error_not_keyerror() -> None:
    """The provider-level wrapper must surface LlmParseError, not KeyError."""
    payload = _valid()
    del payload["predictive"]
    with pytest.raises(LlmParseError):
        _parse_decision_json(json.dumps(payload))
