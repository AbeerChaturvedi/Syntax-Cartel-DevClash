"""
Feature Processor for Project Velure.

Streaming-safe feature engineering: log returns, rolling volatility,
moving averages, and correlation matrix. All functions handle missing
data gracefully.
"""
import numpy as np
from collections import deque
from typing import Dict, List, Optional


class FeatureProcessor:
    """Streaming feature engineering for real-time market data."""

    def __init__(self, window: int = 60):
        self.window = window
        self._return_buffers: Dict[str, deque] = {}
        self._price_buffers: Dict[str, deque] = {}

    def _ensure_buffer(self, ticker: str):
        if ticker not in self._return_buffers:
            self._return_buffers[ticker] = deque(maxlen=self.window)
            self._price_buffers[ticker] = deque(maxlen=self.window * 2)

    def update(self, assets: dict) -> Dict[str, dict]:
        """
        Process one tick of asset data, computing features for each asset.

        Args:
            assets: {"SPY": {"price": 542.0, "pct_change": 0.1, ...}, ...}

        Returns:
            Dict of ticker -> computed features
        """
        results = {}
        for ticker, data in assets.items():
            self._ensure_buffer(ticker)
            price = data.get("price", 0)
            if price <= 0 or not np.isfinite(price):
                continue

            self._price_buffers[ticker].append(price)
            prices = list(self._price_buffers[ticker])

            if len(prices) >= 2:
                log_ret = np.log(prices[-1] / prices[-2])
                self._return_buffers[ticker].append(log_ret)

            returns = list(self._return_buffers[ticker])
            if not returns:
                continue

            results[ticker] = {
                "log_return": returns[-1] if returns else 0.0,
                "rolling_volatility": self.compute_rolling_volatility(returns),
                "sma_20": self._sma(prices, 20),
                "sma_50": self._sma(prices, 50),
                "mean_return": float(np.mean(returns)),
                "max_drawdown": self._max_drawdown(prices),
            }

        return results

    @staticmethod
    def compute_log_returns(prices: List[float]) -> np.ndarray:
        """Compute log returns from price series. Handles NaN via forward-fill."""
        prices = np.array(prices, dtype=np.float64)
        prices = np.where(prices <= 0, np.nan, prices)
        # Forward-fill NaNs
        mask = np.isnan(prices)
        if mask.any():
            idx = np.where(~mask, np.arange(len(prices)), 0)
            np.maximum.accumulate(idx, out=idx)
            prices = prices[idx]
        returns = np.diff(np.log(prices))
        return np.nan_to_num(returns, nan=0.0)

    @staticmethod
    def compute_rolling_volatility(returns, window: int = 20) -> float:
        """Compute rolling volatility from return series."""
        if len(returns) < 2:
            return 0.0
        r = np.array(returns[-window:], dtype=np.float64)
        r = r[np.isfinite(r)]
        if len(r) < 2:
            return 0.0
        return float(np.std(r))

    @staticmethod
    def _sma(prices, window: int) -> float:
        """Simple moving average."""
        if len(prices) < window:
            return float(np.mean(prices)) if prices else 0.0
        return float(np.mean(prices[-window:]))

    @staticmethod
    def _max_drawdown(prices) -> float:
        """Maximum drawdown in the price window."""
        if len(prices) < 2:
            return 0.0
        prices = np.array(prices, dtype=np.float64)
        peak = np.maximum.accumulate(prices)
        drawdown = (peak - prices) / np.where(peak > 0, peak, 1.0)
        return float(np.max(drawdown))

    def compute_correlation_matrix(self, tickers: List[str] = None) -> np.ndarray:
        """Compute correlation matrix from return buffers."""
        if tickers is None:
            tickers = list(self._return_buffers.keys())

        if len(tickers) < 2:
            return np.eye(len(tickers))

        # Build returns matrix
        min_len = min(
            len(self._return_buffers.get(t, [])) for t in tickers
        )
        if min_len < 10:
            return np.eye(len(tickers))

        returns_matrix = []
        for t in tickers:
            r = list(self._return_buffers[t])[-min_len:]
            returns_matrix.append(r)

        corr = np.corrcoef(returns_matrix)
        return np.nan_to_num(corr, nan=0.0)


# Singleton
feature_processor = FeatureProcessor()
