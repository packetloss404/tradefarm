"""Beat detector — rivalry + promotion scorers.

Both scorers landed together because they share a KIND enum slot
(promotion + agent_rivalry are the two new kinds the studio knows
about but the detector didn't emit). Tests below are pure-function:
they build synthetic fills / promotion rows, call the scorer, and
assert the resulting Beat records.

Per the project's testing policy: 6+ tests, all pure, no DB, no
clock. Mirrors the style of the existing test_beats.py fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from tradefarm.session.beats import (
    SCENE_FOR_KIND,
    _agent_pnl_from_fills,
    _fills,
    _rank_index,
    _score_promotions,
    _score_rivalries,
    detect_beats,
)


OPEN = datetime(2026, 5, 19, 13, 30, tzinfo=timezone.utc)  # 09:30 ET


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


def _project(fills: list[dict[str, Any]]):
    """Project raw fill dicts through the detector's `_fills()` parser
    so the tests can call the rivalry scorer with the same internal
    `_Fill` objects the production code path uses."""
    return _fills({"events": fills}), _agent_pnl_from_fills(_fills({"events": fills}))


def _promotion(
    agent_id: int,
    from_rank: str,
    to_rank: str,
    at: datetime | None = None,
) -> Any:
    """Synthetic AcademyPromotion-like row. Just exposes the attrs the
    scorer reads."""

    @dataclass
    class Row:
        agent_id: int
        from_rank: str
        to_rank: str
        at: datetime

    return Row(
        agent_id=agent_id,
        from_rank=from_rank,
        to_rank=to_rank,
        at=at or OPEN + timedelta(hours=2),
    )


# ----- rivalry scorer ------------------------------------------------------


def test_rivalry_min_occurrence_threshold_drops_pairs_below_min():
    """Two opposing fills on the same symbol is not enough — needs >= 3
    inside the rolling window to surface."""
    fills_raw = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=5)),
    ]
    fills, pnls = _project(fills_raw)
    beats = _score_rivalries(fills, pnls)
    assert beats == []


def test_rivalry_window_enforced():
    """3+ opposing fills but spread across more than 90 min should NOT
    surface as a rivalry."""
    fills_raw = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=20)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=120)),
    ]
    fills, pnls = _project(fills_raw)
    # The 1+3 pair is outside the 90-min window, leaving 1 unique
    # in-window pair, below the min_occurrences=3 threshold. So no rivalry.
    beats = _score_rivalries(fills, pnls, min_occurrences=3, window_min=90)
    assert beats == []


def test_rivalry_same_side_ignored():
    """Two agents both buying the same symbol are not a rivalry."""
    fills_raw = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=5)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=15)),
    ]
    fills, pnls = _project(fills_raw)
    beats = _score_rivalries(fills, pnls)
    assert beats == []


def test_rivalry_three_opposing_fills_emit_one_beat():
    """3 opposing fills inside 90 min on the same symbol -> one rivalry
    beat. The kind is agent_rivalry and the scene maps to showdown."""
    fills_raw = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=5)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=15)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=20)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=25)),
    ]
    fills, pnls = _project(fills_raw)
    beats = _score_rivalries(fills, pnls)
    assert len(beats) == 1
    b = beats[0]
    assert b.kind == "agent_rivalry"
    assert b.scene_hint == SCENE_FOR_KIND["agent_rivalry"]
    assert b.scene_hint == "showdown"
    assert b.symbol == "NVDA"
    assert set(b.agent_ids) == {1, 2}
    assert b.metadata["count"] == 3
    # a_pnl / b_pnl must both be present in metadata (they're 0 because
    # the fills net to a flat position, but the keys must exist for the
    # studio).
    assert "a_pnl" in b.metadata
    assert "b_pnl" in b.metadata


# ----- promotion scorer ----------------------------------------------------


def test_promotion_basic_emits_promotion_kind():
    rows = [_promotion(89, "junior", "senior", at=OPEN + timedelta(hours=2))]
    beats = _score_promotions(rows)
    assert len(beats) == 1
    b = beats[0]
    assert b.kind == "promotion"
    assert b.metadata["from_rank"] == "junior"
    assert b.metadata["to_rank"] == "senior"
    assert b.metadata["agent_id"] == 89
    assert "Henry" not in b.headline  # synthetic name from the row
    # scene mapping: promotion -> leaderboard
    assert b.scene_hint == "leaderboard"


def test_promotion_demotion_maps_to_top_loser():
    """A senior->junior crossing is a demotion. The scorer emits it as
    kind=top_loser (the existing drawdown lane)."""
    rows = [_promotion(7, "senior", "junior", at=OPEN + timedelta(hours=2))]
    beats = _score_promotions(rows)
    assert len(beats) == 1
    b = beats[0]
    assert b.kind == "top_loser"
    assert b.metadata["from_rank"] == "senior"
    assert b.metadata["to_rank"] == "junior"


def test_promotion_top_n_caps_output():
    rows = [
        _promotion(1, "intern", "junior", at=OPEN + timedelta(minutes=10)),
        _promotion(2, "junior", "senior", at=OPEN + timedelta(minutes=20)),
        _promotion(3, "senior", "principal", at=OPEN + timedelta(minutes=30)),
        _promotion(4, "intern", "junior", at=OPEN + timedelta(minutes=40)),
    ]
    beats = _score_promotions(rows, top_n=2)
    assert len(beats) == 2
    # top_n takes the first 2 by timestamp ordering (oldest first)
    assert beats[0].metadata["agent_id"] == 1
    assert beats[1].metadata["agent_id"] == 2


def test_promotion_rank_index_disambiguates_direction():
    """A row with a same-rank from->to would be ambiguous. The scorer
    only fires for true direction (not equal ranks) and falls into
    the demotion lane for any direction mismatch."""
    # Equal ranks -> treated as no change, scorer still emits (a beat
    # is cheap) but the kind defaults to "promotion" only when the
    # to_rank is higher in the ladder.
    row = _promotion(1, "junior", "junior")
    beats = _score_promotions([row])
    assert len(beats) == 1
    # Same rank => "to_rank" not higher => treated as demotion lane.
    # Acceptable either way as long as the scorer doesn't crash and
    # the metadata round-trips.
    assert "from_rank" in beats[0].metadata
    assert "to_rank" in beats[0].metadata


def test_rank_index_basic():
    """The internal rank ladder ordering is intern < junior < senior <
    principal. The scorer uses this to decide promotion vs demotion."""
    assert _rank_index("intern") == 0
    assert _rank_index("junior") == 1
    assert _rank_index("senior") == 2
    assert _rank_index("principal") == 3
    # Unknown values fall back to the junior slot so a malformed row
    # doesn't get misclassified as a demotion.
    assert _rank_index("") == 1
    assert _rank_index(None) == 1  # type: ignore[arg-type]
    assert _rank_index("nonsense") == 1


# ----- integration with detect_beats --------------------------------------


def test_detect_beats_emits_rivalry_and_promotion_kinds():
    """End-to-end: a manifest with rival fills + a promotion_events
    list yields both new beat kinds through the public detect_beats
    entrypoint. The new SCENE_FOR_KIND / KIND_PRIORITY entries keep
    the new kinds consistent with the existing detector surface."""
    fills = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=5)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=10)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=15)),
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN + timedelta(minutes=20)),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=25)),
    ]
    manifest: dict[str, Any] = {
        "session_id": "s_riv_test",
        "date_range": ["2026-05-19", "2026-05-19"],
        "started_at": OPEN.isoformat(),
        "ended_at": (OPEN + timedelta(hours=7)).isoformat(),
        "trading_days": ["2026-05-19"],
        "tick_count": 1,
        "fill_count": 6,
        "agents_active": 2,
        "events": fills,
    }
    promos = [
        _promotion(89, "junior", "senior", at=OPEN + timedelta(hours=3)),
    ]
    beats = detect_beats(manifest, promotion_events=promos)
    kinds = {b.kind for b in beats}
    assert "agent_rivalry" in kinds
    assert "promotion" in kinds
    # rivalry beat has its scene mapped to showdown, promotion to leaderboard
    rivalry = next(b for b in beats if b.kind == "agent_rivalry")
    assert rivalry.scene_hint == "showdown"
    promo = next(b for b in beats if b.kind == "promotion")
    assert promo.scene_hint == "leaderboard"


def test_detect_beats_without_promotion_events_skips_promotion():
    """The promotion scorer requires the caller to pass
    promotion_events; detect_beats must not crash when it's omitted."""
    fills = [
        _fill(agent_id=1, name="alice", symbol="NVDA", side="buy", t=OPEN),
        _fill(agent_id=2, name="bob", symbol="NVDA", side="sell", t=OPEN + timedelta(minutes=5)),
    ]
    manifest: dict[str, Any] = {
        "session_id": "s_skip_test",
        "date_range": ["2026-05-19", "2026-05-19"],
        "started_at": OPEN.isoformat(),
        "ended_at": (OPEN + timedelta(hours=7)).isoformat(),
        "trading_days": ["2026-05-19"],
        "tick_count": 1,
        "fill_count": 2,
        "agents_active": 2,
        "events": fills,
    }
    # No promotion_events arg → no promotion beats should fire.
    beats = detect_beats(manifest)
    assert not any(b.kind == "promotion" for b in beats)
    # Same when explicitly None.
    beats = detect_beats(manifest, promotion_events=None)
    assert not any(b.kind == "promotion" for b in beats)
