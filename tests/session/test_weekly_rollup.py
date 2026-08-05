"""Weekly rollup + Strategy Wars detector tests.

The weekly_rollup module walks every session manifest in a given
ISO trading week and sums the per-day strategy_rollup into a
weekly shape. The Strategy Wars detector reads the previous week's
rollup (when present) to emit "vs last week" deltas in the beat's
headline + metadata.

Tests here exercise the pure functions in weekly_rollup.py and the
detector's interaction with the rollup shape.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradefarm.session.beats import detect_beats
from tradefarm.session.weekly_rollup import (
    compute_weekly_rollup,
    previous_week_id,
    read_weekly_rollup,
    week_id_for,
    write_weekly_rollup,
)


# ----- week_id_for -----------------------------------------------------------


def test_week_id_for_sunday_lands_in_previous_week_than_monday():
    """The natural ISO week is Mon-Sun. Sun 2026-08-02 is in W31
    (the last day of W31); Mon 2026-08-03 is in W32 (the first day
    of W32). They land in different buckets — the test pins that
    the no-shift mapping is in effect."""
    sunday = date(2026, 8, 2)
    monday = date(2026, 8, 3)
    assert week_id_for(sunday) == "2026-W31"
    assert week_id_for(monday) == "2026-W32"
    assert week_id_for(sunday) != week_id_for(monday)


def test_week_id_for_saturday_and_sunday_different_weeks():
    """Saturday 2026-08-08 is in W32 (the next trading week's
    Sunday-evening session lives here, since its Monday trading
    day is 2026-08-10)."""
    assert week_id_for(date(2026, 8, 8)) == "2026-W32"
    assert week_id_for(date(2026, 8, 2)) == "2026-W31"


def test_week_id_for_crossing_dates():
    assert week_id_for(date(2026, 8, 2)) == "2026-W31"
    assert week_id_for(date(2026, 8, 9)) == "2026-W32"


def test_week_id_for_aware_datetime_uses_utc():
    dt = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)
    assert week_id_for(dt).startswith("2026-W")


# ----- previous_week_id ------------------------------------------------------


def test_previous_week_id_one_week_back():
    assert previous_week_id("2026-W31") == "2026-W30"


def test_previous_week_id_crosses_year_boundary():
    assert previous_week_id("2026-W01") == "2025-W52"
    # 2025 has 52 ISO weeks (not 53).
    assert previous_week_id("2026-W01", weeks_back=2) == "2025-W51"


# ----- compute_weekly_rollup -------------------------------------------------


def _write_manifest(
    tmp_path: Path,
    session_id: str,
    started_at: datetime,
    strategy_rollup: dict[str, dict],
    rivalries: list[dict] | None = None,
) -> Path:
    sdir = tmp_path / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    ended = started_at + timedelta(hours=6, minutes=30)
    manifest = {
        "session_id": session_id,
        "date_range": [started_at.date().isoformat(), ended.date().isoformat()],
        "started_at": started_at.isoformat(),
        "ended_at": ended.isoformat(),
        "trading_days": [started_at.date().isoformat()],
        "tick_count": 1,
        "fill_count": 0,
        "agents_active": 0,
        "events": [],
        "strategy_rollup": strategy_rollup,
        "rivalries": rivalries or [],
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return sdir / "manifest.json"


def test_compute_weekly_rollup_sums_strategy_pnl_across_days(tmp_path: Path):
    """Two manifests in the same week, different per-strategy PnL —
    the rollup should sum the pnl per strategy and report a pool
    total."""
    base = tmp_path
    # 2026-08-03 (Mon) is in ISO W32. Use two days in the same week.
    monday = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    tuesday = monday + timedelta(days=1)
    _write_manifest(
        base, "s_mon", monday,
        strategy_rollup={
            "momentum": {"agents": 10, "equity": 10_200, "pnl": 200, "fills": 5},
            "pairs": {"agents": 8, "equity": 8_100, "pnl": 100, "fills": 3},
        },
    )
    _write_manifest(
        base, "s_tue", tuesday,
        strategy_rollup={
            "momentum": {"agents": 10, "equity": 10_300, "pnl": 300, "fills": 7},
            "pairs": {"agents": 8, "equity": 8_000, "pnl": 0, "fills": 2},
        },
    )

    week = week_id_for(monday)
    rollup = compute_weekly_rollup(week, sessions_dir=base)
    assert rollup["week_id"] == week
    # Pnl summed across the two days.
    assert rollup["strategy_rollup"]["momentum"]["pnl"] == pytest.approx(500.0)
    assert rollup["strategy_rollup"]["momentum"]["fills"] == 12
    assert rollup["strategy_rollup"]["pairs"]["pnl"] == pytest.approx(100.0)
    # Sessions are listed in the rollup.
    assert len(rollup["sessions"]) == 2
    # Pool totals.
    assert rollup["pool_pnl"] == pytest.approx(600.0)
    # pnlPct is derived (not stored) — sum per strategy, divide by
    # sum of starting capital.
    assert rollup["pool_pnl_pct"] != 0


def test_compute_weekly_rollup_ignores_out_of_window_sessions(tmp_path: Path):
    """A session in last week + this week: only this week counts."""
    base = tmp_path
    last_week = datetime(2026, 7, 27, 14, 0, tzinfo=timezone.utc)  # Mon (W31)
    this_week = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)   # Mon (W32)
    _write_manifest(
        base, "s_last", last_week,
        strategy_rollup={"momentum": {"agents": 1, "equity": 1000, "pnl": 999, "fills": 1}},
    )
    _write_manifest(
        base, "s_this", this_week,
        strategy_rollup={"momentum": {"agents": 1, "equity": 1000, "pnl": 50, "fills": 1}},
    )
    rollup = compute_weekly_rollup(week_id_for(this_week), sessions_dir=base)
    # Only the this-week session counts.
    assert rollup["strategy_rollup"]["momentum"]["pnl"] == pytest.approx(50.0)
    assert len(rollup["sessions"]) == 1


def test_compute_weekly_rollup_dedupes_rivalries(tmp_path: Path):
    """A rivalry present in two days of the week — keep the
    higher-count occurrence."""
    base = tmp_path
    monday = datetime(2026, 8, 3, 14, 0, tzinfo=timezone.utc)
    tuesday = monday + timedelta(days=1)
    rivalry_mon = {
        "a": 5, "b": 12, "symbol": "NVDA",
        "count": 2, "a_pnl": 30.0, "b_pnl": -20.0,
    }
    rivalry_tue = {
        "a": 5, "b": 12, "symbol": "NVDA",
        "count": 4, "a_pnl": 80.0, "b_pnl": -60.0,
    }
    _write_manifest(base, "s_mon", monday, {}, rivalries=[rivalry_mon])
    _write_manifest(base, "s_tue", tuesday, {}, rivalries=[rivalry_tue])
    week = week_id_for(monday)
    rollup = compute_weekly_rollup(week, sessions_dir=base)
    assert len(rollup["rivalries"]) == 1
    # The higher-count occurrence wins.
    assert rollup["rivalries"][0]["count"] == 4
    # The (a, b) is canonical — a < b.
    assert rollup["rivalries"][0]["a"] == 5
    assert rollup["rivalries"][0]["b"] == 12


def test_compute_weekly_rollup_handles_empty_sessions_dir(tmp_path: Path):
    """No sessions dir at all (fresh dev box) — return a valid
    empty-shape rollup so the caller can still write something."""
    nonexistent = tmp_path / "no_such_dir"
    rollup = compute_weekly_rollup("2026-W31", sessions_dir=nonexistent)
    assert rollup["week_id"] == "2026-W31"
    assert rollup["strategy_rollup"] == {}
    assert rollup["rivalries"] == []
    assert rollup["sessions"] == []


# ----- write / read round-trip ---------------------------------------------


def test_write_weekly_rollup_creates_parent_dirs(tmp_path: Path):
    rollup = compute_weekly_rollup("2026-W31", sessions_dir=tmp_path)
    path = write_weekly_rollup(rollup, sessions_dir=tmp_path)
    assert path.is_file()
    assert path.name == "rollup.json"
    assert path.parent.name == "2026-W31"


def test_read_weekly_rollup_round_trip(tmp_path: Path):
    rollup = compute_weekly_rollup("2026-W31", sessions_dir=tmp_path)
    write_weekly_rollup(rollup, sessions_dir=tmp_path)
    loaded = read_weekly_rollup("2026-W31", sessions_dir=tmp_path)
    assert loaded == rollup


def test_read_weekly_rollup_missing_returns_none(tmp_path: Path):
    out = read_weekly_rollup("2099-W01", sessions_dir=tmp_path)
    assert out is None


# ----- Strategy Wars detector -----------------------------------------------


def _manifest_for_strategy_war(
    *,
    strategy_rollup: dict[str, dict],
    ended_at: datetime,
    last_week_rollup: dict | None = None,
) -> dict:
    return {
        "session_id": "s_test",
        "date_range": ["2026-08-04", "2026-08-04"],
        "started_at": (ended_at - timedelta(hours=6, minutes=30)).isoformat(),
        "ended_at": ended_at.isoformat(),
        "trading_days": ["2026-08-04"],
        "tick_count": 1,
        "fill_count": 10,
        "agents_active": 30,
        "events": [],
        "strategy_rollup": strategy_rollup,
        "rivalries": [],
    }


def test_strategy_war_emits_beat_with_per_strategy_pnl():
    ended = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    manifest = _manifest_for_strategy_war(
        strategy_rollup={
            "momentum": {"agents": 14, "equity": 14_200, "pnl": 200, "pnlPct": 1.4, "fills": 12},
            "pairs": {"agents": 8, "equity": 8_100, "pnl": 100, "pnlPct": 1.25, "fills": 5},
            "bb": {"agents": 10, "equity": 9_900, "pnl": -100, "pnlPct": -1.0, "fills": 3},
        },
        ended_at=ended,
    )
    beats = detect_beats(manifest)
    wars = [b for b in beats if b.kind == "strategy_war"]
    assert len(wars) == 1
    war = wars[0]
    assert war.scene_hint == "strategy"
    assert "winner momentum" in war.headline
    assert war.metadata["winner"] == "momentum"
    assert war.metadata["loser"] == "bb"
    assert war.metadata["per_strategy"]["momentum"]["pnl"] == 200


def test_strategy_war_includes_vs_last_week_when_rollup_provided():
    ended = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    manifest = _manifest_for_strategy_war(
        strategy_rollup={
            "momentum": {"agents": 14, "equity": 14_200, "pnl": 200, "pnlPct": 1.4, "fills": 12},
            "bb": {"agents": 10, "equity": 9_900, "pnl": -100, "pnlPct": -1.0, "fills": 3},
        },
        ended_at=ended,
        last_week_rollup={
            "week_id": "2026-W30",
            "strategy_rollup": {
                "momentum": {"pnlPct": 0.5},  # was +0.5% last week
                "bb": {"pnlPct": 0.2},  # was +0.2% last week
            },
        },
    )
    beats = detect_beats(manifest, weekly_rollup=manifest["strategy_rollup"]
                        if False else None)  # placeholder
    # The function reads weekly_rollup as a separate parameter
    # carrying the *previous* week's shape (NOT the current
    # manifest's). Re-call with the right arg.
    beats = detect_beats(manifest, weekly_rollup=manifest.pop("last_week_rollup", None))
    # ^ last_week_rollup was a local kwarg above; the actual test
    # needs to re-construct. Skip and assert via a fresh call:
    last_week = {
        "week_id": "2026-W30",
        "strategy_rollup": {
            "momentum": {"pnlPct": 0.5},
            "bb": {"pnlPct": 0.2},
        },
    }
    beats = detect_beats(manifest, weekly_rollup=last_week)
    wars = [b for b in beats if b.kind == "strategy_war"]
    assert len(wars) == 1
    war = wars[0]
    # vs_last_week metadata carries the deltas.
    assert "momentum" in war.metadata["vs_last_week"]
    # 1.4% (this week) - 0.5% (last week) = 0.9%
    assert war.metadata["vs_last_week"]["momentum"] == pytest.approx(0.9, abs=0.01)
    # Headline includes the winner's delta.
    assert "+0.9" in war.headline


def test_strategy_war_skips_when_no_strategy_rollup():
    ended = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    manifest = _manifest_for_strategy_war(
        strategy_rollup={},  # empty
        ended_at=ended,
    )
    beats = detect_beats(manifest)
    wars = [b for b in beats if b.kind == "strategy_war"]
    assert wars == []


def test_strategy_war_skips_with_only_one_strategy():
    """A single strategy isn't a 'war'."""
    ended = datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc)
    manifest = _manifest_for_strategy_war(
        strategy_rollup={
            "momentum": {"agents": 50, "equity": 50_000, "pnl": 100, "pnlPct": 0.2, "fills": 10},
        },
        ended_at=ended,
    )
    beats = detect_beats(manifest)
    wars = [b for b in beats if b.kind == "strategy_war"]
    assert wars == []
