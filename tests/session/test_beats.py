"""Beat detector — pure-function tests.

The detector is a function of `dict[str, Any]` (the parsed manifest) →
`list[Beat]`. No DB, no async, no clock. Tests build synthetic manifests
inline and assert what fires.

Manifest event shape (matches src/tradefarm/session/run.py):
  {"t": ISO, "kind": "fill"|"decision", "agent_id": int,
   "agent_name": str, "payload": {...}}
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from tradefarm.session.beats import (
    Beat,
    DetectorThresholds,
    SCENE_FOR_KIND,
    _agent_pnl_from_fills,
    _fills,
    detect_beats,
    main,
    write_beats,
)


# ----- fixtures + helpers ---------------------------------------------------

OPEN = datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc)  # 09:30 ET
CLOSE = datetime(2026, 5, 19, 20, 0, tzinfo=timezone.utc)  # 16:00 ET


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


def _manifest(events: list[dict[str, Any]], *, started: datetime | None = None, ended: datetime | None = None) -> dict[str, Any]:
    started = started or OPEN
    ended = ended or CLOSE
    return {
        "session_id": "s_2026-05-19_test",
        "date_range": ["2026-05-19", "2026-05-19"],
        "started_at": started.isoformat(),
        "ended_at": ended.isoformat(),
        "trading_days": ["2026-05-19"],
        "tick_count": 1,
        "fill_count": sum(1 for e in events if e["kind"] == "fill"),
        "agents_active": len({e["agent_id"] for e in events if e.get("agent_id") is not None}),
        "events": events,
    }


# ----- per-scorer tests ----------------------------------------------------


def test_empty_manifest_yields_open_only():
    """The weekend / no-trades case. open beat still fires (it's the
    bookend); nothing else does. No exception."""
    beats = detect_beats(_manifest([]))
    kinds = [b.kind for b in beats]
    assert kinds == ["open"]
    assert beats[0].id == "b_open"
    assert beats[0].score == pytest.approx(0.55)


def test_minimal_manifest_emits_recap_at_close():
    """Even one fill triggers a recap because there's something to
    summarize (and a non-zero ended_at)."""
    f = _fill(agent_id=1, t=OPEN + timedelta(minutes=10), price=100.0, qty=1, side="buy")
    beats = detect_beats(_manifest([f]))
    kinds = [b.kind for b in beats]
    assert "open" in kinds and "recap" in kinds
    # open first, recap last
    assert beats[0].kind == "open"
    assert beats[-1].kind == "recap"


def test_big_fill_above_threshold_fires():
    """A fill above the min-notional threshold becomes a big_fill beat
    with a score that scales linearly toward 1.0 at the full threshold."""
    th = DetectorThresholds(big_fill_notional_min=5_000, big_fill_notional_full=10_000)
    f1 = _fill(agent_id=1, t=OPEN + timedelta(minutes=10), price=100.0, qty=80)   # $8k
    f2 = _fill(agent_id=2, t=OPEN + timedelta(minutes=20), price=100.0, qty=10)   # $1k (skipped)
    beats = detect_beats(_manifest([f1, f2]), thresholds=th)
    bigs = [b for b in beats if b.kind == "big_fill"]
    assert len(bigs) == 1
    assert bigs[0].agent_ids == [1]
    # 8k between 5k and 10k → score 0.6
    assert bigs[0].score == pytest.approx(0.6, abs=0.01)


def test_top_winner_is_top_by_realized_pnl_from_paired_fills():
    """top_winner picks the agent with the highest realized PnL from
    entry-exit pairs in the manifest. agent 1 buys low + sells high,
    agent 2 buys high + sells low → 1 wins, 2 loses."""
    events = [
        _fill(agent_id=1, name="winner", t=OPEN + timedelta(minutes=5), side="buy", qty=10, price=100),
        _fill(agent_id=1, name="winner", t=OPEN + timedelta(minutes=30), side="sell", qty=10, price=110),
        _fill(agent_id=2, name="loser", t=OPEN + timedelta(minutes=5), side="buy", qty=10, price=100),
        _fill(agent_id=2, name="loser", t=OPEN + timedelta(minutes=30), side="sell", qty=10, price=90),
    ]
    beats = detect_beats(_manifest(events))
    winners = [b for b in beats if b.kind == "top_winner"]
    losers = [b for b in beats if b.kind == "top_loser"]
    assert len(winners) == 1 and winners[0].agent_ids == [1]
    assert len(losers) == 1 and losers[0].agent_ids == [2]
    # Realized PnL = +$100 for winner, -$100 for loser
    assert winners[0].metadata["realized_pnl"] == pytest.approx(100.0)
    assert losers[0].metadata["realized_pnl"] == pytest.approx(-100.0)


def test_divergence_pairs_opposite_sides_inside_window():
    """Two agents take opposite sides on AAPL inside the divergence
    window → one divergence beat. Two agents same side → none."""
    events = [
        _fill(agent_id=1, symbol="AAPL", side="buy", qty=20, price=100, t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=2, symbol="AAPL", side="sell", qty=20, price=100, t=OPEN + timedelta(minutes=10, seconds=15)),
        # Same side — should NOT produce a divergence.
        _fill(agent_id=3, symbol="MSFT", side="buy", qty=10, price=200, t=OPEN + timedelta(minutes=11)),
        _fill(agent_id=4, symbol="MSFT", side="buy", qty=10, price=200, t=OPEN + timedelta(minutes=11, seconds=10)),
    ]
    beats = detect_beats(_manifest(events))
    divs = [b for b in beats if b.kind == "divergence"]
    assert len(divs) == 1
    assert divs[0].symbol == "AAPL"
    assert set(divs[0].agent_ids) == {1, 2}


def test_divergence_window_respected():
    """Opposite sides far apart in time do NOT form a divergence."""
    th = DetectorThresholds(divergence_window_sec=30.0)
    events = [
        _fill(agent_id=1, symbol="AAPL", side="buy", qty=20, price=100, t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=2, symbol="AAPL", side="sell", qty=20, price=100, t=OPEN + timedelta(minutes=20)),
    ]
    beats = detect_beats(_manifest(events), thresholds=th)
    assert not [b for b in beats if b.kind == "divergence"]


def test_streak_fires_at_or_above_min_length():
    """Five consecutive winning round-trips for agent 1 → one streak
    beat. Below the min_length, none."""
    events: list[dict[str, Any]] = []
    base = OPEN + timedelta(minutes=5)
    for i in range(5):
        # Buy 10 @ 100, sell 10 @ 105 → +$50 realized each round.
        events.append(_fill(agent_id=1, side="buy", qty=10, price=100, t=base + timedelta(minutes=i * 10)))
        events.append(_fill(agent_id=1, side="sell", qty=10, price=105, t=base + timedelta(minutes=i * 10 + 1)))
    beats = detect_beats(_manifest(events))
    streaks = [b for b in beats if b.kind == "streak"]
    assert len(streaks) == 1
    assert streaks[0].metadata["streak_length"] == 5
    assert streaks[0].metadata["winning_trades"] == 5


def test_streak_resets_on_loss():
    """One loss in the middle breaks the streak — longest_win_streak
    counts only the longer of the two surviving runs (4 wins here)."""
    events: list[dict[str, Any]] = []
    base = OPEN + timedelta(minutes=5)
    # 2 winners, 1 loser, 4 winners → longest run = 4.
    pattern = [(105, "win"), (105, "win"), (95, "loss"), (105, "win"), (105, "win"), (105, "win"), (105, "win")]
    for i, (sell_price, _) in enumerate(pattern):
        events.append(_fill(agent_id=1, side="buy", qty=10, price=100, t=base + timedelta(minutes=i * 10)))
        events.append(_fill(agent_id=1, side="sell", qty=10, price=sell_price, t=base + timedelta(minutes=i * 10 + 1)))
    beats = detect_beats(_manifest(events))
    streaks = [b for b in beats if b.kind == "streak"]
    assert len(streaks) == 1
    assert streaks[0].metadata["streak_length"] == 4


def test_closing_burst_fires_when_density_spikes():
    """Most of the day's fills land in the last 10 minutes → closing
    burst beat. Uniform fills don't trigger it."""
    events: list[dict[str, Any]] = []
    # 5 fills spread across the day
    for i in range(5):
        events.append(_fill(agent_id=10 + i, t=OPEN + timedelta(hours=i + 0.5), qty=1, price=100))
    # 12 fills in the last 9 minutes
    burst_start = CLOSE - timedelta(minutes=9)
    for i in range(12):
        events.append(_fill(agent_id=20 + i, t=burst_start + timedelta(minutes=i * 0.7), qty=1, price=100))
    beats = detect_beats(_manifest(events))
    bursts = [b for b in beats if b.kind == "closing_burst"]
    assert len(bursts) == 1
    assert bursts[0].metadata["burst_ratio"] >= 2.0


def test_uniform_fills_dont_trigger_closing_burst():
    """Fill rate flat across the session → no burst beat."""
    events = [
        _fill(agent_id=i, t=OPEN + timedelta(minutes=i * 30), qty=1, price=100)
        for i in range(12)
    ]
    beats = detect_beats(_manifest(events))
    assert not [b for b in beats if b.kind == "closing_burst"]


# ----- dedup + selection ---------------------------------------------------


def test_dedup_collapses_same_agent_symbol_close_in_time():
    """Two big_fills by the same agent on the same symbol seconds apart
    should not both survive — the higher-scoring wins."""
    th = DetectorThresholds(big_fill_notional_min=1_000, big_fill_notional_full=2_000)
    events = [
        _fill(agent_id=1, symbol="AAPL", side="buy", qty=15, price=100, t=OPEN + timedelta(minutes=10)),  # $1500
        _fill(agent_id=1, symbol="AAPL", side="sell", qty=20, price=100, t=OPEN + timedelta(minutes=10, seconds=30)),  # $2000
    ]
    beats = detect_beats(_manifest(events), thresholds=th)
    bigs = [b for b in beats if b.kind == "big_fill"]
    # Only the higher-scoring (larger notional) survives.
    assert len(bigs) == 1
    assert bigs[0].score == pytest.approx(1.0)


def test_selection_caps_at_target_max():
    """30 big fills should be capped to target_max_beats (default 15),
    minus the anchors. Open + recap are always pinned, so the body
    headroom is target_max - 2."""
    th = DetectorThresholds(big_fill_notional_min=5_000, big_fill_notional_full=6_000)
    events = []
    for i in range(30):
        events.append(
            _fill(
                agent_id=i,
                symbol=f"SYM{i}",
                side="buy",
                qty=100,
                price=60,  # $6000 each → all max-score big_fills
                t=OPEN + timedelta(minutes=10 + i),
            )
        )
    beats = detect_beats(_manifest(events), thresholds=th)
    assert len(beats) <= th.target_max_beats
    assert beats[0].kind == "open"
    assert beats[-1].kind == "recap"


def test_beats_are_chronological_in_the_middle():
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=10), qty=80, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=200), qty=80, price=100),
        _fill(agent_id=3, t=OPEN + timedelta(minutes=100), qty=80, price=100),
    ]
    beats = detect_beats(_manifest(events))
    middle = [b for b in beats if b.kind not in ("open", "recap")]
    times = [b.t for b in middle]
    assert times == sorted(times)


# ----- shape / contract ----------------------------------------------------


def test_every_beat_has_a_known_scene_hint():
    """Every emitted beat's scene_hint must be in SCENE_FOR_KIND so the
    Beat Picker preview pane knows what vignette to draw."""
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=10), qty=80, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=10, seconds=15), side="sell", qty=80, price=100),
    ]
    beats = detect_beats(_manifest(events))
    for b in beats:
        assert b.scene_hint == SCENE_FOR_KIND[b.kind], b


def test_event_refs_index_into_manifest():
    """Each event_refs entry must be a valid index into the manifest's
    events list — the headless renderer dereferences these."""
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=10), qty=80, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=10, seconds=15), side="sell", qty=80, price=100),
    ]
    manifest = _manifest(events)
    beats = detect_beats(manifest)
    n = len(manifest["events"])
    for b in beats:
        for ref in b.event_refs:
            assert 0 <= ref < n


# ----- helpers / I/O ------------------------------------------------------


def test_pnl_pairs_average_cost_on_partial_close():
    """Two opens at different prices, one partial close should realize
    against the average cost — not LIFO / FIFO."""
    fills = _fills(
        _manifest(
            [
                _fill(agent_id=1, side="buy", qty=10, price=100, t=OPEN),
                _fill(agent_id=1, side="buy", qty=10, price=120, t=OPEN + timedelta(minutes=1)),
                _fill(agent_id=1, side="sell", qty=10, price=130, t=OPEN + timedelta(minutes=2)),
            ]
        )
    )
    pnls = _agent_pnl_from_fills(fills)
    # avg cost = 110, sold 10 @ 130 → realized = (130 - 110) * 10 = 200
    assert pnls[1].realized == pytest.approx(200.0)


def test_write_beats_round_trip(tmp_path: Path):
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=10), qty=80, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=20), qty=80, price=100),
    ]
    beats = detect_beats(_manifest(events))
    out = tmp_path / "beats.json"
    write_beats(beats, out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data) == len(beats)
    assert data[0]["id"] == beats[0].id


def test_cli_writes_beats_next_to_manifest(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    sessions_dir = tmp_path / "sessions"
    session_id = "s_test"
    manifest_dir = sessions_dir / session_id
    manifest_dir.mkdir(parents=True)
    events = [
        _fill(agent_id=1, t=OPEN + timedelta(minutes=10), qty=80, price=100),
        _fill(agent_id=2, t=OPEN + timedelta(minutes=10, seconds=15), side="sell", qty=80, price=100),
    ]
    (manifest_dir / "manifest.json").write_text(
        json.dumps(_manifest(events)), encoding="utf-8"
    )
    main([session_id, "--out", str(sessions_dir)])
    beats_path = manifest_dir / "beats.json"
    assert beats_path.is_file()
    payload = json.loads(beats_path.read_text(encoding="utf-8"))
    assert payload and payload[0]["kind"] == "open"
    captured = capsys.readouterr()
    assert "beats=" in captured.out


def test_cli_errors_when_manifest_missing(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        main(["nonexistent", "--out", str(tmp_path)])
    assert "manifest not found" in str(exc.value)
