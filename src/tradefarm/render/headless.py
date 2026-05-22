"""Headless renderer — drives the stream/ broadcast app via Playwright
to capture a per-beat video clip for the VOD pipeline.

Input:  out/sessions/<id>/manifest.json  +  out/sessions/<id>/beats.json
Output: out/sessions/<id>/clips/<beat_id>.webm  (+ <beat_id>.json sidecar)

Per beat we open a fresh Playwright BrowserContext (each context records
exactly one video for its lifetime), navigate to

    {stream_base}/?replay=<session>&at=<beat.t>
                  &scene=<beat.scene_hint>
                  &speed=<replay_speed>
                  &until=<beat.t + beat.duration_sec>

wait for the `data-scene-ready="true"` selector that SceneRotator
exposes, sleep for `beat.duration_sec`, then close the context — which
finalises the .webm to disk.

A sidecar JSON next to each clip carries the timing the stitcher
(Session 5) needs to trim the page-load preamble off the front:

    {
      "beat_id": "b_bigfill_3",
      "scene": "hero",
      "scene_ready_at_ms": 1820,
      "duration_ms": 30000,
      "viewport": [1920, 1080],
      "url": "http://localhost:5180/?replay=...&at=...&scene=hero",
      "captured_at": "2026-05-21T04:55:12+00:00"
    }

For v0 we skip the `recap` scene — its `/api/recap/today` endpoint
isn't replay-aware yet (it talks to the live orchestrator), so its
clip would render a mix of historical equity + live promotions /
predictions. Recap support lands in a follow-up alongside the recap
endpoint's `?session_id=&at=` params.

Stream server must be reachable at `--stream-base` (default
http://localhost:5180/) — start it with `cd stream && npm run dev`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from tradefarm.session import replay_query


DEFAULT_STREAM_BASE = "http://localhost:5180/"
DEFAULT_VIEWPORT = (1920, 1080)
DEFAULT_REPLAY_SPEED = 60.0
DEFAULT_SCENE_READY_TIMEOUT_MS = 15_000
# Seconds of additional sleep after `duration_sec` finishes — bigger
# than you'd think because Playwright's webm muxer can drop the last
# 1-2s on context.close(). Without enough margin, the trimmed
# intermediate ends up shorter than the stitcher's xfade math assumes.
TAIL_BUFFER_SEC = 2.0
# Wait this long for the WS handshake + first REST snapshot before
# giving up on a beat. Generous; most beats are ready in <3s.
DEFAULT_GOTO_TIMEOUT_MS = 30_000
SCENES_WITH_REPLAY_SUPPORT = frozenset(
    {"hero", "leaderboard", "brain", "showdown", "strategy", "decision-lab"}
)

# Per-kind defaults for the render. Mirror beats.py's DURATION_FOR_KIND
# and SCENE_FOR_KIND so the renderer + detector stay coherent.
DEFAULT_SCENE_BY_KIND: dict[str, str] = {
    "open": "hero",
    "big_fill": "hero",
    "divergence": "brain",
    "streak": "leaderboard",
    "top_winner": "hero",
    "top_loser": "hero",
    "closing_burst": "hero",
    "recap": "recap",
}


@dataclass
class RenderJob:
    """One unit of work for the renderer. Derived from a Beat plus the
    session context; stays serialisable so the caller can log / inspect."""

    beat_id: str
    kind: str
    scene: str
    at: str  # ISO timestamp
    until: str  # ISO timestamp
    duration_sec: float
    url: str
    out_path: Path
    sidecar_path: Path


@dataclass
class RenderResult:
    job: RenderJob
    ok: bool
    scene_ready_ms: float | None = None
    elapsed_ms: float | None = None
    error: str | None = None


@dataclass
class RenderSummary:
    session_id: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    clips_dir: Path
    results: list[RenderResult] = field(default_factory=list)


# ----- planning ------------------------------------------------------------


def _parse_iso(ts: str) -> datetime:
    return replay_query.parse_iso(ts)


def build_url(
    *,
    stream_base: str,
    session_id: str,
    at: str,
    until: str,
    scene: str,
    speed: float,
) -> str:
    """Construct the replay URL the renderer navigates to. Kept pure so
    tests can assert the contract without spinning up Chromium."""

    base = stream_base if stream_base.endswith("/") else stream_base + "/"
    qs = urlencode(
        {
            "replay": session_id,
            "at": at,
            "until": until,
            "scene": scene,
            "speed": str(speed),
        }
    )
    return f"{base}?{qs}"


def plan_jobs(
    *,
    session_id: str,
    beats: list[dict[str, Any]],
    clips_dir: Path,
    stream_base: str = DEFAULT_STREAM_BASE,
    speed: float = DEFAULT_REPLAY_SPEED,
    scene_overrides: dict[str, str] | None = None,
    skip_kinds: frozenset[str] | None = None,
    allow_scenes: frozenset[str] | None = None,
) -> tuple[list[RenderJob], list[str]]:
    """Translate a beats.json list into RenderJob records. Returns
    (jobs_to_render, skipped_beat_ids).

    A beat is skipped if its kind is in `skip_kinds` (default: just
    "recap" — its scene depends on /api/recap/today which isn't
    replay-aware yet) OR its scene isn't in `allow_scenes` (default:
    every scene we know has a replay-driven render path).
    """

    overrides = scene_overrides or {}
    skips = skip_kinds if skip_kinds is not None else frozenset({"recap"})
    allowed = allow_scenes if allow_scenes is not None else SCENES_WITH_REPLAY_SUPPORT

    jobs: list[RenderJob] = []
    skipped: list[str] = []
    for b in beats:
        beat_id = str(b.get("id") or "")
        if not beat_id:
            continue  # malformed entry — quietly drop rather than crash the run
        kind = str(b.get("kind") or "")
        scene = overrides.get(kind) or str(
            b.get("scene_hint") or DEFAULT_SCENE_BY_KIND.get(kind, "hero")
        )
        if kind in skips or scene not in allowed:
            skipped.append(beat_id)
            continue
        at_str = str(b["t"])
        duration_sec = float(b.get("duration_sec") or 12)
        until_dt = _parse_iso(at_str) + timedelta(seconds=duration_sec)
        until = until_dt.isoformat()
        url = build_url(
            stream_base=stream_base,
            session_id=session_id,
            at=at_str,
            until=until,
            scene=scene,
            speed=speed,
        )
        jobs.append(
            RenderJob(
                beat_id=beat_id,
                kind=kind,
                scene=scene,
                at=at_str,
                until=until,
                duration_sec=duration_sec,
                url=url,
                out_path=clips_dir / f"{beat_id}.webm",
                sidecar_path=clips_dir / f"{beat_id}.json",
            )
        )
    return jobs, skipped


# ----- rendering ----------------------------------------------------------


def _import_playwright():
    """Defer the playwright import so the rest of the module (planning,
    URL building, sidecar shape) stays usable without the `vod` extra
    installed — tests that don't actually drive Chromium import freely."""
    try:
        from playwright.async_api import async_playwright
    except ImportError as exc:  # pragma: no cover — environment-dependent
        raise RuntimeError(
            "playwright is not installed. Run `uv sync --extra vod` and "
            "`uv run playwright install chromium`."
        ) from exc
    return async_playwright


async def _render_one(
    pw_browser: Any,
    job: RenderJob,
    *,
    viewport: tuple[int, int],
    scene_ready_timeout_ms: int,
    goto_timeout_ms: int,
) -> RenderResult:
    """Open one context, capture one clip, close, write sidecar.

    Any exception is captured and reported on RenderResult — we never
    let a single bad beat abort the loop.
    """

    job.out_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    width, height = viewport

    # Wrap context creation too — a Chromium crash here used to abort
    # the whole session.
    try:
        context = await pw_browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            record_video_dir=str(job.out_path.parent),
            record_video_size={"width": width, "height": height},
        )
    except Exception as exc:  # noqa: BLE001
        return RenderResult(
            job=job,
            ok=False,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=f"new_context failed: {type(exc).__name__}: {exc}",
        )

    page = await context.new_page()
    # Capture page-side errors so an opaque selector timeout doesn't
    # hide a React crash. Attached before navigation.
    page_errors: list[str] = []
    page.on("pageerror", lambda e: page_errors.append(f"pageerror: {e}"))
    page.on(
        "requestfailed",
        lambda req: page_errors.append(f"requestfailed: {req.method} {req.url} ({req.failure})"),
    )

    video = page.video  # handle is valid pre-close; .path() is post-close only

    nav_started = time.perf_counter()
    try:
        await page.goto(
            job.url,
            wait_until="domcontentloaded",
            timeout=goto_timeout_ms,
        )
        await page.wait_for_selector(
            '[data-scene-ready="true"]',
            timeout=scene_ready_timeout_ms,
        )
        # Measured from navigation start (not context creation) so the
        # stitcher's trim point matches what was actually on screen.
        scene_ready_ms = (time.perf_counter() - nav_started) * 1000
        # Hold the scene for the requested duration plus tail-buffer.
        # Playwright's video recorder routinely loses the last 1-2s on
        # `context.close()` codec flush, so we need real margin —
        # the previous 0.25s wasn't enough and short beats came out
        # shorter than `duration_sec`, breaking stitcher xfade math.
        await asyncio.sleep(job.duration_sec + TAIL_BUFFER_SEC)
    except asyncio.CancelledError:
        # Operator hit Ctrl-C. Tear down the context and re-raise so the
        # outer loop's bare `except Exception` doesn't swallow this and
        # keep rendering — was a real footgun.
        try:
            await context.close()
        except Exception:
            pass
        raise
    except Exception as exc:  # noqa: BLE001
        # Don't let context.close() in cleanup swallow the original error.
        try:
            await context.close()
        except Exception:
            pass
        err = f"{type(exc).__name__}: {exc}"
        if page_errors:
            err += " · " + " ; ".join(page_errors[:3])
        return RenderResult(
            job=job,
            ok=False,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=err,
        )

    try:
        await context.close()  # finalises the .webm to record_video_dir
    except Exception as exc:  # noqa: BLE001
        return RenderResult(
            job=job,
            ok=False,
            scene_ready_ms=scene_ready_ms,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=f"context.close() failed: {type(exc).__name__}: {exc}",
        )
    elapsed_ms = (time.perf_counter() - started) * 1000

    # Playwright auto-names the file; rename to <beat_id>.webm so the
    # stitcher can find it by id alone. shutil.move so cross-volume
    # renames (e.g. out/ as a junction on Windows) don't OSError.
    final_path: Path | None = None
    try:
        raw = Path(await video.path())
        if raw.exists():
            if job.out_path.exists():
                job.out_path.unlink()
            shutil.move(str(raw), str(job.out_path))
            final_path = job.out_path
    except Exception as exc:  # noqa: BLE001
        return RenderResult(
            job=job,
            ok=False,
            scene_ready_ms=scene_ready_ms,
            elapsed_ms=elapsed_ms,
            error=f"video.path() failed: {exc}",
        )

    if final_path is None or not final_path.exists():
        return RenderResult(
            job=job,
            ok=False,
            scene_ready_ms=scene_ready_ms,
            elapsed_ms=elapsed_ms,
            error="webm not produced",
        )

    sidecar = {
        "beat_id": job.beat_id,
        "kind": job.kind,
        "scene": job.scene,
        "at": job.at,
        "until": job.until,
        "duration_ms": int(job.duration_sec * 1000),
        "scene_ready_at_ms": int(scene_ready_ms),
        "elapsed_ms": int(elapsed_ms),
        "viewport": list(viewport),
        "url": job.url,
        "clip": final_path.name,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    job.sidecar_path.write_text(json.dumps(sidecar, indent=2), encoding="utf-8")

    return RenderResult(
        job=job,
        ok=True,
        scene_ready_ms=scene_ready_ms,
        elapsed_ms=elapsed_ms,
    )


def _purge_stale_clips(clips_dir: Path, planned_beat_ids: set[str]) -> None:
    """Drop .webm + .json files in clips/ whose beat ids aren't in the
    current plan. Stops the stitcher from picking up clips from a prior
    run whose beat detector emitted a different set."""
    if not clips_dir.is_dir():
        return
    for child in clips_dir.iterdir():
        if child.suffix not in (".webm", ".json"):
            continue
        if child.stem not in planned_beat_ids:
            try:
                child.unlink()
            except OSError:
                pass


async def render_session(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    stream_base: str = DEFAULT_STREAM_BASE,
    speed: float = DEFAULT_REPLAY_SPEED,
    viewport: tuple[int, int] = DEFAULT_VIEWPORT,
    scene_ready_timeout_ms: int = DEFAULT_SCENE_READY_TIMEOUT_MS,
    goto_timeout_ms: int = DEFAULT_GOTO_TIMEOUT_MS,
    only_beat_ids: list[str] | None = None,
    skip_kinds: frozenset[str] | None = None,
    allow_scenes: frozenset[str] | None = None,
    purge_stale: bool = True,
) -> RenderSummary:
    """Top-level entrypoint. Loads beats.json + manifest, renders each
    job sequentially, returns a summary. Skipped beats are recorded
    but don't count as failures."""

    # Reject path-traversal-shaped session_ids at the CLI boundary too —
    # the REST + WS entrypoints already guard, but the renderer was
    # creating directories from `out/sessions/<session_id>/clips/` and
    # would mkdir anywhere a malicious id pointed.
    replay_query._require_safe_session_id(session_id)
    base = sessions_dir or replay_query.DEFAULT_SESSIONS_DIR
    beats_path = base / session_id / "beats.json"
    if not beats_path.is_file():
        raise FileNotFoundError(f"beats.json not found: {beats_path}")
    beats_all = json.loads(beats_path.read_text(encoding="utf-8"))
    if only_beat_ids:
        beat_id_set = set(only_beat_ids)
        beats_all = [b for b in beats_all if b.get("id") in beat_id_set]

    clips_dir = base / session_id / "clips"
    clips_dir.mkdir(parents=True, exist_ok=True)

    jobs, skipped = plan_jobs(
        session_id=session_id,
        beats=beats_all,
        clips_dir=clips_dir,
        stream_base=stream_base,
        speed=speed,
        skip_kinds=skip_kinds,
        allow_scenes=allow_scenes,
    )

    if purge_stale:
        # Keep clips for jobs we're about to render (they'll be
        # overwritten) plus skipped ids (operator may want them).
        keep = {j.beat_id for j in jobs} | set(skipped)
        _purge_stale_clips(clips_dir, keep)

    results: list[RenderResult] = []
    if not jobs:
        return RenderSummary(
            session_id=session_id,
            total=len(jobs) + len(skipped),
            succeeded=0,
            failed=0,
            skipped=len(skipped),
            clips_dir=clips_dir,
            results=results,
        )

    async_playwright = _import_playwright()
    async with async_playwright() as p:
        pw_browser = await p.chromium.launch(headless=True)
        try:
            for job in jobs:
                # _render_one already catches its own exceptions, but
                # belt-and-braces here so an unexpected await raise
                # can't take the loop down.
                try:
                    res = await _render_one(
                        pw_browser,
                        job,
                        viewport=viewport,
                        scene_ready_timeout_ms=scene_ready_timeout_ms,
                        goto_timeout_ms=goto_timeout_ms,
                    )
                except asyncio.CancelledError:
                    # Propagate Ctrl-C / task cancellation. Otherwise the
                    # bare except below ate it and the loop kept running.
                    raise
                except Exception as exc:  # noqa: BLE001
                    res = RenderResult(
                        job=job,
                        ok=False,
                        error=f"loop-level exception: {type(exc).__name__}: {exc}",
                    )
                results.append(res)
        finally:
            await pw_browser.close()

    succeeded = sum(1 for r in results if r.ok)
    failed = sum(1 for r in results if not r.ok)
    return RenderSummary(
        session_id=session_id,
        total=len(jobs) + len(skipped),
        succeeded=succeeded,
        failed=failed,
        skipped=len(skipped),
        clips_dir=clips_dir,
        results=results,
    )


# ----- CLI ----------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    """`python -m tradefarm.render.headless <session_id>` reads
    out/sessions/<id>/beats.json + manifest.json, drives Playwright,
    writes per-beat clips + sidecars to out/sessions/<id>/clips/."""

    parser = argparse.ArgumentParser(
        prog="tradefarm.render.headless",
        description="Render per-beat video clips from a session manifest.",
    )
    parser.add_argument("session_id", help="Session id (matches out/sessions/<session_id>/).")
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--stream-base",
        default=DEFAULT_STREAM_BASE,
        help="Base URL of the running stream/ Vite dev server (default: http://localhost:5180/).",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=DEFAULT_REPLAY_SPEED,
        help="WS replay speed multiplier (default: 60x).",
    )
    parser.add_argument(
        "--beat",
        action="append",
        help="Render only the named beat id(s). Repeat for multiple.",
    )
    parser.add_argument(
        "--include-recap",
        action="store_true",
        help="Render recap beats too. Off by default — /api/recap/today "
        "isn't replay-aware yet so the clip will mix live data.",
    )
    parser.add_argument(
        "--viewport",
        default="1920x1080",
        help="WIDTHxHEIGHT, default 1920x1080.",
    )
    parser.add_argument(
        "--scene-ready-timeout",
        type=int,
        default=DEFAULT_SCENE_READY_TIMEOUT_MS,
        help="Milliseconds to wait for data-scene-ready=true.",
    )
    parser.add_argument(
        "--goto-timeout",
        type=int,
        default=DEFAULT_GOTO_TIMEOUT_MS,
        help="Milliseconds to wait for page navigation.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned jobs (with URLs) without launching Chromium.",
    )
    parser.add_argument(
        "--keep-stale",
        action="store_true",
        help="Don't purge .webm/.json from a prior run whose beats are gone.",
    )
    args = parser.parse_args(argv)

    try:
        w_str, h_str = args.viewport.lower().split("x", 1)
        viewport = (int(w_str), int(h_str))
    except (ValueError, AttributeError) as exc:
        raise SystemExit(f"bad --viewport {args.viewport!r} (want WIDTHxHEIGHT)") from exc

    if args.include_recap:
        skip: frozenset[str] = frozenset()
        allow: frozenset[str] | None = SCENES_WITH_REPLAY_SUPPORT | {"recap"}
    else:
        skip = frozenset({"recap"})
        allow = None

    if args.dry_run:
        beats_path = args.out / args.session_id / "beats.json"
        if not beats_path.is_file():
            raise SystemExit(f"beats.json not found: {beats_path}")
        beats = json.loads(beats_path.read_text(encoding="utf-8"))
        if args.beat:
            beats = [b for b in beats if b.get("id") in set(args.beat)]
        clips_dir = args.out / args.session_id / "clips"
        jobs, skipped = plan_jobs(
            session_id=args.session_id,
            beats=beats,
            clips_dir=clips_dir,
            stream_base=args.stream_base,
            speed=args.speed,
            skip_kinds=skip,
            allow_scenes=allow,
        )
        print(f"would render {len(jobs)} jobs · skip {len(skipped)}")
        for j in jobs:
            print(f"  {j.beat_id} {j.scene} {j.url}")
        for sid in skipped:
            print(f"  SKIP {sid}")
        return

    summary = asyncio.run(
        render_session(
            args.session_id,
            sessions_dir=args.out,
            stream_base=args.stream_base,
            speed=args.speed,
            viewport=viewport,
            scene_ready_timeout_ms=args.scene_ready_timeout,
            goto_timeout_ms=args.goto_timeout,
            only_beat_ids=args.beat,
            skip_kinds=skip,
            allow_scenes=allow,
            purge_stale=not args.keep_stale,
        )
    )
    print(
        f"session_id={summary.session_id}\n"
        f"clips_dir={summary.clips_dir}\n"
        f"total={summary.total} succeeded={summary.succeeded} "
        f"failed={summary.failed} skipped={summary.skipped}"
    )
    # ASCII OK/FAIL — Unicode glyphs raise UnicodeEncodeError under the
    # default Windows console code page (cp1252).
    for r in summary.results:
        if r.ok:
            print(f"  OK   {r.job.beat_id} · {r.job.scene} · {int(r.elapsed_ms or 0)}ms")
        else:
            print(f"  FAIL {r.job.beat_id} · {r.job.scene} · {r.error}")
    if summary.failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()


# Re-export RenderJob fields as a plain dict for easy logging / testing.
def render_job_as_dict(job: RenderJob) -> dict[str, Any]:
    out = asdict(job)
    out["out_path"] = str(job.out_path)
    out["sidecar_path"] = str(job.sidecar_path)
    return out
