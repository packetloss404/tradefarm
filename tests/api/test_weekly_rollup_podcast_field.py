"""Tests for the new ``podcast`` field on the weekly rollup.

The field is read-on-demand: ``write_weekly_rollup`` walks
``out/weekly/<week_id>/podcast/`` and, if ``episode_<week_id>.mp4``
is present, populates a ``podcast`` block with the cover image,
duration, size, upload timestamp, and YouTube video id. Pre-0.16.0
rollups don't have the field; this test pins both branches.
"""

from __future__ import annotations

import json
from pathlib import Path

from tradefarm.session.weekly_rollup import (
    compute_weekly_rollup,
    write_weekly_rollup,
)


def _base_rollup(week_id: str = "2026-W31") -> dict:
    return {
        "week_id": week_id,
        "date_range": ["2026-08-03", "2026-08-07"],
        "strategy_rollup": {},
        "rivalries": [],
        "promotions": [],
        "sessions": [],
        "pool_pnl": 0.0,
        "pool_pnl_pct": 0.0,
    }


def test_rollup_podcast_field_is_none_when_no_episode(tmp_path: Path) -> None:
    """A weekly dir with no ``podcast/`` subdir → the rollup has
    no ``podcast`` key (matches pre-0.16.0 shape)."""
    week_id = "2026-W31"
    rollup = _base_rollup(week_id)
    out = write_weekly_rollup(rollup, sessions_dir=tmp_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["week_id"] == week_id
    # No podcast/ dir means no podcast field.
    assert "podcast" not in data or data.get("podcast") is None


def test_rollup_podcast_field_is_populated_when_episode_exists(tmp_path: Path) -> None:
    """When ``out/weekly/<week_id>/podcast/episode_*.mp4`` exists,
    the rollup picks up the path, cover, size, and (from the
    episode yaml) the duration + YouTube video id."""
    week_id = "2026-W31"
    pdir = tmp_path / "weekly" / week_id / "podcast"
    pdir.mkdir(parents=True)
    ep = pdir / f"episode_{week_id}.mp4"
    ep.write_bytes(b"\x00" * 432_000_000)  # ~432 MB
    cover = pdir / f"cover_{week_id}.jpg"
    cover.write_bytes(b"\x00" * 16)
    yaml_path = pdir / f"episode_{week_id}.yaml"
    yaml_path.write_text(
        json.dumps(
            {
                "kind": "podcast",
                "duration_sec": 1800,
                "uploaded_at": "2026-08-08T16:35:00Z",
                "youtube_video_id": "abc123xyz",
            }
        ),
        encoding="utf-8",
    )
    out = write_weekly_rollup(_base_rollup(week_id), sessions_dir=tmp_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    podcast = data.get("podcast")
    assert podcast is not None
    assert podcast["path"] == str(ep)
    assert podcast["cover"] == str(cover)
    assert podcast["duration_sec"] == 1800
    assert podcast["size_bytes"] == 432_000_000
    assert podcast["uploaded_at"] == "2026-08-08T16:35:00Z"
    assert podcast["youtube_video_id"] == "abc123xyz"


def test_rollup_podcast_field_handles_missing_yaml(tmp_path: Path) -> None:
    """When the episode mp4 is present but the per-episode yaml is
    missing, the rollup still picks up the path + size; the
    duration / upload / youtube id are returned as None / 0."""
    week_id = "2026-W31"
    pdir = tmp_path / "weekly" / week_id / "podcast"
    pdir.mkdir(parents=True)
    (pdir / f"episode_{week_id}.mp4").write_bytes(b"\x00" * 1024)
    out = write_weekly_rollup(_base_rollup(week_id), sessions_dir=tmp_path)
    data = json.loads(out.read_text(encoding="utf-8"))
    podcast = data.get("podcast")
    assert podcast is not None
    assert podcast["size_bytes"] == 1024
    assert podcast["uploaded_at"] is None
    assert podcast["youtube_video_id"] is None
    # Duration is 0 (no yaml to read + no ffprobe to call in tests).
    assert podcast["duration_sec"] == 0


def test_compute_weekly_rollup_does_not_read_podcast_dir(tmp_path: Path) -> None:
    """``compute_weekly_rollup`` is the read-on-demand-free path —
    it must NOT walk the podcast/ subdir. The dir is only read at
    write time. This pins the spec's "read-on-demand" contract."""
    week_id = "2026-W31"
    pdir = tmp_path / "weekly" / week_id / "podcast"
    pdir.mkdir(parents=True)
    (pdir / f"episode_{week_id}.mp4").write_bytes(b"\x00" * 1024)
    rollup = compute_weekly_rollup(week_id, sessions_dir=tmp_path)
    # The compute path doesn't populate the podcast field.
    assert "podcast" not in rollup
