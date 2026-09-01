"""
Project Velure — Twelve Data Live Forex Connector
Streams real-time FX rates for EUR/USD, GBP/USD, USD/JPY via the
Twelve Data REST API.

Why a separate connector:
    Finnhub WebSocket free tier does NOT provide live Forex data
    (OANDA symbols require a paid subscription).  Twelve Data's free
    tier gives us 800 REST requests/day, which is plenty at the
    default 120-second poll interval (= 720 req/day, 10% headroom).

Design:
    - One HTTP request fetches all 3 FX pairs in a single call.
    - The latest prices are stored in `_latest_prices` (class-level,
      shared with FinnhubConnector._build_tick via import).
    - The poller runs as a background asyncio Task; any failure is
      logged and retried on the next interval — it never crashes the
      pipeline.
    - On first boot the prices are populated in the very first poll,
      which happens immediately (no 120-second wait).

Usage:
    from ingestion.twelve_data_connector import twelve_data_connector
    await twelve_data_connector.start()
    # Now twelve_data_connector.latest_prices is always fresh
"""

import asyncio
import json
import time
from typing import Dict, Optional

from utils.logger import ingestion_log as log

try:
    import urllib.request
    import ssl as _ssl_mod
    _HAS_URLLIB = True
except ImportError:
    _HAS_URLLIB = False


# Internal name → Twelve Data symbol
_TD_SYMBOLS = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
}

# Reverse: Twelve Data symbol → internal name
_REVERSE_MAP = {v: k for k, v in _TD_SYMBOLS.items()}

# Comma-joined symbols for a single batch request
_TD_SYMBOL_PARAM = ",".join(_TD_SYMBOLS.values())

# Asset metadata for each FX pair
_FX_META = {
    "EURUSD": {"asset_class": "FX", "base": 1.05, "spread_bps": 1.2},
    "GBPUSD": {"asset_class": "FX", "base": 1.26, "spread_bps": 1.5},
    "USDJPY": {"asset_class": "FX", "base": 145.0, "spread_bps": 1.0},
}


class TwelveDataConnector:
    """
    Polls Twelve Data REST API for live Forex prices at a fixed interval.

    Thread-safe: `latest_prices` is read by the Finnhub connector on
    every tick emission (different async task), but dict reads in Python
    are atomic for simple key lookups so no lock is needed.
    """

    BASE_URL = "https://api.twelvedata.com/price"

    def __init__(self):
        self._api_key: str = ""
        self._poll_interval: float = 120.0
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._poll_count: int = 0
        self._error_count: int = 0
        self._last_poll_ts: float = 0.0
        self._last_error: str = ""

        # Shared price cache — read by FinnhubConnector._build_tick()
        # Format: {"EURUSD": {"price": 1.0923, "pct_change": 0.012, ...}}
        self.latest_prices: Dict[str, dict] = {}

        # Per-symbol price history for pct_change computation
        self._price_history: Dict[str, list] = {k: [] for k in _TD_SYMBOLS}

    def configure(self, api_key: str, poll_interval: float = 120.0):
        """Set API key and poll interval before calling start()."""
        self._api_key = api_key
        self._poll_interval = max(poll_interval, 10.0)  # never faster than 10s

    async def start(self):
        """Start the background poller task."""
        if not self._api_key:
            log.warning("Twelve Data: no API key — FX prices will be absent from live ticks")
            return

        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="twelve_data_poller")
        log.info(
            f"Twelve Data FX connector started "
            f"(interval={self._poll_interval}s, symbols={_TD_SYMBOL_PARAM})",
            extra={"component": "twelve_data"},
        )

    async def stop(self):
        """Cancel the poller gracefully."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        log.info("Twelve Data connector stopped")

    # ── internals ─────────────────────────────────────────────────────

    async def _poll_loop(self):
        """
        Main poll loop.
        - First poll fires immediately so prices are available before any
          Finnhub tick is emitted.
        - Subsequent polls happen every `_poll_interval` seconds.
        - Any HTTP / parse error is logged and skipped; the old prices
          remain valid until the next successful poll.
        """
        # Immediate first poll
        await self._fetch_and_update()

        while self._running:
            await asyncio.sleep(self._poll_interval)
            if not self._running:
                break
            await self._fetch_and_update()

    async def _fetch_and_update(self):
        """Fetch all FX pairs in one HTTP call and update latest_prices."""
        try:
            data = await asyncio.get_running_loop().run_in_executor(
                None, self._http_get
            )
            self._last_poll_ts = time.time()
            self._poll_count += 1
            self._parse_response(data)
            log.debug(
                f"Twelve Data poll #{self._poll_count}: "
                f"{list(self.latest_prices.keys())}",
                extra={"component": "twelve_data"},
            )
        except Exception as e:
            self._error_count += 1
            self._last_error = str(e)
            log.warning(
                f"Twelve Data fetch error (#{self._error_count}): {e}",
                extra={"component": "twelve_data"},
            )

    def _http_get(self) -> dict:
        """Synchronous HTTP GET (runs in executor thread)."""
        url = (
            f"{self.BASE_URL}"
            f"?symbol={_TD_SYMBOL_PARAM}"
            f"&apikey={self._api_key}"
        )
        ctx = _ssl_mod.create_default_context()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "ProjectVelure/3.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    def _parse_response(self, data: dict):
        """
        Parse Twelve Data batch price response and populate latest_prices.

        Single-symbol response: {"price": "1.09312"}
        Multi-symbol response:  {"EUR/USD": {"price": "1.09312"}, ...}

        We always request multiple symbols, so we always get the nested form.
        But we defensively handle both.
        """
        for td_sym, internal_name in _REVERSE_MAP.items():
            # Multi-symbol path (normal)
            entry = data.get(td_sym, {})
            if not isinstance(entry, dict):
                # Fallback: single-symbol path
                entry = data if data.get("price") else {}

            raw_price = entry.get("price")
            if raw_price is None:
                # API might return {"code": 400, "message": "..."}
                msg = data.get("message", "unknown")
                log.warning(
                    f"Twelve Data: no price for {td_sym} — {msg}",
                    extra={"component": "twelve_data"},
                )
                continue

            try:
                price = float(raw_price)
            except (TypeError, ValueError):
                continue

            if price <= 0:
                continue

            # Compute pct_change from price history
            hist = self._price_history[internal_name]
            hist.append(price)
            if len(hist) > 100:
                self._price_history[internal_name] = hist[-100:]

            pct_change = 0.0
            if len(hist) >= 2:
                pct_change = round((hist[-1] / hist[-2] - 1) * 100, 4)

            meta = _FX_META.get(internal_name, {})

            self.latest_prices[internal_name] = {
                "price": round(price, 6),
                "pct_change": pct_change,
                "price_change": round(price - hist[-2], 6) if len(hist) >= 2 else 0.0,
                "high": round(price * 1.0001, 6),   # Twelve Data REST gives spot only
                "low":  round(price * 0.9999, 6),   # micro-spread as placeholder
                "volume": 0,
                "spread_bps": meta.get("spread_bps", 1.0),
                "rolling_volatility": 0.0,           # populated after enough history
                "asset_class": "FX",
                "source": "twelve_data",
                "trade_count": 1,
            }

    def get_status(self) -> dict:
        return {
            "running": self._running,
            "api_key_set": bool(self._api_key),
            "poll_interval_sec": self._poll_interval,
            "poll_count": self._poll_count,
            "error_count": self._error_count,
            "last_poll_ts": self._last_poll_ts,
            "last_error": self._last_error,
            "symbols_cached": list(self.latest_prices.keys()),
        }


# ── Module-level singleton ────────────────────────────────────────────
twelve_data_connector = TwelveDataConnector()
