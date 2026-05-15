"""YouTube Live Chat poller — surfaces real audience messages on the WS bus.

Polls the YouTube Data API v3 ``liveChatMessages.list`` endpoint for the
currently-active live broadcast on the configured channel and republishes new
messages as ``chat_message`` events. The frontend ChatStrip merges these with
its simulated source.

Wire contract (must match the frontend agent):

    {
        "id":     str,
        "user":   str,
        "text":   str,
        "color":  "neutral" | "member" | "moderator" | "owner",
        "source": "youtube",
        "at":     ISO-8601 UTC timestamp,
    }

Lifecycle: ``start()`` is idempotent and never raises. When credentials are
missing or ``youtube_chat_enabled`` is False, the poller logs once and stays
dormant — the trade scheduler keeps running uninterrupted.

OAuth: uses an installed-app refresh-token flow. The one-time consent dance
that produces the refresh token lives in :mod:`tradefarm.tools.youtube_auth`.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import structlog

from tradefarm.api.events import publish_event
from tradefarm.config import settings

log = structlog.get_logger()

OAUTH_TOKEN_URL = "https://oauth2.googleapis.com/token"
LIVE_BROADCASTS_URL = "https://www.googleapis.com/youtube/v3/liveBroadcasts"
LIVE_CHAT_MESSAGES_URL = "https://www.googleapis.com/youtube/v3/liveChat/messages"

# How long before token expiry to refresh proactively.
TOKEN_REFRESH_LEAD = timedelta(minutes=2)

# Default poll interval (server typically returns a ``pollingIntervalMillis``
# we honor; this is the fallback when missing).
DEFAULT_POLL_SEC: float = 5.0
# Sleep when no broadcast is live yet.
NO_BROADCAST_SLEEP_SEC: float = 60.0
# Sleep on 403 quota exhaustion.
QUOTA_EXCEEDED_SLEEP_SEC: float = 600.0
# Initial backoff for generic errors; capped at MAX_BACKOFF_SEC.
INITIAL_BACKOFF_SEC: float = 30.0
MAX_BACKOFF_SEC: float = 300.0

# Network timeouts on httpx — we wrap *all* HTTP in this single client.
HTTP_TIMEOUT_SEC: float = 20.0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _derive_color(author: dict[str, Any]) -> str:
    """Map YouTube author flags onto our 4-color palette.

    Precedence (highest first): owner > moderator > sponsor (member) > regular.
    """
    if author.get("isChatOwner"):
        return "owner"
    if author.get("isChatModerator"):
        return "moderator"
    if author.get("isChatSponsor"):
        return "member"
    return "neutral"


@dataclass
class YouTubeChatPoller:
    """Background task that publishes ``chat_message`` events from YouTube.

    Started/stopped from :class:`Orchestrator`. Self-disabling when
    credentials are missing — no error is raised at boot.
    """

    poll_interval_sec: float = DEFAULT_POLL_SEC

    _task: asyncio.Task | None = field(default=None, init=False, repr=False)
    _stopped: bool = field(default=False, init=False, repr=False)
    _access_token: str | None = field(default=None, init=False, repr=False)
    _access_token_expires_at: datetime | None = field(default=None, init=False, repr=False)
    _live_chat_id: str | None = field(default=None, init=False, repr=False)
    _next_page_token: str | None = field(default=None, init=False, repr=False)
    # First page is used to seed the pagination cursor only — historical chat
    # is NOT replayed. Flipped to True after the first successful poll.
    _seeded: bool = field(default=False, init=False, repr=False)

    async def start(self) -> None:
        """Spin up the background poll task. Idempotent.

        If ``youtube_chat_enabled`` is False or any of the credentials are
        missing, this logs and returns early so the orchestrator never
        crashes on boot.
        """
        if self._task is not None:
            return
        if not self._enabled():
            log.info(
                "youtube_chat_disabled",
                reason="not_configured",
                enabled=settings.youtube_chat_enabled,
                has_client_id=bool(settings.youtube_client_id),
                has_client_secret=bool(settings.youtube_client_secret),
                has_refresh_token=bool(settings.youtube_refresh_token),
            )
            return
        self._task = asyncio.create_task(self._run(), name="orch_youtube_chat")
        log.info("youtube_chat_started", interval_sec=self.poll_interval_sec)

    async def stop(self) -> None:
        """Cancel the poll loop and await its exit."""
        self._stopped = True
        t = self._task
        if t is None:
            return
        t.cancel()
        try:
            await t
        except (asyncio.CancelledError, Exception):
            pass
        self._task = None

    # ------------------------------------------------------------------
    # Internals.
    # ------------------------------------------------------------------

    @staticmethod
    def _enabled() -> bool:
        return bool(
            settings.youtube_chat_enabled
            and settings.youtube_client_id
            and settings.youtube_client_secret
            and settings.youtube_refresh_token
        )

    async def _run(self) -> None:
        backoff = INITIAL_BACKOFF_SEC
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SEC) as client:
            while not self._stopped:
                try:
                    sleep_for = await self._tick(client)
                    backoff = INITIAL_BACKOFF_SEC
                    await asyncio.sleep(sleep_for)
                except asyncio.CancelledError:
                    raise
                except _QuotaExceeded:
                    log.warning("youtube_chat_quota_exceeded")
                    await asyncio.sleep(QUOTA_EXCEEDED_SLEEP_SEC)
                except _NoActiveBroadcast:
                    log.debug("youtube_chat_no_active_broadcast")
                    await asyncio.sleep(NO_BROADCAST_SLEEP_SEC)
                except Exception as e:
                    log.exception("youtube_chat_loop_failed", error=str(e))
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_SEC)

    async def _tick(self, client: httpx.AsyncClient) -> float:
        """Run one poll cycle. Returns the seconds-to-sleep before the next.

        Raises :class:`_NoActiveBroadcast` when the channel isn't live (so the
        outer loop can use its dedicated longer sleep) and
        :class:`_QuotaExceeded` when YouTube returns 403 quotaExceeded.
        """
        await self._ensure_access_token(client)
        await self._ensure_live_chat_id(client)
        return await self._poll_messages(client)

    # -- OAuth ---------------------------------------------------------

    async def _ensure_access_token(self, client: httpx.AsyncClient) -> None:
        now = _utcnow()
        if (
            self._access_token
            and self._access_token_expires_at
            and (self._access_token_expires_at - now) > TOKEN_REFRESH_LEAD
        ):
            return
        await self._refresh_access_token(client)

    async def _refresh_access_token(self, client: httpx.AsyncClient) -> None:
        body = {
            "client_id": settings.youtube_client_id,
            "client_secret": settings.youtube_client_secret,
            "refresh_token": settings.youtube_refresh_token,
            "grant_type": "refresh_token",
        }
        r = await client.post(OAUTH_TOKEN_URL, data=body)
        if r.status_code != 200:
            log.error(
                "youtube_chat_token_refresh_failed",
                status=r.status_code,
                body=r.text[:300],
            )
            r.raise_for_status()
        data = r.json()
        token = data.get("access_token")
        if not token:
            raise RuntimeError("token response missing access_token")
        expires_in = int(data.get("expires_in", 3600))
        self._access_token = token
        self._access_token_expires_at = _utcnow() + timedelta(seconds=expires_in)
        log.info("youtube_chat_token_refreshed", expires_in=expires_in)

    # -- Broadcast discovery ------------------------------------------

    async def _ensure_live_chat_id(self, client: httpx.AsyncClient) -> None:
        if self._live_chat_id is not None:
            return
        params = {
            "part": "snippet",
            "broadcastStatus": "active",
            "broadcastType": "all",
        }
        chat_id = await self._fetch_live_chat_id(client, params)
        if chat_id is None:
            raise _NoActiveBroadcast()
        self._live_chat_id = chat_id
        # Reset pagination state for the new broadcast — we'll seed on the
        # next page fetch.
        self._next_page_token = None
        self._seeded = False
        log.info("youtube_chat_live_chat_id", live_chat_id=chat_id)

    async def _fetch_live_chat_id(
        self, client: httpx.AsyncClient, params: dict[str, str],
    ) -> str | None:
        r = await self._authed_get(client, LIVE_BROADCASTS_URL, params=params)
        data = r.json()
        items = data.get("items") or []
        if not items:
            return None
        return items[0].get("snippet", {}).get("liveChatId")

    # -- Message polling -----------------------------------------------

    async def _poll_messages(self, client: httpx.AsyncClient) -> float:
        assert self._live_chat_id is not None
        params: dict[str, str] = {
            "liveChatId": self._live_chat_id,
            "part": "snippet,authorDetails",
        }
        if self._next_page_token:
            params["pageToken"] = self._next_page_token

        try:
            r = await self._authed_get(client, LIVE_CHAT_MESSAGES_URL, params=params)
        except _LiveChatNotFound:
            # Broadcast ended or moved — clear cache so the next tick re-discovers.
            log.info("youtube_chat_live_chat_id_invalidated")
            self._live_chat_id = None
            self._next_page_token = None
            self._seeded = False
            return 1.0  # quick retry — discovery is cheap

        data = r.json()
        items = data.get("items") or []
        # Honor server-recommended poll interval; default if missing.
        polling_ms = data.get("pollingIntervalMillis")
        try:
            sleep_for = (
                float(polling_ms) / 1000.0
                if polling_ms is not None
                else self.poll_interval_sec
            )
        except (TypeError, ValueError):
            sleep_for = self.poll_interval_sec
        if sleep_for <= 0:
            sleep_for = self.poll_interval_sec

        next_token = data.get("nextPageToken")

        if not self._seeded:
            # First page after (re)discovery — DON'T publish historical
            # messages. Just seed the cursor.
            self._next_page_token = next_token
            self._seeded = True
            log.info(
                "youtube_chat_seeded",
                discarded=len(items),
                next_page=bool(next_token),
            )
            return sleep_for

        self._next_page_token = next_token
        published = 0
        for item in items:
            try:
                payload = self._build_payload(item)
            except Exception as e:
                log.warning("youtube_chat_parse_failed", error=str(e))
                continue
            if payload is None:
                continue
            await publish_event("chat_message", payload)
            published += 1

        if published:
            log.info("youtube_chat_messages", n=published)
        return sleep_for

    @staticmethod
    def _build_payload(item: dict[str, Any]) -> dict[str, Any] | None:
        snippet = item.get("snippet") or {}
        author = item.get("authorDetails") or {}
        msg_id = item.get("id")
        text = snippet.get("displayMessage")
        user = author.get("displayName")
        published_at = snippet.get("publishedAt")
        # Skip messages without the basics — deletions and superchat events
        # may come through without ``displayMessage``.
        if not (msg_id and text and user and published_at):
            return None
        return {
            "id": msg_id,
            "user": user,
            "text": text,
            "color": _derive_color(author),
            "source": "youtube",
            "at": published_at,
        }

    # -- Authed GET with 401 retry + 403 quota detection ----------------

    async def _authed_get(
        self,
        client: httpx.AsyncClient,
        url: str,
        params: dict[str, str],
    ) -> httpx.Response:
        for attempt in (0, 1):
            assert self._access_token is not None
            headers = {"Authorization": f"Bearer {self._access_token}"}
            r = await client.get(url, params=params, headers=headers)
            if r.status_code == 200:
                return r
            if r.status_code == 401 and attempt == 0:
                log.info("youtube_chat_token_stale_retry")
                await self._refresh_access_token(client)
                continue
            if r.status_code == 403 and _is_quota_error(r):
                raise _QuotaExceeded()
            if r.status_code == 404:
                raise _LiveChatNotFound()
            log.warning(
                "youtube_chat_http_error",
                status=r.status_code,
                url=url,
                body=r.text[:300],
            )
            r.raise_for_status()
        # Defensive — unreachable.
        raise RuntimeError("youtube_chat authed_get exhausted retries")


def _is_quota_error(r: httpx.Response) -> bool:
    """Best-effort 403 classifier — YouTube reports ``quotaExceeded`` /
    ``rateLimitExceeded`` reasons inside the error body.
    """
    try:
        data = r.json()
    except Exception:
        return False
    err = data.get("error") or {}
    reason_set = {
        e.get("reason")
        for e in (err.get("errors") or [])
        if isinstance(e, dict)
    }
    quota_reasons = {"quotaExceeded", "rateLimitExceeded", "dailyLimitExceeded"}
    return bool(reason_set & quota_reasons)


class _NoActiveBroadcast(Exception):
    """Channel has no active live broadcast yet — sleep longer and retry."""


class _QuotaExceeded(Exception):
    """YouTube returned 403 quotaExceeded — back off for a long stretch."""


class _LiveChatNotFound(Exception):
    """The cached ``liveChatId`` is no longer valid (broadcast ended)."""
