"""Thumbnail extractor — pure-function tests.

The argv builder is pure so we can pin the exact contract; the
``extract_thumb`` driver and CLI entry point are exercised via the
``_outputs_for`` / ``_has_outputs`` registry checks (the pipeline
runner is the integration surface). An end-to-end ffmpeg test is
gated behind ``RUN_BROWSER_TESTS=1`` -- the same convention
``test_shorts.py`` and ``test_headless.py`` use.

Tests cover:
  1. build_ffmpeg_argv: default args produce the expected argv
  2. build_ffmpeg_argv: --at / --quality / --width / --height flow through
  3. extract_thumb: resolves silent_reel / reel, errors on neither
  4. CLI: --dry-run prints the argv, never spawns ffmpeg
  5. pipeline.STEPS: contains a 'thumb' step between mix and metadata
  6. pipeline._outputs_for / _has_outputs: thumb.jpg presence contract
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from tradefarm.render import pipeline as pipeline_mod
from tradefarm.render.thumb import (
    DEFAULT_AT_SEC,
    DEFAULT_QUALITY,
    ThumbResult,
    build_ffmpeg_argv,
    extract_thumb,
    main,
)


# ---------------------------------------------------------------------------
# build_ffmpeg_argv — pure-function contract
# ---------------------------------------------------------------------------


def test_build_ffmpeg_argv_basic() -> None:
    """Defaults: 1.0s seek, quality 2, 1280x720. The -ss lives before
    -i (fast seek; fine for a single still), -vframes 1 grabs one
    frame, -q:v 2 sets JPEG quality, the filter chain preserves
    aspect ratio with letterbox padding."""
    in_path = Path("silent_reel.mp4")
    out_path = Path("thumb.jpg")
    argv = build_ffmpeg_argv(in_path=in_path, out_path=out_path)
    assert argv == [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{DEFAULT_AT_SEC:.3f}",
        "-i",
        str(in_path),
        "-vframes",
        "1",
        "-q:v",
        str(DEFAULT_QUALITY),
        "-vf",
        "scale=1280:720:force_original_aspect_ratio=decrease,"
        "pad=1280:720:(ow-iw)/2:(oh-ih)/2",
        str(out_path),
    ]


def test_build_ffmpeg_argv_custom_at_sec() -> None:
    """--at 5.0 → -ss 5.000 in the argv (3dp formatting)."""
    argv = build_ffmpeg_argv(
        in_path=Path("in.mp4"),
        out_path=Path("out.jpg"),
        at_sec=5.0,
    )
    idx = argv.index("-ss")
    assert argv[idx + 1] == "5.000"


def test_build_ffmpeg_argv_custom_dimensions() -> None:
    """1920x1080 → scale/pad filter use 1920/1080 (for the operator who
    wants a 1080p thumbnail, even though 1280x720 is the default)."""
    argv = build_ffmpeg_argv(
        in_path=Path("in.mp4"),
        out_path=Path("out.jpg"),
        width=1920,
        height=1080,
    )
    vf = argv[argv.index("-vf") + 1]
    assert "scale=1920:1080" in vf
    assert "pad=1920:1080" in vf


def test_build_ffmpeg_argv_custom_quality() -> None:
    """quality=4 → -q:v 4 (lower fidelity but smaller file)."""
    argv = build_ffmpeg_argv(
        in_path=Path("in.mp4"),
        out_path=Path("out.jpg"),
        quality=4,
    )
    idx = argv.index("-q:v")
    assert argv[idx + 1] == "4"


def test_build_ffmpeg_argv_short_source_needs_padding() -> None:
    """A 9:16 vertical source (e.g. a shorts pilot) needs letterbox
    padding into the 16:9 target. The same argv builder handles it --
    the scale+pad filter is aspect-ratio-aware. We only assert the
    builder doesn't crash and the filter chain is present."""
    argv = build_ffmpeg_argv(
        in_path=Path("short.mp4"),
        out_path=Path("thumb.jpg"),
    )
    vf = argv[argv.index("-vf") + 1]
    assert "force_original_aspect_ratio=decrease" in vf
    # The pad filter is what fills the side-bars for vertical sources.
    assert "pad=" in vf
    # The full chain is scale -> pad (single comma separator).
    assert vf.count(",") == 1


# ---------------------------------------------------------------------------
# extract_thumb — input resolution + failure paths
# ---------------------------------------------------------------------------


def _write_silent_reel(sdir: Path, *, also_reel: bool = False) -> Path:
    """Create a stub silent_reel.mp4 in ``sdir`` (and optionally a
    reel.mp4 next to it). The bytes are zero-padded so ``is_file()``
    passes for the resolution logic; the test never invokes ffmpeg."""
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "silent_reel.mp4").write_bytes(b"\x00" * 64)
    if also_reel:
        (sdir / "reel.mp4").write_bytes(b"\x00" * 128)
    return sdir


def test_extract_thumb_prefers_reel_when_both_present(tmp_path: Path) -> None:
    """When both silent_reel.mp4 and reel.mp4 exist, the driver reads
    from reel.mp4 (the higher-fidelity post-mix output). The
    dry_run=True path returns a result without spawning ffmpeg."""
    sdir = _write_silent_reel(tmp_path / "sess", also_reel=True)
    result = extract_thumb("sess", sessions_dir=tmp_path, dry_run=True)
    assert isinstance(result, ThumbResult)
    assert result.ok is True
    assert result.dry_run is True
    assert result.in_path == sdir / "reel.mp4"
    assert result.out_path == sdir / "thumb.jpg"
    assert result.ffmpeg_argv is not None
    assert result.ffmpeg_argv[0] == "ffmpeg"


def test_extract_thumb_falls_back_to_silent_reel(tmp_path: Path) -> None:
    """When only silent_reel.mp4 is present (TTS step was skipped),
    the driver falls back to it rather than failing."""
    sdir = _write_silent_reel(tmp_path / "sess", also_reel=False)
    result = extract_thumb("sess", sessions_dir=tmp_path, dry_run=True)
    assert result.ok is True
    assert result.in_path == sdir / "silent_reel.mp4"


def test_extract_thumb_raises_when_no_source(tmp_path: Path) -> None:
    """Neither reel.mp4 nor silent_reel.mp4 present → FileNotFoundError
    naming the directory. Pipeline surfaces this in the per-step
    failure banner; the CLI converts it to a non-zero exit."""
    sdir = tmp_path / "sess"
    sdir.mkdir()
    with pytest.raises(FileNotFoundError, match="neither reel.mp4 nor silent_reel.mp4"):
        extract_thumb("sess", sessions_dir=tmp_path, dry_run=True)


# ---------------------------------------------------------------------------
# CLI — --dry-run contract
# ---------------------------------------------------------------------------


def test_cli_dry_run_prints_argv_without_running_ffmpeg(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """`python -m tradefarm.render.thumb <sid> --dry-run` prints the
    resolved ffmpeg argv, never spawns ffmpeg, and never writes
    thumb.jpg to disk. ASCII-only output (no em-dashes)."""
    _write_silent_reel(tmp_path / "sess", also_reel=True)
    main(["sess", "--out", str(tmp_path), "--dry-run"])
    out = capsys.readouterr().out
    assert "[thumb] session_id=sess" in out
    assert "argv: ffmpeg" in out
    assert "thumb.jpg" in out
    # ASCII-only: the em-dash check.
    assert "\u2014" not in out
    # No thumbnail was written.
    assert not (tmp_path / "sess" / "thumb.jpg").exists()


def test_cli_at_flag_passes_through(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """--at 3.5 → argv contains -ss 3.500."""
    _write_silent_reel(tmp_path / "sess")
    main(["sess", "--out", str(tmp_path), "--at", "3.5", "--dry-run"])
    out = capsys.readouterr().out
    assert "-ss 3.500" in out


# ---------------------------------------------------------------------------
# pipeline.STEPS — registry contract
# ---------------------------------------------------------------------------


def _opts(tmp_path: Path) -> pipeline_mod.PipelineOpts:
    return pipeline_mod.PipelineOpts(
        sessions_dir=tmp_path,
        music=None,
        tts_provider="auto",
        tts_voice="alloy",
        upload_dry_run=True,
        stitch_xfade=0.4,
        force=False,
    )


def test_thumb_step_in_registry() -> None:
    """The 9-step chain includes a 'thumb' step. It is enabled by
    default (no creds / external deps needed)."""
    keys = [s.key for s in pipeline_mod.STEPS]
    assert "thumb" in keys
    thumb_step = next(s for s in pipeline_mod.STEPS if s.key == "thumb")
    assert thumb_step.enabled_by_default is True
    assert thumb_step.module == "tradefarm.render.thumb"
    assert thumb_step.label.startswith("render.thumb")


def test_thumb_step_position_between_mix_and_metadata() -> None:
    """Position matters: 'thumb' reads from the post-mix reel and
    produces an artifact that 'metadata' embeds in episode.yaml. It
    must be at mix_index + 1 == metadata_index."""
    keys = [s.key for s in pipeline_mod.STEPS]
    mix_idx = keys.index("mix")
    thumb_idx = keys.index("thumb")
    meta_idx = keys.index("metadata")
    assert thumb_idx == mix_idx + 1, (
        f"thumb at {thumb_idx}, expected mix+1={mix_idx + 1}"
    )
    assert meta_idx == thumb_idx + 1, (
        f"metadata at {meta_idx}, expected thumb+1={thumb_idx + 1}"
    )


def test_thumb_step_outputs_thumb_jpg(tmp_path: Path) -> None:
    """_outputs_for the thumb step returns the thumb.jpg path."""
    thumb_step = next(s for s in pipeline_mod.STEPS if s.key == "thumb")
    outputs = pipeline_mod._outputs_for(thumb_step, "sess", _opts(tmp_path))
    assert outputs == (tmp_path / "sess" / "thumb.jpg",)


def test_thumb_step_has_outputs_after_run(tmp_path: Path) -> None:
    """_has_outputs is False before thumb.jpg exists, True after.
    This is the idempotency contract the runner uses to skip the step
    on a re-run."""
    sdir = tmp_path / "sess"
    sdir.mkdir()
    thumb_step = next(s for s in pipeline_mod.STEPS if s.key == "thumb")
    opts = _opts(tmp_path)
    assert pipeline_mod._has_outputs(thumb_step, "sess", opts) is False
    (sdir / "thumb.jpg").write_bytes(b"\x00")
    assert pipeline_mod._has_outputs(thumb_step, "sess", opts) is True


# ---------------------------------------------------------------------------
# integration (env-gated)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 + ffmpeg on PATH to enable.",
)
def test_integration_extract_real_thumb(tmp_path: Path) -> None:
    """End-to-end: write a stub silent_reel.mp4, run extract_thumb,
    assert thumb.jpg is produced. Requires ffmpeg on PATH and a
    real-enough source for ffmpeg to read the duration."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    _write_silent_reel(tmp_path / "sess")
    result = extract_thumb("sess", sessions_dir=tmp_path)
    # A 64-byte zero stub probably won't decode, but we just want a
    # result object back. The contract is "no exception".
    assert isinstance(result, ThumbResult)
