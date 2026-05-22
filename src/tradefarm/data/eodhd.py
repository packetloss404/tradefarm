import asyncio
import logging
from datetime import date

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
        rows: list = []
        last_exc: Exception | None = None
        for attempt in range(EOD_MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.get(url, params=params)
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
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
