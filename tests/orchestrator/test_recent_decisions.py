"""Unit tests for the 0.19.0 RecentDecisionsLedger.

The ledger is a small bounded-deque store; tests cover the
common-case append, the ring-buffer eviction, the per-tick dedup,
and the query filters (agent_id, only_llm, limit, ordering).
"""

from __future__ import annotations

import pytest

from tradefarm.orchestrator.recent_decisions import RecentDecisionsLedger


def _entry(
    agent_id: int,
    *,
    strategy: str = "lstm_llm_v1",
    verdict: str = "trade",
    llm_bias: str | None = "long",
    llm_stance: str | None = "trade",
    reason: str = "llm says go",
    at: str = "2026-08-05T20:00:00+00:00",
    tick_id: str | None = "t-1",
) -> dict:
    """Build a single ``agent_decisions_batch``-shaped entry."""
    return {
        "agent_id": agent_id,
        "agent_name": f"agent-{agent_id:03d}",
        "strategy": strategy,
        "symbol": "NVDA",
        "verdict": verdict,
        "reason": reason,
        "llm_bias": llm_bias,
        "llm_stance": llm_stance,
        "at": at,
        "tick_id": tick_id,
    }


def _batch(entries: list[dict], *, tick_id: str = "t-1", at: str = "2026-08-05T20:00:00+00:00") -> dict:
    return {"tick_id": tick_id, "at": at, "decisions": entries}


def test_empty_ledger_has_no_entries() -> None:
    led = RecentDecisionsLedger()
    assert len(led) == 0
    assert led.recent() == []


def test_record_batch_appends_each_entry() -> None:
    led = RecentDecisionsLedger()
    n = led.record_batch(_batch([_entry(1), _entry(2), _entry(3)]))
    assert n == 3
    assert len(led) == 3
    # Newest first ordering.
    assert [e["agent_id"] for e in led.recent()] == [3, 2, 1]


def test_max_entries_evicts_oldest() -> None:
    led = RecentDecisionsLedger(max_entries=4)
    led.record_batch(_batch([_entry(1), _entry(2), _entry(3), _entry(4)], tick_id="t-a"))
    led.record_batch(_batch([_entry(5), _entry(6)], tick_id="t-b"))
    assert len(led) == 4
    # agents 1, 2 were evicted; 3, 4, 5, 6 remain (newest first).
    assert [e["agent_id"] for e in led.recent()] == [6, 5, 4, 3]


def test_per_tick_dedup_drops_second_batch() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(_batch([_entry(1), _entry(2)], tick_id="t-1"))
    # Same tick_id replayed (e.g. a WS subscriber re-sending the
    # envelope it just buffered). The second record should be a no-op.
    n = led.record_batch(_batch([_entry(1), _entry(2)], tick_id="t-1"))
    assert n == 0
    assert len(led) == 2


def test_different_tick_ids_are_both_recorded() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(_batch([_entry(1)], tick_id="t-1"))
    led.record_batch(_batch([_entry(2)], tick_id="t-2"))
    led.record_batch(_batch([_entry(3)], tick_id="t-3"))
    assert len(led) == 3
    assert [e["agent_id"] for e in led.recent()] == [3, 2, 1]


def test_recent_respects_limit() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(_batch([_entry(i) for i in range(10)]))
    out = led.recent(limit=3)
    assert len(out) == 3
    # Newest first: 9, 8, 7
    assert [e["agent_id"] for e in out] == [9, 8, 7]


def test_recent_filters_by_agent_id() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(
        _batch([_entry(1), _entry(2), _entry(1), _entry(3), _entry(1)], tick_id="t-mix")
    )
    out = led.recent(agent_id=1)
    assert len(out) == 3
    assert all(e["agent_id"] == 1 for e in out)


def test_recent_only_llm_excludes_rule_based() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(
        _batch(
            [
                # LSTM+LLM agent: has llm_bias/llm_stance
                _entry(1, strategy="lstm_llm_v1", llm_bias="long", llm_stance="trade"),
                # LSTM-only agent: no llm_* keys
                _entry(2, strategy="lstm_v1", llm_bias=None, llm_stance=None),
                # Momentum agent: no llm_* keys
                _entry(
                    3,
                    strategy="momentum_sma20",
                    llm_bias=None,
                    llm_stance=None,
                ),
            ]
        )
    )
    out = led.recent(only_llm=True)
    assert len(out) == 1
    assert out[0]["agent_id"] == 1


def test_record_batch_handles_empty_input() -> None:
    led = RecentDecisionsLedger()
    assert led.record_batch(_batch([])) == 0
    assert led.record_batch({}) == 0
    assert led.record_batch({"decisions": "not a list"}) == 0  # type: ignore[typeddict-item]
    assert len(led) == 0


def test_record_batch_skips_non_dict_entries() -> None:
    led = RecentDecisionsLedger()
    n = led.record_batch(
        {
            "tick_id": "t-x",
            "at": "2026-08-05T20:00:00+00:00",
            "decisions": [_entry(1), "garbage", None, _entry(2)],  # type: ignore[list-item]
        }
    )
    assert n == 2
    assert len(led) == 2


def test_record_batch_stamps_at_and_tick_id_when_missing() -> None:
    """Per-entry rows in the wire payload don't carry ``at`` (it's
    on the batch envelope). The ledger should stamp both onto every
    entry so the API can render a per-row "when did this happen"
    column without re-joining the batch.
    """
    led = RecentDecisionsLedger()
    entries = [
        {"agent_id": 1, "agent_name": "a1", "reason": "go", "verdict": "trade"},
        {"agent_id": 2, "agent_name": "a2", "reason": "wait", "verdict": "wait"},
    ]
    led.record_batch({"tick_id": "t-z", "at": "2026-08-05T20:00:00+00:00", "decisions": entries})
    out = led.recent()
    assert all(e["at"] == "2026-08-05T20:00:00+00:00" for e in out)
    assert all(e["tick_id"] == "t-z" for e in out)


def test_clear_drops_everything() -> None:
    led = RecentDecisionsLedger()
    led.record_batch(_batch([_entry(1), _entry(2)]))
    assert len(led) == 2
    led.clear()
    assert len(led) == 0
    # After clear, a previously-seen tick_id can be recorded again.
    assert led.record_batch(_batch([_entry(1)], tick_id="t-1")) == 1


def test_max_entries_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="max_entries"):
        RecentDecisionsLedger(max_entries=0)


def test_recent_rejects_negative_limit() -> None:
    led = RecentDecisionsLedger()
    with pytest.raises(ValueError, match="limit"):
        led.recent(limit=-1)
