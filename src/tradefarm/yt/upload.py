"""YouTube upload — POST reel.mp4 + episode.yaml to the YT Data API v3.

Uses the same OAuth refresh dance as src/tradefarm/orchestrator/youtube_chat.py
(POST grant_type=refresh_token → access_token), so the operator only
needs to wire up YOUTUBE_CLIENT_ID + YOUTUBE_CLIENT_SECRET +
YOUTUBE_REFRESH_TOKEN in .env. The refresh_token comes from
`uv run python -m tradefarm.tools.youtube_auth`.

Two phases:
  1. Resumable upload session (POST videos?part=snippet,status
     &uploadType=resumable) → 200 OK with `Location:` header.
  2. PUT the mp4 bytes to that Location with a Content-Range header.
     Returns the video resource (id + processing status).

Thumbnail upload is a separate call (POST thumbnails/set with the jpeg
as multipart). Optional — only fired when --upload-thumbnail is set
AND the file is present.

For v0 we keep the upload synchronous (single-shot resumable PUT —
no chunked retry). Real ops use a retry harness on top.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
VIDEOS_INSERT_URL = (
    "https://www.googleapis.com/upload/youtube/v3/videos"
    "?part=snippet,status&uploadType=resumable"
)
THUMBNAILS_SET_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


@dataclass
class UploadResult:
    ok: bool
    video_id: str | None = None
    video_url: str | None = None
    response: dict[str, Any] = field(default_factory=dict)
    elapsed_ms: float | None = None
    error: str | None = None


# ----- credentials --------------------------------------------------------


@dataclass
class YtCredentials:
    client_id: str
    client_secret: str
    refresh_token: str

    @classmethod
    def from_env(cls) -> "YtCredentials":
        cid = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
        sec = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()
        ref = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
        if not (cid and sec and ref):
            raise RuntimeError(
                "YouTube OAuth env vars missing — set YOUTUBE_CLIENT_ID, "
                "YOUTUBE_CLIENT_SECRET, YOUTUBE_REFRESH_TOKEN (run "
                "`uv run python -m tradefarm.tools.youtube_auth` if you "
                "don't have a refresh token yet)."
            )
        return cls(client_id=cid, client_secret=sec, refresh_token=ref)


async def refresh_access_token(creds: YtCredentials) -> str:
    """Trade a refresh_token for a fresh access_token. Same shape as
    src/tradefarm/orchestrator/youtube_chat.py's refresh dance."""
    import httpx
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.post(
            OAUTH_TOKEN_URL,
            data={
                "client_id": creds.client_id,
                "client_secret": creds.client_secret,
                "refresh_token": creds.refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if r.status_code != 200:
        raise RuntimeError(f"token refresh failed {r.status_code}: {r.text[:200]}")
    data = r.json()
    token = data.get("access_token")
    if not token:
        raise RuntimeError("token response missing access_token")
    return token


# ----- snippet/status payload --------------------------------------------


def build_video_resource(meta: dict[str, Any]) -> dict[str, Any]:
    """Translate our episode.yaml dict into the YouTube `video` resource
    shape the API expects on insert."""
    status: dict[str, Any] = {
        "privacyStatus": meta.get("privacy_status", "private"),
        "selfDeclaredMadeForKids": False,
        "embeddable": True,
    }
    publish_at = meta.get("publish_at_iso")
    if publish_at and status["privacyStatus"] == "private":
        status["publishAt"] = publish_at
    return {
        "snippet": {
            "title": meta["title"],
            "description": meta.get("description", ""),
            "tags": meta.get("tags", []),
            "categoryId": meta.get("category_id", "28"),
            "defaultLanguage": "en",
            "defaultAudioLanguage": "en",
        },
        "status": status,
    }


# ----- upload steps -------------------------------------------------------


async def _initiate_resumable_upload(
    *, access_token: str, body: dict[str, Any], video_bytes: int,
) -> str:
    """Step 1 — POST snippet/status, get a resumable upload Location."""
    import httpx
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video_bytes),
        "X-Upload-Content-Type": "video/mp4",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(
            VIDEOS_INSERT_URL,
            headers=headers,
            content=json.dumps(body).encode("utf-8"),
        )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"init upload failed {r.status_code}: {r.text[:300]}")
    loc = r.headers.get("Location")
    if not loc:
        raise RuntimeError("init upload returned no Location header")
    return loc


# Audit fix (C14): chunked resumable PUT. 8 MB chunks per Google's
# guidance (must be a multiple of 256 KB). Streams the file in chunks
# so we don't hold the entire reel in RAM (5 GB reels would otherwise
# peak the process's memory).
RESUMABLE_CHUNK_BYTES = 8 * 1024 * 1024  # 8 MiB


async def _put_video_bytes(
    *, location_url: str, video_path: Path,
    refresh_creds: "YtCredentials | None" = None,
) -> dict[str, Any]:
    """Step 2 — resumable chunked PUT of the mp4 bytes.

    Audit fix (C14): the previous code read the whole video into RAM
    and fired a single PUT with a 600s timeout, which fails on >1hr
    uploads (access token expires) and OOMs on large reels. Now
    streams in 8 MiB chunks; on 308 (incomplete) advances the cursor
    to what the server has; on 401 (token expired) calls
    refresh_creds to get a fresh access token and retries the chunk.
    """
    import httpx

    size = video_path.stat().st_size
    headers_base: dict[str, str] = {
        "Content-Type": "video/mp4",
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        with video_path.open("rb") as fh:
            offset = 0
            while offset < size:
                chunk = fh.read(RESUMABLE_CHUNK_BYTES)
                end = offset + len(chunk) - 1
                headers = {
                    **headers_base,
                    "Content-Length": str(len(chunk)),
                    "Content-Range": f"bytes {offset}-{end}/{size}",
                }
                r = await client.put(location_url, headers=headers, content=chunk)
                if r.status_code in (200, 201):
                    # Final chunk accepted.
                    return r.json()
                if r.status_code == 308:
                    # Incomplete — server reports how far it has via Range.
                    range_hdr = r.headers.get("Range", "")
                    if range_hdr.startswith("bytes="):
                        try:
                            server_end = int(range_hdr.split("-", 1)[1])
                            offset = server_end + 1
                            # Re-seek to where the server actually is.
                            fh.seek(offset)
                            continue
                        except (ValueError, IndexError):
                            pass
                    offset = end + 1
                    continue
                if r.status_code == 401 and refresh_creds is not None:
                    # Token expired mid-upload. The location URL itself
                    # holds the resumable session, so refresh and retry
                    # the same chunk (re-seek to offset).
                    await refresh_access_token(refresh_creds)
                    fh.seek(offset)
                    continue
                raise RuntimeError(
                    f"PUT video failed {r.status_code}: {r.text[:300]}"
                )
    raise RuntimeError("resumable upload ended without final response")


async def _set_thumbnail(*, access_token: str, video_id: str, thumb_path: Path) -> None:
    """Optional step — upload custom thumbnail. Requires the YT
    channel to be eligible for custom thumbnails (verified).

    Audit fix (H30): the URL needs `uploadType=media` for the simple-
    upload protocol (raw image body, not multipart). Without it,
    YouTube returns 400."""
    import httpx
    url = f"{THUMBNAILS_SET_URL}?uploadType=media&videoId={video_id}"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "image/jpeg",
    }
    with thumb_path.open("rb") as fh:
        data = fh.read()
    async with httpx.AsyncClient(timeout=60.0) as client:
        r = await client.post(url, headers=headers, content=data)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"thumbnail upload failed {r.status_code}: {r.text[:300]}")


# ----- top-level ---------------------------------------------------------


async def upload_episode(
    session_id: str,
    *,
    sessions_dir: Path | None = None,
    upload_thumbnail: bool = True,
    creds: YtCredentials | None = None,
    dry_run: bool = False,
) -> UploadResult:
    started = time.perf_counter()
    base = sessions_dir or Path("out/sessions")
    sdir = base / session_id
    meta_path = sdir / "episode.yaml"
    video_path = sdir / "reel.mp4"
    thumb_path = sdir / "thumb.jpg"

    if not meta_path.is_file():
        return UploadResult(ok=False, error=f"episode.yaml not found: {meta_path}")
    if not video_path.is_file():
        return UploadResult(ok=False, error=f"reel.mp4 not found: {video_path}")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return UploadResult(ok=False, error=f"episode.yaml malformed: {exc}")

    body = build_video_resource(meta)

    if dry_run:
        return UploadResult(
            ok=True, video_id=None, video_url=None,
            response={"dry_run": True, "body": body,
                      "video_bytes": video_path.stat().st_size,
                      "thumbnail": str(thumb_path) if thumb_path.is_file() else None},
        )

    creds = creds or YtCredentials.from_env()
    try:
        access_token = await refresh_access_token(creds)
        location = await _initiate_resumable_upload(
            access_token=access_token, body=body,
            video_bytes=video_path.stat().st_size,
        )
        # Pass creds to the chunked PUT so it can refresh the access
        # token mid-upload if the original expires (audit fix C14).
        response = await _put_video_bytes(
            location_url=location, video_path=video_path, refresh_creds=creds,
        )
    except Exception as exc:  # noqa: BLE001
        return UploadResult(
            ok=False,
            elapsed_ms=(time.perf_counter() - started) * 1000,
            error=f"{type(exc).__name__}: {exc}",
        )

    video_id = response.get("id")
    video_url = f"https://youtu.be/{video_id}" if video_id else None

    if upload_thumbnail and thumb_path.is_file() and video_id:
        try:
            # Audit fix: refresh the access token before the thumbnail
            # call — a long PUT could have left the original expired.
            access_token = await refresh_access_token(creds)
            await _set_thumbnail(
                access_token=access_token, video_id=video_id, thumb_path=thumb_path,
            )
        except Exception as exc:  # noqa: BLE001
            # Non-fatal: log via the response, video still uploaded.
            response = {**response, "thumbnail_error": str(exc)}

    return UploadResult(
        ok=True, video_id=video_id, video_url=video_url, response=response,
        elapsed_ms=(time.perf_counter() - started) * 1000,
    )


# ----- CLI ---------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="tradefarm.yt.upload",
        description="Upload reel.mp4 + thumbnail to YouTube.",
    )
    parser.add_argument("session_id")
    parser.add_argument("--out", type=Path, default=Path("out/sessions"))
    parser.add_argument("--no-thumbnail", action="store_true",
                        help="Skip the custom-thumbnail upload step.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the request body without calling YT.")
    args = parser.parse_args(argv)

    try:
        result = asyncio.run(upload_episode(
            args.session_id,
            sessions_dir=args.out,
            upload_thumbnail=not args.no_thumbnail,
            dry_run=args.dry_run,
        ))
    except RuntimeError as exc:
        raise SystemExit(f"upload failed to start: {exc}") from exc

    if args.dry_run:
        print(json.dumps(result.response, indent=2))
        return
    if not result.ok:
        print(f"FAIL: {result.error}", file=__import__('sys').stderr)
        raise SystemExit(1)
    print(
        f"session_id={args.session_id}\n"
        f"video_id={result.video_id}\n"
        f"video_url={result.video_url}\n"
        f"elapsed={int(result.elapsed_ms or 0)}ms"
    )


if __name__ == "__main__":
    main()
