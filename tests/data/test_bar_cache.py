from datetime import date

import pandas as pd
import pytest

from tradefarm.data import bar_cache


@pytest.fixture(autouse=True)
def tmp_cache_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bar_cache, "CACHE_DIR", tmp_path / "bars")
    yield


def _bars(start: date, n: int, close_step: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": [date.fromordinal(start.toordinal() + i) for i in range(n)],
            "open": [100.0 + i * close_step for i in range(n)],
            "high": [101.0 + i * close_step for i in range(n)],
            "low": [99.0 + i * close_step for i in range(n)],
            "close": [100.5 + i * close_step for i in range(n)],
            "adjusted_close": [100.5 + i * close_step for i in range(n)],
            "volume": [1_000_000 for _ in range(n)],
        }
    )


def test_load_returns_none_for_empty_cache() -> None:
    assert bar_cache.load("SPY") is None


def test_covers_returns_false_for_none_or_empty() -> None:
    assert not bar_cache.covers(None, date(2026, 1, 1), date(2026, 1, 31))
    empty = pd.DataFrame({"date": []})
    assert not bar_cache.covers(empty, date(2026, 1, 1), date(2026, 1, 31))


def test_covers_boundary_inclusive() -> None:
    df = _bars(date(2026, 1, 1), 10)  # 2026-01-01 to 2026-01-10
    assert bar_cache.covers(df, date(2026, 1, 2), date(2026, 1, 9))
    assert bar_cache.covers(df, date(2026, 1, 1), date(2026, 1, 10))  # exact match
    assert not bar_cache.covers(df, date(2025, 12, 31), date(2026, 1, 5))  # start before
    assert not bar_cache.covers(df, date(2026, 1, 5), date(2026, 1, 11))  # end after


def test_slice_range_returns_only_matching_rows() -> None:
    df = _bars(date(2026, 1, 1), 10)
    sliced = bar_cache.slice_range(df, date(2026, 1, 3), date(2026, 1, 5))
    assert len(sliced) == 3
    assert sliced["date"].min() == date(2026, 1, 3)
    assert sliced["date"].max() == date(2026, 1, 5)


def test_merge_writes_new_cache_when_empty() -> None:
    df = _bars(date(2026, 1, 1), 5)
    result = bar_cache.merge("SPY", df)
    assert len(result) == 5
    reloaded = bar_cache.load("SPY")
    assert reloaded is not None
    assert len(reloaded) == 5


def test_merge_unions_disjoint_ranges() -> None:
    bar_cache.merge("SPY", _bars(date(2026, 1, 1), 5))
    result = bar_cache.merge("SPY", _bars(date(2026, 1, 10), 3))
    assert len(result) == 8
    assert result["date"].min() == date(2026, 1, 1)
    assert result["date"].max() == date(2026, 1, 12)


def test_merge_dedupes_overlapping_dates() -> None:
    bar_cache.merge("SPY", _bars(date(2026, 1, 1), 5, close_step=1.0))
    overlap = _bars(date(2026, 1, 3), 5, close_step=10.0)
    result = bar_cache.merge("SPY", overlap)
    # 5 + 5 - 3 overlap = 7 unique dates
    assert len(result) == 7
    # The overlap-keep="last" semantics mean the new (close_step=10) bars win
    row_jan_3 = result.loc[result["date"] == date(2026, 1, 3)].iloc[0]
    assert row_jan_3["close"] == 100.5  # new row's first close (0 * 10 + 100.5)


def test_merge_returns_existing_when_new_is_empty() -> None:
    bar_cache.merge("SPY", _bars(date(2026, 1, 1), 5))
    result = bar_cache.merge("SPY", pd.DataFrame({"date": []}))
    assert len(result) == 5
