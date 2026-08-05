"""Thumbnail extractor — grabs a single JPEG frame from the final reel
and writes it to ``<session_dir>/thumb.jpg`` for the YouTube upload
stage.

Pipeline shape (0.8.x):

    render.stitch    -> silent_reel.mp4
    render.mix       -> reel.mp4
    render.thumb     -> thumb.jpg   (this module)
    yt.metadata      -> episode.yaml (embeds thumb.jpg if present)
    yt.upload        -> POST thumb.jpg to YouTube (optional)

Why a separate stage
--------------------
Until 0.8 every published video got YouTube's auto-thumbnail because
no pipeline step produced ``out/sessions/<id>/thumb.jpg``. ``yt.metadata``
already looks for it (``sdir / "thumb.jpg"``) and ``yt.upload`` already
uploads it when present -- this stage is the missing writer.

Approach
--------
One fast ffmpeg invocation. The ``-ss`` lives *before* ``-i`` so the
seek is keyframe-accurate, which is fine for a single still: a thumbnail
doesn't need sample-accurate timing. The ``scale=...:force_original_aspect_
ratio=decrease,pad=...:`` filter preserves the source aspect ratio -- a
16:9 source fills the 1280x720 frame with no padding; a 9:16 shorts
source (vertical pilot footage) letterboxes with a black border rather
than cropping off the headline.

``-q:v`` is the JPEG quality (1 = highest, 2-5 = "high", lower numbers
are larger files). 2 keeps the thumb under YT's 2 MB limit even on
busy frames.

System ffmpeg required. The probe lives in ``render.stitch.ffmpeg_info``
so the existing probe-error UX is reused; we don't duplicate it here.

ASCII-only output (Windows cp1252 console) -- the same constraint
``render.shorts`` carries.

CLI
---
    python -m tradefarm.render.thumb <session_id> \\
        [--out <sessions_dir>] \\
        [--at 1.0] \\
        [--quality 2] \\
        [--width 1280] [--height 720] \\
        [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from tradefarm.render.stitch import ffmpeg_info


# Default seek time. 1.0s avoids the very first frame which is often a
# fade-in / black leader and looks ugly on a thumbnail. Operators can
# override per session via --at.
DEFAULT_AT_SEC = 1.0
# JPEG quality (q:v). 2 is "high" in ffmpeg's JPEG encoder; 1 is the
# highest but balloons the file over YT's 2 MB limit on busy frames.
DEFAULT_QUALITY = 2
# 1280x720 matches YouTube's recommended thumbnail dimensions. A
# thumbnail smaller than 640px on its longest side is rejected by the
# YT Studio UI; 1280x720 leaves headroom and looks crisp on a phone.
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720


# ----- ffmpeg argv builder --------------------------------------------------


def build_ffmpeg_argv(
    *,
    in_path: Path,
    out_path: Path,
    at_sec: float = DEFAULT_AT_SEC,
    quality: int = DEFAULT_QUALITY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[str]:
    """Compose the ffmpeg argv that extracts one JPEG frame from
    ``in_path`` at ``at_sec`` seconds and writes it to ``out_path``.

    Pure function so the unit tests can pin the exact contract (the
    ``test_thumb.py`` test suite asserts on it). The filter chain is
    ``scale=W:H:force_original_aspect_ratio=decrease,pad=W:H:(ow-iw)/2:
    (oh-ih)/2`` so a non-16:9 source (e.g. a vertical shorts pilot)
    letterboxes into the 16:9 target rather than cropping.
    """
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2"
    )
    return [
        "ffmpeg",
        "-y",  # overwrite without prompt
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{at_sec:.3f}",  # fast seek (keyframe); good enough for a still
        "-i",
        str(in_path),
        "-vframes",
        "1",
        "-q:v",
        str(int(quality)),
        "-vf",
        vf,
        str(out_path),
    ]


# ----- record types ---------------------------------------------------------


@dataclass(frozen=True)
class ThumbResult:
    """Outcome of one ``extract_thumb`` call. ``ok`` is the only field
    callers should branch on; the rest are surfaced in dry-run / debug
    print banners."""

    ok: bool
    out_path: Path | None = None
    in_path: Path | None = None
    elapsed_ms: int | None = None
    ffmpeg_argv: list[str] | None = None
    error: str | None = None
    dry_run: bool = False


# ----- top-level driver -----------------------------------------------------


def _resolve_input(sdir: Path) -> Path:
    """Return the file we thumbnail from. The mix step produces
    ``reel.mp4`` (silent_reel + VO + music); when the operator skipped
    TTS, ``silent_reel.mp4`` from the stitcher is the closest thing.
    Prefer the higher-fidelity reel when both exist."""

    reel = sdir / "reel.mp4"
    if reel.is_file():
        return reel
    silent = sdir / "silent_reel.mp4"
    if silent.is_file():
        return silent
    # Neither file is on disk. Raise with a path that names the first
    # one an operator would expect; the pipeline runner surfaces this
    # in the per-step failure banner.
    raise FileNotFoundError(
        f"neither reel.mp4 nor silent_reel.mp4 found in {sdir} "
        "-- run render.mix (or render.stitch) first"
    )


def extract_thumb(
    session_id: str,
    *,
    sessions_dir: Path,
    at_sec: float = DEFAULT_AT_SEC,
    quality: int = DEFAULT_QUALITY,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    dry_run: bool = False,
) -> ThumbResult:
    """Run the ffmpeg thumbnail extraction for one session and return a
    ``ThumbResult``. ``dry_run=True`` builds the argv but never spawns
    ffmpeg -- useful for the pipeline's plan-only mode."""

    sdir = sessions_dir / session_id
    in_path = _resolve_input(sdir)
    out_path = sdir / "thumb.jpg"
    argv = build_ffmpeg_argv(
        in_path=in_path,
        out_path=out_path,
        at_sec=at_sec,
        quality=quality,
        width=width,
        height=height,
    )

    if dry_run:
        return ThumbResult(
            ok=True,
            out_path=out_path,
            in_path=in_path,
            ffmpeg_argv=argv,
            dry_run=True,
        )

    ok, info = ffmpeg_info()
    if not ok:
        return ThumbResult(
            ok=False,
            out_path=out_path,
            in_path=in_path,
            ffmpeg_argv=argv,
            error=f"ffmpeg not available: {info}",
        )

    started = time.perf_counter()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, check=False)
    except OSError as exc:
        return ThumbResult(
            ok=False,
            out_path=out_path,
            in_path=in_path,
            ffmpeg_argv=argv,
            error=f"ffmpeg spawn failed: {type(exc).__name__}: {exc}",
        )
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    if r.returncode != 0 or not out_path.is_file():
        # ffmpeg tends to print the actionable error on stderr. Trim
        # to the last non-empty line so the failure banner stays short.
        err_lines = [ln for ln in (r.stderr or "").splitlines() if ln.strip()]
        last_err = err_lines[-1] if err_lines else f"exit {r.returncode}"
        return ThumbResult(
            ok=False,
            out_path=out_path,
            in_path=in_path,
            ffmpeg_argv=argv,
            elapsed_ms=elapsed_ms,
            error=last_err,
        )

    return ThumbResult(
        ok=True,
        out_path=out_path,
        in_path=in_path,
        ffmpeg_argv=argv,
        elapsed_ms=elapsed_ms,
    )


# ----- CLI ------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    """`python -m tradefarm.render.thumb <session_id> [--at 1.0]`.

    Resolves ``<sessions_dir>/<session_id>/{reel.mp4,silent_reel.mp4}``,
    extracts a single frame, and writes ``thumb.jpg`` next to the
    source. Exits 0 on success, 1 on ffmpeg failure (with the captured
    stderr on the last banner line).
    """

    parser = argparse.ArgumentParser(
        prog="tradefarm.render.thumb",
        description="Extract a single JPEG thumbnail from a session's reel.",
    )
    parser.add_argument("session_id", help="Session id (matches out/sessions/<session_id>/).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--at",
        type=float,
        default=DEFAULT_AT_SEC,
        help=f"Seconds into the source to grab the frame (default {DEFAULT_AT_SEC}).",
    )
    parser.add_argument(
        "--quality",
        type=int,
        default=DEFAULT_QUALITY,
        help=f"JPEG q:v (1=highest, 2-5=high, default {DEFAULT_QUALITY}).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_WIDTH,
        help=f"Output width (default {DEFAULT_WIDTH}).",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_HEIGHT,
        help=f"Output height (default {DEFAULT_HEIGHT}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved ffmpeg argv without running it.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    result = extract_thumb(
        args.session_id,
        sessions_dir=args.out,
        at_sec=args.at,
        quality=args.quality,
        width=args.width,
        height=args.height,
        dry_run=args.dry_run,
    )

    if result.dry_run:
        print(f"[thumb] session_id={args.session_id}")
        print(f"[thumb] in={result.in_path}")
        print(f"[thumb] out={result.out_path}")
        print(f"[thumb] argv: {' '.join(result.ffmpeg_argv or [])}")
        return

    if not result.ok:
        print(f"[thumb] FAIL session_id={args.session_id}", file=sys.stderr)
        print(f"[thumb]   in={result.in_path}", file=sys.stderr)
        print(f"[thumb]   out={result.out_path}", file=sys.stderr)
        print(f"[thumb]   error: {result.error}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"[thumb] session_id={args.session_id}\n"
        f"[thumb] in={result.in_path}\n"
        f"[thumb] out={result.out_path}\n"
        f"[thumb] elapsed={int(result.elapsed_ms or 0)}ms"
    )


if __name__ == "__main__":
    main()
