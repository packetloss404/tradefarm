"""Replay query helpers — pure-function tests.

Same shape as test_beats.py: build a synthetic manifest inline, fold
it, assert the per-agent state and aggregate payloads come out right.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tradefarm.session import replay_query
from tradefarm.session.replay_query import (
    AgentSnapshot,
    account_payload,
    agent_payload,
    agents_payload,
    events_in_window,
    fold_to,
    load_manifest,
    manifest_event_to_ws_envelope,
    parse_iso,
    position_value,
    trades_for_agent,
)


OPEN = datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc)
CLOSE = datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc)


def _fill(
    *,
    agent_id: int,
    name: str | None = None,
    symbol: str = "AAPL",
    side: str = "buy",
    qty: float = 10.0,
    price: float = 100.0,
    t: datetime | None = None,
) -> dict[str, Any]:
    return {
        "t": (t or OPEN).isoformat(),
        "kind": "fill",
        "agent_id": agent_id,
        "agent_name": name or f"agent_{agent_id}",
        "payload": {
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "notional": abs(qty * price),
            "reason": "test",
        },
    }


def _decision(
    *,
    agent_id: int,
    name: str | None = None,
    kind: str = "entry",
    symbol: str = "AAPL",
    content: str = "buy reason",
    t: datetime | None = None,
) -> dict[str, Any]:
    return {
        "t": (t or OPEN).isoformat(),
        "kind": "decision",
        "agent_id": agent_id,
        "agent_name": name or f"agent_{agent_id}",
        "payload": {"kind": kind, "symbol": symbol, "content": content, "metadata": "{}"},
    }


def _manifest(
    events: list[dict[str, Any]], *, started: datetime | None = None, ended: datetime | None = None
) -> dict[str, Any]:
    started = started or OPEN
    ended = ended or CLOSE
    return {
        "session_id": "s_test",
        "date_range": ["2026-05-19", "2026-05-19"],
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "trading_days": ["2026-05-19"],
        "tick_count": 1,
        "fill_count": sum(1 for e in events if e["kind"] == "fill"),
        "agents_active": len({e["agent_id"] for e in events}),
        "events": events,
    }


# ----- fold + position math --------------------------------------------


def test_fold_to_buy_only_holds_position():
    snaps, marks = fold_to(
        _manifest([_fill(agent_id=1, qty=10, price=100, side="buy")]), OPEN + timedelta(minutes=1)
    )
    assert 1 in snaps
    snap = snaps[1]
    assert snap.cash == pytest.approx(0.0)  # 1000 starting - 10*100 spent
    assert "AAPL" in snap.positions
    assert snap.positions["AAPL"].qty == 10
    assert snap.positions["AAPL"].avg_price == pytest.approx(100.0)
    assert marks["AAPL"] == 100


def test_fold_to_realized_pnl_on_round_trip():
    events = [
        _fill(agent_id=1, side="buy", qty=10, price=100, t=OPEN + timedelta(minutes=1)),
        _fill(agent_id=1, side="sell", qty=10, price=110, t=OPEN + timedelta(minutes=2)),
    ]
    snaps, _ = fold_to(_manifest(events), OPEN + timedelta(minutes=3))
    snap = snaps[1]
    assert snap.realized_pnl == pytest.approx(100.0)
    # Closed position should be empty.
    assert "AAPL" not in snap.positions
    # Cash returns to start + profit.
    assert snap.cash == pytest.approx(1100.0)


def test_fold_to_average_cost_on_split_open():
    events = [
        _fill(agent_id=1, side="buy", qty=10, price=100, t=OPEN + timedelta(minutes=1)),
        _fill(agent_id=1, side="buy", qty=10, price=120, t=OPEN + timedelta(minutes=2)),
        _fill(agent_id=1, side="sell", qty=10, price=130, t=OPEN + timedelta(minutes=3)),
    ]
    snaps, _ = fold_to(_manifest(events), OPEN + timedelta(minutes=4))
    snap = snaps[1]
    # avg cost = (100+120)/2 = 110; realized = (130-110)*10 = 200
    assert snap.realized_pnl == pytest.approx(200.0)
    assert snap.positions["AAPL"].qty == 10
    assert snap.positions["AAPL"].avg_price == pytest.approx(110.0)


def test_fold_to_respects_at_cutoff():
    """Events after `at` must be ignored."""
    events = [
        _fill(agent_id=1, side="buy", qty=10, price=100, t=OPEN + timedelta(minutes=1)),
        _fill(agent_id=1, side="sell", qty=10, price=200, t=OPEN + timedelta(minutes=10)),
    ]
    snaps, _ = fold_to(_manifest(events), OPEN + timedelta(minutes=5))
    snap = snaps[1]
    assert snap.realized_pnl == 0  # second event after cutoff
    assert snap.positions["AAPL"].qty == 10


def test_fold_to_captures_last_decision():
    events = [
        _decision(
            agent_id=2,
            kind="entry",
            symbol="MSFT",
            content="early read",
            t=OPEN + timedelta(minutes=1),
        ),
        _decision(
            agent_id=2,
            kind="entry",
            symbol="NVDA",
            content="updated read",
            t=OPEN + timedelta(minutes=5),
        ),
    ]
    snaps, _ = fold_to(_manifest(events), OPEN + timedelta(minutes=10))
    assert snaps[2].last_decision is not None
    assert snaps[2].last_decision["symbol"] == "NVDA"
    assert snaps[2].last_decision["content"] == "updated read"


# ----- payload shapes ---------------------------------------------------


def test_agent_payload_includes_static_meta():
    snap = AgentSnapshot(agent_id=7, name="ian_walmsley", cash=950.0, realized_pnl=-50.0)
    payload = agent_payload(
        snap,
        marks={},
        static_meta={"strategy": "lstm_v1", "rank": "senior", "symbol": "NVDA"},
    )
    assert payload["id"] == 7
    assert payload["strategy"] == "lstm_v1"
    assert payload["rank"] == "senior"
    assert payload["symbol"] == "NVDA"
    assert payload["cash"] == 950.0
    assert payload["realized_pnl"] == -50.0


def test_agents_payload_pads_with_silent_roster():
    """The silent roster ensures the 100-agent diorama renders even
    when only a few agents traded this session."""
    events = [_fill(agent_id=1, qty=10, price=100, t=OPEN + timedelta(minutes=1))]
    snaps, marks = fold_to(_manifest(events), OPEN + timedelta(minutes=10))
    silent = [
        {"id": 1, "name": "trader_001", "strategy": "lstm_v1", "rank": "intern"},
        {"id": 2, "name": "trader_002", "strategy": "momentum_sma20", "rank": "intern"},
        {"id": 3, "name": "trader_003", "strategy": "lstm_llm_v1", "rank": "intern"},
    ]
    payload = agents_payload(snaps, marks, static_meta_by_id={1: silent[0]}, include_silent=silent)
    ids = {a["id"] for a in payload}
    assert ids == {1, 2, 3}
    # The agent that traded should have a position; the silent ones shouldn't.
    by_id = {a["id"]: a for a in payload}
    assert by_id[1]["positions"]
    assert not by_id[2]["positions"]
    # Silent agents pick up their static metadata.
    assert by_id[3]["strategy"] == "lstm_llm_v1"


def test_account_payload_aggregates_correctly():
    events = [
        _fill(agent_id=1, side="buy", qty=10, price=100, t=OPEN + timedelta(minutes=1)),
        _fill(agent_id=1, side="sell", qty=10, price=110, t=OPEN + timedelta(minutes=2)),
        _fill(agent_id=2, side="buy", qty=5, price=200, t=OPEN + timedelta(minutes=1)),
    ]
    snaps, marks = fold_to(_manifest(events), OPEN + timedelta(minutes=10))
    # Agent 2 still holds an open position; agent 1 is flat.
    payload = account_payload(
        snaps, marks, silent_agent_count=98, last_tick_at="2026-05-19T20:00:00Z"
    )
    assert payload["last_tick_at"] == "2026-05-19T20:00:00Z"
    # 98 silent + 1 flat (agent 1, waiting) + 1 holder (agent 2, status depends on unrealized)
    assert payload["waiting_ai"] + payload["profit_ai"] + payload["loss_ai"] == 100
    # Realized: agent 1 booked +$100; agent 2 hasn't closed → 0.
    assert payload["realized_pnl"] == pytest.approx(100.0)
    # Total equity = 98 silent * 1000 + agent 1 (1100 cash) + agent 2 (cash 0 + 5*200 mark)
    assert payload["total_equity"] == pytest.approx(98 * 1000 + 1100 + 1000)


# ----- trades + WS slice ------------------------------------------------


def test_trades_for_agent_filters_and_orders_newest_first():
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=1), qty=1, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=2), qty=1, price=100),
        _fill(agent_id=1, t=OPEN + timedelta(minutes=3), qty=2, price=110),
        _fill(agent_id=1, t=OPEN + timedelta(minutes=20), qty=3, price=120),  # after cutoff
    ]
    rows = trades_for_agent(
        _manifest(events), agent_id=1, at=OPEN + timedelta(minutes=10), limit=10
    )
    assert len(rows) == 2
    # newest first
    assert rows[0]["executed_at"] > rows[1]["executed_at"]


def test_trades_for_agent_handles_agent_id_zero():
    """Regression: agent_id=0 was previously falsy-coerced to -1 and
    every fill for agent 0 dropped silently."""
    events = [
        _fill(agent_id=0, t=OPEN + timedelta(minutes=1), qty=1, price=100),
        _fill(agent_id=0, t=OPEN + timedelta(minutes=2), qty=1, price=105),
    ]
    rows = trades_for_agent(
        _manifest(events), agent_id=0, at=OPEN + timedelta(minutes=10), limit=10
    )
    assert len(rows) == 2


def test_events_in_window_slices_inclusive():
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(seconds=10)),
        _fill(agent_id=1, t=OPEN + timedelta(seconds=30)),
        _fill(agent_id=1, t=OPEN + timedelta(seconds=60)),
        _fill(agent_id=1, t=OPEN + timedelta(seconds=120)),
    ]
    window = events_in_window(
        _manifest(events),
        at=OPEN + timedelta(seconds=25),
        until=OPEN + timedelta(seconds=70),
    )
    offsets = [int((parse_iso(e["t"]) - OPEN).total_seconds()) for e in window]
    assert offsets == [30, 60]


def test_manifest_event_to_ws_envelope_translates_kinds():
    fill_ev = _fill(
        agent_id=5, symbol="MSFT", side="sell", qty=2, price=400, t=OPEN + timedelta(minutes=1)
    )
    envelope = manifest_event_to_ws_envelope(fill_ev)
    assert envelope is not None
    assert envelope["type"] == "fill"
    assert envelope["payload"]["agent_id"] == 5
    assert envelope["payload"]["symbol"] == "MSFT"

    dec_ev = _decision(agent_id=7, kind="exit", symbol="AAPL", content="take profit")
    envelope = manifest_event_to_ws_envelope(dec_ev)
    assert envelope is not None
    assert envelope["type"] == "agent_decisions_batch"
    assert envelope["payload"]["decisions"][0]["agent_id"] == 7

    bad_ev = {"t": OPEN.isoformat(), "kind": "tick_summary", "agent_id": None, "payload": {}}
    assert manifest_event_to_ws_envelope(bad_ev) is None


# ----- IO + edge cases --------------------------------------------------


def test_load_manifest_round_trip(tmp_path: Path):
    session_id = "s_io_test"
    p = tmp_path / session_id / "manifest.json"
    p.parent.mkdir()
    sample = _manifest([_fill(agent_id=1, t=OPEN + timedelta(minutes=1))])
    p.write_text(json.dumps(sample), encoding="utf-8")
    loaded = load_manifest(session_id, sessions_dir=tmp_path)
    # _manifest()'s fixture hardcodes session_id="s_test" inside the
    # JSON; load_manifest reads it verbatim and doesn't override.
    assert loaded["session_id"] == sample["session_id"]
    assert len(loaded["events"]) == 1


def test_load_manifest_missing_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_manifest("never_existed", sessions_dir=tmp_path)


def test_empty_manifest_yields_empty_snapshots():
    """A no-event manifest (weekend / very short replay) must not crash
    fold_to or the payload builders."""
    snaps, marks = fold_to(_manifest([]), OPEN + timedelta(hours=6))
    assert snaps == {}
    assert marks == {}
    payload = agents_payload(snaps, marks, include_silent=[{"id": 1, "name": "a"}])
    assert len(payload) == 1
    assert payload[0]["positions"] == {}
    acct = account_payload(snaps, marks, silent_agent_count=1)
    assert acct["total_equity"] == pytest.approx(1000.0)
    assert acct["waiting_ai"] == 1


def test_position_value_uses_avg_price_when_unmarked():
    positions = {"AAPL": replay_query.Position(qty=10, avg_price=100.0)}
    notional, unrealized = position_value(positions, marks={})
    assert notional == pytest.approx(1000.0)
    assert unrealized == pytest.approx(0.0)
