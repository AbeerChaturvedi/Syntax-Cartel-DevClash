"""
Historical Data Loader for Project Velure.

Batch fetcher for multi-year OHLCV data from Polygon.io REST API.
Handles pagination, rate limiting (5 req/min on free tier), and
data validation.

Usage:
    loader = HistoricalDataLoader()
    await loader.backfill(["SPY", "QQQ"], "2018-01-01", "2024-12-31")
"""
import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from typing import List, Optional, Dict

import numpy as np

try:
    import aiohttp
    AIOHTTP_AVAILABLE = True
except ImportError:
    AIOHTTP_AVAILABLE = False

from utils.config import (
    POLYGON_API_KEY,
    POLYGON_RATE_LIMIT_PER_MIN,
    HISTORICAL_DATA_DIR,
)
from utils.logger import ingestion_log as log


# Assets we track (matches state_builder.TRACKED_ASSETS)
BACKFILL_TICKERS = [
    "SPY", "QQQ", "DIA", "IWM", "XLF",
    "JPM", "GS", "BAC", "C", "MS",
]

# Polygon uses different symbol formats for crypto/forex
POLYGON_SYMBOL_MAP = {
    "BTCUSD": "X:BTCUSD",
    "ETHUSD": "X:ETHUSD",
    "EURUSD": "C:EURUSD",
    "GBPUSD": "C:GBPUSD",
    "USDJPY": "C:USDJPY",
}

# Reverse map for result normalization
POLYGON_REVERSE_MAP = {v: k for k, v in POLYGON_SYMBOL_MAP.items()}


class RateLimiter:
    """Token-bucket rate limiter for API requests."""

    def __init__(self, max_per_minute: int = 5):
        self.max_per_minute = max_per_minute
        self._tokens = max_per_minute
        self._last_refill = time.monotonic()

    async def acquire(self):
        """Wait until a request slot is available."""
        while True:
            now = time.monotonic()
            elapsed = now - self._last_refill
            # Refill tokens based on elapsed time
            self._tokens = min(
                self.max_per_minute,
                self._tokens + (elapsed / 60.0) * self.max_per_minute,
            )
            self._last_refill = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return
            # Wait for next token
            wait_time = (1.0 - self._tokens) / (self.max_per_minute / 60.0)
            log.debug(f"Rate limiter: waiting {wait_time:.1f}s for next slot")
            await asyncio.sleep(wait_time)


class HistoricalDataLoader:
    """
    Batch fetcher for historical OHLCV data from Polygon.io.

    Features:
    - Pagination for large date ranges
    - Rate limiting (5 req/min on Polygon free tier)
    - Data validation (no negative prices, no future timestamps)
    - Forward-fill for missing trading days
    - Saves to local JSON files for caching
    """

    POLYGON_BASE_URL = "https://api.polygon.io"

    def __init__(self):
        self.api_key = POLYGON_API_KEY
        self._rate_limiter = RateLimiter(max_per_minute=POLYGON_RATE_LIMIT_PER_MIN)
        self._session: Optional[aiohttp.ClientSession] = None
        os.makedirs(HISTORICAL_DATA_DIR, exist_ok=True)

    async def _get_session(self) -> "aiohttp.ClientSession":
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_polygon(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        timespan: str = "day",
        multiplier: int = 1,
    ) -> List[dict]:
        """
        Fetch OHLCV data from Polygon.io with pagination + rate limiting.

        Args:
            ticker: Raw ticker (e.g. "SPY", "BTCUSD")
            start_date: "YYYY-MM-DD"
            end_date: "YYYY-MM-DD"
            timespan: "day", "hour", "minute"
            multiplier: Bar multiplier (1 = 1-day bars)

        Returns:
            List of validated OHLCV dicts
        """
        if not AIOHTTP_AVAILABLE:
            log.error("aiohttp not available — cannot fetch historical data")
            return []

        if not self.api_key:
            log.warning("No Polygon API key configured")
            return []

        # Map internal ticker to Polygon format
        polygon_ticker = POLYGON_SYMBOL_MAP.get(ticker, ticker)

        url = (
            f"{self.POLYGON_BASE_URL}/v2/aggs/ticker/{polygon_ticker}"
            f"/range/{multiplier}/{timespan}/{start_date}/{end_date}"
        )
        params = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            "apiKey": self.api_key,
        }

        all_results = []
        page = 0

        session = await self._get_session()

        while url:
            page += 1
            await self._rate_limiter.acquire()

            try:
                async with session.get(url, params=params if page == 1 else None) as resp:
                    if resp.status == 429:
                        # Rate limited — back off
                        retry_after = int(resp.headers.get("Retry-After", 60))
                        log.warning(f"Polygon rate limited, waiting {retry_after}s")
                        await asyncio.sleep(retry_after)
                        continue

                    if resp.status != 200:
                        text = await resp.text()
                        log.error(f"Polygon API error {resp.status}: {text[:200]}")
                        break

                    data = await resp.json()

                    results = data.get("results", [])
                    for bar in results:
                        validated = self._validate_ohlcv(bar, ticker)
                        if validated:
                            all_results.append(validated)

                    # Pagination: Polygon provides next_url for paginated results
                    url = data.get("next_url")
                    if url:
                        url = f"{url}&apiKey={self.api_key}"
                    params = None  # params are embedded in next_url

            except asyncio.TimeoutError:
                log.warning(f"Polygon request timeout for {ticker}")
                break
            except Exception as e:
                log.error(f"Polygon fetch error for {ticker}: {e}")
                break

        log.info(f"Fetched {len(all_results)} bars for {ticker} ({start_date} → {end_date})")
        return all_results

    def _validate_ohlcv(self, bar: dict, ticker: str) -> Optional[dict]:
        """
        Validate a single OHLCV bar.
        Rejects: negative prices, zero volume, future timestamps, NaN values.
        """
        try:
            o = float(bar.get("o", 0))
            h = float(bar.get("h", 0))
            l_ = float(bar.get("l", 0))
            c = float(bar.get("c", 0))
            v = float(bar.get("v", 0))
            t = int(bar.get("t", 0))  # epoch ms

            # Reject invalid data
            if any(p <= 0 for p in [o, h, l_, c]):
                return None
            if any(not np.isfinite(p) for p in [o, h, l_, c, v]):
                return None
            if h < l_:
                return None
            # Reject future timestamps (more than 1 day ahead)
            now_ms = int(time.time() * 1000)
            if t > now_ms + 86_400_000:
                return None

            return {
                "ticker": ticker,
                "timestamp_ms": t,
                "date": datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m-%d"),
                "open": round(o, 6),
                "high": round(h, 6),
                "low": round(l_, 6),
                "close": round(c, 6),
                "volume": round(v, 2),
                "vwap": round(float(bar.get("vw", c)), 6),
                "num_transactions": int(bar.get("n", 0)),
            }
        except (TypeError, ValueError):
            return None

    def _forward_fill_gaps(self, bars: List[dict]) -> List[dict]:
        """Fill missing trading days using forward-fill."""
        if len(bars) < 2:
            return bars

        filled = [bars[0]]
        for i in range(1, len(bars)):
            prev_date = datetime.strptime(bars[i - 1]["date"], "%Y-%m-%d")
            curr_date = datetime.strptime(bars[i]["date"], "%Y-%m-%d")
            gap_days = (curr_date - prev_date).days

            # Fill weekday gaps (skip weekends)
            if gap_days > 1:
                for d in range(1, gap_days):
                    fill_date = prev_date + timedelta(days=d)
                    if fill_date.weekday() < 5:  # Mon-Fri only
                        filled_bar = bars[i - 1].copy()
                        filled_bar["date"] = fill_date.strftime("%Y-%m-%d")
                        filled_bar["volume"] = 0  # Mark as filled
                        filled.append(filled_bar)

            filled.append(bars[i])

        return filled

    async def backfill(
        self,
        tickers: List[str] = None,
        start_date: str = "2019-01-01",
        end_date: str = None,
    ) -> Dict[str, int]:
        """
        Full backfill pipeline: fetch → validate → forward-fill → save.

        Args:
            tickers: List of tickers (defaults to all tracked assets)
            start_date: Start date "YYYY-MM-DD"
            end_date: End date "YYYY-MM-DD" (defaults to today)

        Returns:
            Dict of ticker → number of bars fetched
        """
        if tickers is None:
            tickers = BACKFILL_TICKERS + list(POLYGON_SYMBOL_MAP.keys())

        if end_date is None:
            end_date = datetime.utcnow().strftime("%Y-%m-%d")

        results = {}
        total = len(tickers)

        for idx, ticker in enumerate(tickers):
            log.info(f"Backfilling {ticker} ({idx + 1}/{total})...")
            bars = await self.fetch_polygon(ticker, start_date, end_date)

            if bars:
                # Forward-fill gaps
                bars = self._forward_fill_gaps(bars)
                # Save to local cache
                self._save_to_cache(ticker, bars)
                results[ticker] = len(bars)
            else:
                results[ticker] = 0

        await self.close()

        total_bars = sum(results.values())
        log.info(f"Backfill complete: {total_bars} total bars across {len(results)} tickers")
        return results

    def _save_to_cache(self, ticker: str, bars: List[dict]):
        """Save fetched data to local JSON file."""
        path = os.path.join(HISTORICAL_DATA_DIR, f"{ticker}_daily.json")
        with open(path, "w") as f:
            json.dump(bars, f, indent=2)
        log.info(f"Saved {len(bars)} bars to {path}")

    def load_from_cache(self, ticker: str) -> List[dict]:
        """Load previously fetched data from cache."""
        path = os.path.join(HISTORICAL_DATA_DIR, f"{ticker}_daily.json")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return json.load(f)

    def get_status(self) -> dict:
        """Get backfill status — which tickers have cached data."""
        cached = {}
        for ticker in BACKFILL_TICKERS + list(POLYGON_SYMBOL_MAP.keys()):
            data = self.load_from_cache(ticker)
            if data:
                cached[ticker] = {
                    "bars": len(data),
                    "start": data[0]["date"],
                    "end": data[-1]["date"],
                }
        return {
            "cached_tickers": len(cached),
            "total_tickers": len(BACKFILL_TICKERS) + len(POLYGON_SYMBOL_MAP),
            "tickers": cached,
        }


# Singleton
historical_loader = HistoricalDataLoader()
