"""Audit fix (H25): EodhdClient.get_eod retries transient 429 / 5xx
responses with exponential backoff before giving up.

This test drives the retry loop with a fake httpx client that returns
429 twice then 200, and asserts:

  - the call ultimately succeeds (200 response payload is returned);
  - ``asyncio.sleep`` was awaited twice (one sleep per retry);
  - the two sleep delays are monotonically increasing (exponential).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx
import pytest

from tradefarm.data import eodhd as eodhd_mod


@dataclass
class _FakeRequest:
    url: str = "https://eodhd.com/api/eod/SPY.US"


@dataclass
class _FakeResponse:
    status_code: int
    _payload: Any = field(default_factory=list)
    text: str = ""
    request: _FakeRequest = field(default_factory=_FakeRequest)

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        if 400 <= self.status_code < 600:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self,  # type: ignore[arg-type]
            )


class _FakeClient:
    """Returns scripted responses in order; counts GETs."""

    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.get_count = 0

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc) -> None:  # noqa: ANN001
        return None

    async def get(self, url: str, params: dict[str, str] | None = None, **_: Any):
        self.get_count += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_shared_http_client(monkeypatch):
    """Round-5 (AA) — EodhdClient now reuses a process-wide httpx
    client. Tests that monkeypatch httpx.AsyncClient need the
    singleton reset so each test gets its own fake."""
    from tradefarm.runtime import http as runtime_http

    monkeypatch.setattr(runtime_http, "_client", None)
    yield
    monkeypatch.setattr(runtime_http, "_client", None)


async def test_eodhd_retries_on_429_and_succeeds_with_increasing_backoff(monkeypatch, tmp_path):
    # Disable the bar cache so the retry path is exercised (cache hit
    # would short-circuit). Point the cache dir at a fresh tmp_path so a
    # successful response still has somewhere to merge into.
    from tradefarm.data import bar_cache

    monkeypatch.setattr(bar_cache, "CACHE_DIR", tmp_path / "bars")

    # Make sure the API key check passes.
    monkeypatch.setattr(eodhd_mod.settings, "eodhd_api_key", "test-key")

    # Two 429s then a 200 with a one-bar payload.
    one_bar = [
        {
            "date": "2026-05-01",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "adjusted_close": 100.5,
            "volume": 1_000_000,
        }
    ]
    responses = [
        _FakeResponse(status_code=429, text="rate limited"),
        _FakeResponse(status_code=429, text="rate limited"),
        _FakeResponse(status_code=200, _payload=one_bar),
    ]
    fake = _FakeClient(responses)

    def _factory(*_a, **_kw):
        return fake

    monkeypatch.setattr(httpx, "AsyncClient", _factory)

    # Capture sleep calls without actually sleeping.
    sleep_calls: list[float] = []

    async def _record_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(eodhd_mod.asyncio, "sleep", _record_sleep)

    client = eodhd_mod.EodhdClient(api_key="test-key", use_cache=False)
    df = await client.get_eod(
        "SPY",
        start=date(2026, 5, 1),
        end=date(2026, 5, 1),
    )

    # Final 200 payload made it back as a DataFrame.
    assert len(df) == 1
    assert float(df["adjusted_close"].iloc[0]) == 100.5

    # All three GETs happened.
    assert fake.get_count == 3

    # Two sleeps occurred (one between attempt 0→1 and one between 1→2).
    assert len(sleep_calls) == 2, (
        "Audit H25: expected exactly two backoff sleeps for two retries; "
        f"got {len(sleep_calls)}: {sleep_calls}"
    )

    # Monotonically increasing (exponential: 0.5s, 1.0s, ...).
    assert sleep_calls[0] < sleep_calls[1], (
        f"Audit H25: backoff delays must increase monotonically; got {sleep_calls}"
    )

    # Spot-check the values match the implementation: `(2**attempt) * 0.5`
    # → 0.5 and 1.0 for attempts 0 and 1.
    assert sleep_calls[0] == pytest.approx(0.5)
    assert sleep_calls[1] == pytest.approx(1.0)


async def test_eodhd_gives_up_after_max_retries(monkeypatch, tmp_path):
    """All 4 attempts (initial + 3 retries) return 429 → raises."""
    from tradefarm.data import bar_cache

    monkeypatch.setattr(bar_cache, "CACHE_DIR", tmp_path / "bars")
    monkeypatch.setattr(eodhd_mod.settings, "eodhd_api_key", "test-key")

    responses = [_FakeResponse(status_code=429, text="x") for _ in range(4)]
    fake = _FakeClient(responses)
    monkeypatch.setattr(httpx, "AsyncClient", lambda *_a, **_kw: fake)

    sleep_calls: list[float] = []

    async def _record_sleep(delay: float):
        sleep_calls.append(delay)

    monkeypatch.setattr(eodhd_mod.asyncio, "sleep", _record_sleep)

    client = eodhd_mod.EodhdClient(api_key="test-key", use_cache=False)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_eod("SPY", start=date(2026, 5, 1), end=date(2026, 5, 1))

    # All 4 attempts happened.
    assert fake.get_count == 4
    # 3 sleeps (after attempts 0, 1, 2 — no sleep after the final failure).
    assert len(sleep_calls) == 3
