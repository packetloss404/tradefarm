"""Asset archival — on run-done, tar the session dir to a backup path.

Why this exists
---------------
The VOD pipeline's outputs live under
``out/sessions/<sid>/{manifest.json, beats.json, reel.mp4, ...}``.
A destroyed local box loses every published reel's source artifacts
(manifest, beats, episode.yaml, thumb, vo/, silent_reel.mp4). The
YouTube copy of the reel survives — but you can't re-render or
re-upload if YouTube takes the video down.

This module is the 0.9.0 carryover that closes that gap. On
``run.status == "done"`` (or ``failed``, if the operator wants the
diagnostic state) the HTTP wrapper + orchestrator's scheduler
both call :func:`archive_session` with the session's
``out/sessions/<sid>`` directory. We tar it (minus the
regenerable ``clips/*.webm`` source — the rendered ``reel.mp4`` is
already in the tar) to a configurable backup root.

Usage
-----
- CLI: ``python -m tradefarm.render.archive <session_id> --out
  /var/backups/tradefarm``
- HTTP wrapper: ``await archive_session(session_id, archive_root=...)``
  in the done / failed paths
- Orchestrator scheduler: same

The function is best-effort: any failure (tar missing, disk full,
permissions) is logged + swallowed so a backup failure never fails
a successful run. The on-disk artifact is the source of truth.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


# Subpaths we exclude from the tarball. ``clips/`` holds the raw
# 16:9 headless captures — the rendered ``reel.mp4`` already
# encodes them, and clips are the biggest line item by far (often
# 100MB+ per beat). ``intermediates/`` is whatever the stitch +
# mix + thumb steps drop on disk for their own use; not
# regenerable-from-source data.
#
# Each entry is a path prefix; the archive loop drops any
# member whose path starts with the entry. ``clips/`` covers
# all of the per-beat .webm + .json sidecars under that
# directory.
_EXCLUDE_PREFIXES = ("clips/", "intermediates/")


def _make_tarball(
    src_dir: Path,
    out_path: Path,
) -> int:
    """Sync helper: tar ``src_dir`` to ``out_path`` (gzip).

    Returns the number of files archived. Runs in a worker thread
    by the async wrapper.
    """
    n = 0
    with tarfile.open(out_path, "w:gz") as tar:
        for child in sorted(src_dir.rglob("*")):
            if not child.is_file():
                continue
            rel = child.relative_to(src_dir)
            # Cheap prefix check — anything under ``clips/`` or
            # ``intermediates/`` is excluded. Path uses forward
            # slashes regardless of OS.
            rel_str = str(rel).replace("\\", "/")
            if any(rel_str.startswith(prefix) for prefix in _EXCLUDE_PREFIXES):
                continue
            tar.add(child, arcname=rel)
            n += 1
    return n


async def archive_session(
    session_id: str,
    *,
    archive_root: Path | None = None,
    sessions_dir: Path | None = None,
    also_on_failure: bool = False,
    run_status: str = "done",
) -> Path | None:
    """Tar the named session's directory to ``archive_root``.

    The output file lands at
    ``<archive_root>/<YYYY-MM-DD>/<session_id>.tar.gz``. The
    date-stamped parent dir is a cheap partitioning scheme that
    keeps each backup cycle's tarballs together (most operators
    rsync the date dirs to S3 / GCS on a daily cron).

    Returns the path on success, ``None`` on skip (no archive
    root configured) or on best-effort failure. Failures are
    logged + swallowed — a backup miss is recoverable from a
    re-render; a failed run is not.
    """
    if archive_root is None:
        log.info("asset_archive_skipped_no_root", extra={"session_id": session_id})
        return None
    if not also_on_failure and run_status != "done":
        log.info(
            "asset_archive_skipped_status",
            extra={"session_id": session_id, "status": run_status},
        )
        return None

    base = sessions_dir or Path("out/sessions")
    src_dir = base / session_id
    if not src_dir.is_dir():
        log.warning(
            "asset_archive_missing_src",
            extra={"session_id": session_id, "src": str(src_dir)},
        )
        return None

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(archive_root) / today
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{session_id}.tar.gz"

    # Write to a temp file alongside the final path, then move into
    # place — a partial tarball never lands at the final path. The
    # sync tar helper writes to whichever path we give it; we give
    # it the temp path and move the result to ``out_path`` afterwards.
    import os
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{session_id}.", suffix=".tar.gz.tmp", dir=str(out_dir)
    )
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        # Run the blocking tar in a worker thread so the event loop
        # stays responsive on big sessions.
        loop = asyncio.get_running_loop()
        n = await loop.run_in_executor(None, _make_tarball, src_dir, tmp_path)
        shutil.move(str(tmp_path), str(out_path))
    except Exception as exc:  # noqa: BLE001
        # Best-effort: a backup miss is recoverable; a failed run
        # is the priority signal. Log + clean up + return None.
        log.warning(
            "asset_archive_failed",
            extra={
                "session_id": session_id,
                "error": f"{type(exc).__name__}: {exc}",
            },
        )
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass
        return None
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass

    log.info(
        "asset_archive_ok",
        extra={
            "session_id": session_id,
            "path": str(out_path),
            "file_count": n,
        },
    )
    return out_path


# ----- CLI ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """``python -m tradefarm.render.archive <session_id> --out <dir>``.

    Operator entrypoint for ad-hoc archival — useful when an
    environment runs the pipeline but doesn't have the
    ``vod_archive_path`` env var set (e.g. a dev box that
    occasionally backs up to a USB drive)."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="tradefarm.render.archive",
        description="Tar a session's directory to a backup path.",
    )
    parser.add_argument("session_id")
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Backup root (date-stamped subdirs are created under it).",
    )
    parser.add_argument(
        "--sessions-dir",
        type=Path,
        default=Path("out/sessions"),
    )
    parser.add_argument(
        "--also-on-failure",
        action="store_true",
        help="Archive even when the run failed (diagnostic state).",
    )
    args = parser.parse_args(argv)

    out = asyncio.run(
        archive_session(
            args.session_id,
            archive_root=args.out,
            sessions_dir=args.sessions_dir,
            also_on_failure=args.also_on_failure,
            run_status="done",
        )
    )
    if out is None:
        return 1
    print(f"archived {args.session_id} -> {out}")
    return 0


if __name__ == "__main__":
    import sys as _sys

    raise SystemExit(main(_sys.argv[1:]))
