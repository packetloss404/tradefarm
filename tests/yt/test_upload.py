"""YouTube upload — pure-function tests + httpx-mocked end-to-end.

The real OAuth + upload network calls are env-gated; the default test
path mocks httpx so the upload state-machine runs offline.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tradefarm.yt.upload import (
    UploadResult,
    YtCredentials,
    build_video_resource,
    upload_episode,
)


# ----- credentials --------------------------------------------------------


def test_credentials_from_env_requires_all_three(monkeypatch):
    monkeypatch.delenv("YOUTUBE_CLIENT_ID", raising=False)
    monkeypatch.delenv("YOUTUBE_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("YOUTUBE_REFRESH_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="OAuth env vars missing"):
        YtCredentials.from_env()


def test_credentials_from_env_picks_them_up(monkeypatch):
    monkeypatch.setenv("YOUTUBE_CLIENT_ID", "cid")
    monkeypatch.setenv("YOUTUBE_CLIENT_SECRET", "sec")
    monkeypatch.setenv("YOUTUBE_REFRESH_TOKEN", "ref")
    c = YtCredentials.from_env()
    assert c.client_id == "cid" and c.client_secret == "sec" and c.refresh_token == "ref"


# ----- video resource builder --------------------------------------------


def test_build_video_resource_carries_snippet_and_status():
    meta = {
        "title": "T", "description": "D",
        "tags": ["a", "b"], "category_id": "28",
        "privacy_status": "private",
        "publish_at_iso": "2026-05-21T20:30:00+00:00",
    }
    body = build_video_resource(meta)
    assert body["snippet"]["title"] == "T"
    assert body["snippet"]["categoryId"] == "28"
    assert body["snippet"]["tags"] == ["a", "b"]
    assert body["status"]["privacyStatus"] == "private"
    assert body["status"]["publishAt"] == "2026-05-21T20:30:00+00:00"
    assert body["status"]["selfDeclaredMadeForKids"] is False


def test_build_video_resource_drops_publish_at_when_public():
    meta = {
        "title": "T", "description": "D", "tags": [], "category_id": "28",
        "privacy_status": "public",
        "publish_at_iso": "2026-05-21T20:30:00+00:00",
    }
    body = build_video_resource(meta)
    assert "publishAt" not in body["status"]


def test_build_video_resource_drops_publish_at_when_none():
    meta = {
        "title": "T", "description": "D", "tags": [], "category_id": "28",
        "privacy_status": "private", "publish_at_iso": None,
    }
    body = build_video_resource(meta)
    assert "publishAt" not in body["status"]


# ----- upload_episode short-circuits + dry-run --------------------------


def _seed_session(tmp_path: Path, *, has_video: bool = True,
                  has_meta: bool = True, has_thumb: bool = False) -> Path:
    sdir = tmp_path / "s_up"
    sdir.mkdir()
    if has_meta:
        (sdir / "episode.yaml").write_text(json.dumps({
            "session_id": "s_up", "title": "T", "description": "D",
            "tags": ["x"], "category_id": "28",
            "privacy_status": "private",
            "publish_at_iso": "2026-05-21T20:30:00+00:00",
            "chapters": [], "thumbnail": None, "video": None,
        }))
    if has_video:
        (sdir / "reel.mp4").write_bytes(b"x" * 1024)
    if has_thumb:
        (sdir / "thumb.jpg").write_bytes(b"thumb")
    return sdir


async def test_upload_episode_errors_on_missing_meta(tmp_path: Path):
    _seed_session(tmp_path, has_meta=False)
    result = await upload_episode("s_up", sessions_dir=tmp_path)
    assert not result.ok
    assert "episode.yaml not found" in (result.error or "")


async def test_upload_episode_errors_on_missing_video(tmp_path: Path):
    _seed_session(tmp_path, has_video=False)
    result = await upload_episode("s_up", sessions_dir=tmp_path)
    assert not result.ok
    assert "reel.mp4 not found" in (result.error or "")


async def test_upload_episode_dry_run_emits_body_without_network(tmp_path: Path):
    _seed_session(tmp_path)
    result = await upload_episode("s_up", sessions_dir=tmp_path, dry_run=True)
    assert result.ok
    body = result.response.get("body")
    assert body["snippet"]["title"] == "T"
    assert result.response["video_bytes"] == 1024


# ----- mocked end-to-end --------------------------------------------------


async def test_upload_episode_runs_state_machine_with_mocks(
    tmp_path: Path, monkeypatch,
):
    """Patches httpx so the OAuth refresh + resumable upload sequence
    runs offline. Verifies the function returns video_id + video_url."""
    from tradefarm.yt import upload as up

    _seed_session(tmp_path, has_thumb=True)
    creds = YtCredentials(client_id="cid", client_secret="sec", refresh_token="ref")
    calls: list[str] = []

    async def fake_refresh(_creds):
        calls.append("refresh")
        return "ya29.fake_access_token"

    async def fake_init(*, access_token, body, video_bytes):
        calls.append("init")
        assert access_token.startswith("ya29.")
        assert body["snippet"]["title"] == "T"
        assert video_bytes == 1024
        return "https://upload.googleapis.com/resumable/abc123"

    async def fake_put(*, location_url, video_path, refresh_creds=None):
        calls.append("put")
        assert location_url.endswith("abc123")
        assert video_path.is_file()
        return {"id": "dQw4w9WgXcQ", "status": {"uploadStatus": "uploaded"}}

    thumb_calls: list[str] = []
    async def fake_thumbnail(*, access_token, video_id, thumb_path):
        thumb_calls.append(video_id)

    monkeypatch.setattr(up, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(up, "_initiate_resumable_upload", fake_init)
    monkeypatch.setattr(up, "_put_video_bytes", fake_put)
    monkeypatch.setattr(up, "_set_thumbnail", fake_thumbnail)

    result = await upload_episode("s_up", sessions_dir=tmp_path, creds=creds)
    assert result.ok, result.error
    assert result.video_id == "dQw4w9WgXcQ"
    assert result.video_url == "https://youtu.be/dQw4w9WgXcQ"
    # Audit fix: a second refresh fires before the thumbnail call
    # (the long PUT could have left the original token expired).
    assert calls == ["refresh", "init", "put", "refresh"]
    assert thumb_calls == ["dQw4w9WgXcQ"]


async def test_upload_episode_carries_thumbnail_error_into_response(
    tmp_path: Path, monkeypatch,
):
    """Thumbnail failure is non-fatal — the video still uploaded."""
    from tradefarm.yt import upload as up
    _seed_session(tmp_path, has_thumb=True)
    creds = YtCredentials(client_id="cid", client_secret="sec", refresh_token="ref")

    async def fake_refresh(_c): return "tok"
    async def fake_init(**_): return "https://x/y"
    async def fake_put(**_): return {"id": "vid"}
    async def fake_thumb(**_):
        raise RuntimeError("custom thumbnails require verified channel")

    monkeypatch.setattr(up, "refresh_access_token", fake_refresh)
    monkeypatch.setattr(up, "_initiate_resumable_upload", fake_init)
    monkeypatch.setattr(up, "_put_video_bytes", fake_put)
    monkeypatch.setattr(up, "_set_thumbnail", fake_thumb)

    result = await upload_episode("s_up", sessions_dir=tmp_path, creds=creds)
    assert result.ok
    assert result.video_id == "vid"
    assert "thumbnail_error" in result.response
    assert "verified channel" in result.response["thumbnail_error"]


async def test_upload_episode_failure_path_returns_error(
    tmp_path: Path, monkeypatch,
):
    from tradefarm.yt import upload as up
    _seed_session(tmp_path)
    creds = YtCredentials(client_id="cid", client_secret="sec", refresh_token="ref")

    async def fake_refresh(_c):
        raise RuntimeError("token refresh failed 400: invalid_grant")
    monkeypatch.setattr(up, "refresh_access_token", fake_refresh)

    result = await upload_episode("s_up", sessions_dir=tmp_path, creds=creds)
    assert not result.ok
    assert "invalid_grant" in (result.error or "")


# ----- env-gated real-API smoke test (does NOT actually upload) ----------


@pytest.mark.skipif(
    os.environ.get("RUN_YT_TESTS") != "1"
    or not os.environ.get("YOUTUBE_CLIENT_ID"),
    reason="Set RUN_YT_TESTS=1 + YOUTUBE_* env vars to enable; this hits real auth.",
)
async def test_integration_oauth_refresh_only(tmp_path):
    """Exercise the OAuth refresh against the real Google endpoint to
    catch credential drift. Does NOT upload a video."""
    from tradefarm.yt.upload import refresh_access_token, YtCredentials
    creds = YtCredentials.from_env()
    token = await refresh_access_token(creds)
    assert isinstance(token, str) and token.startswith("ya29.")
