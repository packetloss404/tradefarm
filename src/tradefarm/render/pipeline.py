"""One-shot VOD pipeline runner — chains the eight steps from manifest
to published episode behind a single CLI with skip/force controls and
structured progress.

The VOD chain lives in eight separate CLIs that each take a session id
and do one job:
    1. session.run       replay the orchestrator for a date range -> manifest.json
    2. session.beats     score dramatic moments in the manifest -> beats.json
    3. render.headless   Playwright captures one .webm per beat -> clips/
    4. render.stitch     ffmpeg concatenates the clips -> silent_reel.mp4
    5. tts.run           synthesise per-line VO wavs -> vo/
    6. render.mix        combine silent_reel + VOs + music -> reel.mp4
    7. yt.metadata       build episode.yaml from the artifacts
    8. yt.upload         POST reel.mp4 + thumbnail to YouTube

Each one is already shipped and tested in isolation. The pipeline
runner just sequences them, surfaces a single progress stream, and
short-circuits on the first failure with a clear "which step, which
args" message. It is the operator-facing surface — the existing eight
CLIs stay available for hand-driven debugging.

Usage
-----

Run a date's worth of simulation through the full chain (skipping TTS
+ upload by default since they need external creds):

    python -m tradefarm.render.pipeline --date 2026-08-04

Resume a previously-saved session at the render step:

    python -m tradefarm.render.pipeline --session-id s_2026-08-04_abc123

Include the optional steps (TTS + upload) explicitly:

    python -m tradefarm.render.pipeline --date 2026-08-04 \\
        --include-tts --include-upload --dry-run-upload

Just print the plan, don't actually invoke anything:

    python -m tradefarm.render.pipeline --date 2026-08-04 --dry-run

The runner is idempotent: a step whose expected output already exists
is skipped (use ``--force`` to re-run).
"""

from __future__ import annotations

import argparse
import io
import sys
import uuid
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Sequence

# Each step module exposes a `main(argv: list[str] | None = None) -> None`
# that does its CLI work. We call these in-process with constructed argv
# lists — no subprocess overhead, no need to reparse flags, and we get
# structured access to SystemExit / exceptions raised by the inner CLI.
from tradefarm.render import headless as render_headless
from tradefarm.render import mix as render_mix
from tradefarm.render import stitch as render_stitch
from tradefarm.session import beats as session_beats
from tradefarm.session import run as session_run
from tradefarm.tts import run as tts_run
from tradefarm.yt import metadata as yt_metadata
from tradefarm.yt import upload as yt_upload


# ----- step registry ---------------------------------------------------------


@dataclass(frozen=True)
class Step:
    """One link in the chain. ``label`` is what we print; ``enabled``
    flips between required-by-default and opt-in; ``outputs`` are the
    files whose existence means the step is done; ``run`` is the
    callable that actually invokes the inner module's ``main(argv)``.
    """

    key: str
    label: str
    module: str  # full dotted path used in the printed banner
    enabled_by_default: bool
    outputs: tuple[Path, ...]
    # The callable receives (session_id, sessions_dir) and the runner's
    # extra CLI options; it should return argv to pass to the inner
    # module's main(). Returning an empty list means "skip this step
    # even when enabled" — the runner does not invoke main in that case.
    build_argv: Callable[[str, Path, "PipelineOpts"], list[str]]
    # ``run`` is a thin wrapper that invokes the inner module's main().
    # We keep it as a field (rather than dispatching through a shared
    # dict) so tests can monkeypatch a single step in isolation.
    run: Callable[[list[str]], None]


# Inner ``main`` functions wrapped as callables so each Step can hold
# one. Built at module load so the import cost is paid once.
#
# Note: session.run's main() is parameter-less (it calls parse_args()
# directly with no argv), while every other module accepts an
# optional argv list. We keep the call signatures uniform here for
# the runner's sake; the wrappers translate.
def _run_session(argv: list[str]) -> None:
    # session.run's argparse reads sys.argv. Push our argv onto it for
    # the duration of the call so the run takes the flags the runner
    # chose.
    import sys as _sys
    saved = _sys.argv
    _sys.argv = [str(_sys.argv[0])] + argv
    try:
        session_run.main()
    finally:
        _sys.argv = saved
def _run_beats(argv: list[str]) -> None: session_beats.main(argv)
def _run_headless(argv: list[str]) -> None: render_headless.main(argv)
def _run_stitch(argv: list[str]) -> None: render_stitch.main(argv)
def _run_tts(argv: list[str]) -> None: tts_run.main(argv)
def _run_mix(argv: list[str]) -> None: render_mix.main(argv)
def _run_metadata(argv: list[str]) -> None: yt_metadata.main(argv)
def _run_upload(argv: list[str]) -> None: yt_upload.main(argv)


@dataclass
class PipelineOpts:
    """Resolved CLI options — what each step's build_argv reads."""

    sessions_dir: Path
    music: Path | None
    tts_provider: str
    tts_voice: str
    upload_dry_run: bool
    stitch_xfade: float
    force: bool


def _build_session_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    # session.run needs either --date or --date-range. The pipeline
    # passes --session-id and expects the runner CLI to also have
    # already generated a session_id; we reconstruct the same
    # pattern. We pass --out so the manifest lands in the configured
    # sessions dir even when the user pointed the runner elsewhere.
    return [
        "--session-id",
        session_id,
        "--out",
        str(sessions_dir),
    ]


def _build_beats_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    return [session_id, "--out", str(sessions_dir)]


def _build_headless_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    # headless needs a running stream Vite at :5180 to capture scenes.
    # --dry-run prints the planned jobs without launching Chromium, so
    # the pipeline can sequence past it on a host with no scene
    # server. Operators who want real clips pass --no-headless-dry-run
    # via the headless CLI directly.
    return [session_id, "--out", str(sessions_dir), "--dry-run"]


def _build_stitch_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    return [
        session_id,
        "--out",
        str(sessions_dir),
        "--xfade",
        str(opts.stitch_xfade),
    ]


def _build_tts_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    return [
        session_id,
        "--out",
        str(sessions_dir),
        "--provider",
        opts.tts_provider,
        "--voice",
        opts.tts_voice,
    ]


def _build_mix_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    argv = [
        session_id,
        "--out",
        str(sessions_dir),
        "--xfade",
        str(opts.stitch_xfade),
    ]
    if opts.music is not None:
        argv += ["--music", str(opts.music)]
    return argv


def _build_metadata_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    return [
        session_id,
        "--out",
        str(sessions_dir),
        "--xfade",
        str(opts.stitch_xfade),
    ]


def _build_upload_argv(session_id: str, sessions_dir: Path, opts: PipelineOpts) -> list[str]:
    argv = [session_id, "--out", str(sessions_dir)]
    if opts.upload_dry_run:
        argv.append("--dry-run")
    return argv


# The order matters: each step consumes the previous step's output.
STEPS: tuple[Step, ...] = (
    Step(
        key="session",
        label="session.run  (replay -> manifest.json)",
        module="tradefarm.session.run",
        enabled_by_default=True,
        outputs=(),  # session_id is the only "output"; skip is decided on presence
        build_argv=_build_session_argv,
        run=_run_session,
    ),
    Step(
        key="beats",
        label="session.beats  (manifest -> beats.json)",
        module="tradefarm.session.beats",
        enabled_by_default=True,
        outputs=(),  # checked separately
        build_argv=_build_beats_argv,
        run=_run_beats,
    ),
    Step(
        key="headless",
        label="render.headless  (beats -> clips/*.webm)",
        module="tradefarm.render.headless",
        enabled_by_default=True,
        outputs=(),  # variable; we just check clips/ dir
        build_argv=_build_headless_argv,
        run=_run_headless,
    ),
    Step(
        key="stitch",
        label="render.stitch  (clips -> silent_reel.mp4)",
        module="tradefarm.render.stitch",
        enabled_by_default=True,
        outputs=(),  # checked separately
        build_argv=_build_stitch_argv,
        run=_run_stitch,
    ),
    Step(
        key="tts",
        label="tts.run  (script -> vo/*.wav)",
        module="tradefarm.tts.run",
        enabled_by_default=False,  # needs TTS provider creds
        outputs=(),
        build_argv=_build_tts_argv,
        run=_run_tts,
    ),
    Step(
        key="mix",
        label="render.mix  (silent_reel + vo + music -> reel.mp4)",
        module="tradefarm.render.mix",
        enabled_by_default=True,
        outputs=(),
        build_argv=_build_mix_argv,
        run=_run_mix,
    ),
    Step(
        key="metadata",
        label="yt.metadata  (reel -> episode.yaml)",
        module="tradefarm.yt.metadata",
        enabled_by_default=True,
        outputs=(),
        build_argv=_build_metadata_argv,
        run=_run_metadata,
    ),
    Step(
        key="upload",
        label="yt.upload  (reel + episode.yaml -> YouTube)",
        module="tradefarm.yt.upload",
        enabled_by_default=False,  # needs YT creds; --dry-run-upload is the default if enabled
        outputs=(),
        build_argv=_build_upload_argv,
        run=_run_upload,
    ),
)


# ----- per-step output / presence checks ------------------------------------


def _sdir(opts: PipelineOpts, session_id: str) -> Path:
    return opts.sessions_dir / session_id


def _outputs_for(step: Step, session_id: str, opts: PipelineOpts) -> tuple[Path, ...]:
    """Files that, when present, mean the step already succeeded."""
    s = _sdir(opts, session_id)
    if step.key == "session":
        return (s / "manifest.json",)
    if step.key == "beats":
        return (s / "beats.json",)
    if step.key == "headless":
        # At minimum: beats.json must exist + at least one .webm in clips/.
        # Returning a tuple of "must exist" markers rather than enumerating
        # every clip. The runner skips the step if ALL of these hold.
        return (s / "beats.json",)  # just need the input; we still re-run headless
    if step.key == "stitch":
        return (s / "silent_reel.mp4",)
    if step.key == "tts":
        # tts may legitimately produce nothing (script has no lines).
        # We treat the step as "done" if vo/ exists.
        return (s / "vo",)
    if step.key == "mix":
        return (s / "reel.mp4",)
    if step.key == "metadata":
        return (s / "episode.yaml",)
    if step.key == "upload":
        return (s / "upload_response.json",)  # written by yt.upload in dry-run
    return ()


def _has_outputs(step: Step, session_id: str, opts: PipelineOpts) -> bool:
    s = _sdir(opts, session_id)
    if step.key == "headless":
        # Special case: at least one .webm in clips/ means render is done.
        clips = s / "clips"
        if not clips.is_dir():
            return False
        return any(clips.glob("*.webm"))
    if step.key == "tts":
        # TTS can produce nothing; the presence of vo/ + vo/index.json
        # means it ran successfully.
        vo = s / "vo"
        return vo.is_dir() and (vo / "index.json").is_file()
    outs = _outputs_for(step, session_id, opts)
    return all(p.exists() for p in outs) if outs else False


# ----- runner ---------------------------------------------------------------


def _default_sink(msg: str) -> None:
    """Default progress sink — prints the banner to stdout. The CLI
    uses this; the backend HTTP wrapper passes its own sink that
    publishes to the WS event bus.
    """
    print(f"[pipeline] {msg}")


def _run_step(
    step: Step,
    session_id: str,
    opts: PipelineOpts,
    sink: Callable[[str], None],
) -> None:
    """Run one step's inner main() with the resolved argv, capturing
    its stdout so we can prefix every line with the step name.
    """
    argv = step.build_argv(session_id, opts.sessions_dir, opts)
    sink(f"$ python -m {step.module}  {' '.join(argv)}")
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            step.run(argv)
    except SystemExit as exc:
        # Inner CLIs raise SystemExit(1) on bad input. Re-emit the
        # captured output for context, then propagate the same exit code
        # so the pipeline as a whole fails fast.
        sys.stdout.write(buf.getvalue())
        sys.stdout.flush()
        code = exc.code if isinstance(exc.code, int) else 1
        raise SystemExit(f"step {step.key!r} failed (exit {code})") from exc
    except Exception as exc:  # noqa: BLE001
        sys.stdout.write(buf.getvalue())
        sys.stdout.flush()
        raise SystemExit(f"step {step.key!r} failed: {type(exc).__name__}: {exc}") from exc
    # Forward the step's stdout (filtered) to the pipeline's stdout so
    # the operator sees what happened. Skip blank-line spam.
    for line in buf.getvalue().splitlines():
        if line.strip():
            sys.stdout.write(f"  | {line}\n")
    sys.stdout.flush()


def run_pipeline(
    *,
    session_id: str,
    opts: PipelineOpts,
    enabled: set[str],
    force: bool,
    dry_run: bool,
    sink: Callable[[str], None] | None = None,
) -> None:
    """Sequentially execute the enabled steps. The order is fixed by
    :data:`STEPS`; ``enabled`` chooses which links to fire. ``force``
    bypasses the "outputs already exist" check. ``sink`` receives
    each progress line so the HTTP wrapper can fan out to the WS
    event bus; defaults to printing to stdout.
    """
    emit = sink or _default_sink
    emit(f"session_id={session_id}")
    emit(f"sessions_dir={opts.sessions_dir}")
    emit(f"enabled={sorted(enabled)}")
    if dry_run:
        emit("DRY RUN — printing plan only")
        for step in STEPS:
            if step.key in enabled:
                argv = step.build_argv(session_id, opts.sessions_dir, opts)
                emit(f"  step {step.key}: argv={argv!r}")
        return

    for i, step in enumerate(STEPS, 1):
        if step.key not in enabled:
            emit(f"step {i}/{len(STEPS)}: {step.label}  [skipped — not in --include set]")
            continue
        if not force and _has_outputs(step, session_id, opts):
            emit(f"step {i}/{len(STEPS)}: {step.label}  [skipped — outputs present, --force to re-run]")
            continue
        emit(f"step {i}/{len(STEPS)}: {step.label}")
        _run_step(step, session_id, opts, emit)

    final_reel = _sdir(opts, session_id) / "reel.mp4"
    if final_reel.is_file():
        size = final_reel.stat().st_size
        emit(f"DONE: {final_reel}  ({size / 1024 / 1024:.1f} MB)")
    else:
        emit("DONE: reel.mp4 not produced — check skipped/failed steps above")


# ----- CLI ------------------------------------------------------------------


def _parse_date_arg(s: str) -> date:
    return date.fromisoformat(s)


def _gen_session_id(d: date) -> str:
    # Same formula session.run uses for the --session-id auto path.
    return f"s_{d.isoformat()}_{uuid.uuid4().hex[:6]}"


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.render.pipeline",
        description=(
            "One-shot VOD chain runner. Sequences session.run → session.beats → "
            "render.headless → render.stitch → tts.run → render.mix → "
            "yt.metadata → yt.upload with skip / force / dry-run controls."
        ),
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument(
        "--date",
        type=_parse_date_arg,
        help="ISO date to simulate (e.g. 2026-08-04). Generates a session id.",
    )
    src.add_argument(
        "--session-id",
        help="Existing session id (skips session.run; expects manifest already on disk).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("out/sessions"),
        help="Sessions directory (default: out/sessions).",
    )
    parser.add_argument(
        "--include-tts",
        action="store_true",
        help="Run tts.run (skipped by default — needs TTS provider creds).",
    )
    parser.add_argument(
        "--include-upload",
        action="store_true",
        help="Run yt.upload (skipped by default — needs YouTube creds).",
    )
    parser.add_argument(
        "--skip-headless",
        action="store_true",
        help="Don't run render.headless (useful when you've pre-staged clips).",
    )
    parser.add_argument(
        "--dry-run-upload",
        action="store_true",
        default=True,
        help="If --include-upload is set, do a dry-run upload (prints the YT payload, no HTTP). Default: on.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run steps even when their outputs already exist.",
    )
    parser.add_argument(
        "--music",
        type=Path,
        default=None,
        help="Music bed passed to render.mix (optional).",
    )
    parser.add_argument(
        "--tts-provider",
        default="auto",
        choices=["auto", "elevenlabs", "openai", "silence"],
        help="TTS provider for tts.run. Default: auto (first available, else silence).",
    )
    parser.add_argument(
        "--tts-voice",
        default=None,
        help="TTS voice id (provider-specific).",
    )
    parser.add_argument(
        "--stitch-xfade",
        type=float,
        default=0.4,
        help="Crossfade seconds for render.stitch / render.mix / yt.metadata alignment.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the resolved plan + per-step argv, don't invoke anything.",
    )
    args = parser.parse_args(argv)

    if args.date is not None:
        session_id = _gen_session_id(args.date)
    else:
        session_id = args.session_id

    enabled: set[str] = set()
    for step in STEPS:
        if step.enabled_by_default:
            enabled.add(step.key)
    if args.include_tts:
        enabled.add("tts")
    if args.include_upload:
        enabled.add("upload")
    if args.skip_headless:
        enabled.discard("headless")
    # session.run is mandatory when --date was used. When the operator
    # passes --session-id (resuming an existing session), the replay
    # step makes no sense — there's no fresh date range to replay —
    # so we drop it from the enabled set. The other steps (beats,
    # stitch, mix, etc.) still run against the existing artifacts.
    if args.date is None:
        enabled.discard("session")

    opts = PipelineOpts(
        sessions_dir=args.out,
        music=args.music,
        tts_provider=args.tts_provider,
        tts_voice=args.tts_voice or "alloy",  # sensible default for openai path
        upload_dry_run=args.dry_run_upload,
        stitch_xfade=args.stitch_xfade,
        force=args.force,
    )

    run_pipeline(
        session_id=session_id,
        opts=opts,
        enabled=enabled,
        force=args.force,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
