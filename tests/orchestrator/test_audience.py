"""AudienceCoordinator — sentiment, pin requests, approve/reject."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tradefarm.orchestrator import audience as audience_mod
from tradefarm.orchestrator.audience import AudienceCoordinator


# ---------------------------------------------------------------------------
# Stubs.
# ---------------------------------------------------------------------------


@dataclass
class _StubState:
    id: int
    name: str


@dataclass
class _StubAgent:
    state: _StubState


@dataclass
class _StubOrch:
    agents: list[_StubAgent] = field(default_factory=list)


def _make_orch(agents: list[tuple[int, str]] | None = None) -> _StubOrch:
    agents = agents or [(1, "agent-001"), (2, "agent-002"), (7, "alpha-bot")]
    return _StubOrch(agents=[_StubAgent(state=_StubState(id=i, name=n)) for i, n in agents])


def _msg(text: str, *, user: str = "viewer") -> dict[str, Any]:
    return {
        "id": "x",
        "user": user,
        "text": text,
        "color": "neutral",
        "source": "youtube",
        "at": "2026-05-14T12:00:00Z",
    }


def _payloads(mock: AsyncMock, event_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in mock.await_args_list:
        args = call.args
        if len(args) >= 2 and args[0] == event_type:
            out.append(args[1])
    return out


# ---------------------------------------------------------------------------
# Sentiment.
# ---------------------------------------------------------------------------


async def test_sentiment_accumulates_signed_score():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!vote up", user="a"))
        await coord.on_chat_message(_msg("!vote up", user="b"))
        await coord.on_chat_message(_msg("!vote down", user="c"))

    snap = coord.sentiment_snapshot()
    assert snap["up"] == 2
    assert snap["down"] == 1
    # (2 - 1) / 3 = 0.333...
    assert snap["score"] == pytest.approx(1 / 3)
    assert snap["window_sec"] == 300


async def test_sentiment_score_bounded_minus_one_to_plus_one():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        for i in range(5):
            await coord.on_chat_message(_msg("!vote up", user=f"u{i}"))
    assert coord.sentiment_snapshot()["score"] == pytest.approx(1.0)

    coord2 = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        for i in range(3):
            await coord2.on_chat_message(_msg("!vote down", user=f"d{i}"))
    assert coord2.sentiment_snapshot()["score"] == pytest.approx(-1.0)


async def test_sentiment_window_expires_old_votes(monkeypatch):
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch, window=timedelta(seconds=10))  # type: ignore[arg-type]

    # Manually inject an old vote, then a fresh one.
    far_past = datetime.now(timezone.utc) - timedelta(seconds=60)
    coord._votes.append(audience_mod._Vote(direction="up", at=far_past))
    coord._votes.append(audience_mod._Vote(direction="down", at=datetime.now(timezone.utc)))

    snap = coord.sentiment_snapshot()
    # Old "up" vote evicted; only "down" remains.
    assert snap["up"] == 0
    assert snap["down"] == 1
    assert snap["score"] == pytest.approx(-1.0)


async def test_sentiment_zero_score_when_empty():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    snap = coord.sentiment_snapshot()
    assert snap["up"] == 0
    assert snap["down"] == 0
    assert snap["score"] == 0.0


async def test_sentiment_publishes_event_on_vote():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch, debounce_sec=0.0)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!vote up"))

    payloads = _payloads(fake, "audience_sentiment")
    assert len(payloads) == 1
    assert payloads[0]["up"] == 1
    assert payloads[0]["score"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Pin requests.
# ---------------------------------------------------------------------------


async def test_pin_resolves_by_id():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin 2", user="alice"))

    payloads = _payloads(fake, "audience_pin_request")
    assert len(payloads) == 1
    p = payloads[0]
    assert p["agent_id"] == 2
    assert p["agent_name_query"] == "2"
    assert p["requester"] == "alice"


async def test_pin_resolves_by_name_substring():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin alpha", user="bob"))

    payloads = _payloads(fake, "audience_pin_request")
    assert len(payloads) == 1
    # "alpha" matches "alpha-bot" (id=7).
    assert payloads[0]["agent_id"] == 7


async def test_pin_unresolved_query_keeps_null_agent_id():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin nonexistent", user="carol"))

    payloads = _payloads(fake, "audience_pin_request")
    assert len(payloads) == 1
    assert payloads[0]["agent_id"] is None
    assert payloads[0]["agent_name_query"] == "nonexistent"


async def test_pin_queue_cap_evicts_oldest():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch, queue_cap=3)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        for i in range(5):
            await coord.on_chat_message(_msg(f"!pin {i}", user=f"u{i}"))

    pending = coord.pending_requests()
    assert len(pending) == 3
    # Newest-first ordering; the 5 queries were 0..4 → kept 2, 3, 4.
    assert pending[0]["agent_name_query"] == "4"
    assert pending[-1]["agent_name_query"] == "2"


async def test_approve_publishes_resolved_and_fires_scene():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin 2", user="alice"))
        # Pull the request id from the published event.
        req_id = _payloads(fake, "audience_pin_request")[0]["id"]
        ok = await coord.approve_pin_request(req_id)

    assert ok is True
    resolved = _payloads(fake, "audience_pin_resolved")
    assert len(resolved) == 1
    assert resolved[0]["id"] == req_id
    assert resolved[0]["status"] == "approved"
    assert resolved[0]["agent_id"] == 2

    scenes = _payloads(fake, "stream_scene")
    assert len(scenes) == 1
    assert scenes[0] == {"pin_agent_id": 2}

    # Approving the same id twice is a no-op (request was popped).
    fake2 = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake2):
        ok = await coord.approve_pin_request(req_id)
    assert ok is False


async def test_approve_with_null_agent_id_skips_stream_scene():
    """Approving an unresolved query publishes resolved but no scene change."""
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin nonexistent", user="alice"))
        req_id = _payloads(fake, "audience_pin_request")[0]["id"]
        ok = await coord.approve_pin_request(req_id)

    assert ok is True
    resolved = _payloads(fake, "audience_pin_resolved")
    assert len(resolved) == 1
    assert resolved[0]["status"] == "approved"
    assert resolved[0]["agent_id"] is None
    # No stream_scene event — nothing to spotlight.
    assert _payloads(fake, "stream_scene") == []


async def test_reject_publishes_resolved_rejected():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pin 2", user="alice"))
        req_id = _payloads(fake, "audience_pin_request")[0]["id"]
        ok = await coord.reject_pin_request(req_id)

    assert ok is True
    resolved = _payloads(fake, "audience_pin_resolved")
    assert len(resolved) == 1
    assert resolved[0]["status"] == "rejected"
    assert resolved[0]["agent_id"] == 2
    # Rejection must NOT fire a scene change.
    assert _payloads(fake, "stream_scene") == []


async def test_reject_unknown_id_returns_false():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        ok = await coord.reject_pin_request("does-not-exist")
    assert ok is False


# ---------------------------------------------------------------------------
# 0.12.0 — pin-queue dict refactor + approve/reject lock.
# ---------------------------------------------------------------------------


async def test_pending_requests_returns_newest_first_after_dict_refactor():
    """0.12.0: pin queue is a single insertion-ordered dict now.
    pending_requests() must still return entries newest-first (last
    appended = newest = index 0 in the response)."""
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        # Three pin requests, in order. The agent_name_query is the
        # only field that varies per request, so we can identify them
        # in the response payload.
        for q in ("alpha", "bravo", "charlie"):
            await coord._handle_pin(
                audience_mod.PinCommand(agent_query=q), requester="viewer"
            )

    pending = coord.pending_requests()
    # Newest first = "charlie" was the last _handle_pin, so it leads.
    assert [r["agent_name_query"] for r in pending] == ["charlie", "bravo", "alpha"]


async def test_concurrent_approve_reject_same_id_only_publishes_once():
    """0.12.0: the pin lock closes a double-publish race. An
    approve + reject for the same id fire concurrently; only one
    can pop the request, the other must see ``None`` and return
    False without publishing. Without the lock, both would pass
    the None-check on a stale view of the dict and both would
    publish ``audience_pin_resolved``."""
    import asyncio

    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord._handle_pin(
            audience_mod.PinCommand(agent_query="alpha"), requester="viewer"
        )
        # Capture the request id from the WS publish.
        req_id = _payloads(fake, "audience_pin_request")[0]["id"]
        fake.reset_mock()

        # Fire approve + reject concurrently for the same id. With the
        # lock, exactly one wins; the other sees None and returns
        # False without publishing.
        approve_task = asyncio.create_task(coord.approve_pin_request(req_id))
        reject_task = asyncio.create_task(coord.reject_pin_request(req_id))
        approve_ok, reject_ok = await asyncio.gather(approve_task, reject_task)

    # Exactly one path succeeded.
    assert [approve_ok, reject_ok].count(True) == 1
    # The queue is empty (the winning path popped; the losing path
    # saw None and returned False).
    assert coord.pending_requests() == []
    # Exactly one ``audience_pin_resolved`` publish fired.
    resolved = _payloads(fake, "audience_pin_resolved")
    assert len(resolved) == 1
    assert resolved[0]["id"] == req_id
    assert resolved[0]["status"] in ("approved", "rejected")


async def test_concurrent_approve_same_id_only_publishes_once():
    """0.12.0: the lock closes a different double-publish race — two
    concurrent approvals of the same id (e.g. a flaky UI clicking
    twice). Only one path should pop the request and publish."""
    import asyncio

    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]
    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord._handle_pin(
            audience_mod.PinCommand(agent_query="alpha"), requester="viewer"
        )
        req_id = _payloads(fake, "audience_pin_request")[0]["id"]
        fake.reset_mock()

        # Two concurrent approvals of the same id.
        a = asyncio.create_task(coord.approve_pin_request(req_id))
        b = asyncio.create_task(coord.approve_pin_request(req_id))
        a_ok, b_ok = await asyncio.gather(a, b)

    # Exactly one approval won.
    assert [a_ok, b_ok].count(True) == 1
    assert coord.pending_requests() == []
    resolved = _payloads(fake, "audience_pin_resolved")
    assert len(resolved) == 1
    assert resolved[0]["status"] == "approved"


async def test_pin_queue_cap_evicts_oldest_via_dict_first_key():
    """0.12.0: cap eviction now pops ``next(iter(self._pin_by_id))``
    (the first-inserted key) instead of the deque popleft. Verify
    the oldest request is the one evicted."""
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch, queue_cap=3)  # type: ignore[arg-type]
    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        for q in ("alpha", "bravo", "charlie", "delta"):
            await coord._handle_pin(
                audience_mod.PinCommand(agent_query=q), requester="viewer"
            )
    # alpha is the oldest → evicted when delta was inserted.
    remaining = {r["agent_name_query"] for r in coord.pending_requests()}
    assert remaining == {"bravo", "charlie", "delta"}


# ---------------------------------------------------------------------------
# Non-command messages are inert.
# ---------------------------------------------------------------------------


async def test_non_command_messages_dropped():
    orch = _make_orch()
    coord = AudienceCoordinator(orch=orch)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("hello!"))
        await coord.on_chat_message(_msg("!yeet x"))  # unknown command

    # No events should have been published.
    assert fake.await_count == 0


# ---------------------------------------------------------------------------
# Vote → prediction routing.
# ---------------------------------------------------------------------------


async def test_pick_routes_to_predictions_board():
    orch = _make_orch()
    predictions = AsyncMock()
    coord = AudienceCoordinator(orch=orch, predictions=predictions)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!pick agent-002", user="alice"))

    predictions.record_vote.assert_awaited_once_with(
        "pick-winner",
        "alice",
        "agent-002",
    )


async def test_spy_routes_to_predictions_board():
    orch = _make_orch()
    predictions = AsyncMock()
    coord = AudienceCoordinator(orch=orch, predictions=predictions)  # type: ignore[arg-type]

    fake = AsyncMock()
    with patch("tradefarm.orchestrator.audience.publish_event", fake):
        await coord.on_chat_message(_msg("!spy up", user="bob"))

    predictions.record_vote.assert_awaited_once_with(
        "spy-direction",
        "bob",
        "up",
    )
