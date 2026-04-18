"""
Project Velure — Finnhub Live Data Connector
Real-time market data via Finnhub WebSocket API.

Supports:
- Live trade data for US equities, forex, crypto
- Automatic reconnection with exponential backoff
- Normalization to internal tick format (same as simulator)
- Circuit breaker integration for graceful degradation
- Falls back to simulator if API key missing or connection lost

Usage:
  Set FINNHUB_API_KEY in .env and DATA_MODE=finnhub or DATA_MODE=hybrid
"""
import asyncio
import json
import time
import numpy as np
from collections import defaultdict
from typing import Optional, Callable, Awaitable

from utils.logger import ingestion_log as log
from utils.circuit_breaker import CircuitBreaker

try:
    import websockets
except ImportError:
    websockets = None


# Finnhub symbol mapping → internal asset names
FINNHUB_SYMBOL_MAP = {
    # US Equities (Finnhub uses plain tickers)
    "AAPL": "AAPL", "MSFT": "MSFT", "GOOGL": "GOOGL",
    "AMZN": "AMZN", "TSLA": "TSLA", "JPM": "JPM",
    # Forex (OANDA: format)
    "OANDA:EUR_USD": "EUR/USD", "OANDA:GBP_USD": "GBP/USD",
    "OANDA:USD_JPY": "USD/JPY",
    # Crypto (Binance)
    "BINANCE:BTCUSDT": "BTC/USD", "BINANCE:ETHUSDT": "ETH/USD",
}

# Reverse mapping for subscriptions
SUBSCRIBE_SYMBOLS = list(FINNHUB_SYMBOL_MAP.keys())


class FinnhubConnector:
    """
    Real-time market data ingestion from Finnhub WebSocket.
    
    Aggregates raw trade ticks into OHLCV micro-candles at configurable
    intervals, then emits normalized tick payloads compatible with our
    ML pipeline (same format as simulator.generate_tick()).
    """

    FINNHUB_WS_URL = "wss://ws.finnhub.io"

    def __init__(self, api_key: str, aggregation_interval: float = 0.25):
        self.api_key = api_key
        self.aggregation_interval = aggregation_interval  # seconds between tick emissions
        self._ws = None
        self._running = False
        self._circuit = CircuitBreaker("finnhub_ws", failure_threshold=3, recovery_timeout=60.0)
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        
        # Per-symbol aggregation buffers
        self._trade_buffer: dict[str, list] = defaultdict(list)
        self._last_prices: dict[str, float] = {}
        self._price_history: dict[str, list] = defaultdict(list)
        self._tick_count = 0
        
        # Callback for emitting ticks
        self._on_tick: Optional[Callable[[dict], Awaitable[None]]] = None

    @property
    def connected(self) -> bool:
        return self._ws is not None and self._running

    async def start(self, on_tick: Callable[[dict], Awaitable[None]]):
        """Start the live data connector."""
        if not self.api_key or self.api_key.startswith("your_"):
            log.warning("No valid Finnhub API key — live data disabled")
            return False

        if websockets is None:
            log.warning("websockets package not available")
            return False

        self._on_tick = on_tick
        self._running = True
        asyncio.create_task(self._connection_loop())
        log.info("Finnhub connector started", extra={"component": "finnhub"})
        return True

    async def stop(self):
        """Graceful shutdown."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        log.info("Finnhub connector stopped")

    async def _connection_loop(self):
        """Reconnection loop with exponential backoff."""
        while self._running:
            if not self._circuit.is_available:
                await asyncio.sleep(5)
                continue

            try:
                url = f"{self.FINNHUB_WS_URL}?token={self.api_key}"
                async with websockets.connect(url, ping_interval=30) as ws:
                    self._ws = ws
                    self._reconnect_delay = 1.0  # Reset backoff on success
                    self._circuit.record_success()
                    log.info("Connected to Finnhub WebSocket")

                    # Subscribe to symbols
                    for symbol in SUBSCRIBE_SYMBOLS:
                        await ws.send(json.dumps({"type": "subscribe", "symbol": symbol}))

                    # Start aggregation emitter in parallel
                    emitter = asyncio.create_task(self._aggregation_emitter())

                    try:
                        async for message in ws:
                            await self._handle_message(message)
                    finally:
                        emitter.cancel()

            except Exception as e:
                self._circuit.record_failure()
                self._ws = None
                log.warning(f"Finnhub connection lost: {e}", extra={"component": "finnhub"})
                
                if self._running:
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

    async def _handle_message(self, raw: str):
        """Process incoming Finnhub trade messages."""
        try:
            msg = json.loads(raw)
            if msg.get("type") != "trade":
                return

            for trade in msg.get("data", []):
                symbol = trade.get("s", "")
                price = trade.get("p", 0)
                volume = trade.get("v", 0)
                ts = trade.get("t", 0)  # epoch ms

                internal_name = FINNHUB_SYMBOL_MAP.get(symbol)
                if not internal_name or price <= 0:
                    continue

                self._trade_buffer[internal_name].append({
                    "price": price,
                    "volume": volume,
                    "ts": ts,
                })
                self._last_prices[internal_name] = price

        except (json.JSONDecodeError, KeyError):
            pass

    async def _aggregation_emitter(self):
        """
        Aggregate raw trades into tick payloads at fixed intervals.
        Emits one tick per interval with VWAP, volume, price change.
        """
        while self._running:
            await asyncio.sleep(self.aggregation_interval)

            if not self._trade_buffer:
                continue

            tick_data = self._build_tick()
            if tick_data and self._on_tick:
                await self._on_tick(tick_data)

    def _build_tick(self) -> Optional[dict]:
        """Build a normalized tick payload from buffered trades."""
        assets = {}
        any_data = False

        for symbol, trades in self._trade_buffer.items():
            if not trades:
                continue

            any_data = True
            prices = [t["price"] for t in trades]
            volumes = [t["volume"] for t in trades]

            vwap = np.average(prices, weights=volumes) if sum(volumes) > 0 else np.mean(prices)
            high = max(prices)
            low = min(prices)
            total_volume = sum(volumes)

            # Maintain price history for returns
            history = self._price_history[symbol]
            history.append(vwap)
            if len(history) > 300:
                self._price_history[symbol] = history[-300:]

            # Compute return
            pct_change = 0.0
            if len(history) >= 2:
                pct_change = ((history[-1] / history[-2]) - 1) * 100

            assets[symbol] = {
                "price": round(vwap, 4),
                "pct_change": round(pct_change, 4),
                "high": round(high, 4),
                "low": round(low, 4),
                "volume": round(total_volume, 2),
                "spread_bps": round((high - low) / vwap * 10000 if vwap > 0 else 0, 2),
                "trade_count": len(trades),
            }

        # Clear buffers
        self._trade_buffer.clear()

        if not any_data:
            return None

        self._tick_count += 1

        # Build state vector (72-dim) for ML pipeline
        state_vector = self._build_state_vector()

        return {
            "tick_id": self._tick_count,
            "epoch_ms": int(time.time() * 1000),
            "source": "finnhub_live",
            "assets": assets,
            "state_vector": state_vector,
            "n_assets": len(assets),
        }

    def _build_state_vector(self) -> list:
        """
        Build a 72-dimensional state vector from live data.
        Format: [price_norm, return, vol, spread] × 18 assets.
        Pads with zeros for assets without live data.
        """
        TARGET_ASSETS = [
            "AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "JPM",
            "EUR/USD", "GBP/USD", "USD/JPY",
            "BTC/USD", "ETH/USD",
            # Pad remaining with simulator-only assets
            "US10Y", "US02Y", "DXY", "SPX", "VIX", "GOLD", "OIL",
        ]
        vector = []
        for asset in TARGET_ASSETS:
            history = self._price_history.get(asset, [])
            if len(history) >= 2:
                price_norm = history[-1] / history[0] if history[0] > 0 else 1.0
                ret = (history[-1] / history[-2]) - 1
                returns = np.diff(history[-min(60, len(history)):]) / np.array(history[-min(60, len(history)):-1])
                vol = float(np.std(returns)) if len(returns) > 1 else 0.0
                spread = abs(ret) * 100
            else:
                price_norm, ret, vol, spread = 1.0, 0.0, 0.0, 0.0
            vector.extend([price_norm, ret, vol, spread])

        return vector[:72]  # Ensure exactly 72 dimensions

    def get_status(self) -> dict:
        return {
            "connected": self.connected,
            "circuit": self._circuit.get_status(),
            "tick_count": self._tick_count,
            "active_symbols": len(self._last_prices),
            "last_prices": {k: round(v, 2) for k, v in self._last_prices.items()},
        }


# Singleton (lazy — needs API key from config)
finnhub_connector: Optional[FinnhubConnector] = None


def get_finnhub_connector(api_key: str) -> FinnhubConnector:
    global finnhub_connector
    if finnhub_connector is None:
        finnhub_connector = FinnhubConnector(api_key)
    return finnhub_connector
