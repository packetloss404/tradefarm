"""Headless renderer — pure-function tests (planning, URL building).

The actual Playwright-driven capture is gated behind an env var so it
doesn't run in plain `uv run pytest`. To run the integration test:

    RUN_BROWSER_TESTS=1 uv run pytest tests/render/test_headless.py

…with a stream/ dev server running on :5180 and Chromium installed
(`uv run playwright install chromium`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tradefarm.render.headless import (
    build_url,
    plan_jobs,
    render_job_as_dict,
)


def _beat(
    *,
    id: str = "b_test",
    kind: str = "big_fill",
    scene: str = "hero",
    t: str = "2026-05-19T14:00:00+00:00",
    duration: int = 30,
) -> dict:
    return {
        "id": id,
        "t": t,
        "kind": kind,
        "scene_hint": scene,
        "duration_sec": duration,
        "score": 0.8,
        "headline": "test",
    }


# ----- URL contract ---------------------------------------------------------


def test_build_url_carries_every_query_param():
    url = build_url(
        stream_base="http://localhost:5180/",
        session_id="s_abc",
        at="2026-05-19T14:00:00+00:00",
        until="2026-05-19T14:00:30+00:00",
        scene="hero",
        speed=60.0,
    )
    assert url.startswith("http://localhost:5180/?")
    for fragment in ("replay=s_abc", "scene=hero", "speed=60.0", "at=", "until="):
        assert fragment in url, fragment


def test_build_url_normalises_trailing_slash():
    no_slash = build_url(
        stream_base="http://localhost:5180",
        session_id="s_abc",
        at="2026-05-19T14:00:00+00:00",
        until="2026-05-19T14:00:30+00:00",
        scene="hero",
        speed=60.0,
    )
    with_slash = build_url(
        stream_base="http://localhost:5180/",
        session_id="s_abc",
        at="2026-05-19T14:00:00+00:00",
        until="2026-05-19T14:00:30+00:00",
        scene="hero",
        speed=60.0,
    )
    assert no_slash == with_slash


# ----- planning -------------------------------------------------------------


def test_plan_jobs_emits_one_job_per_beat_and_computes_until(tmp_path: Path):
    beats = [
        _beat(id="b1", kind="big_fill", scene="hero", duration=30),
        _beat(id="b2", kind="streak", scene="leaderboard", duration=20),
    ]
    jobs, skipped = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    assert skipped == []
    assert [j.beat_id for j in jobs] == ["b1", "b2"]
    assert jobs[0].scene == "hero"
    assert jobs[1].scene == "leaderboard"
    # until = at + duration_sec
    assert jobs[0].until.endswith(":00:30+00:00")
    assert jobs[1].until.endswith(":00:20+00:00")
    # out paths land under clips_dir with .webm + .json
    assert jobs[0].out_path.name == "b1.webm"
    assert jobs[0].sidecar_path.name == "b1.json"


def test_plan_jobs_skips_recap_by_default(tmp_path: Path):
    """RecapScene depends on /api/recap/today which isn't replay-aware
    yet — render it and the clip mixes live data. Skip until fixed."""
    beats = [
        _beat(id="b_open", kind="open", scene="hero"),
        _beat(id="b_recap", kind="recap", scene="recap"),
        _beat(id="b_div", kind="divergence", scene="brain"),
    ]
    jobs, skipped = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    assert [j.beat_id for j in jobs] == ["b_open", "b_div"]
    assert skipped == ["b_recap"]


def test_plan_jobs_skips_unknown_scene(tmp_path: Path):
    """A beat whose scene_hint isn't in the replay-supported set is
    skipped rather than rendered into something broken."""
    beats = [
        _beat(id="b_chapter", kind="chapter_change", scene="chapter"),
        _beat(id="b_hero", kind="big_fill", scene="hero"),
    ]
    jobs, skipped = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    assert [j.beat_id for j in jobs] == ["b_hero"]
    assert skipped == ["b_chapter"]


def test_plan_jobs_honours_scene_override(tmp_path: Path):
    """Operator can force a different scene for a given kind."""
    beats = [_beat(id="b1", kind="big_fill", scene="hero", duration=30)]
    jobs, _ = plan_jobs(
        session_id="s_x",
        beats=beats,
        clips_dir=tmp_path / "clips",
        scene_overrides={"big_fill": "leaderboard"},
    )
    assert jobs[0].scene == "leaderboard"
    assert "scene=leaderboard" in jobs[0].url


def test_plan_jobs_falls_back_to_kind_default_when_scene_hint_missing(tmp_path: Path):
    """If a beat is missing scene_hint, the kind→scene default map fills in."""
    beats = [
        {"id": "b1", "t": "2026-05-19T14:00:00+00:00", "kind": "divergence", "duration_sec": 28}
    ]
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    assert jobs[0].scene == "brain"


def test_plan_jobs_carries_through_session_id_and_speed(tmp_path: Path):
    beats = [_beat(id="b1")]
    jobs, _ = plan_jobs(
        session_id="my_session",
        beats=beats,
        clips_dir=tmp_path / "clips",
        speed=120.0,
    )
    assert "replay=my_session" in jobs[0].url
    assert "speed=120.0" in jobs[0].url


def test_render_job_as_dict_is_json_serialisable(tmp_path: Path):
    beats = [_beat(id="b1")]
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    payload = render_job_as_dict(jobs[0])
    # round-trips through json
    rt = json.loads(json.dumps(payload))
    assert rt["beat_id"] == "b1"
    assert rt["url"].startswith("http://localhost:5180/")


def test_plan_jobs_scene_override_lands_in_url(tmp_path: Path):
    beats = [_beat(id="b1", kind="big_fill", scene="hero")]
    jobs, _ = plan_jobs(
        session_id="s_x",
        beats=beats,
        clips_dir=tmp_path / "clips",
        scene_overrides={"big_fill": "brain"},
    )
    assert "scene=brain" in jobs[0].url


def test_plan_jobs_allow_scenes_lets_recap_through_when_requested(tmp_path: Path):
    """--include-recap path: caller widens allow_scenes AND empties
    skip_kinds; both have to be honoured for the recap beat to plan."""
    from tradefarm.render.headless import SCENES_WITH_REPLAY_SUPPORT

    beats = [_beat(id="b_recap", kind="recap", scene="recap")]
    jobs, skipped = plan_jobs(
        session_id="s_x",
        beats=beats,
        clips_dir=tmp_path / "clips",
        skip_kinds=frozenset(),
        allow_scenes=SCENES_WITH_REPLAY_SUPPORT | {"recap"},
    )
    assert [j.beat_id for j in jobs] == ["b_recap"]
    assert skipped == []


def test_plan_jobs_drops_beat_with_missing_id(tmp_path: Path):
    beats = [
        {
            "t": "2026-05-19T14:00:00+00:00",
            "kind": "big_fill",
            "scene_hint": "hero",
            "duration_sec": 10,
        },
        _beat(id="b_ok"),
    ]
    jobs, _ = plan_jobs(session_id="s_x", beats=beats, clips_dir=tmp_path / "clips")
    assert [j.beat_id for j in jobs] == ["b_ok"]


def test_plan_jobs_empty_returns_empty(tmp_path: Path):
    jobs, skipped = plan_jobs(session_id="s_x", beats=[], clips_dir=tmp_path / "clips")
    assert jobs == [] and skipped == []


async def test_render_session_missing_beats_raises(tmp_path: Path):
    from tradefarm.render.headless import render_session

    with pytest.raises(FileNotFoundError):
        await render_session("never_existed", sessions_dir=tmp_path)


async def test_render_session_only_recap_short_circuits(tmp_path: Path):
    """No browser launch when every beat is skipped — exit 0 with
    no failures + a non-zero skipped count."""
    from tradefarm.render.headless import render_session

    sdir = tmp_path / "all_recap"
    sdir.mkdir()
    (sdir / "beats.json").write_text(json.dumps([_beat(id="b_r", kind="recap", scene="recap")]))
    (sdir / "manifest.json").write_text(json.dumps({"events": []}))
    summary = await render_session("all_recap", sessions_dir=tmp_path)
    assert summary.succeeded == 0
    assert summary.failed == 0
    assert summary.skipped == 1
    assert summary.results == []


async def test_render_session_purges_stale_clips(tmp_path: Path):
    """Files from a prior run whose beat ids aren't in the current
    plan must be removed, so the stitcher doesn't pick them up."""
    from tradefarm.render.headless import render_session

    sdir = tmp_path / "purge_test"
    sdir.mkdir()
    (sdir / "beats.json").write_text(json.dumps([_beat(id="b_recap", kind="recap")]))
    (sdir / "manifest.json").write_text(json.dumps({"events": []}))
    clips = sdir / "clips"
    clips.mkdir()
    stale_webm = clips / "b_gone.webm"
    stale_json = clips / "b_gone.json"
    stale_webm.write_bytes(b"")
    stale_json.write_text("{}")
    # render_session short-circuits (only recap, skipped) but should
    # still run the purge step.
    await render_session("purge_test", sessions_dir=tmp_path)
    assert not stale_webm.exists()
    assert not stale_json.exists()


async def test_render_session_keep_stale_keeps_files(tmp_path: Path):
    from tradefarm.render.headless import render_session

    sdir = tmp_path / "keep_test"
    sdir.mkdir()
    (sdir / "beats.json").write_text(json.dumps([_beat(id="b_recap", kind="recap")]))
    (sdir / "manifest.json").write_text(json.dumps({"events": []}))
    clips = sdir / "clips"
    clips.mkdir()
    stale = clips / "b_gone.webm"
    stale.write_bytes(b"x")
    await render_session("keep_test", sessions_dir=tmp_path, purge_stale=False)
    assert stale.exists()


# ----- integration (env-gated) ---------------------------------------------


@pytest.mark.skipif(
    os.environ.get("RUN_BROWSER_TESTS") != "1",
    reason="Set RUN_BROWSER_TESTS=1 + run a stream/ dev server to enable.",
)
async def test_integration_render_one_beat(tmp_path: Path):
    """End-to-end: render the open beat from a tiny synthetic session.
    Requires: stream/ dev server on :5180 + a session manifest at
    out/sessions/it_smoke/."""
    from tradefarm.render.headless import render_session

    # Use the real out/sessions tree so the backend can see the manifest.
    sessions = Path("out/sessions")
    session_id = "it_smoke"
    sdir = sessions / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "manifest.json").write_text(
        json.dumps(
            {
                "session_id": session_id,
                "date_range": ["2026-05-19", "2026-05-19"],
                "started_at": "2026-05-19T13:30:00+00:00",
                "ended_at": "2026-05-19T20:00:00+00:00",
                "trading_days": ["2026-05-19"],
                "tick_count": 1,
                "fill_count": 0,
                "agents_active": 0,
                "events": [],
            }
        )
    )
    (sdir / "beats.json").write_text(
        json.dumps(
            [
                {
                    "id": "b_open",
                    "t": "2026-05-19T13:30:00+00:00",
                    "kind": "open",
                    "scene_hint": "hero",
                    "duration_sec": 5,
                    "score": 0.5,
                    "headline": "smoke",
                    "sub": "smoke",
                    "event_refs": [],
                    "agent_ids": [],
                    "metadata": {},
                }
            ]
        )
    )
    summary = await render_session(session_id, sessions_dir=sessions, speed=120.0)
    assert summary.succeeded == 1, [r.error for r in summary.results]
    clip = sdir / "clips" / "b_open.webm"
    assert clip.is_file() and clip.stat().st_size > 0
    sidecar = sdir / "clips" / "b_open.json"
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text())
    assert meta["beat_id"] == "b_open"
    assert meta["scene_ready_at_ms"] > 0
