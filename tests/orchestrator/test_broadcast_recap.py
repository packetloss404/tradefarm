from __future__ import annotations

import json
from pathlib import Path

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

    ledger.extend(
        [
            _moment("m1"),
            _moment("m2"),
            _moment("m3"),
            _moment("m4"),
        ]
    )

    assert len(ledger) == 3
    assert [moment.id for moment in ledger.recent_moments()] == ["m4", "m3", "m2"]
    assert [moment.id for moment in ledger.recent_moments(limit=2)] == ["m4", "m3"]


def test_top_moments_sort_by_priority_then_recency():
    ledger = BroadcastRecapLedger(max_moments=10)
    ledger.extend(
        [
            _moment("low", priority=10),
            _moment("tie-old", priority=90),
            _moment("best", priority=95),
            _moment("tie-new", priority=90),
        ]
    )

    assert [moment.id for moment in ledger.top_moments(limit=3)] == [
        "best",
        "tie-new",
        "tie-old",
    ]


def test_queries_filter_by_kind_and_output():
    ledger = BroadcastRecapLedger(max_moments=10)
    ledger.extend(
        [
            _moment("activity-ticker", kind="activity", outputs=("ticker", "recap_log")),
            _moment("market-audio", kind="market_move", outputs=("audio",)),
            _moment("market-lower", kind="market_move", outputs=("lower_third", "recap_log")),
            _moment("rank-lower", kind="rank_change", outputs=("lower_third",)),
        ]
    )

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
    ledger.extend(
        [
            _moment("low", priority=20, outputs=("ticker",)),
            _moment("high", priority=80, kind="rank_change", outputs=("ticker", "recap_log")),
        ]
    )

    recent = ledger.recent_payloads(limit=1)
    assert recent == [
        {
            "id": "high",
            "kind": "rank_change",
            "title": "Moment high",
            "priority": 80,
            "color": "neutral",
            "outputs": ["ticker", "recap_log"],
            "ttl_sec": 8,
            "created_at": recent[0]["created_at"],
            "metadata": {"source": "test"},
        }
    ]
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


# ---------------------------------------------------------------------------
# 0.16.0 — record_to_disk tests (milestone 3 from replay-fixtures.md)
# ---------------------------------------------------------------------------


def test_record_to_disk_writes_one_ndjson_line_per_moment(record_path: Path) -> None:
    """Happy path: 3 moments, 3 lines on disk, each line parses as the
    moment's payload."""
    ledger = BroadcastRecapLedger(record_path=record_path)
    moments = [
        _moment("disk-1", priority=40),
        _moment("disk-2", priority=78, kind="agent_pnl", outputs=("ticker", "recap_log")),
        _moment("disk-3", priority=90, kind="rank_change", outputs=("macro_burst",)),
    ]

    for moment in moments:
        ledger.record(moment)
    ledger.close()

    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    payloads = [json.loads(line) for line in lines]
    assert [payload["id"] for payload in payloads] == ["disk-1", "disk-2", "disk-3"]
    # Each line is the canonical to_payload() output (compact, no spaces).
    assert payloads[1]["kind"] == "agent_pnl"
    assert payloads[1]["priority"] == 78
    assert payloads[2]["outputs"] == ["macro_burst"]


def test_record_to_disk_appends_across_ledger_instances(record_path: Path) -> None:
    """Two ``BroadcastRecapLedger(record_path=tmp)`` instances writing to the
    same file produce a single NDJSON stream in submission order."""
    first = BroadcastRecapLedger(record_path=record_path)
    first.record(_moment("append-1"))
    first.record(_moment("append-2"))
    first.close()

    second = BroadcastRecapLedger(record_path=record_path)
    second.record(_moment("append-3"))
    second.record(_moment("append-4"))
    second.close()

    lines = record_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["id"] for line in lines] == [
        "append-1",
        "append-2",
        "append-3",
        "append-4",
    ]


def test_record_to_disk_swallows_io_errors(record_path: Path, monkeypatch) -> None:
    """A write failure (disk-full, permission denied, etc.) must NEVER
    crash the orchestrator. The in-memory record stands; the disk write
    is dropped with a structured warning.

    We simulate the failure by patching the open file handle's ``write``
    to raise ``OSError``. (Patching ``Path.open`` itself would break
    ``__init__``'s file creation; the handle's ``write`` is the actual
    write path the try/except guards.)
    """
    ledger = BroadcastRecapLedger(record_path=record_path)
    moment = _moment("survives-disk-full", priority=95, kind="rank_change")

    # Sanity: the handle is open and writable before we patch.
    assert ledger._record_handle is not None
    original_write = ledger._record_handle.write
    monkeypatch.setattr(
        ledger._record_handle, "write", lambda *_args, **_kw: (_ for _ in ()).throw(OSError("ENOSPC"))
    )

    # The call must NOT raise, even though write() would.
    returned = ledger.record(moment)

    assert returned is moment
    assert len(ledger) == 1  # in-memory record stands
    assert ledger.recent_moments()[0].id == "survives-disk-full"

    # Restore the real write so close() can flush cleanly.
    monkeypatch.setattr(ledger._record_handle, "write", original_write)
    ledger.close()
