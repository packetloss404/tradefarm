"""ffmpeg stitcher — pure-function tests for plan + command builders.

The actual ffmpeg-driven stitch is env-gated (RUN_FFMPEG_TESTS=1)
since CI may not have ffmpeg on PATH. The integration test synthesises
two solid-colour clips on the fly so it doesn't depend on the headless
renderer.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tradefarm.render.stitch import (
    DEFAULT_XFADE_SEC,
    ClipPlan,
    StitchPlan,
    build_normalize_command,
    build_pairwise_commands,
    build_xfade_command,
    caption_filter,
    discover_font,
    ffmpeg_info,
    plan_stitch,
    stitch_session,
)


# ----- helpers -------------------------------------------------------------


def _write_session(
    base: Path,
    session_id: str,
    *,
    beats: list[dict],
    clips: list[tuple[str, dict]],  # (beat_id, sidecar dict)
) -> Path:
    sdir = base / session_id
    (sdir / "clips").mkdir(parents=True, exist_ok=True)
    (sdir / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
    for beat_id, sidecar in clips:
        (sdir / "clips" / f"{beat_id}.webm").write_bytes(b"placeholder")
        (sdir / "clips" / f"{beat_id}.json").write_text(json.dumps(sidecar), encoding="utf-8")
    return sdir


def _beat(beat_id: str, t: str, headline: str = "hl", duration: int = 10) -> dict:
    return {
        "id": beat_id, "t": t, "kind": "big_fill", "scene_hint": "hero",
        "duration_sec": duration, "score": 0.7,
        "headline": headline, "sub": "sub", "event_refs": [], "agent_ids": [], "metadata": {},
    }


def _sidecar(beat_id: str, *, scene_ready_at_ms: int = 1200, duration_ms: int = 10_000) -> dict:
    return {
        "beat_id": beat_id, "kind": "big_fill", "scene": "hero",
        "at": "2026-05-21T14:00:00+00:00", "until": "2026-05-21T14:00:10+00:00",
        "duration_ms": duration_ms,
        "scene_ready_at_ms": scene_ready_at_ms,
        "elapsed_ms": duration_ms + scene_ready_at_ms,
        "viewport": [1920, 1080], "url": "http://x/",
        "clip": f"{beat_id}.webm",
        "captured_at": "2026-05-21T14:00:30+00:00",
    }


# ----- plan ----------------------------------------------------------------


def test_plan_orders_by_beat_timestamp(tmp_path: Path):
    """plan_stitch must order by the beat's `t`, not the sidecar's
    filename. Otherwise b_op... sorts before b_bigfill_3 alphabetically
    even though it fired later in the day."""
    base = tmp_path / "out"
    beats = [
        _beat("b_late", "2026-05-21T15:00:00+00:00"),
        _beat("b_early", "2026-05-21T10:00:00+00:00"),
    ]
    clips = [
        ("b_late", _sidecar("b_late")),
        ("b_early", _sidecar("b_early")),
    ]
    sdir = _write_session(base, "s_order", beats=beats, clips=clips)
    plan = plan_stitch(
        session_id="s_order",
        clips_dir=sdir / "clips",
        beats_path=sdir / "beats.json",
        out_path=sdir / "silent_reel.mp4",
    )
    assert [c.beat_id for c in plan.clips] == ["b_early", "b_late"]


def test_plan_trims_preroll_with_pad(tmp_path: Path):
    """The trim point should be scene_ready_at_ms - PREROLL_PAD_MS so
    the very first frame isn't mid-animation. Sidecar with 1200ms
    ready time → trim ~1050ms."""
    base = tmp_path / "out"
    sdir = _write_session(
        base, "s_trim",
        beats=[_beat("b1", "2026-05-21T14:00:00+00:00")],
        clips=[("b1", _sidecar("b1", scene_ready_at_ms=1200))],
    )
    plan = plan_stitch(
        session_id="s_trim",
        clips_dir=sdir / "clips",
        beats_path=sdir / "beats.json",
        out_path=sdir / "silent_reel.mp4",
    )
    assert len(plan.clips) == 1
    assert plan.clips[0].trim_start_sec == pytest.approx(1.05, abs=0.001)


def test_plan_skips_orphan_sidecar_or_clip(tmp_path: Path):
    """Sidecar with no .webm or .webm with no sidecar → not in plan."""
    base = tmp_path / "out"
    sdir = base / "s_orphan"
    (sdir / "clips").mkdir(parents=True)
    (sdir / "beats.json").write_text(json.dumps([_beat("b1", "2026-05-21T14:00:00+00:00")]))
    # sidecar without webm
    (sdir / "clips" / "b1.json").write_text(json.dumps(_sidecar("b1")))
    # webm without sidecar
    (sdir / "clips" / "b2.webm").write_bytes(b"x")
    plan = plan_stitch(
        session_id="s_orphan",
        clips_dir=sdir / "clips",
        beats_path=sdir / "beats.json",
        out_path=sdir / "out.mp4",
    )
    assert plan.clips == []


def test_plan_falls_back_to_sidecar_when_beats_json_absent(tmp_path: Path):
    """A session whose beats.json was deleted should still plan from
    sidecars alone — headline/sub will just be empty."""
    base = tmp_path / "out"
    sdir = base / "s_nobeats"
    (sdir / "clips").mkdir(parents=True)
    (sdir / "clips" / "b1.webm").write_bytes(b"x")
    (sdir / "clips" / "b1.json").write_text(json.dumps(_sidecar("b1")))
    plan = plan_stitch(
        session_id="s_nobeats",
        clips_dir=sdir / "clips",
        beats_path=sdir / "beats.json",  # doesn't exist
        out_path=sdir / "out.mp4",
    )
    assert [c.beat_id for c in plan.clips] == ["b1"]
    assert plan.clips[0].headline == ""


# ----- command builders ----------------------------------------------------


def _make_plan(clips: list[ClipPlan], *, captions: bool = True, font: str | None = "/x.ttf") -> StitchPlan:
    return StitchPlan(
        session_id="s_x", clips=clips,
        out_path=Path("out.mp4"),
        intermediates_dir=Path("intermediates"),
        captions=captions, font_path=font,
    )


def test_normalize_command_carries_trim_and_filters():
    clip = ClipPlan(
        beat_id="b1", src=Path("clips/b1.webm"), sidecar=Path("clips/b1.json"),
        trim_start_sec=1.0, duration_sec=15.0,
        headline="hl", sub="sub", kind="big_fill",
    )
    plan = _make_plan([clip])
    cmd = build_normalize_command(clip, plan=plan, out_path=Path("interm.mp4"))
    # the -vf filter chain must contain trim + setpts + scale + setsar
    vf_idx = cmd.index("-vf") + 1
    vf = cmd[vf_idx]
    assert "trim=start=1.000:duration=15.000" in vf
    assert "fps=30" in vf and "scale=1920:1080" in vf
    assert "setsar=1" in vf
    assert "-an" in cmd  # no audio
    assert cmd[0] == "ffmpeg" and cmd[-1] == "interm.mp4"


def test_xfade_command_chains_offsets_correctly():
    """For 3 clips of 10s each with 0.4s xfade, offsets should be
    9.6 (first fade ends just before clip 0's tail) and 19.2."""
    clips = [
        ClipPlan(beat_id=f"b{i}", src=Path("x"), sidecar=Path("y"),
                 trim_start_sec=0, duration_sec=10, headline="", sub="", kind="")
        for i in range(3)
    ]
    plan = _make_plan(clips, captions=False)
    cmd = build_xfade_command([Path(f"i{i}.mp4") for i in range(3)], plan=plan, out_path=Path("o.mp4"))
    fc_idx = cmd.index("-filter_complex") + 1
    fc = cmd[fc_idx]
    assert "duration=0.400:offset=9.600" in fc
    assert "duration=0.400:offset=19.200" in fc
    assert "-map" in cmd
    # The map target must be one of vout, vx0, vx1 (chain output)
    map_target = cmd[cmd.index("-map") + 1]
    assert map_target.startswith("[v") and map_target.endswith("]")


def test_xfade_command_single_clip_no_chain():
    clip = ClipPlan(beat_id="b1", src=Path("x"), sidecar=Path("y"),
                    trim_start_sec=0, duration_sec=10, headline="hl", sub="", kind="")
    plan = _make_plan([clip], captions=False)
    cmd = build_xfade_command([Path("i.mp4")], plan=plan, out_path=Path("o.mp4"))
    # single clip → -vf, not -filter_complex
    assert "-filter_complex" not in cmd
    assert "-vf" in cmd


def test_xfade_command_includes_captions_when_font_present():
    clips = [
        ClipPlan(beat_id=f"b{i}", src=Path("x"), sidecar=Path("y"),
                 trim_start_sec=0, duration_sec=10,
                 headline=f"Headline {i}", sub=f"sub {i}", kind="big_fill")
        for i in range(2)
    ]
    plan = _make_plan(clips, captions=True, font="/path/to/font.ttf")
    cmd = build_xfade_command([Path(f"i{i}.mp4") for i in range(2)], plan=plan, out_path=Path("o.mp4"))
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "drawtext" in fc
    assert "Headline 0" in fc and "Headline 1" in fc


def test_pairwise_commands_step_count():
    clips = [
        ClipPlan(beat_id=f"b{i}", src=Path("x"), sidecar=Path("y"),
                 trim_start_sec=0, duration_sec=8, headline="", sub="", kind="")
        for i in range(4)
    ]
    plan = _make_plan(clips, captions=False)
    steps = build_pairwise_commands(
        [Path(f"i{i}.mp4") for i in range(4)],
        plan=plan, work_dir=Path("/tmp/wd"), out_path=Path("o.mp4"),
    )
    # n clips → n-1 xfade steps
    assert len(steps) == 3
    # last step writes to the final output
    assert steps[-1][1] == Path("o.mp4")


# ----- caption filter / escaping ------------------------------------------


def test_caption_filter_empty_when_no_headline():
    assert caption_filter(
        headline="", sub="anything", t_start=0, t_end=10, font_path="/x.ttf",
    ) == ""


def test_caption_filter_empty_when_no_font():
    assert caption_filter(
        headline="hi", sub="", t_start=0, t_end=10, font_path=None,
    ) == ""


def test_caption_filter_escapes_quote_and_percent():
    """Headlines may contain real apostrophes from natural-language
    output ("Mei takes #1 after 47 days · Brian's run") and percent
    signs from the recap (+1.84%). drawtext wants `\\'` (two chars: a
    backslash and a quote) — not the over-escaped `\\\\\\'` an earlier
    version produced, which rendered the backslash on-screen."""
    out = caption_filter(
        headline="Brian's run · +5%",
        sub="",
        t_start=0, t_end=5, font_path="/x.ttf",
    )
    # exactly one backslash + the quote (no doubled-backslash). Search
    # for the substring inside the text='…' segment so other backslashes
    # don't confuse the assertion.
    assert "Brian\\'s run" in out
    assert "+5\\%" in out
    # negative — over-escape is the regression we're guarding against
    assert "Brian\\\\'s" not in out


def test_caption_filter_strips_crlf_from_headline():
    """drawtext leaves \\n as a literal — visible box-glyph in the clip.
    Strip them at escape time."""
    out = caption_filter(
        headline="line one\nline two\r\nthree",
        sub="", t_start=0, t_end=5, font_path="/x.ttf",
    )
    # all three lines collapsed onto one
    assert "line one line two three" in out
    assert "\n" not in out and "\r" not in out


def test_xfade_caption_window_ends_before_outgoing_fade():
    """If captions used `end = start + duration`, the previous caption
    would still be on screen during the 0.4s xfade into the next clip,
    stacking two captions visibly. End for non-last clips must trim by
    one fade."""
    clips = [
        ClipPlan(beat_id=f"b{i}", src=Path("x"), sidecar=Path("y"),
                 trim_start_sec=0, duration_sec=10,
                 headline=f"H{i}", sub="", kind="big_fill")
        for i in range(3)
    ]
    plan = _make_plan(clips, captions=True, font="/x.ttf")
    cmd = build_xfade_command([Path(f"i{i}.mp4") for i in range(3)], plan=plan, out_path=Path("o.mp4"))
    fc = cmd[cmd.index("-filter_complex") + 1]
    # Clip 0: 0 → 9.6 (10 - 0.4 fade-out lead)
    # Clip 1: 9.6 → 19.2 (clip 1 starts at 10 - 0.4 = 9.6, ends at 19.6,
    #         clean end at 19.6 - 0.4 = 19.2)
    # Clip 2 (last): no trim → 19.2 → 29.2
    assert "between(t,0.000,9.600)" in fc
    assert "between(t,9.600,19.200)" in fc
    assert "between(t,19.200,29.200)" in fc


def test_caption_filter_includes_enable_window():
    out = caption_filter(
        headline="hl", sub="", t_start=12.5, t_end=42.0, font_path="/x.ttf",
    )
    assert "between(t,12.500,42.000)" in out


def test_caption_filter_includes_sub_when_present():
    out = caption_filter(
        headline="hl", sub="some sub", t_start=0, t_end=10, font_path="/x.ttf",
    )
    # two drawtext expressions, comma-separated
    assert out.count("drawtext=") == 2


# ----- discovery -----------------------------------------------------------


def test_discover_font_returns_path_or_none():
    found = discover_font()
    if found is not None:
        assert Path(found).is_file()


def test_ffmpeg_info_doesnt_raise_when_missing(monkeypatch):
    """Even if ffmpeg is absent, the probe must return cleanly."""
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    # We can't easily fake the subprocess invocation, so just sanity-check
    # the actual return type contract.
    ok, info = ffmpeg_info()
    assert isinstance(ok, bool) and isinstance(info, str)


# ----- session-level short-circuits ---------------------------------------


def test_stitch_session_returns_error_when_no_clips(tmp_path: Path):
    sdir = tmp_path / "s_empty"
    (sdir / "clips").mkdir(parents=True)
    (sdir / "beats.json").write_text("[]")
    result = stitch_session("s_empty", sessions_dir=tmp_path)
    assert not result.ok
    assert "no clips" in (result.error or "")


def test_stitch_session_dry_run_doesnt_invoke_ffmpeg(tmp_path: Path):
    base = tmp_path / "out"
    sdir = _write_session(
        base, "s_dry",
        beats=[_beat("b1", "2026-05-21T14:00:00+00:00")],
        clips=[("b1", _sidecar("b1"))],
    )
    result = stitch_session("s_dry", sessions_dir=base, dry_run=True)
    assert result.ok
    assert result.out_path == sdir / "silent_reel.mp4"
    # No file should have been produced.
    assert not result.out_path.exists()


# ----- env-gated integration test -----------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_FFMPEG_TESTS") != "1",
    reason="Set RUN_FFMPEG_TESTS=1 to enable (requires system ffmpeg).",
)
def test_integration_stitch_two_solid_clips(tmp_path: Path):
    """Synthesise two short solid-colour webm clips, write beats +
    sidecars, run the stitcher, assert the silent_reel.mp4 lands."""
    ok, _ = ffmpeg_info()
    if not ok:
        pytest.skip("ffmpeg not on PATH")
    sdir = tmp_path / "s_int"
    (sdir / "clips").mkdir(parents=True)
    # Two 3-second test clips, distinct colours so a manual eyeball
    # confirms the order.
    for beat_id, color in [("b1", "red"), ("b2", "blue")]:
        subprocess.run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c={color}:s=320x180:r=30:d=3",
            "-c:v", "libvpx", "-b:v", "400k",
            str(sdir / "clips" / f"{beat_id}.webm"),
        ], check=True)
        (sdir / "clips" / f"{beat_id}.json").write_text(
            json.dumps(_sidecar(beat_id, scene_ready_at_ms=0, duration_ms=2_500))
        )
    (sdir / "beats.json").write_text(json.dumps([
        _beat("b1", "2026-05-21T14:00:00+00:00", headline="First clip", duration=2),
        _beat("b2", "2026-05-21T14:00:05+00:00", headline="Second clip", duration=2),
    ]))
    result = stitch_session(
        "s_int", sessions_dir=tmp_path,
        width=320, height=180, fps=30,
        captions=False,  # solid colours don't need text
    )
    assert result.ok, result.error
    assert result.out_path is not None and result.out_path.is_file()
    assert result.out_path.stat().st_size > 0
