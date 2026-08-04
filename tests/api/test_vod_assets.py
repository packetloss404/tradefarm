"""Tests for ``tradefarm.api.vod`` — VOD asset serving router.

Covers the three endpoints:
- GET /vod/sessions                   list rendered sessions
- GET /vod/{session_id}/reel.mp4      stream rendered video
- GET /vod/{session_id}/thumb.jpg     stream thumbnail

The on-disk layout is ``out/sessions/<id>/reel.mp4`` and
``out/sessions/<id>/thumb.jpg`` — the same convention ``render.mix``
and the thumbnail step write. Tests build a temp SESSIONS_ROOT via
monkeypatch so they don't touch the real ``out/`` dir.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import tradefarm.api.vod as vod_mod
from tradefarm.api.main import app


# ---------------------------------------------------------------------------
# Helpers — build an isolated sessions dir and patch the module's root
# ---------------------------------------------------------------------------


def _make_session(root: Path, session_id: str, *, with_reel: bool, with_thumb: bool) -> None:
    sdir = root / session_id
    sdir.mkdir(parents=True, exist_ok=True)
    if with_reel:
        # Tiny but valid-looking mp4 bytes — the endpoint just streams them,
        # it doesn't parse the file. Magic bytes are decorative.
        (sdir / "reel.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
    if with_thumb:
        (sdir / "thumb.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 16)


@pytest.fixture
def sessions_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "out" / "sessions"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(vod_mod, "SESSIONS_ROOT", root)
    # The module-level constant is read at request time, so a
    # monkeypatch on the module is enough. No re-import needed.
    yield root
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /vod/sessions
# ---------------------------------------------------------------------------


def test_list_sessions_empty(client: TestClient, sessions_root: Path) -> None:
    r = client.get("/vod/sessions")
    assert r.status_code == 200
    assert r.json() == []


def test_list_sessions_reports_reel_and_thumb_flags(
    client: TestClient, sessions_root: Path
) -> None:
    _make_session(sessions_root, "s_2026-05-19_a", with_reel=True, with_thumb=True)
    _make_session(sessions_root, "s_2026-05-19_b", with_reel=True, with_thumb=False)
    _make_session(sessions_root, "s_2026-05-19_c", with_reel=False, with_thumb=True)
    r = client.get("/vod/sessions")
    assert r.status_code == 200
    rows = {row["session_id"]: row for row in r.json()}
    assert rows["s_2026-05-19_a"]["has_reel"] is True
    assert rows["s_2026-05-19_a"]["has_thumb"] is True
    assert rows["s_2026-05-19_b"]["has_reel"] is True
    assert rows["s_2026-05-19_b"]["has_thumb"] is False
    assert rows["s_2026-05-19_c"]["has_reel"] is False
    assert rows["s_2026-05-19_c"]["has_thumb"] is True
    # `date` is an mtime float — must be present and > 0.
    assert rows["s_2026-05-19_a"]["date"] > 0


def test_list_sessions_ignores_non_matching_dirs(
    client: TestClient, sessions_root: Path
) -> None:
    # A non-conforming dir name (one that fails the regex — special
    # chars, dot, etc.) must NOT appear in the listing — the regex
    # filter protects the response.
    _make_session(sessions_root, "s_2026-05-19_ok", with_reel=True, with_thumb=False)
    (sessions_root / "scratch.tmp").mkdir()  # '.' fails the regex
    (sessions_root / "scratch.tmp" / "reel.mp4").write_bytes(b"junk")
    (sessions_root / "with space").mkdir()  # space fails the regex
    r = client.get("/vod/sessions")
    ids = [row["session_id"] for row in r.json()]
    assert ids == ["s_2026-05-19_ok"]


# ---------------------------------------------------------------------------
# GET /vod/{session_id}/reel.mp4
# ---------------------------------------------------------------------------


def test_get_reel_returns_mp4_bytes(client: TestClient, sessions_root: Path) -> None:
    payload = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    _make_session(sessions_root, "s_2026-05-19_a", with_reel=False, with_thumb=False)
    (sessions_root / "s_2026-05-19_a" / "reel.mp4").write_bytes(payload)
    r = client.get("/vod/s_2026-05-19_a/reel.mp4")
    assert r.status_code == 200
    assert r.headers["content-type"] == "video/mp4"
    assert r.content == payload


def test_get_reel_missing_returns_404(client: TestClient, sessions_root: Path) -> None:
    _make_session(sessions_root, "s_2026-05-19_empty", with_reel=False, with_thumb=False)
    r = client.get("/vod/s_2026-05-19_empty/reel.mp4")
    assert r.status_code == 404


def test_get_reel_rejects_path_traversal(
    client: TestClient, sessions_root: Path
) -> None:
    """``../`` and friends in the session id must be rejected with 400
    — never escape the sessions root. The httpx TestClient normalizes
    literal ``..`` away before sending, so we test the validation
    helper directly with a matrix of bad inputs.
    """
    from tradefarm.api.vod import _safe_session_dir
    from fastapi import HTTPException

    for bad in ("..", "../etc", "foo/bar", "scratch.tmp", "with space", "", "a" * 65):
        with pytest.raises(HTTPException) as exc_info:
            _safe_session_dir(bad)
        assert exc_info.value.status_code == 400, f"expected 400 for {bad!r}"


def test_safe_session_dir_accepts_valid_ids(
    client: TestClient, sessions_root: Path
) -> None:
    """Sanity check: well-formed session ids resolve to a child of
    SESSIONS_ROOT and don't raise."""
    from tradefarm.api.vod import _safe_session_dir
    for good in ("a", "s_2026-05-19_a", "abc-123", "X" * 64):
        resolved = _safe_session_dir(good)
        assert resolved.parent.resolve() == sessions_root.resolve()


# ---------------------------------------------------------------------------
# GET /vod/{session_id}/thumb.jpg
# ---------------------------------------------------------------------------


def test_get_thumb_returns_jpeg_bytes(client: TestClient, sessions_root: Path) -> None:
    payload = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 32
    _make_session(sessions_root, "s_2026-05-19_a", with_reel=False, with_thumb=False)
    (sessions_root / "s_2026-05-19_a" / "thumb.jpg").write_bytes(payload)
    r = client.get("/vod/s_2026-05-19_a/thumb.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/jpeg"
    assert r.content == payload


def test_get_thumb_missing_returns_404(client: TestClient, sessions_root: Path) -> None:
    _make_session(sessions_root, "s_2026-05-19_a", with_reel=True, with_thumb=False)
    r = client.get("/vod/s_2026-05-19_a/thumb.jpg")
    assert r.status_code == 404
