"""Shorts renderer — pure-function tests.

The composition + planning is pure; the actual ffmpeg invocation is
gated so `uv run pytest` doesn't require ffmpeg on the PATH. The
integration test that runs ffmpeg is opt-in via the
RUN_BROWSER_TESTS env var (we reuse the existing convention from
tests/render/test_headless.py).

Tests cover:
  1. URL contract: build_ffmpeg_argv produces the expected argv
  2. plan_jobs parity with headless (recap skip, score ordering, top-N)
  3. dry-run prints + does NOT invoke ffmpeg
  4. top-N selection: score-descending, ties broken by time
  5. compose_session handles missing clips gracefully (no crash)
  6. compose_session marks ffmpeg_missing when ffmpeg isn't on PATH
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from tradefarm.render.shorts import (
    DEFAULT_VERTICAL,
    build_ffmpeg_argv,
    compose_session,
    main,
    plan_jobs,
)


# ----- fixtures + helpers ---------------------------------------------------


def _beat(
    *,
    id: str = "b_test",
    kind: str = "big_fill",
    scene: str = "hero",
    t: str = "2026-05-19T14:00:00+00:00",
    duration: int = 30,
    score: float = 0.7,
) -> dict:
    return {
        "id": id,
        "t": t,
        "kind": kind,
        "scene_hint": scene,
        "duration_sec": duration,
        "score": score,
        "headline": "test headline",
        "sub": "test sub",
    }


def _write_beats(tmp_path: Path, beats: list[dict]) -> Path:
    sdir = tmp_path / "sess"
    sdir.mkdir()
    (sdir / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
    return sdir


def _write_clip(clips_dir: Path, beat_id: str, size: int = 16) -> Path:
    clips_dir.mkdir(parents=True, exist_ok=True)
    p = clips_dir / f"{beat_id}.webm"
    p.write_bytes(b"\x00" * size)
    return p


# ----- build_ffmpeg_argv contract ------------------------------------------


def test_build_ffmpeg_argv_uses_vertical_smart_crop():
    """Smart-crop formula: crop=ih*9/16:ih then scale=1080:1920.

    The crop+scale live in a single -vf argument; the test checks the
    full filter string rather than argv membership."""
    in_path = Path("/tmp/in.webm")
    out_path = Path("/tmp/out.mp4")
    argv = build_ffmpeg_argv(in_path=in_path, out_path=out_path)
    # The combined -vf filter string
    vf = next((argv[i + 1] for i, a in enumerate(argv) if a == "-vf"), "")
    assert "crop=ih*9/16:ih" in vf
    assert "scale=1080:1920" in vf
    # Codec chain
    assert "libx264" in argv
    assert "aac" in argv
    # faststart for Shorts player seeking
    assert "+faststart" in argv
    # Inputs / outputs
    assert str(in_path) in argv
    assert str(out_path) in argv


def test_build_ffmpeg_argv_respects_vertical_override():
    """Operator can pick a non-default vertical viewport (e.g. 720x1280)."""
    argv = build_ffmpeg_argv(
        in_path=Path("/in.webm"),
        out_path=Path("/out.mp4"),
        vertical=(720, 1280),
    )
    vf = next((argv[i + 1] for i, a in enumerate(argv) if a == "-vf"), "")
    assert "scale=720:1280" in vf
    assert "crop=ih*9/16:ih" in vf  # crop formula is viewport-agnostic


def test_default_vertical_is_1080x1920():
    assert DEFAULT_VERTICAL == (1080, 1920)


# ----- plan_jobs parity with headless --------------------------------------


def test_plan_jobs_skips_recap_by_default(tmp_path: Path):
    """Same constraint as headless.py: recap scene isn't replay-aware
    so we don't compose it. Plan emits 2 jobs out of 3 beats."""
    beats = [
        _beat(id="b_open", kind="open", scene="hero", t="2026-05-19T13:30:00+00:00", score=0.6),
        _beat(id="b_recap", kind="recap", scene="recap", t="2026-05-19T20:00:00+00:00", score=0.9),
        _beat(id="b_div", kind="divergence", scene="brain", t="2026-05-19T14:00:00+00:00", score=0.8),
    ]
    clips = tmp_path / "clips"
    _write_clip(clips, "b_open")
    _write_clip(clips, "b_recap")
    _write_clip(clips, "b_div")
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=clips)
    # recap is filtered before the top_n cap; both remaining beats
    # make it because top_n=3 > 2 candidates.
    ids = [j.beat_id for j in jobs]
    assert "b_recap" not in ids
    assert set(ids) == {"b_open", "b_div"}


def test_plan_jobs_top_n_limits_output_by_score_desc(tmp_path: Path):
    """6 beats, top_n=3 → only the 3 highest-scoring pass."""
    beats = [
        _beat(id="b1", score=0.5, t="2026-05-19T13:30:00+00:00"),
        _beat(id="b2", score=0.9, t="2026-05-19T13:31:00+00:00"),
        _beat(id="b3", score=0.7, t="2026-05-19T13:32:00+00:00"),
        _beat(id="b4", score=0.4, t="2026-05-19T13:33:00+00:00"),
        _beat(id="b5", score=0.85, t="2026-05-19T13:34:00+00:00"),
        _beat(id="b6", score=0.6, t="2026-05-19T13:35:00+00:00"),
    ]
    clips = tmp_path / "clips"
    for b in beats:
        _write_clip(clips, b["id"])
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=clips, top_n=3)
    assert [j.beat_id for j in jobs] == ["b2", "b5", "b3"]


def test_plan_jobs_caps_per_short_duration(tmp_path: Path):
    """A 90s beat is capped at max_duration (60s) on the URL `until`."""
    beats = [
        _beat(id="b_long", t="2026-05-19T13:30:00+00:00", duration=90),
    ]
    clips = tmp_path / "clips"
    _write_clip(clips, "b_long")
    jobs, _ = plan_jobs(
        session_id="s_x",
        beats=beats,
        clips_dir=clips,
        short_seconds=12,
        max_duration=60,
        top_n=1,
    )
    assert len(jobs) == 1
    assert jobs[0].duration_sec == 12  # short_seconds wins when below max


def test_plan_jobs_skips_beats_with_missing_source_clips(tmp_path: Path):
    """If headless didn't produce the .webm, the shorts planner must
    skip that beat (rather than crash on a missing input file)."""
    beats = [
        _beat(id="b_present", score=0.9),
        _beat(id="b_missing", score=0.95),
    ]
    clips = tmp_path / "clips"
    _write_clip(clips, "b_present")
    jobs, skipped = plan_jobs(
        session_id="s_x", beats=beats, clips_dir=clips, top_n=2
    )
    assert [j.beat_id for j in jobs] == ["b_present"]
    assert "b_missing" in skipped


def test_plan_jobs_handles_zero_top_n():
    """top_n=0 means "compose nothing" — useful for the --dry-run
    plan-only path with an operator who wants to inspect the argv
    before ffmpeg fires."""
    beats = [_beat(id="b1", score=0.9)]
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=Path("/tmp/c"), top_n=0)
    assert jobs == []


# ----- dry-run / no-ffmpeg behaviour --------------------------------------


def test_compose_session_dry_run_does_not_run_ffmpeg(tmp_path: Path, capsys):
    """--dry-run plans the jobs and returns them in the result, but
    never spawns ffmpeg. We assert that no .mp4 lands on disk and
    that each result row has dry_run=True."""
    beats = [_beat(id="b1", score=0.9)]
    sdir = _write_beats(tmp_path, beats)
    _write_clip(sdir / "clips", "b1")
    # Patch _have_ffmpeg so we don't depend on the host. Even with
    # ffmpeg on PATH, dry_run=True must not invoke it.
    with patch("tradefarm.render.shorts._have_ffmpeg", return_value=True):
        result = compose_session(
            "sess",
            sessions_dir=tmp_path,
            top_n=1,
            dry_run=True,
        )
    assert result.succeeded == 1
    assert result.failed == 0
    assert result.ffmpeg_missing is False
    assert result.results[0]["dry_run"] is True
    assert result.results[0]["ffmpeg_argv"][0] == "ffmpeg"
    # The .mp4 must NOT exist on disk.
    assert not (sdir / "clips" / "shorts" / "b1.mp4").exists()
    # But the shorts dir was created.
    assert (sdir / "clips" / "shorts").is_dir()


def test_compose_session_marks_ffmpeg_missing_when_unavailable(tmp_path: Path):
    """If ffmpeg is not on PATH, dry_run plans but the result reports
    ffmpeg_missing=True and the per-job results fail (not succeed)
    so the operator knows to install it."""
    beats = [_beat(id="b1", score=0.9)]
    sdir = _write_beats(tmp_path, beats)
    _write_clip(sdir / "clips", "b1")
    with patch("tradefarm.render.shorts._have_ffmpeg", return_value=False):
        result = compose_session(
            "sess",
            sessions_dir=tmp_path,
            top_n=1,
            dry_run=False,  # would normally run ffmpeg
        )
    assert result.ffmpeg_missing is True
    # No ffmpeg fired, so the job is recorded as a failure with the
    # ffmpeg_missing flag in the per-row result.
    assert result.failed == 1
    assert result.succeeded == 0
    assert result.results[0]["ffmpeg_missing"] is True
    # No .mp4 on disk.
    assert not (sdir / "clips" / "shorts" / "b1.mp4").exists()


# ----- CLI -----------------------------------------------------------------


def test_cli_dry_run_prints_plan(capsys: pytest.CaptureFixture[str], tmp_path: Path):
    """`python -m tradefarm.render.shorts <sid> --dry-run` should print
    the planned argv for each job. ASCII-only (no em-dashes) per the
    Windows cp1252 constraint."""
    beats = [
        _beat(id="b1", score=0.9, t="2026-05-19T13:30:00+00:00"),
        _beat(id="b2", score=0.7, t="2026-05-19T13:31:00+00:00"),
    ]
    sdir = _write_beats(tmp_path, beats)
    _write_clip(sdir / "clips", "b1")
    _write_clip(sdir / "clips", "b2")
    with patch("tradefarm.render.shorts._have_ffmpeg", return_value=True):
        main(["sess", "--out", str(tmp_path), "--top", "2", "--dry-run"])
    out = capsys.readouterr().out
    # ASCII banner present.
    assert "[shorts]" in out
    assert "PLAN b1" in out
    assert "ffmpeg" in out
    # The em-dash check: must NOT contain U+2014 in the printed output.
    assert "\u2014" not in out


def test_cli_rejects_bad_vertical():
    """Bad --viewport string → SystemExit with a clear message."""
    with pytest.raises(SystemExit) as exc:
        main(["sess", "--out", "irrelevant", "--vertical", "nope"])
    assert "bad --vertical" in str(exc.value)


def test_cli_rejects_unsafe_session_id(tmp_path: Path):
    """Path-traversal-shaped session id must be rejected (the same
    guard render/headless.py applies)."""
    with pytest.raises(ValueError, match="invalid session_id"):
        main(["../etc/passwd", "--out", str(tmp_path)])


def test_cli_handles_missing_beats_file(tmp_path: Path):
    """No beats.json → FileNotFoundError on the well-known path. The
    CLI raises rather than silently printing 0 jobs, so the operator
    sees the missing input clearly."""
    # session dir exists but no beats.json
    (tmp_path / "sess").mkdir()
    with pytest.raises(FileNotFoundError, match="beats.json not found"):
        main(["sess", "--out", str(tmp_path), "--dry-run"])


# ----- integration (env-gated) --------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 + ffmpeg on PATH to enable.",
)
def test_integration_compose_real_short(tmp_path: Path):
    """End-to-end: read a tiny beats.json, run ffmpeg, produce a .mp4.
    Requires ffmpeg on PATH."""
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not on PATH")
    beats = [_beat(id="b1", score=0.9, t="2026-05-19T13:30:00+00:00")]
    sdir = _write_beats(tmp_path, beats)
    # Make the source clip look like a real webm. A few bytes is enough
    # for ffmpeg to attempt to read it; it'll fail with a corrupt-input
    # error and we expect the scorer to record the failure rather than
    # crash. We do not assert the .mp4 exists — ffmpeg may refuse to
    # transcode a 16-byte stub. The contract is: no exception, result
    # row present, summary consistent.
    _write_clip(sdir / "clips", "b1", size=16)
    result = compose_session(
        "sess",
        sessions_dir=tmp_path,
        top_n=1,
        dry_run=False,
    )
    # The job ran (or failed) — we just want a row, no crash.
    assert len(result.results) == 1
    assert "beat_id" in result.results[0]
