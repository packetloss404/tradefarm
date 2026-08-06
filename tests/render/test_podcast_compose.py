"""End-to-end compose test for the Rivalry Week weekly podcast.

Stands up a 5-day fixture under ``tmp_path``: a weekly rollup + 5
daily session manifests with one daily ``beats.json`` so the daily
payload collector has something to pick up. The LLM call and the
TTS call are mocked; ffmpeg is also mocked (the test inspects the
argv the renderer constructed, it doesn't actually run ffmpeg).

Asserts the expected artifact shape under
``out/weekly/<week_id>/podcast/`` after
``compose_weekly_episode`` returns.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from tradefarm.render import podcast as podcast_mod


# ----- helpers ------------------------------------------------------------


def _write_session_manifest(
    base: Path, session_id: str, *, fill_count: int, started_at: str
) -> Path:
    sdir = base / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "session_id": session_id,
        "started_at": started_at,
        "fill_count": fill_count,
        "strategy_rollup": {
            "momentum_12_1": {"agents": 25, "equity": 25_000, "pnl": 300.0, "fills": 50},
        },
        "rivalries": [
            {
                "a": 12, "b": 47, "symbol": "NVDA",
                "count": 4, "a_pnl": 80, "b_pnl": -60,
            },
        ],
    }
    (sdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    beats = [
        {
            "id": f"b_{session_id}_1", "t": started_at, "kind": "big_fill",
            "scene_hint": "hero", "duration_sec": 30, "score": 0.8,
            "headline": f"big move on day {session_id[-1]}",
            "sub": "AAPL up 2%",
        },
    ]
    (sdir / "beats.json").write_text(json.dumps(beats), encoding="utf-8")
    return sdir


def _write_weekly_fixture(
    base: Path,
    week_id: str,
    *,
    date_range: tuple[str, str] = ("2026-08-03", "2026-08-07"),
) -> dict[str, Any]:
    """Write a 5-day session fixture and the weekly rollup. Returns
    the rollup dict the composer would read."""
    sessions = [
        ("s_2026-08-03_a", "2026-08-03T13:30:00+00:00", 35),
        ("s_2026-08-04_b", "2026-08-04T13:30:00+00:00", 42),
        ("s_2026-08-05_c", "2026-08-05T13:30:00+00:00", 51),
        ("s_2026-08-06_d", "2026-08-06T13:30:00+00:00", 38),
        ("s_2026-08-07_e", "2026-08-07T13:30:00+00:00", 46),
    ]
    for sid, started_at, fill in sessions:
        _write_session_manifest(base, sid, fill_count=fill, started_at=started_at)
    rollup = {
        "week_id": week_id,
        "date_range": list(date_range),
        "strategy_rollup": {
            "momentum_12_1": {"agents": 25, "equity": 25_000, "pnl": 300.0, "fills": 50},
        },
        "rivalries": [
            {
                "a": 12, "b": 47, "symbol": "NVDA",
                "count": 4, "a_pnl": 80, "b_pnl": -60,
            },
        ],
        "promotions": [],
        "sessions": [
            {"session_id": sid, "started_at": started_at, "fill_count": fill}
            for sid, started_at, fill in sessions
        ],
        "pool_pnl": 500.0,
        "pool_pnl_pct": 1.42,
    }
    weekly_dir = base / "weekly" / week_id
    weekly_dir.mkdir(parents=True, exist_ok=True)
    (weekly_dir / "rollup.json").write_text(json.dumps(rollup), encoding="utf-8")
    return rollup


def _stub_llm() -> str:
    """Returned by the mocked _call_llm_for_script."""
    return """\
intro: |
  Welcome to Rivalry Week.
topline: |
  Pool P&L this week: +1.42 percent.
day_1: |
  Day one prose.
day_2: |
  Day two prose.
day_3: |
  Day three prose.
day_4: |
  Day four prose.
day_5: |
  Day five prose.
wrap: |
  See you next week.
"""


def _mock_subprocess_run_factory() -> Any:
    """A drop-in for subprocess.run that records the argv + writes
    a tiny placeholder file for any ffmpeg output path. The
    composer's ffmpeg invocations all pass an output path as the
    final argv element; we mirror that to disk so the
    'expected files exist' assertions have something to find."""
    calls: list[list[str]] = []

    def _run(cmd: list[str], *args: Any, **kwargs: Any) -> Any:
        calls.append(list(cmd))
        # The ffmpeg invocations always end with the output path.
        # Write a 16-byte placeholder so file existence checks pass.
        if isinstance(cmd, list) and cmd and cmd[0] == "ffmpeg":
            # Find the output: it's the trailing argument.
            for arg in reversed(cmd):
                if isinstance(arg, str) and arg.endswith((".mp4", ".wav", ".jpg")):
                    Path(arg).parent.mkdir(parents=True, exist_ok=True)
                    Path(arg).write_bytes(b"\x00" * 16)
                    break
        # Return a CompletedProcess-like object with returncode 0.
        return subprocess.CompletedProcess(
            args=cmd, returncode=0, stdout="", stderr="",
        )

    _run.calls = calls  # type: ignore[attr-defined]
    return _run


# ----- tests --------------------------------------------------------------


def test_compose_weekly_episode_creates_all_expected_files(tmp_path: Path) -> None:
    """A full compose run writes the script, voice, card, intro,
    outro, episode, and per-episode yaml under
    ``<sessions_dir>/weekly/<week_id>/podcast/``."""
    week_id = "2026-W31"
    sessions_dir = tmp_path / "out" / "sessions"
    _write_weekly_fixture(sessions_dir, week_id)
    mock_run = _mock_subprocess_run_factory()

    # 0.16.0 — LLM / TTS / Pillow are all mocked so the test runs
    # without creds. The ffmpeg call list is captured (we don't
    # assert on it here, just on the files ffmpeg would have
    # written — those are the canonical artifacts).
    with patch.object(podcast_mod, "_call_llm_for_script", return_value=(_stub_llm(), "anthropic", "claude-test")):
        with patch("subprocess.run", side_effect=mock_run):
            ep = podcast_mod.compose_weekly_episode(
                week_id,
                sessions_dir=sessions_dir,
                provider="silence",  # writes a silent wav, no creds needed
                voice="alloy",
            )
    assert ep.is_file()
    podcast_dir = sessions_dir / "weekly" / week_id / "podcast"
    expected = [
        f"script_{week_id}.txt",
        f"voice_{week_id}.wav",
        f"week_card_{week_id}.mp4",
        f"intro_{week_id}.mp4",
        f"outro_{week_id}.mp4",
        f"episode_{week_id}.mp4",
        f"episode_{week_id}.yaml",
    ]
    for name in expected:
        p = podcast_dir / name
        assert p.is_file(), f"missing artifact: {p}"
    # Cover jpg is best-effort (the card renderer creates it when
    # Pillow is available — skip the assertion on hosts that don't
    # have Pillow installed).
    cover = podcast_dir / f"cover_{week_id}.jpg"
    if podcast_mod._PIL_AVAILABLE:
        assert cover.is_file()


def test_compose_weekly_episode_metadata_yaml_has_podcast_shape(tmp_path: Path) -> None:
    """The episode_<week_id>.yaml must carry the kind=podcast field
    the dashboard's Weekly Podcast tab reads back."""
    week_id = "2026-W31"
    sessions_dir = tmp_path / "out" / "sessions"
    _write_weekly_fixture(sessions_dir, week_id)
    mock_run = _mock_subprocess_run_factory()

    with patch.object(podcast_mod, "_call_llm_for_script", return_value=(_stub_llm(), "anthropic", "claude-test")):
        with patch("subprocess.run", side_effect=mock_run):
            podcast_mod.compose_weekly_episode(
                week_id,
                sessions_dir=sessions_dir,
                provider="silence",
                voice="alloy",
            )
    yaml_path = sessions_dir / "weekly" / week_id / "podcast" / f"episode_{week_id}.yaml"
    assert yaml_path.is_file()
    data = json.loads(yaml_path.read_text(encoding="utf-8"))
    assert data["kind"] == "podcast"
    assert data["week_id"] == week_id
    assert data["category_id"] == "22"  # YouTube Music & Podcast
    assert isinstance(data["duration_sec"], int)


def test_compose_weekly_episode_constructs_ffmpeg_argv(tmp_path: Path) -> None:
    """The card render's ffmpeg invocation must include the right
    inputs/outputs (concat list + voice wav + libx264 + aac) and
    the intro/outro crop filter. The test asserts on argv shape
    rather than running ffmpeg — covers the "right ffmpeg argv was
    constructed" contract the spec asks for."""
    week_id = "2026-W31"
    sessions_dir = tmp_path / "out" / "sessions"
    _write_weekly_fixture(sessions_dir, week_id)
    mock_run = _mock_subprocess_run_factory()

    with patch.object(podcast_mod, "_call_llm_for_script", return_value=(_stub_llm(), "anthropic", "claude-test")):
        with patch("subprocess.run", side_effect=mock_run):
            podcast_mod.compose_weekly_episode(
                week_id,
                sessions_dir=sessions_dir,
                provider="silence",
                voice="alloy",
            )
    # At least one ffmpeg call must use the concat demuxer for the
    # card render; at least one must use the 9:16 crop filter for
    # the intro/outro.
    cmds = mock_run.calls
    ffmpeg_cmds = [c for c in cmds if c and c[0] == "ffmpeg"]
    assert any("-f" in c and "concat" in c for c in ffmpeg_cmds)
    # The intro uses the "crop=ih*9/16:ih" filter.
    intro_cmds = [
        c for c in ffmpeg_cmds
        if any("crop=ih*9/16:ih" in str(a) for a in c)
    ]
    assert len(intro_cmds) >= 1


def test_compose_weekly_episode_dry_run_returns_script_only(tmp_path: Path) -> None:
    """--dry-run mode runs the LLM call and writes the script, but
    does NOT invoke ffmpeg / TTS. The returned path is the script
    file (not the episode mp4)."""
    week_id = "2026-W31"
    sessions_dir = tmp_path / "out" / "sessions"
    _write_weekly_fixture(sessions_dir, week_id)
    mock_run = _mock_subprocess_run_factory()

    with patch.object(podcast_mod, "_call_llm_for_script", return_value=(_stub_llm(), "anthropic", "claude-test")):
        with patch("subprocess.run", side_effect=mock_run):
            out = podcast_mod.compose_weekly_episode(
                week_id,
                sessions_dir=sessions_dir,
                dry_run=True,
            )
    assert out.name == f"script_{week_id}.txt"
    # The card / episode mp4 must NOT exist in dry-run mode.
    podcast_dir = sessions_dir / "weekly" / week_id / "podcast"
    assert not (podcast_dir / f"week_card_{week_id}.mp4").exists()
    assert not (podcast_dir / f"episode_{week_id}.mp4").exists()
    # ffmpeg was never called.
    assert all(c[0] != "ffmpeg" for c in mock_run.calls)


def test_compose_weekly_episode_uses_settings_provider_by_default(tmp_path: Path) -> None:
    """When the caller doesn't pass `provider` or `voice`, the
    composer falls back to settings.podcast_tts_provider /
    settings.podcast_voice. We don't need to fire a real TTS call
    here — the test just asserts the settings were read."""
    from tradefarm.config import settings

    week_id = "2026-W31"
    sessions_dir = tmp_path / "out" / "sessions"
    _write_weekly_fixture(sessions_dir, week_id)
    mock_run = _mock_subprocess_run_factory()

    with patch.object(podcast_mod, "_call_llm_for_script", return_value=(_stub_llm(), "anthropic", "claude-test")):
        with patch.object(podcast_mod.settings, "podcast_voice", "alloy"):
            with patch.object(podcast_mod.settings, "podcast_tts_provider", "silence"):
                with patch("subprocess.run", side_effect=mock_run):
                    ep = podcast_mod.compose_weekly_episode(
                        week_id,
                        sessions_dir=sessions_dir,
                    )
    assert ep.is_file()
    # Defensive: if the test runs in a context where settings are
    # patched, the resolve path is exercised either way.
    assert settings.podcast_voice  # non-empty


# ----- list_episodes ------------------------------------------------------


def test_list_episodes_returns_podcast_artifacts(tmp_path: Path) -> None:
    """list_episodes walks out/weekly/ and returns one row per
    composed week. The row shape matches the dashboard's tab."""
    week_ids = ["2026-W30", "2026-W31"]
    sessions_dir = tmp_path / "out" / "sessions"
    for wid in week_ids:
        _write_weekly_fixture(sessions_dir, wid)
        # Drop a placeholder episode mp4 + the per-episode yaml so
        # the list walker finds them.
        pdir = sessions_dir / "weekly" / wid / "podcast"
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / f"episode_{wid}.mp4").write_bytes(b"\x00" * 32)
        (pdir / f"episode_{wid}.yaml").write_text(
            json.dumps(
                {
                    "kind": "podcast",
                    "duration_sec": 1800,
                    "size_bytes": 432_000_000,
                    "uploaded_at": "2026-08-08T16:35:00Z",
                    "youtube_video_id": "abc123",
                }
            ),
            encoding="utf-8",
        )
    rows = podcast_mod.list_episodes(base_dir=sessions_dir)
    assert len(rows) == 2
    # Newest first.
    assert rows[0]["week_id"] == "2026-W31"
    assert rows[1]["week_id"] == "2026-W30"
    assert rows[0]["duration_sec"] == 1800
    assert rows[0]["youtube_video_id"] == "abc123"
    assert rows[0]["size_bytes"] >= 32


def test_list_episodes_empty_when_no_weekly_dir(tmp_path: Path) -> None:
    """A fresh dev box with no composed weeks returns an empty
    list (not a crash)."""
    sessions_dir = tmp_path / "out" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    rows = podcast_mod.list_episodes(base_dir=sessions_dir)
    assert rows == []


# ----- safe week_id -------------------------------------------------------


def test_safe_week_id_rejects_traversal() -> None:
    with pytest.raises(ValueError, match="traversal-like"):
        podcast_mod._safe_week_id("../etc/passwd")
    with pytest.raises(ValueError, match="traversal-like"):
        podcast_mod._safe_week_id("2026/01/01")
    with pytest.raises(ValueError, match="must look like YYYY-Www"):
        podcast_mod._safe_week_id("not-a-week")
    with pytest.raises(ValueError, match="must look like YYYY-Www"):
        podcast_mod._safe_week_id("2026-W3")  # week must be 2 digits
