"""
Market Data Simulator for Project Velure.
Generates realistic synthetic financial data streams for demo purposes.
Simulates normal market conditions AND crisis events with configurable parameters.
"""
import numpy as np
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional
from collections import deque


class MarketSimulator:
    """
    Generates correlated multi-asset financial data using geometric Brownian motion.
    Can inject crisis events that spike correlations and volatility.
    """

    ASSETS = {
        "SPY":    {"base": 542.0,  "vol": 0.012, "class": "EQUITY"},
        "QQQ":    {"base": 470.0,  "vol": 0.015, "class": "EQUITY"},
        "DIA":    {"base": 398.0,  "vol": 0.010, "class": "EQUITY"},
        "IWM":    {"base": 205.0,  "vol": 0.018, "class": "EQUITY"},
        "XLF":    {"base": 42.5,   "vol": 0.014, "class": "EQUITY"},
        "JPM":    {"base": 198.0,  "vol": 0.016, "class": "EQUITY"},
        "GS":     {"base": 465.0,  "vol": 0.018, "class": "EQUITY"},
        "BAC":    {"base": 39.5,   "vol": 0.017, "class": "EQUITY"},
        "C":      {"base": 64.0,   "vol": 0.019, "class": "EQUITY"},
        "MS":     {"base": 98.0,   "vol": 0.017, "class": "EQUITY"},
        "EURUSD": {"base": 1.0850, "vol": 0.004, "class": "FX"},
        "GBPUSD": {"base": 1.2650, "vol": 0.005, "class": "FX"},
        "USDJPY": {"base": 154.20, "vol": 0.006, "class": "FX"},
        "US10Y":  {"base": 4.35,   "vol": 0.008, "class": "BOND"},
        "US2Y":   {"base": 4.72,   "vol": 0.010, "class": "BOND"},
        "SOFR":   {"base": 5.33,   "vol": 0.002, "class": "RATE"},
        "BTCUSD": {"base": 67500,  "vol": 0.025, "class": "CRYPTO"},
        "ETHUSD": {"base": 3250,   "vol": 0.030, "class": "CRYPTO"},
    }

    def __init__(self):
        self.prices = {k: v["base"] for k, v in self.ASSETS.items()}
        self.crisis_mode = False
        self.crisis_intensity = 0.0  # 0 to 1
        self.crisis_start_time = None
        self.tick_count = 0
        self._correlation_matrix = self._build_normal_correlation()
        self._history: Dict[str, deque] = {k: deque([v["base"]], maxlen=300) for k, v in self.ASSETS.items()}

    def _build_normal_correlation(self) -> np.ndarray:
        """Build a realistic cross-asset correlation matrix for normal conditions."""
        n = len(self.ASSETS)
        corr = np.eye(n)
        tickers = list(self.ASSETS.keys())

        for i in range(n):
            for j in range(i + 1, n):
                ci = self.ASSETS[tickers[i]]["class"]
                cj = self.ASSETS[tickers[j]]["class"]

                if ci == cj == "EQUITY":
                    corr[i, j] = corr[j, i] = 0.6 + np.random.uniform(0, 0.2)
                elif ci == cj:
                    corr[i, j] = corr[j, i] = 0.4 + np.random.uniform(0, 0.2)
                elif ("EQUITY" in (ci, cj)) and ("BOND" in (ci, cj)):
                    corr[i, j] = corr[j, i] = -0.2 + np.random.uniform(-0.1, 0.1)
                else:
                    corr[i, j] = corr[j, i] = np.random.uniform(-0.1, 0.3)

        # Ensure positive semi-definite
        eigvals, eigvecs = np.linalg.eigh(corr)
        eigvals = np.maximum(eigvals, 0.01)
        corr = eigvecs @ np.diag(eigvals) @ eigvecs.T
        d = np.sqrt(np.diag(corr))
        corr = corr / np.outer(d, d)
        np.fill_diagonal(corr, 1.0)
        return corr

    def activate_crisis(self, intensity: float = 0.8):
        """Activate crisis mode — correlations spike, volatility explodes."""
        self.crisis_mode = True
        self.crisis_intensity = np.clip(intensity, 0.1, 1.0)
        self.crisis_start_time = time.time()

    def deactivate_crisis(self):
        """Return to normal market conditions."""
        self.crisis_mode = False
        self.crisis_intensity = 0.0
        self.crisis_start_time = None

    def generate_tick(self) -> Dict:
        """Generate one tick of correlated market data."""
        self.tick_count += 1
        now = datetime.now(timezone.utc)
        epoch_ms = int(now.timestamp() * 1000)
        tickers = list(self.ASSETS.keys())
        n = len(tickers)

        # Build covariance-adjusted returns
        vols = np.array([self.ASSETS[t]["vol"] for t in tickers])

        if self.crisis_mode:
            # Crisis: spike vol by 3-8x, correlations → 0.85+
            crisis_vol_mult = 3.0 + 5.0 * self.crisis_intensity
            vols = vols * crisis_vol_mult

            crisis_corr = np.full((n, n), 0.85 * self.crisis_intensity)
            np.fill_diagonal(crisis_corr, 1.0)
            corr = crisis_corr
            
            # Add directional bias (everything crashes)
            drift = -0.003 * self.crisis_intensity
        else:
            corr = self._correlation_matrix
            drift = 0.0001  # Slight upward bias

        # Cholesky decomposition for correlated returns
        try:
            L = np.linalg.cholesky(corr)
        except np.linalg.LinAlgError:
            L = np.eye(n)

        z = np.random.standard_normal(n)
        correlated_shocks = L @ z

        # Update prices using GBM
        tick_data = {
            "timestamp": now.isoformat(),
            "epoch_ms": epoch_ms,
            "tick_id": self.tick_count,
            "crisis_mode": self.crisis_mode,
            "crisis_intensity": round(self.crisis_intensity, 4),
            "assets": {}
        }

        for i, ticker in enumerate(tickers):
            shock = correlated_shocks[i]
            ret = drift + vols[i] * shock / np.sqrt(252 * 390)  # Annualized → per-tick

            old_price = self.prices[ticker]
            new_price = old_price * np.exp(ret)
            self.prices[ticker] = new_price

            # Track history (deque auto-trims to 300)
            self._history[ticker].append(new_price)

            # Compute additional features
            hist = list(self._history[ticker])[-60:]
            returns = np.diff(np.log(hist)) if len(hist) > 2 else [0]
            rolling_vol = float(np.std(returns) * np.sqrt(252 * 390)) if len(returns) > 1 else 0
            price_change = new_price - old_price
            pct_change = (price_change / old_price) * 100

            # Bid-ask spread widens in crisis
            base_spread = 0.01 * old_price / 100
            if self.crisis_mode:
                base_spread *= (2 + 5 * self.crisis_intensity)

            volume = int(np.random.exponential(50000) * (1 + 3 * self.crisis_intensity if self.crisis_mode else 1))

            tick_data["assets"][ticker] = {
                "price": round(new_price, 6),
                "price_change": round(price_change, 6),
                "pct_change": round(pct_change, 4),
                "volume": volume,
                "bid": round(new_price - base_spread, 6),
                "ask": round(new_price + base_spread, 6),
                "spread_bps": round((2 * base_spread / new_price) * 10000, 2),
                "rolling_volatility": round(rolling_vol, 6),
                "asset_class": self.ASSETS[ticker]["class"],
            }

        # Compute cross-asset correlation (actual from recent data)
        if len(self._history[tickers[0]]) > 30:
            returns_matrix = []
            for t in tickers:
                r = np.diff(np.log(list(self._history[t])[-31:]))
                returns_matrix.append(r)
            returns_matrix = np.array(returns_matrix)
            actual_corr = np.corrcoef(returns_matrix)
            actual_corr = np.nan_to_num(actual_corr, nan=0.0)
            
            # Average absolute correlation as contagion proxy
            upper_tri = actual_corr[np.triu_indices_from(actual_corr, k=1)]
            tick_data["avg_correlation"] = round(float(np.mean(np.abs(upper_tri))), 4)
            tick_data["correlation_matrix"] = actual_corr.tolist()
        else:
            tick_data["avg_correlation"] = 0.0
            tick_data["correlation_matrix"] = []

        return tick_data

    def get_state_vector(self) -> np.ndarray:
        """Get current market state as a feature vector for ML models."""
        features = []
        for ticker in sorted(self.ASSETS.keys()):
            hist = self._history[ticker]
            if len(hist) < 10:
                features.extend([0, 0, 0, 0])
                continue
            
            returns = np.diff(np.log(list(hist)[-60:]))
            features.append(float(returns[-1]) if len(returns) > 0 else 0)  # Latest return
            features.append(float(np.std(returns)) if len(returns) > 1 else 0)  # Vol
            features.append(float(np.mean(returns)) if len(returns) > 0 else 0)  # Mean return
            features.append(float(np.max(np.abs(returns))) if len(returns) > 0 else 0)  # Max |return|
        
        return np.array(features, dtype=np.float32)


# Singleton instance
simulator = MarketSimulator()
