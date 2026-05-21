"""Thumbnail generator — pure-function tests + Pillow-driven render.

Pillow is already a dev dep so the render path runs without env-gating.
ffmpeg frame-grab is mocked away so we don't need the binary for the
default test path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tradefarm.thumb.gen import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    ThumbPlan,
    derive_badge,
    derive_title,
    make_thumbnail,
    pick_source_beat,
    plan_thumb,
)


# ----- helpers ------------------------------------------------------------


def _beat(beat_id: str, *, kind: str = "big_fill", score: float = 0.7,
          headline: str = "h", sub: str = "s", duration: int = 30,
          metadata: dict | None = None) -> dict:
    return {
        "id": beat_id, "kind": kind, "score": score,
        "headline": headline, "sub": sub, "duration_sec": duration,
        "t": "2026-05-21T14:00:00+00:00",
        "metadata": metadata or {},
    }


def _write_session(
    tmp_path: Path,
    session_id: str,
    *,
    beats: list[dict],
    clips_present: list[str] | None = None,
    script_title: str | None = None,
    manifest: dict | None = None,
) -> Path:
    sdir = tmp_path / session_id
    (sdir / "clips").mkdir(parents=True, exist_ok=True)
    (sdir / "beats.json").write_text(json.dumps(beats))
    for bid in clips_present or []:
        (sdir / "clips" / f"{bid}.webm").write_bytes(b"placeholder")
    if script_title is not None:
        (sdir / "script.json").write_text(json.dumps({
            "session_id": session_id, "episode_title": script_title,
            "model": "m", "usage": {}, "total_words": 0,
            "total_duration_sec": 0, "beats": [],
        }))
    if manifest is not None:
        (sdir / "manifest.json").write_text(json.dumps(manifest))
    return sdir


# ----- pick_source_beat ---------------------------------------------------


def test_pick_source_beat_takes_highest_score_with_clip(tmp_path: Path):
    sdir = _write_session(
        tmp_path, "s_pick",
        beats=[
            _beat("b_low", score=0.3),
            _beat("b_high", score=0.9),
            _beat("b_mid", score=0.6),
        ],
        clips_present=["b_low", "b_mid"],  # b_high's clip is MISSING
    )
    beats = json.loads((sdir / "beats.json").read_text())
    pick = pick_source_beat(beats, sdir / "clips")
    assert pick is not None
    beat, clip = pick
    assert beat["id"] == "b_mid"  # b_high skipped because no clip
    assert clip.name == "b_mid.webm"


def test_pick_source_beat_returns_none_when_no_clips(tmp_path: Path):
    sdir = _write_session(
        tmp_path, "s_empty",
        beats=[_beat("b1")], clips_present=[],
    )
    beats = json.loads((sdir / "beats.json").read_text())
    assert pick_source_beat(beats, sdir / "clips") is None


def test_pick_source_beat_returns_none_for_empty_beats(tmp_path: Path):
    assert pick_source_beat([], tmp_path / "clips") is None


# ----- derive_title -------------------------------------------------------


def test_derive_title_prefers_script_episode_title():
    title = derive_title(
        beats=[_beat("b1", headline="best beat headline", score=0.9)],
        script={"episode_title": "  Mei takes #1 after 47 days  "},
        manifest=None, session_id="s_x",
    )
    assert title == "Mei takes #1 after 47 days"


def test_derive_title_falls_back_to_best_beat_headline():
    title = derive_title(
        beats=[
            _beat("b_low", headline="boring", score=0.2),
            _beat("b_high", headline="The Big Move", score=0.95),
        ],
        script=None, manifest=None, session_id="s_x",
    )
    assert title == "The Big Move"


def test_derive_title_falls_back_to_manifest_then_session_id():
    title = derive_title(beats=[], script=None,
                         manifest={"trading_days": ["2026-05-21"]},
                         session_id="s_x")
    assert "2026-05-21" in title
    # And last-ditch session_id
    title2 = derive_title(beats=[], script=None, manifest=None, session_id="s_xyz")
    assert "s_xyz" in title2


# ----- derive_badge -------------------------------------------------------


def test_derive_badge_uses_recap_realized_pnl_when_numeric():
    beats = [_beat("b_recap", kind="recap", metadata={"realized_pnl": 1840.0})]
    assert derive_badge(beats) == "+$1,840"


def test_derive_badge_negative_pnl_formatted_with_minus_glyph():
    # 350.7 to dodge Python's banker's rounding on the half-value case.
    beats = [_beat("b_recap", kind="recap", metadata={"realized_pnl": -350.7})]
    assert derive_badge(beats) == "−$351"


def test_derive_badge_falls_back_to_recap_sub_when_no_pnl():
    beats = [_beat("b_recap", kind="recap", sub="momentum +2.1% · lstm +1.2%",
                   metadata={})]
    assert derive_badge(beats) == "momentum +2.1% · lstm +1.2%"


def test_derive_badge_none_when_no_recap_beat():
    beats = [_beat("b_open"), _beat("b_close")]
    assert derive_badge(beats) is None


# ----- plan_thumb ---------------------------------------------------------


def test_plan_thumb_grabs_mid_clip_frame(tmp_path: Path):
    _write_session(
        tmp_path, "s_plan",
        beats=[_beat("b1", score=0.9, duration=30)],
        clips_present=["b1"],
        script_title="Test Episode",
    )
    plan = plan_thumb(session_id="s_plan", sessions_dir=tmp_path)
    assert plan is not None
    assert plan.grab_at_sec == pytest.approx(15.0)
    assert plan.title == "Test Episode"
    assert plan.source_clip.name == "b1.webm"


def test_plan_thumb_returns_none_when_no_clips(tmp_path: Path):
    _write_session(
        tmp_path, "s_none",
        beats=[_beat("b1")], clips_present=[],
    )
    assert plan_thumb(session_id="s_none", sessions_dir=tmp_path) is None


# ----- make_thumbnail (end-to-end with mocked frame grab) ----------------


def _stub_grab_frame_to_solid(monkeypatch, color=(80, 100, 140)):
    """Replace _grab_frame with a stub that drops a solid-colour PNG."""
    from tradefarm.thumb import gen
    from PIL import Image

    def fake_grab(clip, at_sec, out_png):
        Image.new("RGB", (1920, 1080), color).save(out_png)
    monkeypatch.setattr(gen, "_grab_frame", fake_grab)


def test_make_thumbnail_produces_jpeg_at_target_size(tmp_path: Path, monkeypatch):
    _stub_grab_frame_to_solid(monkeypatch)
    _write_session(
        tmp_path, "s_e2e",
        beats=[
            _beat("b1", score=0.9, headline="The Big Day", duration=30),
            _beat("b_recap", kind="recap", score=0.5,
                  metadata={"realized_pnl": 1840.0}),
        ],
        clips_present=["b1"],
    )
    result = make_thumbnail("s_e2e", sessions_dir=tmp_path)
    assert result.ok, result.error
    assert result.out_path is not None and result.out_path.is_file()
    # Verify the rendered file is a JPEG at the target resolution.
    from PIL import Image
    img = Image.open(result.out_path)
    assert img.format == "JPEG"
    assert img.size == (DEFAULT_WIDTH, DEFAULT_HEIGHT)
    # Should be in a sane size range (not empty, not absurd).
    size_kb = result.out_path.stat().st_size / 1024
    assert 5 < size_kb < 800


def test_make_thumbnail_cleans_temp_frame(tmp_path: Path, monkeypatch):
    _stub_grab_frame_to_solid(monkeypatch)
    _write_session(
        tmp_path, "s_clean",
        beats=[_beat("b1", score=0.9)], clips_present=["b1"],
    )
    result = make_thumbnail("s_clean", sessions_dir=tmp_path)
    assert result.ok
    assert not (tmp_path / "s_clean" / ".thumb_frame.png").exists()


def test_make_thumbnail_dry_run_skips_render(tmp_path: Path):
    _write_session(
        tmp_path, "s_dry",
        beats=[_beat("b1", score=0.9)], clips_present=["b1"],
    )
    result = make_thumbnail("s_dry", sessions_dir=tmp_path, dry_run=True)
    assert result.ok
    assert result.plan is not None
    assert not (tmp_path / "s_dry" / "thumb.jpg").exists()


def test_make_thumbnail_errors_when_no_clips(tmp_path: Path):
    _write_session(
        tmp_path, "s_no",
        beats=[_beat("b1")], clips_present=[],
    )
    result = make_thumbnail("s_no", sessions_dir=tmp_path)
    assert not result.ok
    assert "no rendered clips" in (result.error or "")


def test_make_thumbnail_recovers_after_grab_failure(tmp_path: Path, monkeypatch):
    """If ffmpeg fails the temp png + half-written jpg are cleaned up."""
    from tradefarm.thumb import gen

    def fake_grab(clip, at_sec, out_png):
        raise RuntimeError("simulated ffmpeg failure")
    monkeypatch.setattr(gen, "_grab_frame", fake_grab)

    _write_session(
        tmp_path, "s_fail",
        beats=[_beat("b1", score=0.9)], clips_present=["b1"],
    )
    result = make_thumbnail("s_fail", sessions_dir=tmp_path)
    assert not result.ok
    assert "simulated" in (result.error or "")
    assert not (tmp_path / "s_fail" / "thumb.jpg").exists()
    assert not (tmp_path / "s_fail" / ".thumb_frame.png").exists()
