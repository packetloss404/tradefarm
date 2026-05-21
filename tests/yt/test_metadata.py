"""Episode metadata builder — pure-function tests."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradefarm.yt.metadata import (
    DEFAULT_PRIVACY,
    Chapter,
    EpisodeMeta,
    _format_chapter_stamp,
    build_description,
    build_episode_meta,
    compute_chapters,
    default_publish_at,
    meta_to_dict,
    write_meta,
)


# ----- helpers ------------------------------------------------------------


def _beat(beat_id: str, *, kind: str = "big_fill", score: float = 0.7,
          headline: str = "h", sub: str = "s", duration: int = 30,
          t: str = "2026-05-21T14:00:00+00:00",
          metadata: dict | None = None) -> dict:
    return {
        "id": beat_id, "kind": kind, "score": score,
        "headline": headline, "sub": sub, "duration_sec": duration,
        "t": t, "metadata": metadata or {},
    }


def _sidecar(beat_id: str, *, duration_ms: int = 30000) -> dict:
    return {
        "beat_id": beat_id, "kind": "big_fill", "scene": "hero",
        "at": "x", "until": "x", "duration_ms": duration_ms,
        "scene_ready_at_ms": 1200, "elapsed_ms": duration_ms + 1200,
        "viewport": [1920, 1080], "url": "x",
        "clip": f"{beat_id}.webm", "captured_at": "x",
    }


def _write_session(
    base: Path,
    session_id: str,
    *,
    beats: list[dict],
    rendered_beat_ids: list[str] | None = None,
    script_title: str | None = None,
    manifest: dict | None = None,
    has_video: bool = False,
    has_thumb: bool = False,
) -> Path:
    sdir = base / session_id
    (sdir / "clips").mkdir(parents=True, exist_ok=True)
    (sdir / "beats.json").write_text(json.dumps(beats))
    for bid in rendered_beat_ids or []:
        (sdir / "clips" / f"{bid}.json").write_text(
            json.dumps(_sidecar(bid, duration_ms=30000))
        )
    if script_title is not None:
        (sdir / "script.json").write_text(json.dumps({
            "session_id": session_id, "episode_title": script_title,
            "model": "m", "usage": {}, "total_words": 0,
            "total_duration_sec": 0, "beats": [],
        }))
    if manifest is not None:
        (sdir / "manifest.json").write_text(json.dumps(manifest))
    if has_video:
        (sdir / "reel.mp4").write_bytes(b"placeholder")
    if has_thumb:
        (sdir / "thumb.jpg").write_bytes(b"placeholder")
    return sdir


# ----- chapter stamp formatting ------------------------------------------


def test_chapter_stamp_mmss_under_one_hour():
    assert _format_chapter_stamp(0) == "0:00"
    assert _format_chapter_stamp(75) == "1:15"
    assert _format_chapter_stamp(3599) == "59:59"


def test_chapter_stamp_hhmmss_over_one_hour():
    assert _format_chapter_stamp(3600) == "1:00:00"
    assert _format_chapter_stamp(3661) == "1:01:01"


# ----- compute_chapters --------------------------------------------------


def test_compute_chapters_threads_xfade_offsets(tmp_path: Path):
    """3 beats × 30s with 0.4s xfade → starts 0, 29.6, 59.2."""
    beats = [_beat(f"b{i}") for i in range(3)]
    sidecars = {f"b{i}": _sidecar(f"b{i}") for i in range(3)}
    rows = compute_chapters(beats, sidecars, xfade_sec=0.4)
    assert [c.start_sec for c in rows] == [0, 30, 59]
    # First chapter must start at exactly 0 even with rounding noise.
    assert rows[0].start_sec == 0


def test_compute_chapters_returns_empty_when_too_few_renders():
    """YouTube requires ≥3 chapters; emit none rather than half a list."""
    beats = [_beat("b0"), _beat("b1")]
    sidecars = {"b0": _sidecar("b0"), "b1": _sidecar("b1")}
    assert compute_chapters(beats, sidecars) == []


def test_compute_chapters_skips_beats_without_sidecar():
    """Beats whose clip never rendered (e.g. recap-skip) don't appear
    in the chapters and don't push later beats' offsets."""
    beats = [_beat("b0"), _beat("b_skip"), _beat("b1"), _beat("b2")]
    sidecars = {"b0": _sidecar("b0"), "b1": _sidecar("b1"), "b2": _sidecar("b2")}
    rows = compute_chapters(beats, sidecars, xfade_sec=0.4)
    assert [c.title for c in rows] == ["h", "h", "h"]  # b0, b1, b2 — skipped b_skip
    assert [c.start_sec for c in rows] == [0, 30, 59]


def test_compute_chapters_truncates_long_titles():
    long_h = "x" * 200
    beats = [_beat(f"b{i}", headline=long_h) for i in range(3)]
    sidecars = {f"b{i}": _sidecar(f"b{i}") for i in range(3)}
    rows = compute_chapters(beats, sidecars)
    assert all(len(c.title) <= 80 for c in rows)
    assert all(c.title.endswith("...") for c in rows)


# ----- build_description --------------------------------------------------


def test_description_includes_summary_then_boilerplate_then_chapters():
    beats = [_beat("b_recap", kind="recap", sub="+1.84% pool · best since Apr 24"),
             _beat("b1"), _beat("b2"), _beat("b3")]
    chapters = [
        Chapter(start_sec=0, title="Opening"),
        Chapter(start_sec=30, title="Mid"),
        Chapter(start_sec=60, title="Close"),
    ]
    desc = build_description(
        beats=beats, script={"episode_title": "Mei takes #1"},
        manifest=None, chapters=chapters, session_id="s_x",
    )
    # Summary first.
    assert desc.startswith("+1.84% pool · best since Apr 24 · Mei takes #1")
    # Chapter block follows.
    assert "Chapters:" in desc
    for stamp in ("0:00 Opening", "0:30 Mid", "1:00 Close"):
        assert stamp in desc


def test_description_handles_no_recap_no_script():
    desc = build_description(
        beats=[_beat("b1")], script=None, manifest=None,
        chapters=[], session_id="s_xyz",
    )
    assert "s_xyz" in desc
    assert "Not financial advice." in desc


def test_description_omits_chapter_block_when_empty():
    desc = build_description(
        beats=[_beat("b1")], script=None, manifest=None,
        chapters=[], session_id="s_xyz",
    )
    assert "Chapters:" not in desc


# ----- default_publish_at -------------------------------------------------


def test_default_publish_at_is_iso_and_in_future():
    now = datetime(2026, 5, 21, 15, 0, tzinfo=timezone.utc)  # 11am ET-ish
    ts = default_publish_at(now=now)
    parsed = datetime.fromisoformat(ts)
    assert parsed > now
    assert parsed.tzinfo is not None


def test_default_publish_at_rolls_to_next_day_when_past():
    now = datetime(2026, 5, 21, 21, 0, tzinfo=timezone.utc)  # past 20:30 UTC
    ts = default_publish_at(now=now)
    parsed = datetime.fromisoformat(ts)
    assert parsed.date() > now.date()


# ----- build_episode_meta -------------------------------------------------


def test_build_meta_uses_script_title_first(tmp_path: Path):
    _write_session(
        tmp_path, "s_t1",
        beats=[_beat("b1", headline="ignored fallback")],
        rendered_beat_ids=["b1"],
        script_title="The Real Title",
    )
    meta = build_episode_meta("s_t1", sessions_dir=tmp_path)
    assert meta.title == "The Real Title"


def test_build_meta_falls_back_to_best_headline(tmp_path: Path):
    _write_session(
        tmp_path, "s_t2",
        beats=[
            _beat("b_low", score=0.3, headline="boring"),
            _beat("b_high", score=0.9, headline="The Big Move"),
        ],
        rendered_beat_ids=["b_low", "b_high"],
    )
    meta = build_episode_meta("s_t2", sessions_dir=tmp_path)
    assert meta.title == "The Big Move"


def test_build_meta_caps_title_at_100_chars(tmp_path: Path):
    long_title = "X" * 200
    _write_session(
        tmp_path, "s_t3",
        beats=[_beat("b1")],
        rendered_beat_ids=["b1"],
        script_title=long_title,
    )
    meta = build_episode_meta("s_t3", sessions_dir=tmp_path)
    assert len(meta.title) == 100


def test_build_meta_sets_publish_at_for_private_only(tmp_path: Path):
    _write_session(
        tmp_path, "s_t4",
        beats=[_beat(f"b{i}") for i in range(3)],
        rendered_beat_ids=[f"b{i}" for i in range(3)],
    )
    private = build_episode_meta("s_t4", sessions_dir=tmp_path, privacy_status="private")
    assert private.publish_at_iso is not None
    public = build_episode_meta("s_t4", sessions_dir=tmp_path, privacy_status="public")
    assert public.publish_at_iso is None


def test_build_meta_includes_video_and_thumbnail_when_present(tmp_path: Path):
    _write_session(
        tmp_path, "s_t5",
        beats=[_beat("b1")], rendered_beat_ids=["b1"],
        has_video=True, has_thumb=True,
    )
    meta = build_episode_meta("s_t5", sessions_dir=tmp_path)
    assert meta.video is not None and meta.video.name == "reel.mp4"
    assert meta.thumbnail is not None and meta.thumbnail.name == "thumb.jpg"


def test_build_meta_omits_missing_video_thumbnail(tmp_path: Path):
    _write_session(
        tmp_path, "s_t6",
        beats=[_beat("b1")], rendered_beat_ids=["b1"],
    )
    meta = build_episode_meta("s_t6", sessions_dir=tmp_path)
    assert meta.video is None
    assert meta.thumbnail is None


# ----- write_meta -------------------------------------------------------


def test_write_meta_round_trip(tmp_path: Path):
    meta = EpisodeMeta(
        session_id="s_w",
        title="t",
        description="d",
        tags=["a"],
        category_id="28",
        privacy_status="private",
        publish_at_iso="2026-05-21T20:30:00+00:00",
        chapters=[Chapter(start_sec=0, title="hi")],
        thumbnail=None, video=None,
    )
    out = tmp_path / "episode.yaml"
    write_meta(meta, out)
    rt = json.loads(out.read_text(encoding="utf-8"))
    assert rt["title"] == "t"
    assert rt["chapters"][0]["stamp"] == "0:00"
