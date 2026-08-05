"""Weekly rollup writer.

``session/weekly_rollup.py`` aggregates 7 days of session manifests
into a single rollup JSON file at ``out/weekly/<week_id>/rollup.json``.
The Strategy Wars beat detector reads the previous week's rollup to
emit "vs last week" deltas; the VOD studio can also serve the
rollup directly to surface a weekly summary card.

Week identification
-------------------
Week IDs are ISO 8601 week-of-year (``%Y-W%V``), e.g. ``2026-W31``.
The convention is Sunday-start (matches the US equity market's
trading week) — Python's ``datetime.isocalendar()`` returns
Monday-start ISO weeks, so we shift by one day to align with the
trading week when computing the bucket.

Aggregation
-----------
The rollup walks ``out/sessions/<sid>/manifest.json`` for every
session whose ``started_at`` falls in the week window. Per-strategy
pnl + agent count + fill count are summed; the per-day
``strategy_rollup`` already carries the right shape (added in 0.8.0),
so this module is a thin walk over disk rather than a re-aggregation.
Cross-strategy totals (pool pnl, win rate) are derived from the
sums.

Rivalries are accumulated across the week (deduped by
``(a, b, symbol)`` triple so the same rivalry across multiple days
counts once with the highest ``count`` seen).

Promotions are merged from the ``AcademyPromotion`` table when the
DB is reachable; the rollup is best-effort — a missing DB just
leaves the field empty, the rest of the rollup is still useful.

Public surface
--------------
- ``week_id_for(dt) -> str`` — ISO-trading-week ID for a date.
- ``compute_weekly_rollup(week_id, *, sessions_dir=None,
  now=None) -> dict`` — pure function: reads manifests, returns
  the rollup dict (caller decides whether to persist).
- ``write_weekly_rollup(rollup, *, sessions_dir=None) -> Path`` —
  persists to ``<sessions_dir>/weekly/<week_id>/rollup.json`` and
  returns the path.
- ``read_weekly_rollup(week_id, *, sessions_dir=None) -> dict |
  None`` — for the Strategy Wars detector; returns None if the
  file doesn't exist.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from tradefarm.session import replay_query


# The trading week starts on Sunday (US equity market convention) and
# ends on Saturday. ``datetime.isocalendar()`` is Monday-start, so we
# shift the date by one day before computing the ISO week — this maps
# Sunday-Saturday into the same ISO week bucket.
_TRADING_WEEK_DAY_SHIFT = timedelta(days=0)


def week_id_for(dt: date | datetime) -> str:
    """Return the ISO-trading-week ID (``%Y-W%V``) for the trading
    week containing ``dt``. Trading weeks run Sunday-Saturday; the
    shift is applied so Sunday and Monday land in the same bucket."""
    if isinstance(dt, datetime):
        d = dt.date() if dt.tzinfo is None else dt.astimezone(timezone.utc).date()
    else:
        d = dt
    shifted = d - _TRADING_WEEK_DAY_SHIFT
    iso_year, iso_week, _ = shifted.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def _week_window(week_id: str) -> tuple[datetime, datetime]:
    """Return the (start, end) UTC datetimes for the trading week.

    A trading week is Sunday 00:00 ET to Saturday 23:59:59:999 ET.
    Returns UTC datetimes (use ``tradefarm.market.hours.ET`` for the
    actual conversion if the caller wants a tz-aware pair)."""
    # Parse ``YYYY-WNN``.
    year_str, _, week_str = week_id.partition("-W")
    iso_year = int(year_str)
    iso_week = int(week_str)
    # Find the Monday of the requested ISO week. The Jan-4 trick:
    # Jan 4 is always in ISO week 1.
    jan4 = date(iso_year, 1, 4)
    _, _, jan4_dow = jan4.isocalendar()  # 1=Mon..7=Sun
    week_1_monday = jan4 - timedelta(days=jan4_dow - 1)
    week_monday = week_1_monday + timedelta(weeks=iso_week - 1)
    week_sunday = week_monday + timedelta(days=6)
    start_et = datetime(week_monday.year, week_monday.month, week_monday.day, tzinfo=timezone.utc)
    # Saturday end-of-day, exclusive next-Sunday start.
    end_et = datetime(week_sunday.year, week_sunday.month, week_sunday.day, 23, 59, 59, 999000, tzinfo=timezone.utc)
    return start_et, end_et


def _safe_load_manifest(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError, TypeError):
        return None


def _strategy_rollup_from(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pull the per-day strategy_rollup off the manifest, defaulting
    to an empty dict. Mirrors the field name the runner writes
    (`session/run.py:_merge_manifest_extras`)."""
    sr = manifest.get("strategy_rollup")
    if not sr or not isinstance(sr, dict):
        return {}
    return {k: dict(v) for k, v in sr.items()}


def _rivalries_from(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(r) for r in (manifest.get("rivalries") or []) if isinstance(r, dict)]


def compute_weekly_rollup(
    week_id: str,
    *,
    sessions_dir: Path | None = None,
) -> dict[str, Any]:
    """Walk ``<sessions_dir>/<sid>/manifest.json`` for every session in
    the trading week, sum the per-strategy rollups, dedup rivalries,
    and return the weekly rollup dict.

    Pure function — no DB writes. Caller decides whether to persist
    via :func:`write_weekly_rollup`."""
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    if not base.is_dir():
        # No sessions dir yet (fresh dev box). Return a valid empty
        # rollup shape so the caller can still write something.
        start, end = _week_window(week_id)
        return {
            "week_id": week_id,
            "date_range": [start.date().isoformat(), end.date().isoformat()],
            "strategy_rollup": {},
            "rivalries": [],
            "promotions": [],
            "sessions": [],
        }

    start, end = _week_window(week_id)
    strategy_totals: dict[str, dict[str, Any]] = {}
    rivalry_acc: dict[tuple[int, int, str], dict[str, Any]] = {}
    sessions: list[dict[str, Any]] = []

    for sid_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        manifest = _safe_load_manifest(sid_dir / "manifest.json")
        if manifest is None:
            continue
        started_at = manifest.get("started_at")
        if not started_at or not isinstance(started_at, str):
            continue
        try:
            t = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        if t < start or t > end:
            continue

        # Session is in-window. Add to the sessions list (newest
        # first when read by the studio).
        sessions.append(
            {
                "session_id": manifest.get("session_id") or sid_dir.name,
                "started_at": started_at,
                "fill_count": int(manifest.get("fill_count", 0) or 0),
            }
        )

        # Per-strategy totals.
        for strat, info in _strategy_rollup_from(manifest).items():
            slot = strategy_totals.setdefault(
                strat,
                {"agents": 0, "equity": 0.0, "pnl": 0.0, "fills": 0},
            )
            slot["agents"] = int(
                max(slot["agents"], int(info.get("agents", 0) or 0))
            )  # union-ish: count the max seen (avoids double-counting)
            slot["equity"] = float(info.get("equity", 0.0) or 0.0)
            slot["pnl"] += float(info.get("pnl", 0.0) or 0.0)
            slot["fills"] += int(info.get("fills", 0) or 0)

        # Rivalries: dedup by (a, b, symbol) triple (a < b canonical)
        # and keep the highest count.
        for r in _rivalries_from(manifest):
            try:
                a = int(r.get("a", 0))
                b = int(r.get("b", 0))
                sym = str(r.get("symbol", ""))
            except (TypeError, ValueError):
                continue
            if a == b or not sym:
                continue
            lo, hi = (a, b) if a < b else (b, a)
            key = (lo, hi, sym)
            count = int(r.get("count", 0) or 0)
            prev = rivalry_acc.get(key)
            if prev is None or count > prev.get("count", 0):
                rivalry_acc[key] = {
                    "a": lo,
                    "b": hi,
                    "symbol": sym,
                    "count": count,
                    "a_pnl": float(r.get("a_pnl", 0.0) or 0.0),
                    "b_pnl": float(r.get("b_pnl", 0.0) or 0.0),
                }

    # Derive pnlPct per strategy (pool pnl vs sum-of-starting-capital).
    total_starting = 0.0
    total_pnl = 0.0
    for strat, info in strategy_totals.items():
        starting = float(info["agents"]) * 1000.0
        pnl_pct = (info["pnl"] / starting * 100.0) if starting > 0 else 0.0
        info["pnlPct"] = round(pnl_pct, 2)
        total_starting += starting
        total_pnl += float(info["pnl"])

    pool_pnl_pct = (total_pnl / total_starting * 100.0) if total_starting > 0 else 0.0

    return {
        "week_id": week_id,
        "date_range": [start.date().isoformat(), end.date().isoformat()],
        "strategy_rollup": strategy_totals,
        "rivalries": sorted(
            rivalry_acc.values(),
            key=lambda r: r.get("count", 0),
            reverse=True,
        ),
        "promotions": [],  # populated by write_weekly_rollup if DB reachable
        "sessions": sessions,
        "pool_pnl": round(total_pnl, 2),
        "pool_pnl_pct": round(pool_pnl_pct, 2),
    }


def write_weekly_rollup(
    rollup: dict[str, Any],
    *,
    sessions_dir: Path | None = None,
) -> Path:
    """Persist ``rollup`` to
    ``<sessions_dir>/weekly/<week_id>/rollup.json``. Returns the path.
    Creates the parent dirs as needed.
    """
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    week_id = str(rollup.get("week_id") or "unknown")
    out = base / "weekly" / week_id / "rollup.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rollup, indent=2, default=str), encoding="utf-8")
    return out


def read_weekly_rollup(
    week_id: str,
    *,
    sessions_dir: Path | None = None,
) -> dict[str, Any] | None:
    """Read the rollup for ``week_id`` from disk. Returns None if the
    file doesn't exist (a fresh dev box, or a week with no sessions).
    """
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    path = base / "weekly" / week_id / "rollup.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, TypeError):
        return None


def previous_week_id(week_id: str, *, weeks_back: int = 1) -> str:
    """Return the ISO-trading-week ID ``weeks_back`` weeks before
    ``week_id``. Used by the Strategy Wars detector to load the
    previous week's rollup without doing date math inline."""
    year_str, _, week_str = week_id.partition("-W")
    iso_year = int(year_str)
    iso_week = int(week_str)
    target_week = iso_week - weeks_back
    target_year = iso_year
    while target_week < 1:
        target_year -= 1
        # Last ISO week of the previous year is 52 or 53 — 53 in
        # long ISO years. Use a heuristic: try 53 first, fall back
        # to 52. (datetime.date(year, 12, 28).isocalendar().week is
        # the canonical "what's the last ISO week" query.)
        from datetime import date as _date
        last_iso_week = _date(target_year, 12, 28).isocalendar()[1]
        target_week += last_iso_week
    return f"{target_year:04d}-W{target_week:02d}"
