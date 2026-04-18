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


# Finnhub symbol mapping → internal asset names (15-asset universe)
FINNHUB_SYMBOL_MAP = {
    # US Equities — ETFs (Finnhub uses plain tickers)
    "SPY": "SPY", "QQQ": "QQQ", "DIA": "DIA", "IWM": "IWM", "XLF": "XLF",
    # US Equities — Banks
    "JPM": "JPM", "GS": "GS", "BAC": "BAC", "C": "C", "MS": "MS",
    # Forex (OANDA — may need paid plan on free tier)
    "OANDA:EUR_USD": "EURUSD", "OANDA:GBP_USD": "GBPUSD",
    "OANDA:USD_JPY": "USDJPY",
    # Crypto (Binance — free tier)
    "BINANCE:BTCUSDT": "BTCUSD", "BINANCE:ETHUSDT": "ETHUSD",
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

    def __init__(self, api_key: str, aggregation_interval: float = None):
        from utils.config import FINNHUB_AGGREGATION_INTERVAL
        self.api_key = api_key
        self.aggregation_interval = aggregation_interval or FINNHUB_AGGREGATION_INTERVAL
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
        self._last_trade_ts: dict[str, float] = {}  # For dedup
        self._last_trade_price: dict[str, float] = {}  # For dedup
        
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

                # Tick deduplication: skip if same symbol + same price within 50ms
                last_ts = self._last_trade_ts.get(internal_name, 0)
                last_p = self._last_trade_price.get(internal_name, -1)
                if abs(ts - last_ts) < 50 and abs(price - last_p) < 1e-8:
                    continue
                self._last_trade_ts[internal_name] = ts
                self._last_trade_price[internal_name] = price

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

            # Compute rolling_volatility from price history
            prices_list = self._price_history[symbol]
            if len(prices_list) >= 3:
                log_rets = np.diff(np.log(prices_list[-min(60, len(prices_list)):])) 
                rolling_vol = float(np.std(log_rets) * np.sqrt(252 * 390)) if len(log_rets) > 1 else 0.0
            else:
                rolling_vol = 0.0

            # Map to asset class
            asset_class = "EQUITY"
            if symbol in ("EURUSD", "GBPUSD", "USDJPY"):
                asset_class = "FX"
            elif symbol in ("BTCUSD", "ETHUSD"):
                asset_class = "CRYPTO"

            assets[symbol] = {
                "price": round(vwap, 6),
                "pct_change": round(pct_change, 4),
                "price_change": round(vwap - history[-2] if len(history) >= 2 else 0, 6),
                "high": round(high, 6),
                "low": round(low, 6),
                "volume": round(total_volume, 2),
                "spread_bps": round((high - low) / vwap * 10000 if vwap > 0 else 0, 2),
                "rolling_volatility": round(rolling_vol, 6),
                "asset_class": asset_class,
                "trade_count": len(trades),
            }

        # Clear buffers
        self._trade_buffer.clear()

        if not any_data:
            return None

        self._tick_count += 1

        from datetime import datetime, timezone

        return {
            "tick_id": self._tick_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "epoch_ms": int(time.time() * 1000),
            "source": "finnhub_live",
            "crisis_mode": False,
            "crisis_intensity": 0.0,
            "assets": assets,
            "n_assets": len(assets),
        }

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
