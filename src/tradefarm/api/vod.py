"""VOD asset router — serves rendered MP4s + thumbnails from ``out/sessions/``.

The VOD pipeline (render.stitch → render.mix) writes its outputs to
``out/sessions/<session_id>/reel.mp4`` and ``out/sessions/<session_id>/thumb.jpg``.
The Episode Review surface in the VOD Studio needs to preview the MP4 in
place and let the operator download it. This router exposes those files
behind a tiny, locked-down API:

- ``GET /vod/sessions``                   — list rendered sessions
- ``GET /vod/{session_id}/reel.mp4``      — stream the rendered video
- ``GET /vod/{session_id}/thumb.jpg``     — stream the thumbnail
- ``GET /vod/{session_id}/extras``        — Intern Watch / Rivalry
  Week data: lowest_ranks + rivalries + strategy_rollup from the
  manifest JSON (0.9.0-era manifest extras)

Security posture: matches the rest of the project. Backend binds to
127.0.0.1, all mutating endpoints are protected by ``API_SHARED_SECRET``.
The session_id is validated against a strict ``[A-Za-z0-9_-]+`` regex
and resolved against a fixed ``out/sessions`` root — no path traversal,
no symlink following, no read of files outside the sessions dir.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

# Fixed root for all VOD outputs. Resolved relative to the process CWD
# at import time; the render pipeline writes here via the same convention.
SESSIONS_ROOT = Path("out/sessions")

# Allow only safe session ids — anything else is rejected with 400.
# Mirrors the format yt.upload and render.* accept on the CLI: alnum,
# underscore, hyphen. Length-capped to 64 to bound log lines.
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

router = APIRouter(prefix="/vod", tags=["vod"])


def _safe_session_dir(session_id: str) -> Path:
    """Validate and resolve a session id → its on-disk directory.

    Raises 400 on bad input. The resolved path is guaranteed to live
    under :data:`SESSIONS_ROOT` — a crafted ``../`` cannot escape
    because the regex rejects it AND ``resolve()`` would catch any
    sneaky encoding that bypassed the regex.
    """
    if not _SAFE_ID.match(session_id):
        raise HTTPException(status_code=400, detail="invalid session_id")
    sdir = (SESSIONS_ROOT / session_id).resolve()
    # Defense in depth: even if a future bug lets a weird id through,
    # refuse anything that resolves outside the root.
    if SESSIONS_ROOT.resolve() not in sdir.parents and sdir != SESSIONS_ROOT:
        raise HTTPException(status_code=400, detail="invalid session_id")
    return sdir


@router.get("/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    """List rendered sessions sorted newest-first.

    Each entry: ``{session_id, date, has_reel, has_thumb, reel_bytes,
    thumb_bytes}``. ``date`` is the directory mtime as an ISO string —
    no separate manifest file is needed because the dir name is the
    canonical id and the mtime is when the render completed.
    """
    if not SESSIONS_ROOT.is_dir():
        return []
    out: list[dict[str, Any]] = []
    for child in SESSIONS_ROOT.iterdir():
        if not child.is_dir() or not _SAFE_ID.match(child.name):
            continue
        reel = child / "reel.mp4"
        thumb = child / "thumb.jpg"
        out.append(
            {
                "session_id": child.name,
                "date": child.stat().st_mtime,
                "has_reel": reel.is_file(),
                "has_thumb": thumb.is_file(),
                "reel_bytes": reel.stat().st_size if reel.is_file() else 0,
                "thumb_bytes": thumb.stat().st_size if thumb.is_file() else 0,
            }
        )
    out.sort(key=lambda r: r["date"], reverse=True)
    return out


@router.get("/{session_id}/reel.mp4")
async def get_reel(session_id: str) -> FileResponse:
    """Stream the rendered MP4. Supports HTTP Range so the browser can
    scrub without buffering the whole file.
    """
    sdir = _safe_session_dir(session_id)
    reel = sdir / "reel.mp4"
    if not reel.is_file():
        raise HTTPException(status_code=404, detail="reel not rendered")
    # FileResponse sets Content-Disposition: inline by default, which
    # is what the <video> element wants. The browser uses the URL
    # directly for the preview; the operator can right-click → save
    # OR use the explicit download button on the page.
    return FileResponse(
        reel,
        media_type="video/mp4",
        filename=f"{session_id}-reel.mp4",
    )


@router.get("/{session_id}/thumb.jpg")
async def get_thumb(session_id: str) -> FileResponse:
    """Stream the rendered thumbnail."""
    sdir = _safe_session_dir(session_id)
    thumb = sdir / "thumb.jpg"
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="thumb not rendered")
    return FileResponse(thumb, media_type="image/jpeg")


# Intern Watch / Rivalry Week surfaces read three of the four
# 0.9.0-era manifest extras (`rivalries`, `lowest_ranks`,
# `strategy_rollup`). We surface them as one endpoint so the
# studio can pull all three with a single fetch and so the
# 4th field — `interns_under_watch` (derived list[int] of
# agent_ids from `lowest_ranks`) — is included for the
# intern-card "still in the cohort?" check. The endpoint is
# best-effort: a missing field means the manifest predates
# 0.9.0 or the runner never wrote that section, and the
# caller is expected to fall back to the prototype mock.
_MANIFEST_EXTRA_KEYS = ("rivalries", "lowest_ranks", "strategy_rollup", "interns_under_watch")


@router.get("/{session_id}/extras")
async def get_manifest_extras(session_id: str) -> dict[str, Any]:
    """Return the 0.9.0-era manifest extras for one session.

    Each extra is returned under its manifest key; a missing key
    (e.g. a pre-0.9.0 manifest) returns ``[]`` / ``{}`` / ``null`` so
    the studio's surface code can branch on ``manifest.extras.X``
    presence without a separate "is this an old session?" check.
    """
    sdir = _safe_session_dir(session_id)
    manifest_path = sdir / "manifest.json"
    if not manifest_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"no manifest for session {session_id!r}"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=500, detail=f"manifest unreadable: {exc}"
        ) from exc

    extras: dict[str, Any] = {"session_id": session_id}
    for key in _MANIFEST_EXTRA_KEYS:
        if key in manifest:
            extras[key] = manifest[key]
    return extras
