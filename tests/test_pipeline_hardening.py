"""Regression tests for the final-review fixes across the VOD pipeline.

Covers:
  - session_id sanitisation (path-traversal guard)
  - drawtext extra-escape (filter-graph injection guard)
  - mix VO-onset arithmetic with skipped beats
  - reel.meta.json persistence (stitch → mix + metadata)
"""
from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from tradefarm.session import replay_query
from tradefarm.session.replay_query import _require_safe_session_id


# ----- session_id sanitisation -------------------------------------------


@pytest.mark.parametrize("bad", [
    "../etc/passwd",
    "..\\Windows\\win.ini",
    "../../out/sessions/legit",
    ".hidden",
    "",
    "name with spaces",
    "name\x00null",
    "name\nnewline",
    "name/slash",
    "name\\backslash",
    "name:colon",
    "name'quote",
    "name`backtick",
    "x" * 200,  # too long
])
def test_session_id_rejects_unsafe(bad):
    with pytest.raises(ValueError):
        _require_safe_session_id(bad)


@pytest.mark.parametrize("ok", [
    "s_2026-05-21_a3f2",
    "s_smoke",
    "demo.test",
    "A1",
    "name_with_underscores-and-dashes.123",
])
def test_session_id_accepts_safe(ok):
    assert _require_safe_session_id(ok) == ok


def test_load_manifest_rejects_traversal_attempt(tmp_path: Path):
    """Even with a manifest.json sitting at the would-be target path,
    the sanitiser refuses to resolve it."""
    evil_dir = tmp_path / ".." / "evil"
    with pytest.raises(ValueError):
        replay_query.load_manifest("../evil", sessions_dir=tmp_path)


# ----- drawtext extra escapes --------------------------------------------


def test_drawtext_escape_blocks_filter_graph_injection():
    from tradefarm.render.stitch import _ff_text
    # An attempt to break out of `text='…'` and inject another filter.
    payload = "Bob,drawtext=text='lol':x=0:y=0,setpts="
    out = _ff_text(payload)
    # `,` was the primary injection vector — make sure it's escaped.
    assert "\\," in out
    # And the other separators we tightened.
    for token in ("[", "]", ";"):
        assert ("\\" + token) in _ff_text(f"x{token}y")


def test_drawtext_escape_doesnt_break_normal_punctuation():
    from tradefarm.render.stitch import _ff_text
    # The escaped form contains the real text, just with backslash prefixes.
    out = _ff_text("Mei takes #1 — a +1.84% day")
    assert "Mei takes #1" in out
    # No new commas introduced (only the literal one, escaped to \,).
    assert out.count(",") == 0  # the dash and digits don't have commas


# ----- mix VO onset arithmetic with skipped beats ------------------------


def _build_session_for_mix(
    tmp_path: Path,
    session_id: str,
    *,
    all_beat_ids: list[str],
    rendered_beat_ids: list[str],
    clip_durations_sec: dict[str, float],
    vo_per_beat: dict[str, list[float]],
) -> Path:
    sdir = tmp_path / session_id
    (sdir / "clips").mkdir(parents=True, exist_ok=True)
    (sdir / "vo").mkdir(parents=True, exist_ok=True)
    # beats.json — every beat in chronological order.
    (sdir / "beats.json").write_text(json.dumps([
        {"id": bid, "t": f"2026-05-21T14:0{i}:00+00:00",
         "kind": "big_fill", "headline": f"h{i}", "sub": "s",
         "duration_sec": int(clip_durations_sec.get(bid, 30))}
        for i, bid in enumerate(all_beat_ids)
    ]))
    # Sidecars only for rendered beats.
    for bid in rendered_beat_ids:
        (sdir / "clips" / f"{bid}.webm").write_bytes(b"")
        (sdir / "clips" / f"{bid}.json").write_text(json.dumps({
            "beat_id": bid, "kind": "big_fill", "scene": "hero",
            "at": "x", "until": "x",
            "duration_ms": int(clip_durations_sec[bid] * 1000),
            "scene_ready_at_ms": 1200,
            "elapsed_ms": int(clip_durations_sec[bid] * 1000) + 1200,
            "viewport": [1920, 1080], "url": "x",
            "clip": f"{bid}.webm", "captured_at": "x",
        }))
    # placeholder silent_reel.
    (sdir / "silent_reel.mp4").write_bytes(b"")
    # VO wavs + index.json (for every beat, including skipped — the
    # script writer doesn't know which beats were rendered).
    vo_rows = []
    for bid, line_durs in vo_per_beat.items():
        for idx, dur in enumerate(line_durs):
            wav_name = f"{bid}_{idx:02d}.wav"
            wav_path = sdir / "vo" / wav_name
            with wave.open(str(wav_path), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(22050)
                w.writeframes(b"\x00\x00" * int(dur * 22050))
            vo_rows.append({
                "beat_id": bid, "line_idx": idx,
                "text": "x", "wav": wav_name,
                "duration_sec": dur, "provider": "silence", "voice": "Test",
            })
    (sdir / "vo" / "index.json").write_text(json.dumps({
        "session_id": session_id, "provider": "silence", "voice": "Test",
        "sample_rate": 22050, "lines": vo_rows,
    }))
    return sdir


def test_mix_vo_onsets_no_drift_when_recap_skipped(tmp_path: Path, monkeypatch):
    """The regression: when beats.json has 4 beats but only the first 3
    were rendered (recap skipped by default), the mixer used to subtract
    an extra xfade after clip 2 — drifting every subsequent VO line by
    0.4s. Fix re-computes onsets only over rendered beats."""
    from tradefarm.render import mix as mix_mod
    monkeypatch.setattr(mix_mod, "_ffprobe_duration", lambda _p: 90.0)
    _build_session_for_mix(
        tmp_path, "s_skip",
        all_beat_ids=["b1", "b2", "b3", "b_recap"],
        rendered_beat_ids=["b1", "b2", "b3"],  # recap skipped
        clip_durations_sec={"b1": 30.0, "b2": 30.0, "b3": 30.0},
        vo_per_beat={"b1": [2.0], "b2": [2.0], "b3": [2.0],
                      "b_recap": [2.0]},
    )
    plan = mix_mod.plan_mix(
        session_id="s_skip", sessions_dir=tmp_path,
        music_path=None, xfade_sec=0.4,
    )
    # Three onsets, one per rendered beat. Recap's VO is in the index
    # but has no clip, so it must NOT appear.
    onsets = [round(v.onset_sec, 3) for v in plan.vo_lines]
    expected = [
        0.5,                       # b1 starts at 0 + 0.5 lead-in
        30.0 - 0.4 + 0.5,          # b2 starts at 29.6 + 0.5
        (30.0 - 0.4) * 2 + 0.5,    # b3 starts at 59.2 + 0.5
    ]
    assert onsets == [round(e, 3) for e in expected]
    assert all(v.beat_id != "b_recap" for v in plan.vo_lines)


# ----- reel.meta.json persistence ----------------------------------------


def test_load_reel_meta_returns_empty_when_missing(tmp_path: Path):
    from tradefarm.render.stitch import load_reel_meta
    assert load_reel_meta(tmp_path / "no-such-session") == {}


def test_load_reel_meta_reads_persisted_xfade(tmp_path: Path):
    from tradefarm.render.stitch import load_reel_meta
    sdir = tmp_path / "s_xfade"
    sdir.mkdir()
    (sdir / "reel.meta.json").write_text(json.dumps({
        "xfade_sec": 0.6, "fps": 30, "width": 1920, "height": 1080,
    }))
    meta = load_reel_meta(sdir)
    assert meta["xfade_sec"] == 0.6


def test_mix_session_honours_persisted_xfade_when_cli_omits_it(
    tmp_path: Path, monkeypatch,
):
    """If the stitcher wrote reel.meta.json with xfade=0.6 and the
    operator forgets `--xfade 0.6` to the mixer, the mixer should pick
    up 0.6 anyway — not silently use the 0.4 default."""
    from tradefarm.render import mix as mix_mod
    monkeypatch.setattr(mix_mod, "_ffprobe_duration", lambda _p: 60.0)
    sdir = _build_session_for_mix(
        tmp_path, "s_persist",
        all_beat_ids=["b1", "b2"],
        rendered_beat_ids=["b1", "b2"],
        clip_durations_sec={"b1": 30.0, "b2": 30.0},
        vo_per_beat={"b1": [1.0], "b2": [1.0]},
    )
    (sdir / "reel.meta.json").write_text(json.dumps({"xfade_sec": 0.6}))
    result = mix_mod.mix_session("s_persist", sessions_dir=tmp_path, dry_run=True)
    assert result.ok and result.plan is not None
    # Second clip's reel-start = 30 - 0.6 = 29.4 → onset = 29.9
    onsets = [round(v.onset_sec, 3) for v in result.plan.vo_lines]
    assert onsets == [0.5, 29.9]


def test_metadata_chapters_honour_persisted_xfade(tmp_path: Path):
    """Same idea on the metadata side: the chapter markers should land
    at the stitcher's actual offsets, not the CLI default."""
    from tradefarm.yt import metadata
    sdir = tmp_path / "s_chap"
    (sdir / "clips").mkdir(parents=True)
    (sdir / "beats.json").write_text(json.dumps([
        {"id": f"b{i}", "t": f"2026-05-21T14:0{i}:00+00:00",
         "kind": "big_fill", "headline": f"h{i}", "sub": "s",
         "duration_sec": 30}
        for i in range(3)
    ]))
    for i in range(3):
        (sdir / "clips" / f"b{i}.json").write_text(json.dumps({
            "beat_id": f"b{i}", "kind": "big_fill", "scene": "hero",
            "at": "x", "until": "x", "duration_ms": 30000,
            "scene_ready_at_ms": 1200, "elapsed_ms": 31200,
            "viewport": [1920, 1080], "url": "x",
            "clip": f"b{i}.webm", "captured_at": "x",
        }))
    (sdir / "reel.meta.json").write_text(json.dumps({"xfade_sec": 0.5}))
    meta = metadata.build_episode_meta("s_chap", sessions_dir=tmp_path)
    # Three chapters at 0, 30 - 0.5 = 29.5 → rounds to 30 (int), and
    # 59.0 → 59. The exact rounded values match the xfade=0.5 timeline.
    assert [c.start_sec for c in meta.chapters] == [0, 30, 59]
