from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from tradefarm.orchestrator.scheduler import Orchestrator, _FillMomentCandidate


def _payloads(mock: AsyncMock, event_type: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for call in mock.await_args_list:
        args = call.args
        if len(args) >= 2 and args[0] == event_type:
            out.append(args[1])
    return out


async def test_fill_of_tick_publishes_lower_third_moment():
    orch = Orchestrator(agents=[])
    publish = AsyncMock()
    fill = _FillMomentCandidate(
        agent_id=7,
        agent_name="agent-007",
        symbol="NVDA",
        side="buy",
        qty=2.0,
        price=100.0,
        reason="test fill",
    )

    with patch("tradefarm.orchestrator.scheduler.publish_event", publish):
        await orch._publish_fill_of_tick("tick123", [fill])

    moments = _payloads(publish, "broadcast_moment")
    banners = _payloads(publish, "stream_banner")
    macros = _payloads(publish, "stream_macro_fired")

    assert moments[0]["id"] == "fill-of-tick-tick123"
    assert moments[0]["trigger"] == "fill_of_tick"
    assert moments[0]["outputs"] == ["lower_third", "ticker", "recap_log"]
    assert moments[0]["metadata"]["notional"] == 200.0
    assert banners[0]["title"] == "Fill of the tick"
    assert "agent-007 bought 2 NVDA" in banners[0]["subtitle"]
    assert macros == []


async def test_fill_of_tick_skips_tiny_fills():
    orch = Orchestrator(agents=[])
    publish = AsyncMock()
    fill = _FillMomentCandidate(
        agent_id=7,
        agent_name="agent-007",
        symbol="NVDA",
        side="buy",
        qty=0.1,
        price=100.0,
        reason="dust fill",
    )

    with patch("tradefarm.orchestrator.scheduler.publish_event", publish):
        await orch._publish_fill_of_tick("tick123", [fill])

    assert publish.await_count == 0
