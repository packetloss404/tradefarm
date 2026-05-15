"""YouTubeChatPoller — dormancy, OAuth refresh, seeding, color, quota.

All HTTP traffic is faked. ``httpx.AsyncClient`` is patched via a stub that
matches the subset of the API the poller uses (``post`` + ``get``).
``publish_event`` is patched to a list-appender so we can inspect each
emitted payload.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from tradefarm.config import settings
from tradefarm.orchestrator import youtube_chat as yt
from tradefarm.orchestrator.youtube_chat import (
    YouTubeChatPoller,
    _NoActiveBroadcast,
    _QuotaExceeded,
    _derive_color,
)


# ---------------------------------------------------------------------------
# Faux httpx response & client.
# ---------------------------------------------------------------------------


@dataclass
class _FakeResponse:
    status_code: int = 200
    _payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code}: {self.text}")


@dataclass
class _Call:
    method: str
    url: str
    params: dict[str, str] | None
    data: dict[str, str] | None
    headers: dict[str, str] | None


class _FakeClient:
    """Stand-in for ``httpx.AsyncClient`` used inside an ``async with`` block.

    Supports queuing per-URL response sequences. The fake supports both an
    explicit per-URL queue (preferred) and a simple fallback queue used when
    no URL-keyed response is registered.
    """

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self._by_url: dict[str, list[_FakeResponse]] = {}
        self._fallback: list[_FakeResponse] = []

    def queue(self, url: str, response: _FakeResponse) -> None:
        self._by_url.setdefault(url, []).append(response)

    def queue_fallback(self, response: _FakeResponse) -> None:
        self._fallback.append(response)

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN001
        return None

    async def post(
        self,
        url: str,
        data: dict[str, str] | None = None,
        **_: Any,
    ) -> _FakeResponse:
        self.calls.append(_Call(method="POST", url=url, params=None, data=data, headers=None))
        return self._pop(url)

    async def get(
        self,
        url: str,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        **_: Any,
    ) -> _FakeResponse:
        self.calls.append(
            _Call(method="GET", url=url, params=params, data=None, headers=headers)
        )
        return self._pop(url)

    def _pop(self, url: str) -> _FakeResponse:
        queue = self._by_url.get(url)
        if queue:
            return queue.pop(0)
        if self._fallback:
            return self._fallback.pop(0)
        raise AssertionError(f"_FakeClient: no response queued for {url}")


def _install_fake_client(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> None:
    """Patch ``httpx.AsyncClient`` inside the poller module to return ``client``."""

    def _factory(*_args, **_kwargs):
        return client

    monkeypatch.setattr(yt.httpx, "AsyncClient", _factory)


def _enable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_chat_enabled", True)
    monkeypatch.setattr(settings, "youtube_client_id", "cid")
    monkeypatch.setattr(settings, "youtube_client_secret", "csec")
    monkeypatch.setattr(settings, "youtube_refresh_token", "rtok")


# ---------------------------------------------------------------------------
# 1. Dormancy — disabled / missing creds → no task, no HTTP.
# ---------------------------------------------------------------------------


async def test_disabled_when_flag_off(monkeypatch):
    monkeypatch.setattr(settings, "youtube_chat_enabled", False)
    monkeypatch.setattr(settings, "youtube_client_id", "cid")
    monkeypatch.setattr(settings, "youtube_client_secret", "csec")
    monkeypatch.setattr(settings, "youtube_refresh_token", "rtok")

    fake = _FakeClient()  # would error on access — but we shouldn't touch it
    _install_fake_client(monkeypatch, fake)

    poller = YouTubeChatPoller()
    await poller.start()
    assert poller._task is None
    assert fake.calls == []
    await poller.stop()  # idempotent on dormant poller


async def test_disabled_when_creds_missing(monkeypatch):
    monkeypatch.setattr(settings, "youtube_chat_enabled", True)
    monkeypatch.setattr(settings, "youtube_client_id", "")  # missing
    monkeypatch.setattr(settings, "youtube_client_secret", "csec")
    monkeypatch.setattr(settings, "youtube_refresh_token", "rtok")

    fake = _FakeClient()
    _install_fake_client(monkeypatch, fake)

    poller = YouTubeChatPoller()
    await poller.start()
    assert poller._task is None
    assert fake.calls == []


# ---------------------------------------------------------------------------
# 2. Token refresh on 401 → retry succeeds.
# ---------------------------------------------------------------------------


async def test_401_triggers_refresh_and_retries(monkeypatch):
    _enable_settings(monkeypatch)
    fake = _FakeClient()

    # First token refresh (initial _ensure_access_token).
    fake.queue(
        yt.OAUTH_TOKEN_URL,
        _FakeResponse(status_code=200, _payload={"access_token": "tok-1", "expires_in": 3600}),
    )
    # First liveBroadcasts call: 401 (stale token).
    fake.queue(
        yt.LIVE_BROADCASTS_URL,
        _FakeResponse(status_code=401, _payload={}, text="unauth"),
    )
    # The 401 path triggers a token refresh inside _authed_get.
    fake.queue(
        yt.OAUTH_TOKEN_URL,
        _FakeResponse(status_code=200, _payload={"access_token": "tok-2", "expires_in": 3600}),
    )
    # Retried liveBroadcasts call succeeds.
    fake.queue(
        yt.LIVE_BROADCASTS_URL,
        _FakeResponse(
            status_code=200,
            _payload={
                "items": [
                    {"snippet": {"liveChatId": "chat-xyz"}}
                ]
            },
        ),
    )
    # First liveChatMessages call — seeds the cursor (no publishes).
    fake.queue(
        yt.LIVE_CHAT_MESSAGES_URL,
        _FakeResponse(
            status_code=200,
            _payload={
                "items": [],
                "nextPageToken": "page-1",
                "pollingIntervalMillis": 5000,
            },
        ),
    )

    _install_fake_client(monkeypatch, fake)

    poller = YouTubeChatPoller()
    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.youtube_chat.publish_event", fake_publish):
        async with yt.httpx.AsyncClient() as client:
            sleep_for = await poller._tick(client)

    # Token was refreshed twice (initial + after 401).
    token_posts = [c for c in fake.calls if c.url == yt.OAUTH_TOKEN_URL and c.method == "POST"]
    assert len(token_posts) == 2
    # Final token in use is "tok-2".
    assert poller._access_token == "tok-2"
    assert poller._live_chat_id == "chat-xyz"
    # Seeded, no publishes.
    assert poller._seeded is True
    assert poller._next_page_token == "page-1"
    assert fake_publish.await_count == 0
    assert sleep_for == 5.0


# ---------------------------------------------------------------------------
# 3. First-page seeding: initial poll discards, second poll publishes.
# ---------------------------------------------------------------------------


async def test_first_poll_seeds_then_second_poll_publishes(monkeypatch):
    _enable_settings(monkeypatch)
    fake = _FakeClient()

    # Token refresh.
    fake.queue(
        yt.OAUTH_TOKEN_URL,
        _FakeResponse(status_code=200, _payload={"access_token": "tok", "expires_in": 3600}),
    )
    # liveBroadcasts.
    fake.queue(
        yt.LIVE_BROADCASTS_URL,
        _FakeResponse(
            status_code=200,
            _payload={"items": [{"snippet": {"liveChatId": "lc-1"}}]},
        ),
    )
    # First liveChatMessages — has messages but we should DROP them (seeding).
    fake.queue(
        yt.LIVE_CHAT_MESSAGES_URL,
        _FakeResponse(
            status_code=200,
            _payload={
                "items": [
                    _make_message("old-1", "Ghost", "history", color_flags={}),
                ],
                "nextPageToken": "page-1",
                "pollingIntervalMillis": 4000,
            },
        ),
    )
    # Second liveChatMessages — these get published.
    fake.queue(
        yt.LIVE_CHAT_MESSAGES_URL,
        _FakeResponse(
            status_code=200,
            _payload={
                "items": [
                    _make_message("new-1", "Alice", "hi", color_flags={}),
                    _make_message(
                        "new-2",
                        "Bob",
                        "mod here",
                        color_flags={"isChatModerator": True},
                    ),
                ],
                "nextPageToken": "page-2",
                "pollingIntervalMillis": 4000,
            },
        ),
    )

    _install_fake_client(monkeypatch, fake)

    poller = YouTubeChatPoller()
    fake_publish = AsyncMock()
    with patch("tradefarm.orchestrator.youtube_chat.publish_event", fake_publish):
        async with yt.httpx.AsyncClient() as client:
            await poller._tick(client)  # seeds
            assert fake_publish.await_count == 0
            await poller._tick(client)  # publishes

    payloads = [call.args[1] for call in fake_publish.await_args_list]
    assert len(payloads) == 2
    assert payloads[0]["id"] == "new-1"
    assert payloads[0]["user"] == "Alice"
    assert payloads[0]["text"] == "hi"
    assert payloads[0]["source"] == "youtube"
    assert payloads[0]["color"] == "neutral"
    assert payloads[0]["at"] == "2026-05-14T12:00:00Z"
    assert payloads[1]["color"] == "moderator"


# ---------------------------------------------------------------------------
# 4. Author color derivation.
# ---------------------------------------------------------------------------


def test_color_owner_wins_over_other_flags():
    author = {
        "isChatOwner": True,
        "isChatModerator": True,
        "isChatSponsor": True,
    }
    assert _derive_color(author) == "owner"


def test_color_moderator_over_sponsor():
    author = {"isChatModerator": True, "isChatSponsor": True}
    assert _derive_color(author) == "moderator"


def test_color_sponsor_member():
    assert _derive_color({"isChatSponsor": True}) == "member"


def test_color_regular_neutral():
    assert _derive_color({}) == "neutral"


# ---------------------------------------------------------------------------
# 5. Quota-exceeded 403 → raises _QuotaExceeded (loop handles via long sleep).
# ---------------------------------------------------------------------------


async def test_quota_exceeded_raises_specific_exception(monkeypatch):
    _enable_settings(monkeypatch)
    fake = _FakeClient()

    fake.queue(
        yt.OAUTH_TOKEN_URL,
        _FakeResponse(status_code=200, _payload={"access_token": "tok", "expires_in": 3600}),
    )
    fake.queue(
        yt.LIVE_BROADCASTS_URL,
        _FakeResponse(
            status_code=403,
            _payload={
                "error": {
                    "errors": [{"reason": "quotaExceeded", "message": "out of quota"}],
                    "code": 403,
                }
            },
            text="quota",
        ),
    )

    _install_fake_client(monkeypatch, fake)
    poller = YouTubeChatPoller()
    with pytest.raises(_QuotaExceeded):
        async with yt.httpx.AsyncClient() as client:
            await poller._tick(client)


# ---------------------------------------------------------------------------
# 6. No active broadcast → raises _NoActiveBroadcast for the long-sleep path.
# ---------------------------------------------------------------------------


async def test_no_active_broadcast(monkeypatch):
    _enable_settings(monkeypatch)
    fake = _FakeClient()

    fake.queue(
        yt.OAUTH_TOKEN_URL,
        _FakeResponse(status_code=200, _payload={"access_token": "tok", "expires_in": 3600}),
    )
    fake.queue(
        yt.LIVE_BROADCASTS_URL,
        _FakeResponse(status_code=200, _payload={"items": []}),
    )

    _install_fake_client(monkeypatch, fake)
    poller = YouTubeChatPoller()
    with pytest.raises(_NoActiveBroadcast):
        async with yt.httpx.AsyncClient() as client:
            await poller._tick(client)


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _make_message(
    msg_id: str,
    user: str,
    text: str,
    color_flags: dict[str, bool],
) -> dict[str, Any]:
    author = {"displayName": user}
    author.update(color_flags)
    return {
        "id": msg_id,
        "snippet": {
            "displayMessage": text,
            "publishedAt": "2026-05-14T12:00:00Z",
        },
        "authorDetails": author,
    }
