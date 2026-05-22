"""Audit fix (H9): consecutive-failure circuit breaker on the YouTube
OAuth refresh path.

After 5 consecutive 400 responses (e.g. revoked refresh token), the
poller opens a 1-hour circuit. The 6th call into ``_ensure_access_token``
must raise WITHOUT hitting Google's OAuth endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from tradefarm.config import settings
from tradefarm.orchestrator import youtube_chat as yt
from tradefarm.orchestrator.youtube_chat import YouTubeChatPoller


@dataclass
class _FakeResponse:
    status_code: int = 400
    _payload: dict[str, Any] = field(default_factory=dict)
    text: str = ""

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeClient:
    """Counts every POST to the OAuth endpoint so we can prove the
    6th call short-circuited."""

    def __init__(self) -> None:
        self.token_post_count: int = 0

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN001
        return None

    async def post(self, url: str, data: dict[str, str] | None = None, **_: Any):
        if url == yt.OAUTH_TOKEN_URL:
            self.token_post_count += 1
        # Always 400 — simulates a revoked refresh token.
        return _FakeResponse(
            status_code=400,
            _payload={"error": "invalid_grant"},
            text="invalid_grant",
        )

    async def get(self, *_a, **_kw):  # pragma: no cover — unused
        raise AssertionError("circuit-breaker test should never reach an authed GET")


def _enable_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_chat_enabled", True)
    monkeypatch.setattr(settings, "youtube_client_id", "cid")
    monkeypatch.setattr(settings, "youtube_client_secret", "csec")
    monkeypatch.setattr(settings, "youtube_refresh_token", "rtok")


async def test_five_consecutive_400s_open_circuit_and_sixth_call_short_circuits(
    monkeypatch,
):
    _enable_settings(monkeypatch)
    fake = _FakeClient()

    poller = YouTubeChatPoller()
    # 5 consecutive failing refresh calls.
    for i in range(5):
        with pytest.raises(RuntimeError):
            await poller._refresh_access_token(fake)
        assert poller._refresh_failures == i + 1

    # Circuit is now open.
    assert poller._refresh_circuit_open_until is not None
    assert fake.token_post_count == 5

    # 6th call goes through _ensure_access_token, which sees the open
    # circuit and raises BEFORE touching the HTTP client.
    with pytest.raises(RuntimeError, match="circuit open"):
        await poller._ensure_access_token(fake)

    # Crucial assertion: the OAuth endpoint was NOT hit by the 6th call.
    assert fake.token_post_count == 5, (
        "Audit H9: 6th call must not hit Google's OAuth endpoint while the circuit is open"
    )


async def test_successful_refresh_resets_failure_counter(monkeypatch):
    """After a successful refresh the counter resets so transient 400s
    don't accumulate forever toward the circuit threshold."""
    _enable_settings(monkeypatch)

    class _MixedClient:
        def __init__(self):
            self.token_post_count = 0
            self._scripted = [
                _FakeResponse(status_code=400, _payload={"error": "invalid_grant"}),
                _FakeResponse(status_code=400, _payload={"error": "invalid_grant"}),
                _FakeResponse(
                    status_code=200,
                    _payload={"access_token": "tok", "expires_in": 3600},
                ),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def post(self, url, data=None, **_):
            if url == yt.OAUTH_TOKEN_URL:
                self.token_post_count += 1
            return self._scripted.pop(0)

        async def get(self, *_a, **_kw):  # pragma: no cover
            raise AssertionError("unused")

    fake = _MixedClient()
    poller = YouTubeChatPoller()

    # Two 400s lift the counter.
    with pytest.raises(RuntimeError):
        await poller._refresh_access_token(fake)
    with pytest.raises(RuntimeError):
        await poller._refresh_access_token(fake)
    assert poller._refresh_failures == 2

    # A 200 resets it + closes the circuit.
    await poller._refresh_access_token(fake)
    assert poller._refresh_failures == 0
    assert poller._refresh_circuit_open_until is None
    assert poller._access_token == "tok"
