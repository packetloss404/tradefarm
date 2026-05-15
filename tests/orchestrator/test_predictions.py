"""PredictionsBoard — voting, lifecycle, winner resolution, dedup."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from unittest.mock import AsyncMock, patch

from tradefarm.market.hours import ET
from tradefarm.orchestrator.predictions import PredictionsBoard


# ---------------------------------------------------------------------------
# Stubs.
# ---------------------------------------------------------------------------


@dataclass
class _StubBook:
    realized: float = 0.0
    unrealized: float = 0.0

    @property
    def realized_pnl(self) -> float:
        return self.realized

    def unrealized_pnl(self, marks: dict[str, float]) -> float:
        return self.unrealized


@dataclass
class _StubState:
    id: int
    name: str
    book: _StubBook = field(default_factory=_StubBook)


@dataclass
class _StubAgent:
    state: _StubState


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)
    last_marks: dict[str, float] = field(default_factory=dict)


def _make_orch(
    pnls: list[tuple[int, str, float]] | None = None,
    marks: dict[str, float] | None = None,
) -> _StubOrch:
    pnls = pnls or [(1, "agent-001", 0.0), (2, "agent-002", 0.0)]
    agents = [
        _StubAgent(state=_StubState(id=i, name=n, book=_StubBook(realized=p)))
        for i, n, p in pnls
    ]
    return _StubOrch(agents=agents, last_marks=marks or {})


def _et(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=ET)


# ---------------------------------------------------------------------------
# Seeding + open-state voting.
# ---------------------------------------------------------------------------


async def test_seed_creates_both_predictions():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    snapshot = board.snapshot()
    assert len(snapshot) == 2
    ids = {p["id"] for p in snapshot}
    assert ids == {"pick-winner", "spy-direction"}
    for p in snapshot:
        assert p["status"] == "open"
        assert p["tally"] == {}


async def test_vote_accepted_when_open():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        ok = await board.record_vote("spy-direction", "alice", "up")
        assert ok is True

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["tally"] == {"up": 1}


async def test_vote_rejected_when_locked():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    # Force-lock.
    board._predictions["spy-direction"].status = "locked"

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        ok = await board.record_vote("spy-direction", "alice", "up")

    assert ok is False
    assert board.snapshot()[0]["tally"] in ({}, {"up": 0})  # tally unchanged


async def test_unknown_prediction_id_rejected():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    ok = await board.record_vote("nope", "alice", "up")
    assert ok is False


async def test_spy_direction_only_accepts_up_or_down():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        assert await board.record_vote("spy-direction", "a", "sideways") is False
        assert await board.record_vote("spy-direction", "a", "UP") is True

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["tally"] == {"up": 1}


async def test_one_vote_per_user_dedup():
    """Re-voting overwrites the previous option rather than double-counting."""
    orch = _make_orch()
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.record_vote("spy-direction", "alice", "up")
        await board.record_vote("spy-direction", "alice", "down")
        await board.record_vote("spy-direction", "bob", "up")

    snap = {p["id"]: p for p in board.snapshot()}
    # Alice's "up" was replaced by "down". Bob's "up" still stands.
    assert snap["spy-direction"]["tally"] == {"up": 1, "down": 1}


async def test_same_vote_repeated_is_noop():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    board._seed_session(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.record_vote("spy-direction", "alice", "up")
        await board.record_vote("spy-direction", "alice", "up")

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["tally"] == {"up": 1}


# ---------------------------------------------------------------------------
# Lifecycle transitions.
# ---------------------------------------------------------------------------


async def test_lifecycle_open_to_locked_to_revealed():
    orch = _make_orch(
        pnls=[(1, "agent-001", 50.0), (2, "agent-002", 10.0)],
        marks={"SPY": 410.0},
    )
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    # Open at 8:00 ET — seed + record some votes.
    pre_open = _et(2026, 5, 14, 8, 0)
    await board.tick(pre_open)

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.record_vote("spy-direction", "alice", "up")
        await board.record_vote("pick-winner", "bob", "agent-001")

        # 9:30 → locked.
        at_lock = _et(2026, 5, 14, 9, 30)
        # Seed SPY baseline before locking by ticking with marks present:
        await board.tick(at_lock)

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["status"] == "locked"
    assert snap["pick-winner"]["status"] == "locked"
    assert snap["spy-direction"]["tally"] == {"up": 1}

    # Votes rejected once locked.
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        ok = await board.record_vote("spy-direction", "carol", "down")
    assert ok is False

    # 16:00 → revealed. SPY moves up vs. baseline (410 → 415).
    orch.last_marks["SPY"] = 415.0
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.tick(_et(2026, 5, 14, 16, 0))

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["status"] == "revealed"
    assert snap["spy-direction"]["winning_option"] == "up"
    assert snap["pick-winner"]["status"] == "revealed"
    # agent-001 has highest realized PnL → winning option matches.
    assert snap["pick-winner"]["winning_option"] == "agent-001"


async def test_spy_direction_down_winner():
    orch = _make_orch(marks={"SPY": 400.0})
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    await board.tick(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.record_vote("spy-direction", "alice", "down")
        # Lock with baseline=400.
        await board.tick(_et(2026, 5, 14, 9, 30))

    # SPY drops by close.
    orch.last_marks["SPY"] = 388.0
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.tick(_et(2026, 5, 14, 16, 0))

    snap = {p["id"]: p for p in board.snapshot()}
    assert snap["spy-direction"]["winning_option"] == "down"


async def test_pick_winner_uses_highest_realized_plus_unrealized():
    """Resolution should consider both realized and unrealized P&L."""
    @dataclass
    class _Book:
        @property
        def realized_pnl(self) -> float:
            return self._realized

        def unrealized_pnl(self, marks: dict[str, float]) -> float:
            return self._unrealized

        _realized: float = 0.0
        _unrealized: float = 0.0

    orch = _StubOrch(
        agents=[
            _StubAgent(state=_StubState(
                id=1, name="alpha", book=_StubBook(realized=10.0, unrealized=0.0),
            )),
            _StubAgent(state=_StubState(
                id=2, name="beta", book=_StubBook(realized=5.0, unrealized=100.0),
            )),
        ],
        last_marks={},
    )
    board = PredictionsBoard(orch=orch)  # type: ignore[arg-type]
    await board.tick(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.tick(_et(2026, 5, 14, 16, 0))

    snap = {p["id"]: p for p in board.snapshot()}
    # beta wins because realized+unrealized (105) > alpha (10).
    assert snap["pick-winner"]["winning_option"] == "beta"


# ---------------------------------------------------------------------------
# Publish payload shape.
# ---------------------------------------------------------------------------


async def test_publish_event_carries_state_dict():
    orch = _make_orch()
    board = PredictionsBoard(orch=orch, publish_debounce_sec=0.0)  # type: ignore[arg-type]
    await board.tick(_et(2026, 5, 14, 8, 0))

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.predictions.publish_event", fake):
        await board.record_vote("spy-direction", "alice", "up")

    matches = [
        call.args[1]
        for call in fake.await_args_list
        if call.args and call.args[0] == "prediction_state"
    ]
    assert len(matches) >= 1
    payload = matches[-1]
    assert payload["id"] == "spy-direction"
    assert payload["status"] == "open"
    assert payload["tally"] == {"up": 1}
    assert payload["options"] == ["up", "down"]
    # Locks_at / reveals_at are ISO strings.
    assert payload["locks_at"].startswith("2026-05-14")
    assert payload["reveals_at"].startswith("2026-05-14")
