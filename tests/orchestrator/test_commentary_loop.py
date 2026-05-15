"""CommentaryLoop — snapshot, cost-gate, LLM call, fallback, parse-error tests.

Uses stub Orchestrator / agent objects so the loop logic can be exercised
without touching the broker, DB, or a real LLM. The provider's underlying
client (``_commentary_completion``) is monkey-patched on the module to a
predictable async stub.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tradefarm.orchestrator import commentary_loop as cl
from tradefarm.orchestrator.commentary_loop import CommentaryLoop


# ---------------------------------------------------------------------------
# Stubs: just enough surface area for CommentaryLoop to read.
# ---------------------------------------------------------------------------


@dataclass
class _StubPos:
    qty: float
    avg_price: float


@dataclass
class _StubBook:
    cash: float = 1000.0
    positions: dict[str, _StubPos] = field(default_factory=dict)
    equity_value: float = 1000.0

    def equity(self, marks: dict[str, float]) -> float:
        return self.equity_value


@dataclass
class _StubState:
    id: int
    name: str
    strategy: str = "lstm_llm_v1"
    book: _StubBook = field(default_factory=_StubBook)


@dataclass
class _StubAgent:
    state: _StubState
    symbol: str | None = "AAPL"


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)
    last_marks: dict[str, float] = field(default_factory=dict)


def _make_agent(
    agent_id: int = 1,
    name: str = "agent-001",
    strategy: str = "lstm_llm_v1",
    equity: float = 1000.0,
    symbol: str | None = "AAPL",
    positions: dict[str, _StubPos] | None = None,
) -> _StubAgent:
    book = _StubBook(equity_value=equity, positions=positions or {})
    return _StubAgent(
        state=_StubState(id=agent_id, name=name, strategy=strategy, book=book),
        symbol=symbol,
    )


def _captured_payloads(mock: AsyncMock) -> list[dict[str, Any]]:
    """Pull the payload dict from each publish_event call."""
    out: list[dict[str, Any]] = []
    for call in mock.await_args_list:
        args = call.args
        kwargs = call.kwargs
        if len(args) >= 2:
            assert args[0] == "stream_commentary"
            out.append(args[1])
        else:
            assert kwargs.get("type") == "stream_commentary"
            out.append(kwargs["payload"])
    return out


# ---------------------------------------------------------------------------
# 1. Happy path — LLM returns valid JSON; emits source=llm.
# ---------------------------------------------------------------------------


async def test_successful_llm_call_emits_source_llm(monkeypatch):
    agent = _make_agent(
        agent_id=42,
        name="agent-042",
        equity=1060.0,
        symbol="AAPL",
        positions={"AAPL": _StubPos(qty=10, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 160.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    # Stub the LLM completion to return a parseable JSON payload.
    stub_completion = AsyncMock(
        return_value='{"text": "Agent-042 riding AAPL higher.", "kind": "play_by_play"}'
    )
    # And stub overlay construction so we don't need real API keys.
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        result = await loop.tick_once()

    assert result is not None
    assert result["source"] == "llm"
    assert result["kind"] == "play_by_play"
    assert result["text"] == "Agent-042 riding AAPL higher."
    assert result["id"] == "commentary-1"

    payloads = _captured_payloads(fake_publish)
    assert len(payloads) == 1
    assert payloads[0]["source"] == "llm"


# ---------------------------------------------------------------------------
# 2. LLM raises → fallback path with source=fallback.
# ---------------------------------------------------------------------------


async def test_llm_error_falls_back(monkeypatch):
    agent = _make_agent(
        equity=1020.0,
        positions={"AAPL": _StubPos(qty=5, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 152.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    stub_completion = AsyncMock(side_effect=RuntimeError("API down"))
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        result = await loop.tick_once()

    assert result is not None
    assert result["source"] == "fallback"
    assert result["kind"] == "color"
    assert isinstance(result["text"], str) and len(result["text"]) > 0
    assert len(result["text"]) <= cl.MAX_TEXT_CHARS

    payloads = _captured_payloads(fake_publish)
    assert len(payloads) == 1
    assert payloads[0]["source"] == "fallback"


# ---------------------------------------------------------------------------
# 3. Cost-gate skip — empty fills + tiny SPY move = no emission.
# ---------------------------------------------------------------------------


async def test_cost_gate_skips_when_quiet(monkeypatch):
    # Agent has no open positions; SPY hasn't moved (baseline == mark).
    agent = _make_agent(equity=1000.0, positions={})
    orch = _StubOrch(agents=[agent], last_marks={"SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    stub_completion = AsyncMock(
        return_value='{"text": "should not be called", "kind": "color"}'
    )
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        # First tick seeds the SPY baseline and finds no fills → quiet → skip.
        result = await loop.tick_once()

    assert result is None
    # Provider should NOT have been called.
    assert stub_completion.await_count == 0
    # No event published.
    assert fake_publish.await_count == 0


# ---------------------------------------------------------------------------
# 4. JSON parse failure → falls back gracefully.
# ---------------------------------------------------------------------------


async def test_unparseable_json_falls_back(monkeypatch):
    agent = _make_agent(
        equity=1010.0,
        positions={"AAPL": _StubPos(qty=2, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 151.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    # Return text that's not valid JSON.
    stub_completion = AsyncMock(return_value="not a json blob — sorry, model.")
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        result = await loop.tick_once()

    assert result is not None
    assert result["source"] == "fallback"
    assert result["kind"] == "color"
    assert isinstance(result["text"], str) and len(result["text"]) > 0


# ---------------------------------------------------------------------------
# 5. Text truncation — overlong LLM output is clipped to MAX_TEXT_CHARS.
# ---------------------------------------------------------------------------


async def test_overlong_text_is_truncated(monkeypatch):
    agent = _make_agent(
        equity=1100.0,
        positions={"AAPL": _StubPos(qty=10, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 165.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    long_text = "A " * 200  # 400+ chars
    stub_completion = AsyncMock(
        return_value=f'{{"text": "{long_text.strip()}", "kind": "color"}}'
    )
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        result = await loop.tick_once()

    assert result is not None
    assert len(result["text"]) <= cl.MAX_TEXT_CHARS


# ---------------------------------------------------------------------------
# 6. SPY drift past the quiet threshold → not skipped even with zero fills.
# ---------------------------------------------------------------------------


async def test_spy_drift_overrides_cost_gate(monkeypatch):
    agent = _make_agent(equity=1000.0, positions={})
    orch = _StubOrch(agents=[agent], last_marks={"SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    stub_completion = AsyncMock(
        return_value='{"text": "SPY turning south on heavy tape.", "kind": "color"}'
    )
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        # First call seeds the baseline (400.0) and is quiet → skip.
        first = await loop.tick_once()
        assert first is None
        # SPY drops 0.5% — well past SPY_QUIET_PCT (0.3%).
        orch.last_marks["SPY"] = 398.0
        second = await loop.tick_once()

    assert second is not None
    assert second["source"] == "llm"
    assert stub_completion.await_count == 1


# ---------------------------------------------------------------------------
# 7. Counter increments across emissions.
# ---------------------------------------------------------------------------


async def test_counter_increments_per_emission(monkeypatch):
    agent = _make_agent(
        equity=1040.0,
        positions={"AAPL": _StubPos(qty=5, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 158.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    stub_completion = AsyncMock(
        return_value='{"text": "Tape humming.", "kind": "color"}'
    )
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        r1 = await loop.tick_once()
        r2 = await loop.tick_once()

    assert r1 is not None and r2 is not None
    assert r1["id"] == "commentary-1"
    assert r2["id"] == "commentary-2"


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


class _FakeProvider:
    name = "stub"
    model = "stub-model"


class _FakeOverlay:
    """Stand-in for LlmOverlay.from_settings() — bypasses real API key checks."""

    def __init__(self) -> None:
        self.provider = _FakeProvider()

    @property
    def info(self) -> dict[str, str]:
        return {"provider": self.provider.name, "model": self.provider.model}


# ---------------------------------------------------------------------------
# 8. Direct test of _parse_commentary_json — handles fenced code blocks.
# ---------------------------------------------------------------------------


def test_parse_commentary_json_strips_code_fences():
    raw = '```json\n{"text": "Hello.", "kind": "play_by_play"}\n```'
    text, kind = cl._parse_commentary_json(raw)
    assert text == "Hello."
    assert kind == "play_by_play"


def test_parse_commentary_json_defaults_unknown_kind_to_color():
    raw = '{"text": "Hello.", "kind": "weird"}'
    _, kind = cl._parse_commentary_json(raw)
    assert kind == "color"


def test_parse_commentary_json_rejects_empty_text():
    with pytest.raises(ValueError):
        cl._parse_commentary_json('{"text": "", "kind": "color"}')


# ---------------------------------------------------------------------------
# 9. Prompt formatting — recent-fills line includes "shares" + notional.
# ---------------------------------------------------------------------------


def test_user_message_formats_fills_with_shares_and_notional():
    # Replicates the bug case: 1.0 shares XLV @ $146.63 → notional ≈ $146.63.
    # (1.364 * 146.63 ≈ 199.997 which rounds to $200.00 — pick whole share
    # so the exact formatted notional is unambiguous.)
    agent = _make_agent(
        agent_id=88,
        name="agent-088",
        symbol="XLV",
        positions={"XLV": _StubPos(qty=1.0, avg_price=146.63)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"XLV": 146.63, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    snap = loop._snapshot()
    msg = loop._user_message(snap)

    # The line must call out "shares" so qty can't be misread as a kilo-share,
    # and must pre-compute the dollar notional so the LLM doesn't multiply.
    assert "1 shares XLV" in msg
    assert "(notional ≈ $146.63)" in msg


def test_user_message_formats_large_notional_without_decimals():
    # Notional >= $10k drops the decimals (".0f").
    agent = _make_agent(
        agent_id=7,
        name="agent-007",
        symbol="AAPL",
        positions={"AAPL": _StubPos(qty=100, avg_price=150.0)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"AAPL": 150.0, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    snap = loop._snapshot()
    msg = loop._user_message(snap)

    assert "100 shares AAPL" in msg
    assert "(notional ≈ $15,000)" in msg


# ---------------------------------------------------------------------------
# 10. _strip_hallucinated_magnitudes — clean text passes, hallucinated returns None.
# ---------------------------------------------------------------------------


def _snap_with_max_notional(notional: float) -> cl._StateSnapshot:
    """Build a minimal snapshot whose max recent-fill notional matches `notional`."""
    fills = (
        [cl._FillSnap(agent_name="agent-001", side="long", qty=1.0, symbol="XLV", price=notional)]
        if notional > 0
        else []
    )
    return cl._StateSnapshot(
        top_agents=[],
        recent_fills=fills,
        spy_mark=400.0,
        spy_pct=0.0,
        provider_name="stub",
    )


def test_strip_hallucinated_magnitudes_passes_clean_text():
    snap = _snap_with_max_notional(200.0)
    text = "Agent-088 picking up XLV on the dip."
    assert cl._strip_hallucinated_magnitudes(text, snap) == text


def test_strip_hallucinated_magnitudes_returns_none_for_inflated_dollar_claim():
    # Max notional $200; LLM claims "$200K" → 1000× inflation → hallucinated.
    snap = _snap_with_max_notional(200.0)
    text = "Agent-088 just dropped a $200K long on XLV."
    assert cl._strip_hallucinated_magnitudes(text, snap) is None


def test_strip_hallucinated_magnitudes_returns_none_for_inflated_bare_magnitude():
    # Max notional $200; threshold = $2000. LLM says "5k shares" → magnitude
    # 5000 > 2000 → flagged as hallucinated.
    snap = _snap_with_max_notional(200.0)
    text = "Agent-088 sitting on 5k shares of XLV."
    assert cl._strip_hallucinated_magnitudes(text, snap) is None


def test_strip_hallucinated_magnitudes_allows_modest_overstatement():
    # Max notional $200, 10× threshold → claims up to $2000 are tolerated.
    # "$1k" = 5× → fine; "$2k" = 10× → still at the boundary (not strictly >).
    snap = _snap_with_max_notional(200.0)
    assert cl._strip_hallucinated_magnitudes("XLV $1k clip just hit.", snap) is not None


def test_strip_hallucinated_magnitudes_allows_text_when_no_positions():
    # Empty snapshot — no positions to misrepresent; ambient flavor is fine.
    snap = _snap_with_max_notional(0.0)
    text = "Quiet $2M tape, options gamma is muted."
    assert cl._strip_hallucinated_magnitudes(text, snap) == text


def test_strip_hallucinated_magnitudes_ignores_word_boundary_letters():
    # Make sure "Mark", "Karen", etc. aren't read as magnitude tokens.
    snap = _snap_with_max_notional(200.0)
    text = "Agent Mark and Karen are leaning long on XLV."
    assert cl._strip_hallucinated_magnitudes(text, snap) == text


# ---------------------------------------------------------------------------
# 11. End-to-end — LLM emits "$200K" against $200 snapshot → fallback path.
# ---------------------------------------------------------------------------


async def test_hallucinated_llm_response_falls_back():
    # 1.364 shares XLV @ $146.63 → max notional $199.99
    agent = _make_agent(
        agent_id=88,
        name="agent-088",
        symbol="XLV",
        positions={"XLV": _StubPos(qty=1.364, avg_price=146.63)},
    )
    orch = _StubOrch(agents=[agent], last_marks={"XLV": 146.63, "SPY": 400.0})
    loop = CommentaryLoop(orch=orch)  # type: ignore[arg-type]

    stub_completion = AsyncMock(
        return_value='{"text": "Agent-088 throwing a $200K long on XLV!", "kind": "play_by_play"}'
    )
    fake_publish = AsyncMock()
    with patch.object(cl, "_commentary_completion", stub_completion), \
         patch.object(cl.LlmOverlay, "from_settings", return_value=_FakeOverlay()), \
         patch.object(cl, "publish_event", fake_publish):
        result = await loop.tick_once()

    # The LLM call succeeded but its output was rejected → fallback path.
    assert result is not None
    assert result["source"] == "fallback"
    # And the fabricated "$200K" claim must not have made it through.
    assert "$200K" not in result["text"]
    assert "200K" not in result["text"]
