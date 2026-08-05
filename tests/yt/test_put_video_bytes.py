"""Audit fix (round-3 V): ``_put_video_bytes`` 308-no-Range handling.

When YouTube returns 308 (incomplete) with no/unparseable Range header,
the server has UNKNOWN bytes — the cursor must NOT optimistically
advance (that would skip unwritten bytes silently and corrupt the
upload). Instead the same chunk is re-PUT after a brief backoff.

The round-3 V fix replaced a buggy
``locals().get("_same_offset_retries", 0) + 1`` (which measured lifetime
no-Range 308s across the whole upload) with an explicit counter that
resets whenever the offset actually advances. This test drives the
function with a fake httpx that returns 308-no-Range TWICE then 200,
and asserts:

  1. the cursor (offset / fh.tell()) did NOT advance between the two
     308 responses;
  2. the same chunk bytes were re-PUT both times;
  3. the function returned the 200 response payload.

0.12.0: ``_put_video_bytes`` now reuses the shared httpx client
(``tradefarm.runtime.http.get_shared_client``) instead of constructing
its own ``httpx.AsyncClient`` inside the function body. The test
patches ``up.get_shared_client`` (not ``httpx.AsyncClient``) to return
the fake client directly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tradefarm.yt import upload as up


@dataclass
class _FakeResponse:
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    _payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self._payload


@dataclass
class _PutCall:
    offset: int  # parsed from Content-Range start byte
    content_length: int
    body_first_byte: int  # first byte of the chunk (so we see if bytes match)
    body_len: int


class _FakeClient:
    """Records every PUT and returns scripted responses in order.

    No ``__aenter__``/``__aexit__`` — the shared-client migration
    (0.12.0) dropped the ``async with httpx.AsyncClient(...) as
    client`` wrapper around the upload body. The client is now
    returned directly from ``get_shared_client()``.
    """

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.put_calls: list[_PutCall] = []

    async def put(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
        **_: Any,
    ) -> _FakeResponse:
        headers = headers or {}
        content = content or b""
        content_range = headers.get("Content-Range", "")
        # Format: "bytes <start>-<end>/<total>"
        offset = 0
        if content_range.startswith("bytes "):
            try:
                offset = int(content_range.split(" ", 1)[1].split("-", 1)[0])
            except (ValueError, IndexError):
                offset = -1
        self.put_calls.append(
            _PutCall(
                offset=offset,
                content_length=int(headers.get("Content-Length", "0")),
                body_first_byte=content[0] if content else -1,
                body_len=len(content),
            )
        )
        return self._responses.pop(0)


async def test_put_video_bytes_does_not_advance_on_308_without_range(
    tmp_path: Path,
    monkeypatch,
):
    # Tiny "video" — a single chunk's worth of recognisable bytes.
    # We use 16 bytes (well under RESUMABLE_CHUNK_BYTES) so the whole
    # file is one chunk; the 308-no-Range retry must re-PUT the same
    # 16 bytes from offset 0.
    video_path = tmp_path / "tiny.mp4"
    video_path.write_bytes(bytes(range(16)))  # 0x00, 0x01, ..., 0x0F

    responses = [
        # First PUT — 308 with NO Range header. Cursor must stay at 0.
        _FakeResponse(status_code=308, headers={}),
        # Second PUT — 308 with NO Range header again. Still at 0.
        _FakeResponse(status_code=308, headers={}),
        # Third PUT — 200 OK. Final chunk accepted.
        _FakeResponse(
            status_code=200,
            _payload={"id": "vid-abc", "status": {"uploadStatus": "uploaded"}},
        ),
    ]
    fake = _FakeClient(responses)

    # 0.12.0 — patch the shared-client factory so the chunked PUT
    # body uses the fake. The real ``httpx.AsyncClient`` constructor
    # is no longer called inside ``_put_video_bytes``.
    async def _get_fake() -> _FakeClient:
        return fake

    monkeypatch.setattr(up, "get_shared_client", _get_fake)

    # Avoid the 1s backoff between 308-no-Range retries.
    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(up.asyncio, "sleep", _no_sleep)

    result = await up._put_video_bytes(
        location_url="https://upload.googleapis.com/resumable/xyz",
        video_path=video_path,
        refresh_creds=None,
    )

    # 1. Cursor never advanced between the two 308s — all three PUTs
    #    targeted offset 0.
    assert [c.offset for c in fake.put_calls] == [0, 0, 0], (
        "Audit-V: cursor must NOT advance on 308-no-Range; all PUTs "
        "should re-target the same offset"
    )

    # 2. Same chunk bytes re-PUT each time (first byte is 0x00, full
    #    16 bytes resent).
    for call in fake.put_calls:
        assert call.body_first_byte == 0
        assert call.body_len == 16
        assert call.content_length == 16

    # 3. Final 200 payload is returned.
    assert result == {"id": "vid-abc", "status": {"uploadStatus": "uploaded"}}


async def test_put_video_bytes_bails_after_six_consecutive_same_offset_308s(
    tmp_path: Path,
    monkeypatch,
):
    """Audit-V: the same-offset-retries counter caps at 5. The 6th
    consecutive 308-no-Range at the same offset must raise so the
    operator notices a stuck upload instead of looping forever."""
    video_path = tmp_path / "tiny.mp4"
    video_path.write_bytes(bytes(range(8)))

    # 6+ scripted 308-no-Range responses — function should raise on the
    # 6th retry without consuming them all.
    responses = [_FakeResponse(status_code=308, headers={}) for _ in range(10)]
    fake = _FakeClient(responses)

    # 0.12.0 — patch the shared-client factory (see comment in the
    # 200-OK test above).
    async def _get_fake() -> _FakeClient:
        return fake

    monkeypatch.setattr(up, "get_shared_client", _get_fake)

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(up.asyncio, "sleep", _no_sleep)

    with pytest.raises(RuntimeError, match="stalled at offset"):
        await up._put_video_bytes(
            location_url="https://upload.googleapis.com/resumable/xyz",
            video_path=video_path,
            refresh_creds=None,
        )

    # All retries hit offset 0.
    for call in fake.put_calls:
        assert call.offset == 0
