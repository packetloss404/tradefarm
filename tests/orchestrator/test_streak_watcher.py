"""StreakWatcher — pattern detection against the journal + cooldown tests.

Uses stub Orchestrator / agent objects and patches
``tradefarm.storage.journal.recent_outcomes`` so the polling logic is
exercised without a real DB. ``publish_event`` is patched to a list-appender
to inspect every macro fire.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest  # noqa: F401  (asyncio_mode = "auto"; import to register fixtures)

from tradefarm.orchestrator.streak_watcher import StreakWatcher


# ---------------------------------------------------------------------------
# Stubs — minimal Orchestrator/agent surface area for StreakWatcher.
# ---------------------------------------------------------------------------


@dataclass
class _StubState:
    id: int
    name: str


@dataclass
class _StubAgent:
    state: _StubState
    symbol: str | None = None


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)


def _make_agent(agent_id: int = 1, name: str | None = None, symbol: str | None = "AAPL") -> _StubAgent:
    return _StubAgent(
        state=_StubState(id=agent_id, name=name or f"agent-{agent_id:03d}"),
        symbol=symbol,
    )


def _outcome(pnl: float, closed_at: datetime, symbol: str = "AAPL") -> dict:
    """Build a journal note row matching the shape ``recent_outcomes`` emits."""
    return {
        "id": 1,
        "agent_id": 0,
        "kind": "entry",
        "symbol": symbol,
        "content": "",
        "metadata": {},
        "created_at": closed_at.isoformat(),
        "outcome_trade_id": None,
        "outcome_realized_pnl": pnl,
        "outcome_closed_at": closed_at.isoformat(),
    }


def _captured_payloads(mock: AsyncMock) -> list[dict[str, Any]]:
    """Pull the payload dict from each publish_event call (positional or kw)."""
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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _journal_stub(rows_by_agent: dict[int, list[dict]]):
    """Build an AsyncMock for ``journal.recent_outcomes`` that returns the
    canned rows per agent id.
    """
    async def _impl(agent_id: int, n: int = 20) -> list[dict]:
        return list(rows_by_agent.get(agent_id, []))[:n]
    return AsyncMock(side_effect=_impl)


# ---------------------------------------------------------------------------
# 1. Win streak fires once; second poll suppressed by cooldown.
# ---------------------------------------------------------------------------


async def test_win_streak_fires_then_cooldown_suppresses():
    now = _now()
    rows = [
        _outcome(50.0, now - timedelta(minutes=1)),
        _outcome(20.0, now - timedelta(minutes=10)),
        _outcome(10.0, now - timedelta(minutes=30)),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=1, name="agent-001")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({1: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired_a = await watcher.check_once()
        fired_b = await watcher.check_once()

    assert "streak-win3-1" in fired_a
    assert fired_b == []  # cooldown
    payloads = _captured_payloads(fake_publish)
    win = next(p for p in payloads if p["id"] == "streak-win3-1")
    assert win["label"] == "agent-001 on a heater"
    assert win["color"] == "profit"
    assert win["subtitle"] == "3 wins straight"


# ---------------------------------------------------------------------------
# 2. Mixed history with last-3 wins — fires (tail-only semantics).
#
# We chose the semantics where only the last N outcomes matter; "L W W W"
# trips the 3-win detector because its tail is all wins. Document via this
# test so future readers don't get confused.
# ---------------------------------------------------------------------------


async def test_mixed_history_with_tail_wins_fires():
    now = _now()
    # Newest first: W W W L.  Tail of length 3 is all positive.
    rows = [
        _outcome(15.0, now - timedelta(minutes=1)),
        _outcome(10.0, now - timedelta(minutes=5)),
        _outcome(20.0, now - timedelta(minutes=10)),
        _outcome(-50.0, now - timedelta(minutes=30)),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=2, name="agent-002")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({2: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert "streak-win3-2" in fired


async def test_broken_tail_does_not_fire():
    """Last 3 contain a loss → no win streak."""
    now = _now()
    # W L W (newest first) — tail isn't 3 wins.
    rows = [
        _outcome(10.0, now - timedelta(minutes=1)),
        _outcome(-5.0, now - timedelta(minutes=5)),
        _outcome(15.0, now - timedelta(minutes=10)),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=3, name="agent-003")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({3: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert "streak-win3-3" not in fired
    # Likewise no loss streak (need 5 reds).
    assert "streak-loss5-3" not in fired


# ---------------------------------------------------------------------------
# 3. Five-loss streak.
# ---------------------------------------------------------------------------


async def test_five_loss_streak_fires():
    now = _now()
    rows = [
        _outcome(-10.0, now - timedelta(minutes=1)),
        _outcome(-12.0, now - timedelta(minutes=5)),
        _outcome(-8.0, now - timedelta(minutes=10)),
        _outcome(-15.0, now - timedelta(minutes=20)),
        _outcome(-20.0, now - timedelta(minutes=30)),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=4, name="agent-004")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({4: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert "streak-loss5-4" in fired
    payload = next(p for p in _captured_payloads(fake_publish) if p["id"] == "streak-loss5-4")
    assert payload["label"] == "agent-004 ice cold"
    assert payload["color"] == "loss"
    assert payload["subtitle"] == "5 in a row red"


# ---------------------------------------------------------------------------
# 4. Biggest gain of the day — first poll seeds leader; bigger PnL refires.
# ---------------------------------------------------------------------------


async def test_bigwin_of_day_refires_on_new_leader():
    now = _now()

    # First poll: agent 10 has +$120 today (the only win today).
    initial_rows = {
        10: [_outcome(120.0, now - timedelta(minutes=5))],
        11: [_outcome(50.0, now - timedelta(minutes=10))],
    }
    orch = _StubOrch(agents=[
        _make_agent(agent_id=10, name="agent-010"),
        _make_agent(agent_id=11, name="agent-011"),
    ])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub(initial_rows)
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        # First poll seeds the leader cache without firing (mid-day-restart
        # protection — stale leaders shouldn't auto-announce on boot).
        seed = await watcher.check_once()
        # Second poll on the same data — still no fire (seeded leader unchanged).
        steady = await watcher.check_once()
        # New trade pushes agent 11 ahead with +$200 → leader changes → fires.
        initial_rows[11] = [
            _outcome(200.0, now - timedelta(minutes=1)),
            _outcome(50.0, now - timedelta(minutes=10)),
        ]
        first_fire = await watcher.check_once()
        # Same data again — no new leader → no fire.
        third = await watcher.check_once()

    assert "streak-bigwin-day" not in seed
    assert "streak-bigwin-day" not in steady
    assert "streak-bigwin-day" in first_fire
    assert "streak-bigwin-day" not in third
    payloads = _captured_payloads(fake_publish)
    leader_payloads = [p for p in payloads if p["id"] == "streak-bigwin-day"]
    assert len(leader_payloads) == 1
    assert leader_payloads[0]["color"] == "profit"
    assert leader_payloads[0]["label"] == "Trade of the day"
    assert leader_payloads[0]["subtitle"] == "agent-011: +$200"


async def test_bigwin_of_day_cooldown_suppresses_repeat_fire():
    """With cooldown intact, same data on second poll doesn't refire."""
    now = _now()
    rows = {10: [_outcome(120.0, now - timedelta(minutes=5))]}
    orch = _StubOrch(agents=[_make_agent(agent_id=10, name="agent-010")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub(rows)
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        # First poll seeds. Push a bigger leader so the second poll fires once.
        await watcher.check_once()
        rows[10] = [_outcome(300.0, now - timedelta(minutes=4))]
        first_fire = await watcher.check_once()
        # No change; cooldown should keep it quiet.
        second = await watcher.check_once()

    assert "streak-bigwin-day" in first_fire
    assert "streak-bigwin-day" not in second


# ---------------------------------------------------------------------------
# 5. Quiet → active "back in action".
# ---------------------------------------------------------------------------


async def test_back_in_action_after_quiet():
    now = _now()
    rows = [
        # Latest: just closed (within FRESH_WINDOW).
        _outcome(15.0, now - timedelta(seconds=10), symbol="NVDA"),
        # Previous: 2 hours ago — comfortably beyond QUIET_GAP.
        _outcome(-5.0, now - timedelta(hours=2), symbol="NVDA"),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=7, name="agent-007", symbol="NVDA")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({7: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert "streak-awake-7" in fired
    payload = next(p for p in _captured_payloads(fake_publish) if p["id"] == "streak-awake-7")
    assert payload["label"] == "agent-007 back in action"
    assert payload["color"] == "neutral"
    assert payload["subtitle"] == "NVDA"


async def test_back_in_action_skipped_when_not_quiet():
    """Previous outcome was only 5 minutes earlier → not a "long quiet" gap."""
    now = _now()
    rows = [
        _outcome(15.0, now - timedelta(seconds=10)),
        _outcome(10.0, now - timedelta(minutes=5)),
    ]
    orch = _StubOrch(agents=[_make_agent(agent_id=8, name="agent-008")])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({8: rows})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert "streak-awake-8" not in fired


# ---------------------------------------------------------------------------
# 6. Empty / sparse journals don't crash and don't fire.
# ---------------------------------------------------------------------------


async def test_no_outcomes_no_fires():
    orch = _StubOrch(agents=[_make_agent(agent_id=99)])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub({99: []})
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        fired = await watcher.check_once()

    assert fired == []
    assert fake_publish.await_count == 0


# ---------------------------------------------------------------------------
# 7. Biggest-loss-of-day mirrors big-win path.
# ---------------------------------------------------------------------------


async def test_bigloss_of_day_fires_and_refires_on_worse_loss():
    now = _now()
    rows = {
        20: [_outcome(-150.0, now - timedelta(minutes=5))],
        21: [_outcome(-30.0, now - timedelta(minutes=8))],
    }
    orch = _StubOrch(agents=[
        _make_agent(agent_id=20, name="agent-020"),
        _make_agent(agent_id=21, name="agent-021"),
    ])
    watcher = StreakWatcher(orch=orch)  # type: ignore[arg-type]

    fake_publish = AsyncMock()
    journal_mock = _journal_stub(rows)
    with patch("tradefarm.orchestrator.streak_watcher.publish_event", fake_publish), \
            patch("tradefarm.orchestrator.streak_watcher.journal.recent_outcomes", journal_mock):
        # First poll seeds the leader cache; doesn't fire.
        seed = await watcher.check_once()
        rows[21] = [
            _outcome(-400.0, now - timedelta(minutes=1)),
            _outcome(-30.0, now - timedelta(minutes=8)),
        ]
        first_fire = await watcher.check_once()

    assert "streak-bigloss-day" not in seed
    assert "streak-bigloss-day" in first_fire
    loss_payloads = [p for p in _captured_payloads(fake_publish) if p["id"] == "streak-bigloss-day"]
    assert len(loss_payloads) == 1
    assert loss_payloads[0]["subtitle"] == "agent-021: −$400"
    assert loss_payloads[0]["color"] == "loss"
    assert loss_payloads[0]["label"] == "Wipeout of the day"
