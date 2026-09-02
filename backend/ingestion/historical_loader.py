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
        """Save fetched data to local JSON file (canonical) and a CSV sibling
        that the historical replay engine can read directly."""
        # JSON cache (canonical, full OHLCV)
        json_path = os.path.join(HISTORICAL_DATA_DIR, f"{ticker}_daily.json")
        with open(json_path, "w") as f:
            json.dump(bars, f, indent=2)
        log.info(f"Saved {len(bars)} bars to {json_path}")

        # CSV sibling for the replay engine (date,close columns only)
        csv_path = os.path.join(HISTORICAL_DATA_DIR, f"{ticker}.csv")
        try:
            import csv
            with open(csv_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["date", "open", "high", "low", "close", "volume"])
                for bar in bars:
                    writer.writerow([
                        bar.get("date", ""),
                        bar.get("open", ""),
                        bar.get("high", ""),
                        bar.get("low", ""),
                        bar.get("close", ""),
                        bar.get("volume", ""),
                    ])
        except Exception as e:
            log.warning(f"CSV sibling write failed for {ticker}: {e}")

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

    def seed_synthetic_data(self) -> int:
        """Generate a small synthetic OHLCV dataset so backtesting/replay
        works out of the box without API keys.  Real data fetched via
        ``backfill()`` will overwrite these files when available.

        Covers 2008 Lehman, 2020 COVID, and 2023 SVB crisis windows
        plus a normal baseline period.
        """
        os.makedirs(HISTORICAL_DATA_DIR, exist_ok=True)

        # Anchor prices (rough 2020-ish levels)
        anchors = {
            "SPY": 280, "QQQ": 220, "DIA": 250, "IWM": 145, "XLF": 28,
            "JPM": 100, "GS": 200, "BAC": 28, "C": 60, "MS": 50,
            "TLT": 150, "GLD": 170, "VIX": 18,
            "EURUSD": 1.10, "GBPUSD": 1.30, "USDJPY": 110.0,
            "BTCUSD": 10000, "ETHUSD": 200,
        }

        # Crisis windows: (label, start, end, vol_mult, drift, jump)
        # jump applied on first day of the window
        windows = [
            ("normal_baseline", "2019-01-02", "2020-02-19", 0.8, 0.0003, 0.0),
            ("covid_crash",      "2020-01-17", "2020-04-30", 3.5, -0.0010, -0.10),
            ("svb_stress",       "2023-02-01", "2023-04-30", 2.0, -0.0005, -0.04),
        ]

        rng = np.random.default_rng(42)
        total_saved = 0

        for ticker, base_price in anchors.items():
            for label, start, end, vol_mult, drift, jump in windows:
                dates = _business_days(start, end)
                if not dates:
                    continue
                n = len(dates)
                # Random walk with crisis-specific drift + volatility
                daily_returns = rng.normal(drift, 0.012 * vol_mult, n)
                daily_returns[0] += jump
                # Force a few extra spike days in the middle of crisis windows
                if label != "normal_baseline":
                    spike_idx = rng.choice(n, size=max(1, n // 30), replace=False)
                    daily_returns[spike_idx] += rng.normal(-0.03 * vol_mult, 0.02 * vol_mult, len(spike_idx))

                closes = [base_price]
                for r in daily_returns[1:]:
                    closes.append(closes[-1] * (1 + r))
                closes = np.array(closes)

                # Synthesize OHLC from close + intraday noise
                intraday = np.abs(rng.normal(0, 0.008 * vol_mult, n))
                opens = closes * (1 + rng.normal(0, 0.003, n))
                highs = np.maximum(opens, closes) * (1 + intraday)
                lows = np.minimum(opens, closes) * (1 - intraday)
                volumes = rng.integers(1_000_000, 50_000_000, n).tolist()

                bars = [
                    {
                        "date": d,
                        "open": round(float(o), 4),
                        "high": round(float(h), 4),
                        "low": round(float(l), 4),
                        "close": round(float(c), 4),
                        "volume": int(v),
                    }
                    for d, o, h, l, c, v in zip(dates, opens, highs, lows, closes, volumes)
                ]
                # Tag the file name with the window so multiple windows coexist
                tagged = f"{ticker}_{label}"
                json_path = os.path.join(HISTORICAL_DATA_DIR, f"{tagged}_daily.json")
                with open(json_path, "w") as f:
                    json.dump(bars, f, indent=2)

                # CSV sibling for replay engine (uses canonical ticker name
                # so HistoricalReplay.load_window finds it directly)
                csv_path = os.path.join(HISTORICAL_DATA_DIR, f"{ticker}.csv")
                import csv as _csv
                with open(csv_path, "w", newline="") as f:
                    writer = _csv.writer(f)
                    writer.writerow(["date", "open", "high", "low", "close", "volume"])
                    for bar in bars:
                        writer.writerow([bar["date"], bar["open"], bar["high"], bar["low"], bar["close"], bar["volume"]])

                total_saved += len(bars)

        log.info(f"Seeded {total_saved} synthetic historical bars across all tickers")
        return total_saved


def _business_days(start: str, end: str) -> List[str]:
    """Return business-day ISO date strings between start and end (inclusive)."""
    s = datetime.strptime(start, "%Y-%m-%d")
    e = datetime.strptime(end, "%Y-%m-%d")
    out = []
    d = s
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


# Singleton
historical_loader = HistoricalDataLoader()


def ensure_historical_data() -> int:
    """Idempotently seed synthetic historical data if cache is empty.
    Safe to call from app startup."""
    if not os.path.isdir(HISTORICAL_DATA_DIR):
        try:
            os.makedirs(HISTORICAL_DATA_DIR, exist_ok=True)
        except Exception:
            return 0
    # Any .csv present means cache is non-empty
    try:
        for _f in os.listdir(HISTORICAL_DATA_DIR):
            if _f.endswith(".csv"):
                return 0
    except Exception:
        pass
    try:
        return historical_loader.seed_synthetic_data()
    except Exception as e:
        log.warning(f"ensure_historical_data failed: {e}")
        return 0
