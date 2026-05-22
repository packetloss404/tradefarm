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

import os
import threading
from datetime import date
from pathlib import Path

import pandas as pd

from tradefarm.runtime.clock import today_utc

CACHE_DIR = Path("data_cache")

# Per-symbol locks so two coroutines / threads fetching the same symbol
# don't trample each other's parquet write. Created on demand.
_SYMBOL_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(symbol: str) -> threading.Lock:
    with _LOCKS_GUARD:
        lock = _SYMBOL_LOCKS.get(symbol)
        if lock is None:
            lock = threading.Lock()
            _SYMBOL_LOCKS[symbol] = lock
        return lock


def _path(symbol: str) -> Path:
    return CACHE_DIR / f"{symbol}.parquet"


def load(symbol: str) -> pd.DataFrame | None:
    p = _path(symbol)
    if not p.exists():
        return None
    return pd.read_parquet(p)


def covers(df: pd.DataFrame | None, start: date, end: date) -> bool:
    """True when the cache already contains every bar from start..end.

    Audit fix (C17): if `end` is today, treat the cache as NOT
    covering — today's bar is provisional until close + EOD settlement,
    and we never want to serve a stale intraday snapshot from cache.
    The forced re-fetch only costs one network call per symbol per day.
    """
    if df is None or df.empty:
        return False
    if end >= today_utc():
        return False
    return df["date"].min() <= start and df["date"].max() >= end


def slice_range(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame(columns=["date"])
    if "date" not in df.columns:
        # Audit fix: an empty frame from EODHD lacks the date column;
        # callers downstream would KeyError on the mask. Return an
        # empty-but-schema'd frame so the rest of the pipeline keeps
        # treating it as "no data" cleanly.
        return pd.DataFrame(columns=df.columns.tolist() + ["date"])
    mask = (df["date"] >= start) & (df["date"] <= end)
    return df.loc[mask].reset_index(drop=True)


def merge(symbol: str, new_df: pd.DataFrame) -> pd.DataFrame:
    """Union the new bars into the on-disk cache and return the combined frame.

    Audit fix (C17): refuse to cache today's row — it can still be
    revised by EODHD until end-of-session, so caching it would freeze
    the morning's provisional close forever. Filter it out of `new_df`
    before unioning.

    Audit fix (parquet concurrency): take a per-symbol lock and use
    write-temp-then-rename so a second writer can't observe a partial
    file. The lock is process-local; for cross-process safety the
    rename gives atomicity at the filesystem level.

    On write failure (disk full, perms) the in-memory union is still
    returned — the cache is an optimization, never a correctness layer.
    """
    cached = load(symbol)

    if new_df is None or new_df.empty:
        return cached if cached is not None else (new_df if new_df is not None else pd.DataFrame())

    # Filter out today's bar from anything written to disk. Callers that
    # need today's value can still see it in the returned frame (we add
    # it back before returning) but it never persists.
    today = today_utc()
    if "date" in new_df.columns:
        persistable = new_df[new_df["date"] < today]
        provisional = new_df[new_df["date"] >= today]
    else:
        persistable = new_df
        provisional = new_df.iloc[0:0]

    if cached is None:
        on_disk = persistable.sort_values("date").reset_index(drop=True)
    else:
        on_disk = (
            pd.concat([cached, persistable])
            .drop_duplicates(subset=["date"], keep="last")
            .sort_values("date")
            .reset_index(drop=True)
        )

    p = _path(symbol)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(symbol):
        tmp = p.with_suffix(".parquet.tmp")
        try:
            on_disk.to_parquet(tmp, index=False)
            os.replace(tmp, p)
        except Exception:
            # Best effort: clean up the temp file if the rename never
            # happened, swallow the error so the cache miss falls back
            # to the in-memory union.
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # Combined return includes today's provisional bar (NOT on disk).
    combined = (
        pd.concat([on_disk, provisional])
        .drop_duplicates(subset=["date"], keep="last")
        .sort_values("date")
        .reset_index(drop=True)
        if not provisional.empty
        else on_disk
    )
    return combined
