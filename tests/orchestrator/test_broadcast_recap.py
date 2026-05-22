from __future__ import annotations

import pytest

from tradefarm.orchestrator.broadcast_os import BroadcastMoment
from tradefarm.orchestrator.broadcast_recap import BroadcastRecapLedger


def _moment(
    moment_id: str,
    *,
    priority: int = 50,
    kind: str = "activity",
    outputs: tuple[str, ...] = ("recap_log",),
) -> BroadcastMoment:
    return BroadcastMoment(
        id=moment_id,
        kind=kind,
        title=f"Moment {moment_id}",
        priority=priority,
        outputs=outputs,
        metadata={"source": "test"},
    )


def test_recent_moments_are_newest_first_and_bounded():
    ledger = BroadcastRecapLedger(max_moments=3)

    ledger.extend([
        _moment("m1"),
        _moment("m2"),
        _moment("m3"),
        _moment("m4"),
    ])

    assert len(ledger) == 3
    assert [moment.id for moment in ledger.recent_moments()] == ["m4", "m3", "m2"]
    assert [moment.id for moment in ledger.recent_moments(limit=2)] == ["m4", "m3"]


def test_top_moments_sort_by_priority_then_recency():
    ledger = BroadcastRecapLedger(max_moments=10)
    ledger.extend([
        _moment("low", priority=10),
        _moment("tie-old", priority=90),
        _moment("best", priority=95),
        _moment("tie-new", priority=90),
    ])

    assert [moment.id for moment in ledger.top_moments(limit=3)] == [
        "best",
        "tie-new",
        "tie-old",
    ]


def test_queries_filter_by_kind_and_output():
    ledger = BroadcastRecapLedger(max_moments=10)
    ledger.extend([
        _moment("activity-ticker", kind="activity", outputs=("ticker", "recap_log")),
        _moment("market-audio", kind="market_move", outputs=("audio",)),
        _moment("market-lower", kind="market_move", outputs=("lower_third", "recap_log")),
        _moment("rank-lower", kind="rank_change", outputs=("lower_third",)),
    ])

    assert [moment.id for moment in ledger.recent_moments(kind="market_move")] == [
        "market-lower",
        "market-audio",
    ]
    assert [moment.id for moment in ledger.recent_moments(output="lower_third")] == [
        "rank-lower",
        "market-lower",
    ]
    assert [
        moment.id
        for moment in ledger.recent_moments(kind={"activity", "market_move"}, output="recap_log")
    ] == ["market-lower", "activity-ticker"]


def test_payloads_are_plain_dicts_for_api_work():
    ledger = BroadcastRecapLedger(max_moments=5)
    ledger.extend([
        _moment("low", priority=20, outputs=("ticker",)),
        _moment("high", priority=80, kind="rank_change", outputs=("ticker", "recap_log")),
    ])

    recent = ledger.recent_payloads(limit=1)
    assert recent == [{
        "id": "high",
        "kind": "rank_change",
        "title": "Moment high",
        "priority": 80,
        "color": "neutral",
        "outputs": ["ticker", "recap_log"],
        "ttl_sec": 8,
        "created_at": recent[0]["created_at"],
        "metadata": {"source": "test"},
    }]
    assert isinstance(recent[0], dict)
    assert isinstance(recent[0]["outputs"], list)

    recent[0]["metadata"]["source"] = "mutated"
    assert ledger.recent_payloads(limit=1)[0]["metadata"] == {"source": "test"}

    snapshot = ledger.to_payload(recent_limit=2, top_limit=1, output="ticker")
    assert snapshot["max_moments"] == 5
    assert snapshot["count"] == 2
    assert [moment["id"] for moment in snapshot["recent"]] == ["high", "low"]
    assert [moment["id"] for moment in snapshot["top"]] == ["high"]


def test_invalid_capacity_or_limit_raises():
    with pytest.raises(ValueError, match="max_moments"):
        BroadcastRecapLedger(max_moments=0)

    ledger = BroadcastRecapLedger()
    with pytest.raises(ValueError, match="limit"):
        ledger.recent_moments(limit=-1)
