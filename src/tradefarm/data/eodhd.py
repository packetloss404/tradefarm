import asyncio
import logging
from datetime import date, datetime

import httpx
import pandas as pd
from pydantic import BaseModel

from tradefarm.config import settings
from tradefarm.data import bar_cache

log = logging.getLogger(__name__)

BASE_URL = "https://eodhd.com/api"
# Audit fix (H25): retry budget for transient 5xx / 429 / network blips.
# Backoff is exponential with jitter capped at MAX_RETRY_DELAY_SEC.
EOD_MAX_RETRIES = 3
MAX_RETRY_DELAY_SEC = 8.0


class EodBar(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float
    volume: int


class EodhdClient:
    def __init__(self, api_key: str | None = None, *, use_cache: bool = True) -> None:
        self.api_key = api_key or settings.eodhd_api_key
        self.use_cache = use_cache

    async def get_eod(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        exchange: str = "US",
    ) -> pd.DataFrame:
        if self.use_cache:
            # Audit fix (T): parquet I/O is sync and can take 50-200ms
            # on multi-year frames; offload to a thread so the event
            # loop doesn't stall while the WS bus / scheduler tick
            # waits for the cache read.
            cached = await asyncio.to_thread(bar_cache.load, symbol)
            if bar_cache.covers(cached, start, end):
                return bar_cache.slice_range(cached, start, end)

        if not self.api_key:
            raise RuntimeError("EODHD_API_KEY not configured")

        url = f"{BASE_URL}/eod/{symbol}.{exchange}"
        params = {
            "api_token": self.api_key,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "period": "d",
            "fmt": "json",
        }
        # Audit fix (H25): retry transient 5xx / 429 / network errors.
        # 4xx (other than 429) raise immediately — they're caller errors.
        # Empty 200 responses are now logged so "API healthy, no data"
        # is distinguishable from "API broken" in operator logs.
        # Round-5 audit fix (AA): reuse the process-wide httpx client
        # instead of creating a fresh one per call. With 100 agents
        # ticking every 5 minutes, the previous code paid TLS + pool-
        # init cost ~3k times an hour.
        from tradefarm.runtime.http import get_shared_client

        client = await get_shared_client()
        rows: list = []
        last_exc: Exception | None = None
        for attempt in range(EOD_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params, timeout=30.0)
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"EODHD {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    raise last_exc
                resp.raise_for_status()
                rows = resp.json()
                break
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= EOD_MAX_RETRIES:
                    raise
                delay = min(MAX_RETRY_DELAY_SEC, (2**attempt) * 0.5)
                log.warning(
                    "eodhd_retry symbol=%s attempt=%d delay=%.2fs err=%s",
                    symbol,
                    attempt + 1,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

        df = pd.DataFrame(rows)
        if df.empty:
            # Audit fix: log so the operator can tell "no data" apart
            # from "API healthy, empty range" (delisted symbol, weekend,
            # out-of-coverage). Return an empty frame with the schema
            # column so downstream `slice_range` doesn't KeyError.
            log.info(
                "eodhd_empty_response symbol=%s start=%s end=%s",
                symbol,
                start.isoformat(),
                end.isoformat(),
            )
            return pd.DataFrame(
                columns=["date", "open", "high", "low", "close", "adjusted_close", "volume"]
            )
        df["date"] = pd.to_datetime(df["date"]).dt.date
        if self.use_cache:
            # Audit fix (T): parquet write is sync — offload to a
            # thread so the event loop stays responsive. The per-
            # symbol threading.Lock inside merge() is now correct
            # (running on the threadpool), not loop-blocking.
            merged = await asyncio.to_thread(bar_cache.merge, symbol, df)
            return bar_cache.slice_range(merged, start, end)
        return df

    async def get_real_time(self, symbol: str, exchange: str = "US") -> dict:
        """Delayed quote on free tier; real-time with paid subscription."""
        if not self.api_key:
            raise RuntimeError("EODHD_API_KEY not configured")
        url = f"{BASE_URL}/real-time/{symbol}.{exchange}"
        params = {"api_token": self.api_key, "fmt": "json"}
        # Round-5 audit fix (AA): reuse the shared httpx client.
        from tradefarm.runtime.http import get_shared_client

        client = await get_shared_client()
        resp = await client.get(url, params=params, timeout=15.0)
        resp.raise_for_status()
        return resp.json()

    async def get_intraday(
        self,
        symbol: str,
        *,
        start: datetime,
        end: datetime,
        period: str = "5m",
        exchange: str = "US",
    ) -> pd.DataFrame:
        """0.24.0 - intraday bars (1m / 5m / 1h) from EODHD.

        The daily ``get_eod`` returns yesterday's close as the
        orchestrator's mark for today's tick, so an RTH agent reasons
        on a 24h-stale price. This method backs the 0.24.0 intraday
        mark path: during RTH, the orchestrator fetches today's 5m
        bars and takes the most recent one's close as the mark. Off-
        RTH the daily path stays in charge (no point fetching
        intraday bars when the market is closed).

        EODHD's ``/intraday/{symbol}`` endpoint is a paid feature on
        the free tier (returns 401/403 without a subscription); the
        client wraps the call in the same retry envelope as
        ``get_eod`` so a transient 5xx doesn't kill the tick.
        Returns an empty frame with the documented schema on
        "no data" (delisted symbol, weekend, missing subscription)
        so the orchestrator's fall-through to the daily mark is
        a single ``if df.empty`` check.
        """
        from tradefarm.runtime.http import get_shared_client

        if not self.api_key:
            raise RuntimeError("EODHD_API_KEY not configured")
        url = f"{BASE_URL}/intraday/{symbol}.{exchange}"
        params: dict[str, str | int] = {
            "api_token": self.api_key,
            "from": int(start.timestamp()),
            "to": int(end.timestamp()),
            "period": period,
            "interval": period,
            "fmt": "json",
        }
        client = await get_shared_client()
        rows: list = []
        last_exc: Exception | None = None
        for attempt in range(EOD_MAX_RETRIES + 1):
            try:
                resp = await client.get(url, params=params, timeout=30.0)
                if resp.status_code in (401, 403):
                    # Paid-only endpoint without a subscription. Log
                    # once and return an empty frame so the caller can
                    # fall through to the daily mark. Not retried -
                    # a subscription is either present or not.
                    log.info(
                        "eodhd_intraday_subscription_required symbol=%s status=%d",
                        symbol,
                        resp.status_code,
                    )
                    return pd.DataFrame(
                        columns=[
                            "datetime", "open", "high", "low", "close",
                            "volume",
                        ]
                    )
                if resp.status_code == 429 or resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        f"EODHD {resp.status_code}",
                        request=resp.request,
                        response=resp,
                    )
                    raise last_exc
                resp.raise_for_status()
                rows = resp.json()
                break
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= EOD_MAX_RETRIES:
                    raise
                delay = min(MAX_RETRY_DELAY_SEC, (2**attempt) * 0.5)
                log.warning(
                    "eodhd_intraday_retry symbol=%s attempt=%d delay=%.2fs err=%s",
                    symbol,
                    attempt + 1,
                    delay,
                    type(exc).__name__,
                )
                await asyncio.sleep(delay)

        df = pd.DataFrame(rows)
        if df.empty:
            log.info(
                "eodhd_intraday_empty symbol=%s period=%s",
                symbol,
                period,
            )
            return pd.DataFrame(
                columns=[
                    "datetime", "open", "high", "low", "close",
                    "volume",
                ]
            )
        # EODHD's intraday response uses ``datetime`` (Unix-ms string)
        # or ``timestamp`` depending on the plan. Normalize to a
        # tz-aware ``datetime`` column so the orchestrator's mark
        # logic can compare against ``now_utc()`` without ambiguity.
        # The explicit ``pd.to_numeric`` cast dodges a pandas 3.0
        # FutureWarning about ``unit="ms"`` when the column is
        # already a string of digits.
        ts_col = "datetime" if "datetime" in df.columns else "timestamp"
        df[ts_col] = pd.to_datetime(
            pd.to_numeric(df[ts_col], errors="raise"), unit="ms", utc=True
        )
        df = df.rename(columns={ts_col: "datetime"})
        return df
