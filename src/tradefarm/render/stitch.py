"""ffmpeg stitcher — turns per-beat .webm clips into one silent_reel.mp4.

Input:  out/sessions/<id>/clips/<beat_id>.webm + .json (from headless.py)
        out/sessions/<id>/beats.json                  (from session.beats)
Output: out/sessions/<id>/silent_reel.mp4

Two-pass design recommended by review:

  Pass 1 — normalise each clip
    * trim off `scene_ready_at_ms` of page-load garbage (filter-based,
      VP8 keyframe gaps make `-ss` before `-i` too coarse)
    * fixed timebase / fps / pix_fmt so xfade in pass 2 doesn't choke
    * encode H.264 yuv420p; run in parallel via a thread pool

  Pass 2 — single filter_complex with chained xfade
    * 0.4s fade between every pair
    * burn per-beat captions via drawtext with `enable='between(t,…)'`
    * no audio track at all — Session 8 mixer adds VO + music + stingers
      on a fresh audio stream and -c:v copy's this video stream over

When the chained-xfade graph blows up (very long sessions, codec quirks)
the renderer falls back to a pairwise reduction: stitch clips 0+1 into a
prefix mp4, then prefix+clip2, etc. Slower but bulletproof.

System `ffmpeg` is required (`winget install Gyan.FFmpeg` on Windows,
`brew install ffmpeg` on macOS). The Python module has no media deps —
keeps the trading-rig install lean.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_FPS = 30
DEFAULT_XFADE_SEC = 0.4
# Pre-roll padding kept past scene_ready, so the very first frame isn't
# mid-animation. Trim point becomes scene_ready_at_ms - PREROLL_PAD_MS.
PREROLL_PAD_MS = 150


# ----- font discovery for drawtext -----------------------------------------

CANDIDATE_FONTS = (
    # Windows
    "C:/Windows/Fonts/segoeui.ttf",
    "C:/Windows/Fonts/arial.ttf",
    # macOS
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    # Linux fallback
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


def discover_font() -> str | None:
    """Find a TTF on disk drawtext can load. Returns POSIX path or None."""
    for cand in CANDIDATE_FONTS:
        p = Path(cand)
        if p.is_file():
            return p.resolve().as_posix()
    return None


def _ff_path(p: str | Path) -> str:
    """Escape a path for drawtext's `fontfile=`. Coerce to `Path` first
    so a `--font "C:\\Windows\\Fonts\\arial.ttf"` string flag still goes
    through `as_posix()` and the drive-colon escape."""
    s = Path(p).resolve().as_posix()
    return s.replace(":", r"\:")


def _ff_text(s: str) -> str:
    """Escape text for drawtext's `text='...'`. Order matters: backslash
    first, then the other meta-chars. CR/LF are dropped — drawtext
    can't wrap and leaves them as literal box-glyphs."""
    cleaned = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return (
        cleaned.replace("\\", r"\\")
               .replace(":", r"\:")
               .replace("'", r"\'")
               .replace("%", r"\%")
    )


# ----- ffmpeg discovery -----------------------------------------------------


def ffmpeg_info() -> tuple[bool, str]:
    """Cross-platform `ffmpeg -version` probe. Doesn't raise."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        return False, str(e)
    if r.returncode != 0:
        # stderr can be empty even on non-zero exit (e.g. signalled). Don't
        # index a possibly-empty splitlines() result.
        err_lines = (r.stderr or "").strip().splitlines()
        return False, err_lines[0] if err_lines else "non-zero exit"
    out_lines = (r.stdout or "").splitlines()
    return True, out_lines[0] if out_lines else ""


# ----- record types --------------------------------------------------------


@dataclass(frozen=True)
class ClipPlan:
    """One input clip with its trim + caption metadata."""

    beat_id: str
    src: Path              # the .webm
    sidecar: Path          # the .json
    trim_start_sec: float  # scene_ready_at_ms - preroll, clamped >=0
    duration_sec: float    # how much of the clip to keep
    headline: str
    sub: str
    kind: str


@dataclass
class StitchPlan:
    session_id: str
    clips: list[ClipPlan]
    out_path: Path
    intermediates_dir: Path
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    xfade_sec: float = DEFAULT_XFADE_SEC
    captions: bool = True
    font_path: str | None = None  # resolved at plan time


@dataclass
class StitchResult:
    ok: bool
    out_path: Path | None = None
    plan: StitchPlan | None = None
    elapsed_ms: float | None = None
    error: str | None = None
    fallback_used: bool = False


# ----- plan builder --------------------------------------------------------


def _load_beat_map(beats_path: Path) -> dict[str, dict[str, Any]]:
    """Read beats.json and key by beat id. Duplicate ids keep the FIRST
    occurrence (chronological per the detector) and the rest are dropped
    — collisions normally mean two detector runs were concatenated."""
    if not beats_path.is_file():
        return {}
    rows = json.loads(beats_path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        bid = row.get("id")
        if not bid or bid in out:
            continue
        out[bid] = row
    return out


def plan_stitch(
    *,
    session_id: str,
    clips_dir: Path,
    beats_path: Path,
    out_path: Path,
    intermediates_dir: Path | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    xfade_sec: float = DEFAULT_XFADE_SEC,
    captions: bool = True,
    font_path: str | None = None,
) -> StitchPlan:
    """Discover clips + sidecars in `clips_dir`, pair them with beat
    headlines from `beats.json`, and return the StitchPlan in
    chronological order (by the beat's `t` timestamp)."""

    beats = _load_beat_map(beats_path)

    sidecars = sorted(clips_dir.glob("*.json"))
    clips: list[ClipPlan] = []
    for sc in sidecars:
        try:
            meta = json.loads(sc.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        beat_id = meta.get("beat_id")
        if not beat_id:
            continue
        webm = clips_dir / f"{beat_id}.webm"
        if not webm.is_file():
            continue
        beat = beats.get(beat_id, {})
        trim_ms = max(0, int(meta.get("scene_ready_at_ms") or 0) - PREROLL_PAD_MS)
        duration_ms = int(meta.get("duration_ms") or int(beat.get("duration_sec", 0)) * 1000)
        clips.append(
            ClipPlan(
                beat_id=beat_id,
                src=webm,
                sidecar=sc,
                trim_start_sec=trim_ms / 1000.0,
                duration_sec=max(0.0, duration_ms / 1000.0),
                headline=str(beat.get("headline") or ""),
                sub=str(beat.get("sub") or ""),
                kind=str(beat.get("kind") or meta.get("kind") or ""),
            )
        )

    # Order by the beat's `at` timestamp so the reel reads as the day's
    # story; fall back to filename if a beat went missing from beats.json.
    order_key: dict[str, str] = {
        bid: row.get("t", "") for bid, row in beats.items()
    }
    clips.sort(key=lambda c: (order_key.get(c.beat_id, ""), c.beat_id))

    return StitchPlan(
        session_id=session_id,
        clips=clips,
        out_path=out_path,
        intermediates_dir=intermediates_dir or (out_path.parent / ".stitch-intermediates"),
        width=width,
        height=height,
        fps=fps,
        xfade_sec=xfade_sec,
        captions=captions,
        font_path=font_path if font_path is not None else discover_font(),
    )


# ----- command builders ----------------------------------------------------


def build_normalize_command(clip: ClipPlan, *, plan: StitchPlan, out_path: Path) -> list[str]:
    """Pass-1: trim + normalise one clip → intermediate .mp4."""
    vf = (
        f"trim=start={clip.trim_start_sec:.3f}:duration={clip.duration_sec:.3f},"
        f"setpts=PTS-STARTPTS,"
        f"fps={plan.fps},"
        f"format=yuv420p,"
        f"scale={plan.width}:{plan.height},"
        f"setsar=1"
    )
    return [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(clip.src),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-g", str(plan.fps),
        "-an",
        "-video_track_timescale", "30000",
        str(out_path),
    ]


def caption_filter(
    *,
    headline: str,
    sub: str,
    t_start: float,
    t_end: float,
    font_path: str | None,
    head_size: int = 56,
    sub_size: int = 28,
) -> str:
    """drawtext expression(s) for one beat's caption window. Returns
    "" if the headline is blank or no font is available."""
    if not headline or not font_path:
        return ""
    enable = f"between(t,{t_start:.3f},{t_end:.3f})"
    font = _ff_path(font_path)
    head_text = _ff_text(headline)
    common_pos = "x=(w-text_w)/2"
    head = (
        f"drawtext=fontfile='{font}':text='{head_text}':"
        f"fontsize={head_size}:fontcolor=white:"
        f"borderw=3:bordercolor=black@0.85:"
        f"box=1:boxcolor=black@0.55:boxborderw=24:"
        f"{common_pos}:y=h-h/4-text_h:"
        f"enable='{enable}'"
    )
    if not sub:
        return head
    sub_text = _ff_text(sub)
    sub_f = (
        f"drawtext=fontfile='{font}':text='{sub_text}':"
        f"fontsize={sub_size}:fontcolor=white@0.85:"
        f"borderw=2:bordercolor=black@0.85:"
        f"{common_pos}:y=h-h/4+12:"
        f"enable='{enable}'"
    )
    return f"{head},{sub_f}"


def build_xfade_command(
    intermediates: list[Path],
    *,
    plan: StitchPlan,
    out_path: Path,
) -> list[str]:
    """Pass-2: chained xfade across normalised intermediates +
    drawtext per beat. All clips assumed normalised to identical
    width/height/fps/pix_fmt/timebase."""

    n = len(intermediates)
    if n == 0:
        raise ValueError("no intermediates to stitch")
    if n == 1:
        # Single clip path: still apply captions if requested, then copy.
        captions_filter = ""
        if plan.captions:
            cap = caption_filter(
                headline=plan.clips[0].headline,
                sub=plan.clips[0].sub,
                t_start=0.0,
                t_end=plan.clips[0].duration_sec,
                font_path=plan.font_path,
            )
            if cap:
                captions_filter = f",{cap}"
        vf = f"setpts=PTS-STARTPTS{captions_filter}"
        return [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(intermediates[0]),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",
            str(out_path),
        ]

    args: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for p in intermediates:
        args.extend(["-i", str(p)])

    # Chained xfade. Offset for fade i = sum(duration_j for j<=i) - xfade*(i+1)
    fade = plan.xfade_sec
    durations = [c.duration_sec for c in plan.clips]
    filter_parts: list[str] = []
    cumulative = 0.0
    prev_label = "0:v"
    for i in range(n - 1):
        cumulative += durations[i]
        offset = cumulative - fade * (i + 1)
        out_label = f"vx{i}"
        filter_parts.append(
            f"[{prev_label}][{i + 1}:v]"
            f"xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}"
            f"[{out_label}]"
        )
        prev_label = out_label

    # Caption pass: walk clips with cumulative time minus per-fade lap,
    # so caption windows align with what's on screen post-xfade.
    if plan.captions and plan.font_path:
        # Per-clip on-screen window: clip i is on screen from
        #   start_i = sum(duration_j for j<i) - fade*i
        # The end of clip i's *clean* window (no overlap with i+1) is
        # start_i + duration_i - fade for non-last clips. Without that
        # trim the next clip's caption fires during the outgoing fade
        # and the two stack visibly for the full fade duration.
        caption_exprs: list[str] = []
        t_cursor = 0.0
        last_i = len(plan.clips) - 1
        for i, c in enumerate(plan.clips):
            if i > 0:
                t_cursor -= fade  # the fade overlaps the previous clip
            start = t_cursor
            clean_end = start + c.duration_sec - (fade if i < last_i else 0.0)
            cap = caption_filter(
                headline=c.headline,
                sub=c.sub,
                t_start=start,
                t_end=clean_end,
                font_path=plan.font_path,
            )
            if cap:
                caption_exprs.append(cap)
            t_cursor += c.duration_sec
        if caption_exprs:
            caption_chain = ",".join(caption_exprs)
            filter_parts.append(f"[{prev_label}]{caption_chain}[vout]")
            prev_label = "vout"

    filter_complex = ";".join(filter_parts)
    args.extend([
        "-filter_complex", filter_complex,
        "-map", f"[{prev_label}]",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        "-an",
        str(out_path),
    ])
    return args


def build_pairwise_commands(
    intermediates: list[Path],
    *,
    plan: StitchPlan,
    work_dir: Path,
    out_path: Path,
) -> list[tuple[list[str], Path]]:
    """Fallback: pairwise reduction. Stitches clips left-to-right, one
    xfade at a time, into a growing prefix mp4. Slower (re-encodes the
    prefix at each step) but recovers when the chained graph fails."""

    if len(intermediates) <= 1:
        return [(build_xfade_command(intermediates, plan=plan, out_path=out_path), out_path)]

    work_dir.mkdir(parents=True, exist_ok=True)
    steps: list[tuple[list[str], Path]] = []
    fade = plan.xfade_sec
    prefix = intermediates[0]
    cumulative = plan.clips[0].duration_sec
    for i in range(1, len(intermediates)):
        is_last = i == len(intermediates) - 1
        target = out_path if is_last else (work_dir / f"prefix_{i:02d}.mp4")
        offset = cumulative - fade
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(prefix),
            "-i", str(intermediates[i]),
            "-filter_complex",
            f"[0:v][1:v]xfade=transition=fade:duration={fade:.3f}:offset={offset:.3f}[vout]",
            "-map", "[vout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-an",
        ]
        if is_last:
            cmd.extend(["-movflags", "+faststart"])
        cmd.append(str(target))
        steps.append((cmd, target))
        cumulative = cumulative + plan.clips[i].duration_sec - fade
        prefix = target
    return steps


# ----- execution -----------------------------------------------------------


def _run_one(cmd: list[str], *, cleanup_on_fail: Path | None = None) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except OSError as e:
        if cleanup_on_fail is not None:
            cleanup_on_fail.unlink(missing_ok=True)
        return False, str(e)
    if r.returncode != 0:
        if cleanup_on_fail is not None:
            # ffmpeg writes a 0-byte or partial file on failure; the next
            # run otherwise reuses it and the operator chases a phantom bug.
            cleanup_on_fail.unlink(missing_ok=True)
        # ffmpeg's useful output is on stderr.
        return False, (r.stderr or r.stdout or "").strip()[-800:]
    return True, ""


def stitch_session(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: int = DEFAULT_FPS,
    xfade_sec: float = DEFAULT_XFADE_SEC,
    captions: bool = True,
    font_path: str | None = None,
    dry_run: bool = False,
    pass_through_only: bool = False,
    parallel_normalize: int = 4,
) -> StitchResult:
    """Top-level entrypoint. Loads beats + clips, normalises, stitches,
    returns the resulting mp4 path. Falls back to pairwise reduction if
    the chained-xfade pass fails."""

    started = time.perf_counter()
    base = sessions_dir or Path("out/sessions")
    sdir = base / session_id
    clips_dir = sdir / "clips"
    beats_path = sdir / "beats.json"
    out_path = sdir / "silent_reel.mp4"
    intermediates_dir = sdir / ".stitch-intermediates"

    plan = plan_stitch(
        session_id=session_id,
        clips_dir=clips_dir,
        beats_path=beats_path,
        out_path=out_path,
        intermediates_dir=intermediates_dir,
        width=width,
        height=height,
        fps=fps,
        xfade_sec=xfade_sec,
        captions=captions,
        font_path=font_path,
    )

    if not plan.clips:
        return StitchResult(
            ok=False,
            plan=plan,
            error=f"no clips found in {clips_dir}",
        )

    if dry_run:
        return StitchResult(ok=True, plan=plan, out_path=out_path)

    ok, info = ffmpeg_info()
    if not ok:
        return StitchResult(
            ok=False, plan=plan,
            error=f"ffmpeg not available on PATH: {info}",
        )

    intermediates_dir.mkdir(parents=True, exist_ok=True)
    intermediate_paths: list[Path] = [
        intermediates_dir / f"{i:03d}_{c.beat_id}.mp4"
        for i, c in enumerate(plan.clips)
    ]

    # Pass 1: normalise in parallel.
    norm_failures: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, parallel_normalize)) as pool:
        futures = {
            pool.submit(
                _run_one,
                build_normalize_command(c, plan=plan, out_path=intermediate_paths[i]),
            ): c.beat_id
            for i, c in enumerate(plan.clips)
        }
        for fut in as_completed(futures):
            ok, err = fut.result()
            if not ok:
                norm_failures.append(f"{futures[fut]}: {err.splitlines()[-1] if err else 'unknown'}")
    if norm_failures:
        return StitchResult(
            ok=False, plan=plan,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error="normalize failed: " + " | ".join(norm_failures[:3]),
        )

    if pass_through_only:
        # Diagnostic mode: just concat the intermediates without xfade,
        # useful when debugging the captions filter.
        list_file = intermediates_dir / "concat.txt"
        list_file.write_text(
            "\n".join(f"file '{p.resolve().as_posix()}'" for p in intermediate_paths),
            encoding="utf-8",
        )
        ok, err = _run_one([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", "-movflags", "+faststart",
            str(out_path),
        ])
        if not ok:
            return StitchResult(
                ok=False, plan=plan,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=f"concat-demux failed: {err.splitlines()[-1] if err else ''}",
            )
        return StitchResult(
            ok=True, plan=plan, out_path=out_path,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    # Pass 2: chained xfade. If it fails, fall back to pairwise.
    chain_cmd = build_xfade_command(intermediate_paths, plan=plan, out_path=out_path)
    ok, err = _run_one(chain_cmd, cleanup_on_fail=out_path)
    if ok:
        return StitchResult(
            ok=True, plan=plan, out_path=out_path,
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )

    # Fallback path.
    pairwise_steps = build_pairwise_commands(
        intermediate_paths, plan=plan,
        work_dir=intermediates_dir / "pairwise",
        out_path=out_path,
    )
    for cmd, target in pairwise_steps:
        ok, err = _run_one(cmd, cleanup_on_fail=target)
        if not ok:
            return StitchResult(
                ok=False, plan=plan,
                elapsed_ms=(time.perf_counter() - started) * 1000,
                error=f"pairwise step failed ({target.name}): {err.splitlines()[-1] if err else ''}",
                fallback_used=True,
            )
    return StitchResult(
        ok=True, plan=plan, out_path=out_path,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        fallback_used=True,
    )


# ----- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.render.stitch <session_id>` walks
    out/sessions/<id>/clips/*.webm + *.json, stitches them with
    crossfades + captions, writes silent_reel.mp4 next to them."""

    parser = argparse.ArgumentParser(
        prog="tradefarm.render.stitch",
        description="Concatenate per-beat clips with crossfades + drawtext captions.",
    )
    parser.add_argument("session_id", help="Session id (matches out/sessions/<session_id>/).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument("--xfade", type=float, default=DEFAULT_XFADE_SEC, help="Crossfade seconds.")
    parser.add_argument("--no-captions", action="store_true", help="Skip drawtext caption overlay.")
    parser.add_argument(
        "--font",
        default=None,
        help="Font file to use for captions (default: auto-discover).",
    )
    parser.add_argument(
        "--pass-through",
        action="store_true",
        help="Diagnostic: just concat-demux the normalised intermediates (no xfade, no captions).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan + ffmpeg commands without running them.",
    )
    parser.add_argument(
        "--parallel-normalize",
        type=int,
        default=4,
        help="Pass-1 worker count (default 4).",
    )
    args = parser.parse_args(argv)

    result = stitch_session(
        args.session_id,
        sessions_dir=args.out,
        width=args.width,
        height=args.height,
        fps=args.fps,
        xfade_sec=args.xfade,
        captions=not args.no_captions,
        font_path=args.font,
        dry_run=args.dry_run,
        pass_through_only=args.pass_through,
        parallel_normalize=args.parallel_normalize,
    )

    if args.dry_run and result.plan is not None:
        print(f"session_id={args.session_id}")
        print(f"clips={len(result.plan.clips)} font={result.plan.font_path}")
        for c in result.plan.clips:
            print(f"  {c.beat_id} trim={c.trim_start_sec:.3f}s dur={c.duration_sec:.3f}s · {c.headline[:60]}")
        # Per the flag's help text, emit the ffmpeg commands too — so an
        # operator can copy-paste them and debug a specific clip outside
        # the pipeline.
        intermediates = [
            result.plan.intermediates_dir / f"{i:03d}_{c.beat_id}.mp4"
            for i, c in enumerate(result.plan.clips)
        ]
        print("\n# pass 1 (normalise, one per clip):")
        for i, c in enumerate(result.plan.clips):
            cmd = build_normalize_command(c, plan=result.plan, out_path=intermediates[i])
            print("  " + " ".join(cmd))
        print("\n# pass 2 (chained xfade):")
        if intermediates:
            cmd = build_xfade_command(intermediates, plan=result.plan, out_path=result.plan.out_path)
            print("  " + " ".join(cmd))
        return

    if not result.ok:
        print(f"FAIL session_id={args.session_id}", file=sys.stderr)
        print(f"  error: {result.error}", file=sys.stderr)
        raise SystemExit(1)

    print(
        f"session_id={args.session_id}\n"
        f"out={result.out_path}\n"
        f"elapsed={int(result.elapsed_ms or 0)}ms"
        + (" · fallback=pairwise" if result.fallback_used else "")
    )


if __name__ == "__main__":
    main()
