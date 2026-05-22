"""Audio mixer — pure-function tests for plan + command building.

Real-ffmpeg integration is env-gated (RUN_FFMPEG_TESTS=1)."""

from __future__ import annotations

import json
import os
import subprocess
import wave
from pathlib import Path

import pytest

from tradefarm.render.mix import (
    DEFAULT_XFADE_SEC,
    VO_LEAD_IN_SEC,
    MixPlan,
    VoLine,
    build_mix_command,
    mix_session,
    plan_mix,
)


# ----- helpers -----------------------------------------------------------


def _write_session(
    base: Path,
    session_id: str,
    *,
    beats_ids: list[str],
    clip_durations_sec: list[float],
    vo_per_beat: dict[str, list[float]] | None = None,  # beat_id → [line durs]
    silent_reel_dur_sec: float = 60.0,
) -> Path:
    sdir = base / session_id
    (sdir / "clips").mkdir(parents=True, exist_ok=True)
    (sdir / "vo").mkdir(parents=True, exist_ok=True)
    # beats.json — at-timestamps don't matter for the mixer; we use
    # ids to find sidecars and `t` only for ordering.
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": bid,
                    "t": f"2026-05-21T14:0{i}:00+00:00",
                    "kind": "big_fill",
                    "headline": "h",
                    "sub": "s",
                    "duration_sec": clip_durations_sec[i],
                }
                for i, bid in enumerate(beats_ids)
            ]
        )
    )
    for bid, dur in zip(beats_ids, clip_durations_sec, strict=True):
        (sdir / "clips" / f"{bid}.webm").write_bytes(b"")
        (sdir / "clips" / f"{bid}.json").write_text(
            json.dumps(
                {
                    "beat_id": bid,
                    "kind": "big_fill",
                    "scene": "hero",
                    "at": "2026-05-21T14:00:00+00:00",
                    "until": "2026-05-21T14:00:30+00:00",
                    "duration_ms": int(dur * 1000),
                    "scene_ready_at_ms": 1200,
                    "elapsed_ms": int(dur * 1000) + 1200,
                    "viewport": [1920, 1080],
                    "url": "http://x/",
                    "clip": f"{bid}.webm",
                    "captured_at": "2026-05-21T14:00:30+00:00",
                }
            )
        )
    # Placeholder silent_reel.mp4 — for plan_mix tests we monkey-patch
    # ffprobe; for build_mix_command tests we set reel duration directly.
    (sdir / "silent_reel.mp4").write_bytes(b"placeholder")
    # VO wavs + index.json.
    vo_lines = []
    if vo_per_beat:
        for bid, line_durs in vo_per_beat.items():
            for idx, dur in enumerate(line_durs):
                wav_name = f"{bid}_{idx:02d}.wav"
                wav_path = sdir / "vo" / wav_name
                # Write a real (silent) wav so plan_mix can resolve it.
                with wave.open(str(wav_path), "wb") as w:
                    w.setnchannels(1)
                    w.setsampwidth(2)
                    w.setframerate(22050)
                    n = int(dur * 22050)
                    w.writeframes(b"\x00\x00" * n)
                vo_lines.append(
                    {
                        "beat_id": bid,
                        "line_idx": idx,
                        "text": f"line {idx}",
                        "wav": wav_name,
                        "duration_sec": dur,
                        "provider": "silence",
                        "voice": "Test",
                    }
                )
    (sdir / "vo" / "index.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "provider": "silence",
                "voice": "Test",
                "sample_rate": 22050,
                "lines": vo_lines,
            }
        )
    )
    return sdir


def _patch_ffprobe(monkeypatch, duration_sec: float):
    """Make _ffprobe_duration return a fixed value without spawning ffprobe."""
    from tradefarm.render import mix

    monkeypatch.setattr(mix, "_ffprobe_duration", lambda _p: duration_sec)


# ----- plan: onset arithmetic --------------------------------------------


def test_plan_mix_onsets_match_stitcher_xfade_math(tmp_path: Path, monkeypatch):
    """For three 20-second clips with 0.4s xfade between, clip starts
    are 0, 19.6, 39.2. VO line 0 of clip i starts at start_i + 0.5
    (the lead-in)."""
    _patch_ffprobe(monkeypatch, 60.0)
    _write_session(
        tmp_path,
        "s_align",
        beats_ids=["b0", "b1", "b2"],
        clip_durations_sec=[20.0, 20.0, 20.0],
        vo_per_beat={"b0": [3.0], "b1": [3.0], "b2": [3.0]},
    )
    plan = plan_mix(
        session_id="s_align",
        sessions_dir=tmp_path,
        music_path=None,
        xfade_sec=DEFAULT_XFADE_SEC,
    )
    onsets = [round(v.onset_sec, 3) for v in plan.vo_lines]
    expected = [
        0.0 + VO_LEAD_IN_SEC,
        20.0 - DEFAULT_XFADE_SEC + VO_LEAD_IN_SEC,
        (20.0 - DEFAULT_XFADE_SEC) * 2 + VO_LEAD_IN_SEC,
    ]
    assert onsets == [round(e, 3) for e in expected]


def test_plan_mix_threads_multiple_vo_lines_per_beat(tmp_path: Path, monkeypatch):
    """Per-line cursor: onset_i+1 = onset_i + duration_i + 0.1s breath."""
    _patch_ffprobe(monkeypatch, 60.0)
    _write_session(
        tmp_path,
        "s_thread",
        beats_ids=["b0"],
        clip_durations_sec=[30.0],
        vo_per_beat={"b0": [2.0, 3.0, 2.5]},
    )
    plan = plan_mix(
        session_id="s_thread",
        sessions_dir=tmp_path,
        music_path=None,
    )
    o = [round(v.onset_sec, 3) for v in plan.vo_lines]
    # 0.5 lead-in, then +2.0+0.1, then +3.0+0.1 (with float-noise cleanup)
    expected = [
        round(x, 3)
        for x in (
            0.5,
            0.5 + 2.0 + 0.1,
            0.5 + 2.0 + 0.1 + 3.0 + 0.1,
        )
    ]
    assert o == expected


def test_plan_mix_skips_beats_without_sidecar(tmp_path: Path, monkeypatch):
    """beats.json may include beats whose clip never rendered (e.g.
    recap). Those should be silently skipped — no VO laid out for them."""
    _patch_ffprobe(monkeypatch, 60.0)
    sdir = _write_session(
        tmp_path,
        "s_skip",
        beats_ids=["b0", "b_missing"],
        clip_durations_sec=[10.0, 10.0],
        vo_per_beat={"b0": [2.0], "b_missing": [2.0]},
    )
    # Delete the second sidecar to simulate "clip wasn't rendered".
    (sdir / "clips" / "b_missing.json").unlink()
    plan = plan_mix(
        session_id="s_skip",
        sessions_dir=tmp_path,
        music_path=None,
    )
    # b_missing's VO line is still in the index but the planner only
    # threads lines for beats with rendered clips.
    assert all(v.beat_id == "b0" for v in plan.vo_lines)


def test_plan_mix_with_no_vo_returns_empty_lines(tmp_path: Path, monkeypatch):
    _patch_ffprobe(monkeypatch, 60.0)
    _write_session(
        tmp_path,
        "s_novo",
        beats_ids=["b0"],
        clip_durations_sec=[10.0],
        vo_per_beat=None,
    )
    plan = plan_mix(
        session_id="s_novo",
        sessions_dir=tmp_path,
        music_path=None,
    )
    assert plan.vo_lines == []
    assert plan.reel_duration_sec == 60.0


# ----- command builder ----------------------------------------------------


def _make_plan(
    *, vo_lines: list[VoLine] | None = None, music_path: Path | None = None, reel_dur: float = 60.0
) -> MixPlan:
    return MixPlan(
        session_id="s_x",
        silent_reel=Path("silent_reel.mp4"),
        vo_lines=vo_lines or [],
        music_path=music_path,
        out_path=Path("reel.mp4"),
        reel_duration_sec=reel_dur,
    )


def test_build_mix_command_video_only_when_no_vo_no_music():
    plan = _make_plan()
    cmd = build_mix_command(plan)
    # No filter_complex; just stream-copy video, drop audio.
    assert "-filter_complex" not in cmd
    assert "-an" in cmd
    assert "-c:v" in cmd and cmd[cmd.index("-c:v") + 1] == "copy"


def test_build_mix_command_with_vo_only_delays_each_line():
    vo = [
        VoLine(beat_id="b0", line_idx=0, wav=Path("vo/b0_00.wav"), duration_sec=2.0, onset_sec=0.5),
        VoLine(
            beat_id="b1", line_idx=0, wav=Path("vo/b1_00.wav"), duration_sec=2.0, onset_sec=20.0
        ),
    ]
    plan = _make_plan(vo_lines=vo)
    cmd = build_mix_command(plan)
    assert "-filter_complex" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    # Onsets in ms become adelay arguments.
    assert "adelay=500|500" in fc
    assert "adelay=20000|20000" in fc
    # No music branch present.
    assert "sidechaincompress" not in fc
    assert "[mus]" not in fc
    # Output mapping: video copy + aac audio
    assert "-c:a" in cmd and cmd[cmd.index("-c:a") + 1] == "aac"


def test_build_mix_command_with_music_includes_loop_and_duck():
    vo = [
        VoLine(beat_id="b0", line_idx=0, wav=Path("vo/b0_00.wav"), duration_sec=2.0, onset_sec=0.5)
    ]
    plan = _make_plan(vo_lines=vo, music_path=Path("music/bed.mp3"))
    cmd = build_mix_command(plan)
    # -stream_loop -1 attached to the music input
    assert "-stream_loop" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc
    assert "atrim=duration=" in fc


def test_build_mix_command_with_music_no_vo_just_loops_music():
    plan = _make_plan(music_path=Path("music/bed.mp3"))
    cmd = build_mix_command(plan)
    assert "-stream_loop" in cmd
    fc = cmd[cmd.index("-filter_complex") + 1]
    # No duck branch when there's no VO sidechain key.
    assert "sidechaincompress" not in fc


def test_build_mix_command_raises_when_reel_duration_unknown():
    plan = _make_plan(reel_dur=0.0)
    with pytest.raises(ValueError, match="reel duration unknown"):
        build_mix_command(plan)


# ----- session-level short-circuits --------------------------------------


def test_mix_session_errors_when_silent_reel_missing(tmp_path: Path):
    result = mix_session("never_exists", sessions_dir=tmp_path)
    assert not result.ok
    assert "silent_reel.mp4 not found" in (result.error or "")


def test_mix_session_dry_run_skips_ffmpeg(tmp_path: Path, monkeypatch):
    _patch_ffprobe(monkeypatch, 30.0)
    _write_session(
        tmp_path,
        "s_dry",
        beats_ids=["b0"],
        clip_durations_sec=[10.0],
        vo_per_beat={"b0": [2.0]},
    )
    result = mix_session("s_dry", sessions_dir=tmp_path, dry_run=True)
    assert result.ok
    assert result.plan is not None
    assert result.plan.vo_lines  # plan was built
    # No output file should exist.
    assert not result.out_path.exists()


# ----- env-gated integration test ----------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_FFMPEG_TESTS") != "1",
    reason="Set RUN_FFMPEG_TESTS=1 to enable (requires ffmpeg + ffprobe).",
)
def test_integration_mix_silent_reel_with_vo(tmp_path: Path):
    """Synthesise a 6-second silent reel + one short VO line, mix
    them, assert the output reel.mp4 lands."""
    sdir = tmp_path / "s_int"
    sdir.mkdir()
    # Solid-colour 6s mp4 acts as silent_reel.
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=320x180:r=30:d=6",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(sdir / "silent_reel.mp4"),
        ],
        check=True,
    )
    # Beats + sidecar pointing at a 6s clip starting at 0.
    (sdir / "clips").mkdir()
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b0",
                    "t": "2026-05-21T14:00:00+00:00",
                    "kind": "open",
                    "headline": "h",
                    "sub": "s",
                    "duration_sec": 6,
                }
            ]
        )
    )
    (sdir / "clips" / "b0.json").write_text(
        json.dumps(
            {
                "beat_id": "b0",
                "kind": "open",
                "scene": "hero",
                "at": "x",
                "until": "x",
                "duration_ms": 6000,
                "scene_ready_at_ms": 0,
                "elapsed_ms": 6000,
                "viewport": [320, 180],
                "url": "x",
                "clip": "b0.webm",
                "captured_at": "x",
            }
        )
    )
    # 1s synthetic VO wav.
    (sdir / "vo").mkdir()
    with wave.open(str(sdir / "vo" / "b0_00.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * 22050)
    (sdir / "vo" / "index.json").write_text(
        json.dumps(
            {
                "session_id": "s_int",
                "provider": "silence",
                "voice": "Test",
                "sample_rate": 22050,
                "lines": [
                    {
                        "beat_id": "b0",
                        "line_idx": 0,
                        "text": "test",
                        "wav": "b0_00.wav",
                        "duration_sec": 1.0,
                        "provider": "silence",
                        "voice": "Test",
                    }
                ],
            }
        )
    )
    result = mix_session("s_int", sessions_dir=tmp_path)
    assert result.ok, result.error
    assert result.out_path is not None and result.out_path.is_file()
