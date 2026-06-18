from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from tradefarm.orchestrator.broadcast_os import (
    BroadcastMoment,
    install_broadcast_arbiter,
    moment_from_macro,
    publish_broadcast_moment,
)
from tradefarm.orchestrator.broadcast_scheduler import BroadcastScheduler


def _payloads(mock: AsyncMock, event_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in mock.await_args_list:
        args = call.args
        if len(args) >= 2 and args[0] == event_type:
            out.append(args[1])
    return out


def test_moment_from_macro_maps_trigger_priority_and_kind():
    moment = moment_from_macro(
        {
            "id": "auto-rank-3",
            "label": "Promotion: agent-003",
            "color": "profit",
            "subtitle": "intern -> junior",
            "agent_id": 3,
            "trigger": "promotion",
        }
    )

    assert moment.id == "auto-rank-3"
    assert moment.kind == "rank_change"
    assert moment.priority == 90
    assert moment.title == "Promotion: agent-003"
    assert moment.agent_id == 3
    assert moment.outputs == ("macro_burst", "ticker", "recap_log")


async def test_publish_broadcast_moment_emits_canonical_and_legacy_events():
    publish = AsyncMock()
    moment = BroadcastMoment(
        id="moment-1",
        kind="activity",
        title="Desk note",
        subtitle="Quiet tape",
        color="neutral",
        outputs=("macro_burst", "lower_third", "recap_log"),
    )

    await publish_broadcast_moment(moment, publish=publish)

    canonical = _payloads(publish, "broadcast_moment")
    macros = _payloads(publish, "stream_macro_fired")
    banners = _payloads(publish, "stream_banner")

    assert canonical[0]["title"] == "Desk note"
    assert canonical[0]["outputs"] == ["macro_burst", "lower_third", "recap_log"]
    assert macros[0] == {
        "id": "moment-1",
        "label": "Desk note",
        "color": "neutral",
        "subtitle": "Quiet tape",
    }
    assert banners[0] == {
        "title": "Desk note",
        "ttl_sec": 8,
        "subtitle": "Quiet tape",
    }


async def test_publish_broadcast_moment_emits_queued_slot_state():
    """A moment blocked behind a higher-priority slot must report 'queued',
    not the old always-'active' value."""

    clock = iter([0.0, 1.0])
    scheduler = BroadcastScheduler(clock=lambda: next(clock))
    publish = AsyncMock()
    install_broadcast_arbiter(None, scheduler)
    try:
        active = BroadcastMoment(
            id="breaking",
            kind="market_move",
            title="Breaking",
            priority=90,
            outputs=("lower_third",),
            ttl_sec=30,
        )
        ambient = BroadcastMoment(
            id="ambient",
            kind="activity",
            title="Ambient",
            priority=20,
            outputs=("lower_third",),
            ttl_sec=10,
        )
        await publish_broadcast_moment(active, publish=publish, emit_legacy=False)
        await publish_broadcast_moment(ambient, publish=publish, emit_legacy=False)
    finally:
        install_broadcast_arbiter(None, None)

    slots = _payloads(publish, "broadcast_slot")
    by_id = {slot["moment_id"]: slot["state"] for slot in slots}
    assert by_id == {"breaking": "active", "ambient": "queued"}
