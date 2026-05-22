"""Online SQLite backup for tradefarm.db.

Uses SQLite's `.backup` API (via aiosqlite's underlying connection)
so the live backend can keep writing during the copy — `cp tradefarm.db
backup.db` is NOT safe; this script is.

Usage:
    uv run python -m scripts.backup_db                 # → backups/tradefarm-YYYYMMDD-HHMMSS.db
    uv run python -m scripts.backup_db --out /path     # explicit destination
    uv run python -m scripts.backup_db --retain 14     # also prune backups older than 14 days

Schedule via Task Scheduler / cron — recommend daily at off-hours
(00:30 UTC: post-close, pre-train).
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

DEFAULT_DB = Path("tradefarm.db")
DEFAULT_BACKUP_DIR = Path("backups")


def backup(src: Path, dst: Path) -> None:
    """SQLite online backup: source → dst. dst is overwritten."""
    if not src.is_file():
        raise SystemExit(f"source db not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            # progress=None → copy all pages in one go.
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def prune(backup_dir: Path, retain_days: int) -> int:
    """Delete .db backups older than retain_days. Returns count removed."""
    if not backup_dir.is_dir() or retain_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retain_days)
    removed = 0
    for p in backup_dir.glob("tradefarm-*.db"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            try:
                p.unlink()
                removed += 1
            except OSError:
                pass
    return removed


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="scripts.backup_db")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="explicit destination path; default backups/tradefarm-<ts>.db",
    )
    parser.add_argument(
        "--retain", type=int, default=0, help="also prune backups older than N days (0=keep all)"
    )
    args = parser.parse_args(argv)

    if args.out is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        dst = DEFAULT_BACKUP_DIR / f"tradefarm-{ts}.db"
    else:
        dst = args.out

    backup(args.db, dst)
    size_mb = dst.stat().st_size / (1024 * 1024)
    print(f"backed up {args.db} -> {dst} ({size_mb:.1f} MB)")

    if args.retain > 0:
        n = prune(dst.parent, args.retain)
        if n:
            print(f"pruned {n} backup(s) older than {args.retain} days")


if __name__ == "__main__":
    main(sys.argv[1:])
