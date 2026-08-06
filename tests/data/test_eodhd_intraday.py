"""0.24.0 — EodhdClient.get_intraday tests.

Mirrors the structure of ``test_eodhd_retries.py`` but covers the
new intraday path: subscription-required short-circuit, retry
envelope, empty-frame schema normalization, timestamp column
unification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from tradefarm.data import eodhd as eodhd_mod


@dataclass
class _FakeRequest:
    url: str = "https://eodhd.com/api/intraday/SPY.US"


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
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.get_count = 0

    async def get(self, url: str, params: dict[str, str] | None = None, **_: Any):
        self.get_count += 1
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_shared_http_client(monkeypatch):
    """The shared client singleton must reset between tests so each
    test gets a fresh fake.
    """
    from tradefarm.runtime import http as runtime_http

    monkeypatch.setattr(runtime_http, "_client", None)
    yield
    monkeypatch.setattr(runtime_http, "_client", None)


def _install_fake_client(monkeypatch, responses: list[_FakeResponse]) -> _FakeClient:
    fake = _FakeClient(responses)
    monkeypatch.setattr(eodhd_mod.settings, "eodhd_api_key", "test-key")
    # Patch the shared client's get_shared_client. The eodhd
    # module does ``from tradefarm.runtime.http import
    # get_shared_client`` lazily inside the function, so the
    # function-local name is resolved at call time. Patching
    # ``tradefarm.runtime.http.get_shared_client`` (the source
    # module, not eodhd's local name) is what takes effect.
    from tradefarm.runtime import http as runtime_http
    async def _fake_get_shared_client(**_kwargs: Any):
        return fake
    monkeypatch.setattr(runtime_http, "get_shared_client", _fake_get_shared_client)
    return fake


async def test_intraday_returns_normalized_dataframe(monkeypatch) -> None:
    # Three intraday bars, 5m apart, Unix-ms timestamps.
    base_ms = int(
        datetime(2026, 8, 5, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    payload = [
        {
            "datetime": str(base_ms),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000,
        },
        {
            "datetime": str(base_ms + 5 * 60 * 1000),
            "open": 100.5, "high": 102.0, "low": 100.0, "close": 101.0, "volume": 1500,
        },
        {
            "datetime": str(base_ms + 10 * 60 * 1000),
            "open": 101.0, "high": 101.5, "low": 100.5, "close": 101.2, "volume": 2000,
        },
    ]
    fake = _install_fake_client(monkeypatch, [_FakeResponse(status_code=200, _payload=payload)])
    client = eodhd_mod.EodhdClient(api_key="test-key")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    df = await client.get_intraday("SPY", start=start, end=end, period="5m")
    assert len(df) == 3
    assert "datetime" in df.columns
    # Normalized: tz-aware UTC.
    assert df["datetime"].dt.tz is not None
    # The most-recent close is the second's 101.0... wait, the last
    # row's close is 101.2. Verify the row order is preserved.
    assert float(df["close"].iloc[-1]) == 101.2
    assert fake.get_count == 1


async def test_intraday_empty_response_returns_empty_dataframe(monkeypatch) -> None:
    _install_fake_client(monkeypatch, [_FakeResponse(status_code=200, _payload=[])])
    client = eodhd_mod.EodhdClient(api_key="test-key")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    df = await client.get_intraday("SPY", start=start, end=end, period="5m")
    assert df.empty
    # Schema is preserved on the empty frame so downstream code can
    # safely read ``df["close"]`` without KeyError.
    assert list(df.columns) == [
        "datetime", "open", "high", "low", "close", "volume",
    ]


async def test_intraday_subscription_required_short_circuits(monkeypatch) -> None:
    """EODHD's /intraday is paid-tier. A 401/403 returns an empty
    frame and a single info log; the operator's tick is not killed.
    """
    fake = _install_fake_client(monkeypatch, [_FakeResponse(status_code=403, text="subscription required")])
    client = eodhd_mod.EodhdClient(api_key="test-key")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    df = await client.get_intraday("SPY", start=start, end=end, period="5m")
    assert df.empty
    # No retries on 401/403 — one call, no exponential backoff.
    assert fake.get_count == 1


async def test_intraday_retries_on_5xx(monkeypatch) -> None:
    """The same retry envelope as get_eod: 5xx + 429 get up to 3
    retries with exponential backoff.
    """
    base_ms = int(
        datetime(2026, 8, 5, 14, 30, 0, tzinfo=timezone.utc).timestamp() * 1000
    )
    ok_payload = [
        {
            "datetime": str(base_ms),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000,
        }
    ]
    responses = [
        _FakeResponse(status_code=503, text="upstream down"),
        _FakeResponse(status_code=503, text="upstream down"),
        _FakeResponse(status_code=200, _payload=ok_payload),
    ]
    fake = _install_fake_client(monkeypatch, responses)
    # Capture sleep calls without sleeping.
    sleeps: list[float] = []
    async def _record_sleep(d: float) -> None:
        sleeps.append(d)
    monkeypatch.setattr(eodhd_mod.asyncio, "sleep", _record_sleep)

    client = eodhd_mod.EodhdClient(api_key="test-key")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    df = await client.get_intraday("SPY", start=start, end=end, period="5m")
    assert len(df) == 1
    # Two 503s + one 200 = 3 GETs.
    assert fake.get_count == 3
    # Two sleeps (one between each retry); delays are positive.
    assert len(sleeps) == 2
    assert all(d > 0 for d in sleeps)


async def test_intraday_raises_after_max_retries(monkeypatch) -> None:
    responses = [
        _FakeResponse(status_code=503, text="upstream down"),
        _FakeResponse(status_code=503, text="upstream down"),
        _FakeResponse(status_code=503, text="upstream down"),
        _FakeResponse(status_code=503, text="upstream down"),
    ]
    _install_fake_client(monkeypatch, responses)
    # Replace sleep with a no-op so the test doesn't actually wait.
    async def _noop_sleep(_d: float) -> None:
        return None
    monkeypatch.setattr(eodhd_mod.asyncio, "sleep", _noop_sleep)

    client = eodhd_mod.EodhdClient(api_key="test-key")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(httpx.HTTPStatusError):
        await client.get_intraday("SPY", start=start, end=end, period="5m")


async def test_intraday_requires_api_key(monkeypatch) -> None:
    """No API key -> RuntimeError. The orchestrator's catch in
    _refresh_intraday_marks means this falls through to the daily
    mark, not a crashed tick.
    """
    monkeypatch.setattr(eodhd_mod.settings, "eodhd_api_key", "")
    client = eodhd_mod.EodhdClient(api_key="")
    start = datetime(2026, 8, 5, 14, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 8, 5, 15, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError, match="EODHD_API_KEY"):
        await client.get_intraday("SPY", start=start, end=end, period="5m")
