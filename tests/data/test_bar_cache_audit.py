"""Audit fixes for bar_cache: today-bar staleness + parquet concurrency."""
from __future__ import annotations

import threading
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from tradefarm.data import bar_cache


def _df(dates: list[date]) -> pd.DataFrame:
    return pd.DataFrame({
        "date": dates,
        "open": [1.0] * len(dates),
        "high": [1.0] * len(dates),
        "low": [1.0] * len(dates),
        "close": [1.0] * len(dates),
        "adjusted_close": [1.0] * len(dates),
        "volume": [100] * len(dates),
    })


def test_covers_returns_false_when_end_is_today(monkeypatch):
    """Refuse to serve today's row from cache — the EOD bar is still
    provisional and can revise until end-of-session."""
    fixed = date(2026, 5, 22)
    monkeypatch.setattr(bar_cache, "today_utc", lambda: fixed)
    df = _df([date(2026, 5, 20), date(2026, 5, 21), fixed])
    assert bar_cache.covers(df, date(2026, 5, 20), fixed) is False
    # End strictly before today is fine.
    assert bar_cache.covers(df, date(2026, 5, 20), date(2026, 5, 21)) is True


def test_merge_does_not_persist_today_bar(tmp_path, monkeypatch):
    """Today's row appears in the returned frame but is not on disk."""
    fixed = date(2026, 5, 22)
    monkeypatch.setattr(bar_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(bar_cache, "today_utc", lambda: fixed)
    df = _df([date(2026, 5, 21), fixed])
    out = bar_cache.merge("AAA", df)
    # Both rows in return.
    assert len(out) == 2
    # Only yesterday's row on disk.
    persisted = pd.read_parquet(tmp_path / "AAA.parquet")
    assert list(persisted["date"]) == [date(2026, 5, 21)]


def test_slice_range_safe_on_empty_frame_without_date_col():
    """Audit fix: empty EODHD response lacks the `date` column. Mask
    used to KeyError; now returns an empty schema-bearing frame."""
    empty = pd.DataFrame()
    out = bar_cache.slice_range(empty, date(2026, 1, 1), date(2026, 1, 31))
    assert out.empty


def test_concurrent_merges_dont_corrupt_parquet(tmp_path, monkeypatch):
    """Two threads merging the same symbol must not lose data or
    leave a partial file. Audit fix: write-temp-then-rename + per-
    symbol lock."""
    fixed = date(2026, 5, 22)
    monkeypatch.setattr(bar_cache, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(bar_cache, "today_utc", lambda: fixed)

    def worker(start_offset: int):
        rows = [date(2026, 5, 1) + timedelta(days=start_offset + i) for i in range(10)]
        bar_cache.merge("XYZ", _df(rows))

    threads = [threading.Thread(target=worker, args=(o,)) for o in (0, 5, 10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    persisted = pd.read_parquet(tmp_path / "XYZ.parquet")
    # No corruption: monotonic increasing dates, no duplicates.
    dates = list(persisted["date"])
    assert dates == sorted(dates)
    assert len(dates) == len(set(dates))
