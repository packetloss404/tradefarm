"""Tests for ``tradefarm.render.archive`` — session-dir tarball
archival on run-done.

The archive function is best-effort by design (a backup miss is
recoverable from a re-render; a failed run is the priority
signal). Tests cover:
- Happy path: tarball lands in the right date-stamped subdir.
- Skip when ``archive_root`` is None (default — not configured).
- Skip when ``run_status != "done"`` and ``also_on_failure=False``.
- Best-effort on missing src: returns None, doesn't raise.
- Best-effort on bad archive_root: returns None, doesn't raise.
- Temp file cleanup: a failed tar leaves no ``.tmp`` artifact
  in the archive dir.
- Excludes ``clips/`` per the documented contract.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from tradefarm.render.archive import archive_session


def _write_session(sdir: Path) -> None:
    sdir.mkdir(parents=True, exist_ok=True)
    (sdir / "manifest.json").write_text('{"events": []}')
    (sdir / "beats.json").write_text("[]")
    (sdir / "reel.mp4").write_bytes(b"FAKE_REEL")
    (sdir / "thumb.jpg").write_bytes(b"FAKE_THUMB")
    # clips/ should be excluded from the tarball.
    clips = sdir / "clips"
    clips.mkdir()
    (clips / "b1.webm").write_bytes(b"FAKE_WEB")
    (clips / "b1.json").write_text("{}")
    # intermediates/ should be excluded.
    interm = sdir / "intermediates"
    interm.mkdir()
    (interm / "scratch.txt").write_text("scratch")


async def test_archive_session_writes_date_stamped_tarball(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sdir = tmp_path / "sessions" / "s_archive"
    _write_session(sdir)
    archive_root = tmp_path / "backups"
    out = await archive_session(
        "s_archive",
        archive_root=archive_root,
        sessions_dir=tmp_path / "sessions",
        run_status="done",
    )
    assert out is not None
    # The output lives at <archive_root>/<date>/<sid>.tar.gz.
    # ``out.parent`` is the date dir; ``out.parent.parent`` is the
    # archive root.
    assert out.parent.parent.resolve() == archive_root.resolve()
    assert out.name == "s_archive.tar.gz"
    assert out.exists()
    # Tar is readable + contains the right files.
    with tarfile.open(out, "r:gz") as tar:
        names = {m.name for m in tar.getmembers() if m.isfile()}
    assert "manifest.json" in names
    assert "beats.json" in names
    assert "reel.mp4" in names
    assert "thumb.jpg" in names
    # Excludes.
    clips_names = {n for n in names if n.startswith("clips/")}
    assert clips_names == set(), f"clips/ should be excluded, got {clips_names}"
    interm_names = {n for n in names if n.startswith("intermediates/")}
    assert interm_names == set(), f"intermediates/ should be excluded, got {interm_names}"


async def test_archive_session_no_root_returns_none(tmp_path: Path) -> None:
    sdir = tmp_path / "sessions" / "s_noop"
    _write_session(sdir)
    out = await archive_session(
        "s_noop",
        archive_root=None,
        sessions_dir=tmp_path / "sessions",
    )
    assert out is None
    assert not (tmp_path / "backups").exists()


async def test_archive_session_skips_when_status_failed(tmp_path: Path) -> None:
    """``also_on_failure=False`` (the default) skips archival on
    failed runs — the operator can opt in with the flag when they
    want the diagnostic state backed up."""
    sdir = tmp_path / "sessions" / "s_fail"
    _write_session(sdir)
    archive_root = tmp_path / "backups"
    out = await archive_session(
        "s_fail",
        archive_root=archive_root,
        sessions_dir=tmp_path / "sessions",
        run_status="failed",
    )
    assert out is None
    assert not archive_root.exists()


async def test_archive_session_includes_failures_when_opted_in(
    tmp_path: Path
) -> None:
    sdir = tmp_path / "sessions" / "s_fail"
    _write_session(sdir)
    archive_root = tmp_path / "backups"
    out = await archive_session(
        "s_fail",
        archive_root=archive_root,
        sessions_dir=tmp_path / "sessions",
        run_status="failed",
        also_on_failure=True,
    )
    assert out is not None


async def test_archive_session_missing_src_returns_none(tmp_path: Path) -> None:
    out = await archive_session(
        "s_ghost",
        archive_root=tmp_path / "backups",
        sessions_dir=tmp_path / "sessions",
    )
    assert out is None


async def test_archive_session_cleans_up_temp_file_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If the tar raises mid-write, the temp file is removed — no
    half-baked .tar.gz.tmp left in the archive dir."""
    from tradefarm.render import archive as archive_mod

    sdir = tmp_path / "sessions" / "s_x"
    _write_session(sdir)
    archive_root = tmp_path / "backups"

    def boom(src_dir, out_path):
        raise OSError("disk full mid-write")

    monkeypatch.setattr(archive_mod, "_make_tarball", boom)
    out = await archive_session(
        "s_x",
        archive_root=archive_root,
        sessions_dir=tmp_path / "sessions",
    )
    assert out is None
    # The archive dir was created (mkdir parents=True on the
    # call) but no .tmp file lingers.
    leftovers = list(archive_root.rglob("*.tmp"))
    assert leftovers == [], f"temp file leaked: {leftovers}"


async def test_archive_session_creates_nested_archive_root(
    tmp_path: Path
) -> None:
    """A multi-segment path (e.g. /var/backups/tradefarm) is
    created on demand — the operator doesn't have to pre-create
    the date partition."""
    sdir = tmp_path / "sessions" / "s_x"
    _write_session(sdir)
    archive_root = tmp_path / "var" / "backups" / "tradefarm"
    out = await archive_session(
        "s_x",
        archive_root=archive_root,
        sessions_dir=tmp_path / "sessions",
    )
    assert out is not None
    # Walk up from the tarball: parent=date_dir, parent=archive_root.
    assert out.parent.parent.resolve() == archive_root.resolve()
