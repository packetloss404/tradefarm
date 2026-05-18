"""Parquet bar cache for EODHD daily bars.

One parquet per symbol holding the union of every historical range
we've ever fetched. ``EodhdClient.get_eod`` consults it before any
network call; on a cache miss it fetches and unions the new bars in.

Replaces the prior per-range cache layout (one file per distinct
``(symbol, start, end)`` tuple), which fragmented the disk and
re-fetched data on every shifted window — fine for one-off live ticks,
painful for the session runner which will iterate over the same
historical weeks many times.

Old per-range cache files (``data_cache/eod_*.parquet``) coexist
harmlessly with the new layout — they're simply never consulted.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

CACHE_DIR = Path("data_cache")


def _path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}.parquet"


def load(symbol: str) -> pd.DataFrame | None:
    p = _path(symbol)
    if not p.exists():
        return None
    return pd.read_parquet(p)


def covers(df: pd.DataFrame | None, start: date, end: date) -> bool:
    if df is None or df.empty:
        return False
    return df["date"].min() <= start and df["date"].max() >= end


def slice_range(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty:
        return df
    mask = (df["date"] >= start) & (df["date"] <= end)
    return df.loc[mask].reset_index(drop=True)


def merge(symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """Union the new bars into the on-disk cache and return the combined frame.

    On write failure (disk full, perms) the in-memory union is still
    returned — the cache is an optimization, never a correctness layer.
    """
    cached = load(symbol)
    if new_df.empty:
        return cached if cached is not None else new_df
    if cached is None:
        combined = new_df.sort_values("date").reset_index(drop=True)
    else:
        combined = (
            pd.concat([cached, new_df])
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )
    p = _path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        combined.to_parquet(p, index=False)
    except Exception:
        pass
    return combined
