from datetime import date, datetime
from pathlib import Path

import httpx
import pandas as pd
from pydantic import BaseModel

from tradefarm.config import settings

CACHE_DIR = Path("data_cache")
BASE_URL = "https://eodhd.com/api"


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
        if use_cache:
            CACHE_DIR.mkdir(exist_ok=True)

    def _cache_path(self, symbol: str, start: date, end: date) -> Path:
        return CACHE_DIR / f"eod_{symbol}_{start}_{end}.parquet"

    async def get_eod(
        self,
        symbol: str,
        *,
        start: date,
        end: date,
        exchange: str = "US",
    ) -> pd.DataFrame:
        cache = self._cache_path(symbol, start, end)
        if self.use_cache and cache.exists():
            return pd.read_parquet(cache)

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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            rows = resp.json()

        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["date"] = pd.to_datetime(df["date"]).dt.date
        if self.use_cache:
            try:
                df.to_parquet(cache)
            except Exception:
                pass  # cache miss is non-fatal — fall back to live fetch next time
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
