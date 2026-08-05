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
        "title": "T",
        "description": "D",
        "tags": ["a", "b"],
        "category_id": "28",
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
        "title": "T",
        "description": "D",
        "tags": [],
        "category_id": "28",
        "privacy_status": "public",
        "publish_at_iso": "2026-05-21T20:30:00+00:00",
    }
    body = build_video_resource(meta)
    assert "publishAt" not in body["status"]


def test_build_video_resource_drops_publish_at_when_none():
    meta = {
        "title": "T",
        "description": "D",
        "tags": [],
        "category_id": "28",
        "privacy_status": "private",
        "publish_at_iso": None,
    }
    body = build_video_resource(meta)
    assert "publishAt" not in body["status"]


# ----- upload_episode short-circuits + dry-run --------------------------


def _seed_session(
    tmp_path: Path, *, has_video: bool = True, has_meta: bool = True, has_thumb: bool = False
) -> Path:
    sdir = tmp_path / "s_up"
    sdir.mkdir()
    if has_meta:
        (sdir / "episode.yaml").write_text(
            json.dumps(
                {
                    "session_id": "s_up",
                    "title": "T",
                    "description": "D",
                    "tags": ["x"],
                    "category_id": "28",
                    "privacy_status": "private",
                    "publish_at_iso": "2026-05-21T20:30:00+00:00",
                    "chapters": [],
                    "thumbnail": None,
                    "video": None,
                }
            )
        )
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
    tmp_path: Path,
    monkeypatch,
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
    tmp_path: Path,
    monkeypatch,
):
    """Thumbnail failure is non-fatal — the video still uploaded."""
    from tradefarm.yt import upload as up

    _seed_session(tmp_path, has_thumb=True)
    creds = YtCredentials(client_id="cid", client_secret="sec", refresh_token="ref")

    async def fake_refresh(_c):
        return "tok"

    async def fake_init(**_):
        return "https://x/y"

    async def fake_put(**_):
        return {"id": "vid"}

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
    tmp_path: Path,
    monkeypatch,
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


# ----- 0.12.0 — shared httpx client for the 4 upload callsites -------------
#
# The OAuth refresh, init-resumable POST, chunked PUT, and thumbnail
# POST all used to instantiate ``httpx.AsyncClient`` per call. They
# now all reuse ``tradefarm.runtime.http.get_shared_client()`` so the
# keepalive survives the whole 4-call sequence (a real win on the
# chunked PUT — 100s of 8 MiB chunks ride the same TCP/TLS session).


class _SharedClientStub:
    """Records every post + put + replays scripted responses."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.puts: list[dict] = []
        self._post_responses: list[tuple[int, dict, dict]] = []
        self._put_responses: list[tuple[int, dict, dict]] = []

    def queue_post(self, status: int, body: dict = None, headers: dict = None) -> None:
        self._post_responses.append((status, body or {}, headers or {}))

    def queue_put(self, status: int, body: dict = None, headers: dict = None) -> None:
        self._put_responses.append((status, body or {}, headers or {}))

    async def post(self, url, *, json=None, headers=None, content=None, timeout=None, **_):
        from types import SimpleNamespace

        self.posts.append(
            {"url": url, "json": json, "headers": headers, "content": content, "timeout": timeout}
        )
        if not self._post_responses:
            raise RuntimeError("no scripted post response")
        status, body, resp_headers = self._post_responses.pop(0)
        return SimpleNamespace(
            status_code=status,
            json=lambda: body,
            content=b"" if not body else str(body).encode("utf-8"),
            headers=resp_headers,
            text=str(body),
            raise_for_status=lambda: _maybe_raise(status, url),
        )

    async def put(self, url, *, headers=None, content=None, timeout=None, **_):
        from types import SimpleNamespace

        self.puts.append(
            {"url": url, "headers": headers, "content": content, "timeout": timeout}
        )
        if not self._put_responses:
            raise RuntimeError("no scripted put response")
        status, body, resp_headers = self._put_responses.pop(0)
        return SimpleNamespace(
            status_code=status,
            json=lambda: body,
            content=b"" if not body else str(body).encode("utf-8"),
            headers=resp_headers,
            text=str(body),
            raise_for_status=lambda: _maybe_raise(status, url),
        )


def _maybe_raise(status: int, url: str) -> None:
    if status < 400:
        return
    import httpx

    request = httpx.Request("POST", url)
    response = httpx.Response(status, request=request)
    raise httpx.HTTPStatusError(
        f"HTTP {status}", request=request, response=response
    )


async def test_refresh_access_token_uses_shared_client(monkeypatch):
    """0.12.0: the OAuth refresh POST goes through the shared
    client (not a fresh ``httpx.AsyncClient``)."""
    from tradefarm.yt import upload as up

    fake = _SharedClientStub()
    fake.queue_post(200, body={"access_token": "ya29.fake"})

    async def _get():
        return fake

    monkeypatch.setattr(up, "get_shared_client", _get)

    creds = YtCredentials(client_id="cid", client_secret="sec", refresh_token="ref")
    token = await up.refresh_access_token(creds)
    assert token == "ya29.fake"
    assert len(fake.posts) == 1
    # The shared client is the only thing that should have fired.
    assert "oauth2.googleapis.com" in fake.posts[0]["url"]
    # 10s timeout is the per-request override (the shared client's
    # default is 30s; the refresh dance doesn't need more).
    assert fake.posts[0]["timeout"] == 10.0


async def test_initiate_resumable_upload_uses_shared_client(monkeypatch):
    """0.12.0: the resumable init POST goes through the shared
    client so the keepalive carries into the chunked PUT."""
    from tradefarm.yt import upload as up

    fake = _SharedClientStub()
    fake.queue_post(200, headers={"Location": "https://upload.googleapis.com/resumable/xyz"})

    async def _get():
        return fake

    monkeypatch.setattr(up, "get_shared_client", _get)

    loc = await up._initiate_resumable_upload(
        access_token="tok", body={"snippet": {"title": "T"}}, video_bytes=42
    )
    assert loc == "https://upload.googleapis.com/resumable/xyz"
    assert len(fake.posts) == 1
    assert "youtube/v3/videos" in fake.posts[0]["url"]
    assert fake.posts[0]["headers"]["Authorization"] == "Bearer tok"
    assert fake.posts[0]["timeout"] == 30.0


async def test_set_thumbnail_uses_shared_client(tmp_path, monkeypatch):
    """0.12.0: the thumbnail POST goes through the shared client."""
    from tradefarm.yt import upload as up

    fake = _SharedClientStub()
    fake.queue_post(200)

    async def _get():
        return fake

    monkeypatch.setattr(up, "get_shared_client", _get)

    thumb = tmp_path / "thumb.jpg"
    thumb.write_bytes(b"thumbbytes")
    await up._set_thumbnail(access_token="tok", video_id="vid", thumb_path=thumb)
    assert len(fake.posts) == 1
    assert "thumbnails/set" in fake.posts[0]["url"]
    assert "videoId=vid" in fake.posts[0]["url"]
    # 60s timeout is the per-request override.
    assert fake.posts[0]["timeout"] == 60.0
    # Raw bytes in content (multipart uses `files=`, this uses `content=`).
    assert fake.posts[0]["content"] == b"thumbbytes"


# ----- env-gated real-API smoke test (does NOT actually upload) ----------


@pytest.mark.skipif(
    os.environ.get("RUN_YT_TESTS") != "1" or not os.environ.get("YOUTUBE_CLIENT_ID"),
    reason="Set RUN_YT_TESTS=1 + YOUTUBE_* env vars to enable; this hits real auth.",
)
async def test_integration_oauth_refresh_only(tmp_path):
    """Exercise the OAuth refresh against the real Google endpoint to
    catch credential drift. Does NOT upload a video."""
    from tradefarm.yt.upload import refresh_access_token, YtCredentials

    creds = YtCredentials.from_env()
    token = await refresh_access_token(creds)
    assert isinstance(token, str) and token.startswith("ya29.")
