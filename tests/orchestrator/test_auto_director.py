"""AutoDirector — threshold detection, cooldown, and macro payload tests.

Uses stub Orchestrator / agent objects so the polling logic can be exercised
without touching the DB, broker, or LLM. ``publish_event`` is patched to a
list-appender so we can inspect every macro fire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tradefarm.config import settings
from tradefarm.orchestrator.auto_director import AutoDirector


# ---------------------------------------------------------------------------
# Stubs: just enough surface area for AutoDirector to read.
# ---------------------------------------------------------------------------


@dataclass
class _StubBook:
    equity_value: float = 1000.0

    def equity(self, marks: dict[str, float]) -> float:
        return self.equity_value


@dataclass
class _StubRisk:
    rank: str = "intern"


@dataclass
class _StubState:
    id: int
    name: str
    book: _StubBook = field(default_factory=_StubBook)


@dataclass
class _StubAgent:
    state: _StubState
    risk: _StubRisk = field(default_factory=_StubRisk)
    symbol: str | None = None


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)
    last_marks: dict[str, float] = field(default_factory=dict)


def _make_agent(
    agent_id: int = 1,
    name: str = "agent-001",
    equity: float = 1000.0,
    rank: str = "intern",
    symbol: str | None = "AAPL",
) -> _StubAgent:
    return _StubAgent(
        state=_StubState(id=agent_id, name=name, book=_StubBook(equity_value=equity)),
        risk=_StubRisk(rank=rank),
        symbol=symbol,
    )


def _captured_payloads(mock: AsyncMock) -> list[dict[str, Any]]:
    """Pull the payload dict from each publish_event call."""
    out: list[dict[str, Any]] = []
    for call in mock.await_args_list:
        args = call.args
        kwargs = call.kwargs
        if len(args) >= 2:
            assert args[0] == "stream_macro_fired"
            out.append(args[1])
        else:
            assert kwargs.get("type") == "stream_macro_fired"
            out.append(kwargs["payload"])
    return out


# ---------------------------------------------------------------------------
# 1. Big-win threshold + cooldown.
# ---------------------------------------------------------------------------


async def test_big_win_fires_once_and_respects_cooldown(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agent = _make_agent(agent_id=42, name="agent-042", equity=1060.0, symbol="AAPL")
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        fired_a = await director.check_once()
        fired_b = await director.check_once()

    assert fired_a == ["auto-big-win-42"]
    assert fired_b == []  # within cooldown

    payloads = _captured_payloads(fake_publish)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["id"] == "auto-big-win-42"
    assert payload["label"] == "Big win: agent-042"
    assert payload["color"] == "profit"
    assert payload["subtitle"].startswith("AAPL +")
    assert "6.0" in payload["subtitle"]


# ---------------------------------------------------------------------------
# 2. Crash threshold.
# ---------------------------------------------------------------------------


async def test_crash_fires_loss_macro(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agent = _make_agent(agent_id=7, name="agent-007", equity=940.0, symbol="TSLA")
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        fired = await director.check_once()

    assert fired == ["auto-crash-7"]
    payload = _captured_payloads(fake_publish)[0]
    assert payload["id"] == "auto-crash-7"
    assert payload["label"] == "Crash: agent-007"
    assert payload["color"] == "loss"
    assert payload["subtitle"].startswith("TSLA")
    assert "-6.0" in payload["subtitle"] or "−6.0" in payload["subtitle"]


# ---------------------------------------------------------------------------
# 3. SPY market surge.
# ---------------------------------------------------------------------------


async def test_market_surge_fires_after_baseline(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    orch = _StubOrch(agents=[], last_marks={"SPY": 400.0})
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        # First poll seeds the baseline; nothing fires.
        first = await director.check_once()
        assert first == []
        # SPY moves +2.5%.
        orch.last_marks["SPY"] = 410.0
        second = await director.check_once()

    assert second == ["auto-market-surge"]
    payload = _captured_payloads(fake_publish)[0]
    assert payload["id"] == "auto-market-surge"
    assert payload["label"] == "Market surge"
    assert payload["color"] == "profit"
    assert payload["subtitle"].startswith("SPY +")
    assert "2.5" in payload["subtitle"]


async def test_market_crash_fires_after_baseline(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    orch = _StubOrch(agents=[], last_marks={"SPY": 400.0})
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        first = await director.check_once()
        assert first == []
        orch.last_marks["SPY"] = 388.0  # -3.0%
        fired = await director.check_once()

    assert fired == ["auto-market-crash"]
    payload = _captured_payloads(fake_publish)[0]
    assert payload["color"] == "loss"
    assert payload["subtitle"].startswith("SPY −")


# ---------------------------------------------------------------------------
# 4. Rank promotion.
# ---------------------------------------------------------------------------


async def test_promotion_fires_on_rank_up():
    agent = _make_agent(agent_id=3, name="agent-003", rank="intern", equity=1000.0)
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        # First poll: snapshot only, no movement.
        first = await director.check_once()
        assert first == []
        # Promote the agent and poll again.
        agent.risk.rank = "junior"
        fired = await director.check_once()

    assert fired == ["auto-rank-3"]
    payload = _captured_payloads(fake_publish)[0]
    assert payload["id"] == "auto-rank-3"
    assert payload["label"] == "Promotion: agent-003"
    assert payload["color"] == "profit"
    assert payload["subtitle"] == "intern → junior"


async def test_demotion_is_silent():
    """Demotions shouldn't fire a celebratory macro."""
    agent = _make_agent(agent_id=4, name="agent-004", rank="senior", equity=1000.0)
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        await director.check_once()
        agent.risk.rank = "junior"  # demoted
        fired = await director.check_once()

    assert fired == []
    assert fake_publish.await_count == 0


# ---------------------------------------------------------------------------
# 5. Cooldown — second crossing within 30 min is suppressed.
# ---------------------------------------------------------------------------


async def test_cooldown_suppresses_second_fire(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agent = _make_agent(agent_id=11, name="agent-011", equity=1080.0, symbol="MSFT")
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        first = await director.check_once()
        # Equity oscillates back into the green a moment later.
        agent.state.book.equity_value = 1090.0
        second = await director.check_once()

    assert first == ["auto-big-win-11"]
    assert second == []
    assert fake_publish.await_count == 1


async def test_cooldown_expires_after_window(monkeypatch):
    """After 30 min, the same trigger can fire again."""
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agent = _make_agent(agent_id=11, name="agent-011", equity=1080.0, symbol="MSFT")
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch, cooldown=timedelta(seconds=0))  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        first = await director.check_once()
        second = await director.check_once()

    assert first == ["auto-big-win-11"]
    assert second == ["auto-big-win-11"]
    assert fake_publish.await_count == 2


# ---------------------------------------------------------------------------
# 6. Independence — different agents fire independently.
# ---------------------------------------------------------------------------


async def test_independent_cooldowns_across_agents(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    a1 = _make_agent(agent_id=1, name="agent-001", equity=1070.0)
    a2 = _make_agent(agent_id=2, name="agent-002", equity=1080.0)
    orch = _StubOrch(agents=[a1, a2])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        fired = await director.check_once()

    assert set(fired) == {"auto-big-win-1", "auto-big-win-2"}


# ---------------------------------------------------------------------------
# 7. Macro payload shape — only id/label required; color & subtitle optional.
# ---------------------------------------------------------------------------


async def test_payload_omits_optional_when_unset(monkeypatch):
    """Agent with no pinned symbol still emits a valid payload (no symbol token)."""
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agent = _make_agent(agent_id=9, name="agent-009", equity=1060.0, symbol=None)
    orch = _StubOrch(agents=[agent])
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        await director.check_once()

    payload = _captured_payloads(fake_publish)[0]
    assert payload["id"] == "auto-big-win-9"
    assert payload["color"] == "profit"
    # Subtitle should be just the percentage, no symbol prefix.
    assert payload["subtitle"].startswith("+")
    assert "6.0" in payload["subtitle"]


# ---------------------------------------------------------------------------
# 8. No-equity-move agents don't fire.
# ---------------------------------------------------------------------------


async def test_no_threshold_crossings_no_fires(monkeypatch):
    monkeypatch.setattr(settings, "agent_starting_capital", 1000.0)
    agents = [
        _make_agent(agent_id=i, name=f"agent-{i:03d}", equity=1020.0)
        for i in range(5)
    ]
    orch = _StubOrch(agents=agents, last_marks={"SPY": 400.0})
    director = AutoDirector(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.auto_director.publish_event", fake_publish):
        first = await director.check_once()
        second = await director.check_once()  # SPY didn't move

    assert first == []
    assert second == []
    assert fake_publish.await_count == 0
