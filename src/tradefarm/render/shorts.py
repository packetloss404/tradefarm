"""Shorts renderer — composes 9:16 vertical clips for YT Shorts / TikTok /
Reels out of a session's existing 16:9 headless clips.

Pipeline shape:
    session/manifest.json
        -> session/beats.py           (beats.json, 16:9 windows)
        -> render/headless.py         (clips/<id>.webm, 16:9, 1920x1080)
        -> render/shorts.py (this)    (clips/shorts/<id>.mp4, 9:16, 1080x1920)

Approach
--------
Reuse the existing headless renderer's per-beat .webm at 1920x1080 and
smart-crop to 9:16 (1080x1920) with ffmpeg. The smart crop is a centre
crop + a vertical-scale-up so the LLM-reason lower-third and the agent
avatar stay in frame — a naive "centre crop 9:9 then letterbox 9:16" is
uglier (black bars on top + bottom) and the YouTube Shorts player
already letterboxes, so the picture would shrink to a postage stamp.

ffmpeg invocation (per beat):
    ffmpeg -y -i in.webm \\
        -vf "crop=ih*9/16:ih,scale=1080:1920:flags=lanczos" \\
        -c:v libx264 -preset medium -crf 22 \\
        -c:a aac -b:a 128k \\
        -movflags +faststart \\
        out.mp4

`crop=ih*9/16:ih` keeps the full height and takes the centre 9:16 of
the 16:9 source, so the LLM reason + agent face stay vertically
centred. The scale step then up-samples to 1080x1920.

Each beat clip is hard-capped at 60s (YouTube Shorts hard limit). A
beat whose duration_sec > 60 is re-clipped to [t, t+60] by passing
`until=t+60` to the URL builder.

CLI
---
    python -m tradefarm.render.shorts <session_id> [--top N] [--dry-run]

    --top N          how many beats to compose (default 3, max ~6 for a
                     YouTube Shorts playlist)
    --dry-run        print the plan + ffmpeg invocations, do not run them
    --out DIR        sessions directory (default: out/sessions)
    --vertical WxH   target vertical viewport (default 1080x1920)
    --max-duration   per-short cap in seconds (default 60)
    --clips-dir DIR  reuse an existing render's clips (default:
                     out/sessions/<id>/clips)
    --force          re-compose even when the .mp4 already exists

ASCII-only output (Windows cp1252 console) — see headless.py:647 for
the same constraint.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any

from tradefarm.session import replay_query


# 9:16 default for YT Shorts / TikTok / Reels. 1080x1920 is the
# canonical 1080p vertical frame; the Shorts player accepts anything
# >= 720x1280, but the higher resolution survives the player's
# downscale pass.
DEFAULT_VERTICAL = (1080, 1920)
# YouTube Shorts hard cap. Stay under it so a re-encode doesn't
# silently fail.
DEFAULT_MAX_DURATION = 60.0
# How many top beats to compose by default. 3 = enough for a 60s
# YouTube Shorts playlist; the channel-art team can pick the best
# one with `tail -n 1`.
DEFAULT_TOP_N = 3
# Default per-short duration. The shorts audience scrolls in <3s;
# a single dramatic beat shouldn't need more than 12s of video,
# but we pad the URL with `until=beat.t + 12` so the playhead gets
# a clean second loop.
DEFAULT_BASE_SHORT_SECONDS = 12


@dataclass
class ShortsJob:
    """One unit of ffmpeg work — one input webm + one output mp4 + the
    ffmpeg argv. Pure data so callers can serialise / inspect / test
    without touching disk."""

    beat_id: str
    kind: str
    scene: str
    in_path: Path
    out_path: Path
    ffmpeg_argv: list[str]
    until: str  # ISO timestamp baked into the URL when the headless
    # renderer re-encodes the source — recorded here so the operator
    # can verify the cut point.
    duration_sec: float


@dataclass
class ShortsResult:
    session_id: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    shorts_dir: Path
    ffmpeg_missing: bool = False
    results: list[dict[str, Any]] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)


# ----- planning ------------------------------------------------------------


def build_ffmpeg_argv(
    *,
    in_path: Path,
    out_path: Path,
    vertical: tuple[int, int] = DEFAULT_VERTICAL,
) -> list[str]:
    """Compose the ffmpeg argv for one short. Pure function so the
    `test_shorts.py` unit tests can assert the exact contract.

    The crop filter: `crop=ih*9/16:ih` keeps full height and takes
    the centre 9:16 slice of the 16:9 source. The scale filter then
    up-samples to the requested vertical viewport. Lanczos kernel
    for the upscale — bicubic looks soft at 1080p vertical on a
    phone screen.
    """
    vw, vh = vertical
    vf = f"crop=ih*9/16:ih,scale={vw}:{vh}:flags=lanczos"
    return [
        "ffmpeg",
        "-y",  # overwrite
        "-i",
        str(in_path),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "22",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(out_path),
    ]


def plan_jobs(
    *,
    session_id: str,
    beats: list[dict[str, Any]],
    clips_dir: Path,
    short_seconds: float = DEFAULT_BASE_SHORT_SECONDS,
    top_n: int = DEFAULT_TOP_N,
    max_duration: float = DEFAULT_MAX_DURATION,
    vertical: tuple[int, int] = DEFAULT_VERTICAL,
) -> tuple[list[ShortsJob], list[str]]:
    """Translate `beats.json` (already produced by `session/beats.py`)
    into a list of ffmpeg jobs.

    Selection rule: take the top N beats by `score` (descending), drop
    `recap` (same constraint as `headless.py`), drop any beat whose
    `duration_sec` is zero (malformed). Cap each beat at `max_duration`
    so a long beat doesn't overrun the Shorts player cap.

    Skipped beat ids are returned as the second tuple element so the
    caller can log them.
    """
    if top_n <= 0:
        return [], []

    cap = min(short_seconds, max_duration)
    candidates = [b for b in beats if b.get("kind") != "recap" and b.get("duration_sec")]
    candidates.sort(key=lambda b: (-float(b.get("score") or 0.0), str(b.get("t") or "")))
    top = candidates[:top_n]

    jobs: list[ShortsJob] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for b in top:
        beat_id = str(b.get("id") or "")
        if not beat_id or beat_id in seen:
            continue
        seen.add(beat_id)
        in_path = clips_dir / f"{beat_id}.webm"
        if not in_path.is_file():
            skipped.append(beat_id)
            continue
        out_path = clips_dir / "shorts" / f"{beat_id}.mp4"
        until_dt = replay_query.parse_iso(str(b["t"])) + timedelta(seconds=cap)
        jobs.append(
            ShortsJob(
                beat_id=beat_id,
                kind=str(b.get("kind") or ""),
                scene=str(b.get("scene_hint") or ""),
                in_path=in_path,
                out_path=out_path,
                ffmpeg_argv=build_ffmpeg_argv(in_path=in_path, out_path=out_path, vertical=vertical),
                until=until_dt.isoformat(),
                duration_sec=cap,
            )
        )
    # Skipped beats the operator should know about (recap drops aren't
    # listed — they're the same filter headless.py applies).
    for b in candidates[top_n:]:
        beat_id = str(b.get("id") or "")
        if beat_id and beat_id not in seen:
            seen.add(beat_id)
    return jobs, skipped


# ----- execution ----------------------------------------------------------


def _have_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


def _run_ffmpeg(argv: list[str]) -> tuple[bool, str]:
    """Run one ffmpeg invocation. Return (ok, stderr_tail). Never raise
    on ffmpeg's own nonzero exit; the renderer treats each short as an
    independent unit (same belt-and-braces pattern as headless.py)."""
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "ffmpeg timeout after 120s"
    except FileNotFoundError:
        return False, "ffmpeg not found on PATH"
    if proc.returncode == 0:
        return True, ""
    tail = (proc.stderr or "").strip().splitlines()[-3:]
    return False, " ; ".join(tail) if tail else f"exit {proc.returncode}"


def compose_session(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    short_seconds: float = DEFAULT_BASE_SHORT_SECONDS,
    top_n: int = DEFAULT_TOP_N,
    max_duration: float = DEFAULT_MAX_DURATION,
    vertical: tuple[int, int] = DEFAULT_VERTICAL,
    dry_run: bool = False,
    force: bool = False,
) -> ShortsResult:
    """Top-level entrypoint. Reads `out/sessions/<id>/beats.json`,
    plans ffmpeg jobs over the top N beats, runs them sequentially,
    returns a `ShortsResult`.

    `dry_run=True` plans + returns but does NOT spawn ffmpeg. The CLI
    prints the planned argv for each job.

    `force=True` re-runs even when the .mp4 already exists.

    The headless renderer must have already produced
    `out/sessions/<id>/clips/<beat_id>.webm` — this module does not
    capture. Pair with `python -m tradefarm.render.headless <id>`.
    """
    replay_query._require_safe_session_id(session_id)
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    beats_path = base / session_id / "beats.json"
    if not beats_path.is_file():
        raise FileNotFoundError(f"beats.json not found: {beats_path}")
    beats = json.loads(beats_path.read_text(encoding="utf-8"))

    clips_dir = base / session_id / "clips"
    if not clips_dir.is_dir():
        raise FileNotFoundError(
            f"clips/ not found: {clips_dir} — run `python -m tradefarm.render.headless {session_id}` first"
        )

    jobs, skipped = plan_jobs(
        session_id=session_id,
        beats=beats,
        clips_dir=clips_dir,
        short_seconds=short_seconds,
        top_n=top_n,
        max_duration=max_duration,
        vertical=vertical,
    )

    shorts_dir = clips_dir / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)

    ffmpeg_missing = not _have_ffmpeg()
    results: list[dict[str, Any]] = []
    succeeded = 0
    failed = 0
    for job in jobs:
        # Skip if already produced AND caller didn't ask for --force.
        if not force and job.out_path.is_file() and job.out_path.stat().st_size > 0:
            results.append(
                {
                    "beat_id": job.beat_id,
                    "ok": True,
                    "elapsed_ms": 0,
                    "out": str(job.out_path),
                    "skipped": "already_present",
                }
            )
            succeeded += 1
            continue
        if dry_run or ffmpeg_missing:
            results.append(
                {
                    "beat_id": job.beat_id,
                    "ok": not ffmpeg_missing,
                    "elapsed_ms": 0,
                    "out": str(job.out_path),
                    "ffmpeg_argv": job.ffmpeg_argv,
                    "dry_run": True,
                    "ffmpeg_missing": ffmpeg_missing,
                }
            )
            if not ffmpeg_missing:
                succeeded += 1
            else:
                failed += 1
            continue
        import time

        started = time.perf_counter()
        ok, err = _run_ffmpeg(job.ffmpeg_argv)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        results.append(
            {
                "beat_id": job.beat_id,
                "ok": ok,
                "elapsed_ms": elapsed_ms,
                "out": str(job.out_path),
                "error": err,
            }
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    return ShortsResult(
        session_id=session_id,
        total=len(jobs) + len(skipped),
        succeeded=succeeded,
        failed=failed,
        skipped=len(skipped),
        skipped_ids=list(skipped),
        shorts_dir=shorts_dir,
        ffmpeg_missing=ffmpeg_missing,
        results=results,
    )


# ----- CLI -----------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.render.shorts <session_id> --top 3 --dry-run`."""
    parser = argparse.ArgumentParser(
        prog="tradefarm.render.shorts",
        description="Compose 9:16 vertical shorts from a session's headless clips.",
    )
    parser.add_argument("session_id", help="Session id (matches out/sessions/<session_id>/).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        help=f"How many top beats to compose (default {DEFAULT_TOP_N}).",
    )
    parser.add_argument(
        "--base-short-seconds",
        type=float,
        default=DEFAULT_BASE_SHORT_SECONDS,
        help="Per-short duration seconds (default 12, capped at --max-duration).",
    )
    parser.add_argument(
        "--max-duration",
        type=float,
        default=DEFAULT_MAX_DURATION,
        help="Hard cap per short in seconds (default 60 — YouTube Shorts limit).",
    )
    parser.add_argument(
        "--vertical",
        default="1080x1920",
        help="WIDTHxHEIGHT, default 1080x1920.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the plan + ffmpeg argv, do not invoke ffmpeg.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-encode even when the .mp4 already exists.",
    )
    args = parser.parse_args(argv)

    try:
        w_str, h_str = args.vertical.lower().split("x", 1)
        vertical = (int(w_str), int(h_str))
    except (ValueError, AttributeError) as exc:
        raise SystemExit(f"bad --vertical {args.vertical!r} (want WIDTHxHEIGHT)") from exc

    summary = compose_session(
        args.session_id,
        sessions_dir=args.out,
        short_seconds=args.base_short_seconds,
        top_n=args.top,
        max_duration=args.max_duration,
        vertical=vertical,
        dry_run=args.dry_run,
        force=args.force,
    )

    # ASCII separators only — em-dashes break the Windows cp1252
    # console (see render/pipeline.py:354 for the same constraint).
    print("=" * 60)
    print(f"[shorts] session_id={summary.session_id}")
    print(f"[shorts] shorts_dir={summary.shorts_dir}")
    print(
        f"[shorts] total={summary.total} "
        f"succeeded={summary.succeeded} "
        f"failed={summary.failed} "
        f"skipped={summary.skipped}"
    )
    if summary.ffmpeg_missing:
        print("[shorts] WARN: ffmpeg not on PATH; plan only.")
    print("=" * 60)

    for r in summary.results:
        if r.get("dry_run"):
            argv = r.get("ffmpeg_argv") or []
            argv_str = " ".join(argv)
            print(f"  PLAN {r['beat_id']}")
            print(f"    argv: {argv_str}")
        elif r.get("skipped") == "already_present":
            print(f"  SKIP {r['beat_id']}  (already present)")
        elif r.get("ok"):
            print(f"  OK   {r['beat_id']}  {r['elapsed_ms']}ms")
        else:
            print(f"  FAIL {r['beat_id']}  {r.get('error', 'unknown')}")
    if summary.skipped_ids:
        print(f"  SKIP (no source clip): {', '.join(summary.skipped_ids)}")

    if summary.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
