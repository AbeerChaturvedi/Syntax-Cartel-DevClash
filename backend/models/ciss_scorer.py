"""
CISS — Composite Indicator of Systemic Stress
Transforms raw market indicators into a bounded [0, 1] systemic stress gauge.
Uses empirical CDF normalization + correlation-weighted aggregation.
"""
import numpy as np
from scipy.stats import rankdata
from collections import deque
from typing import Dict, List, Tuple


class CISSScorer:
    """
    Implements the ECB's Composite Indicator of Systemic Stress methodology.
    
    Key insight: Rather than simple averaging, CISS weights by cross-correlation.
    When all markets stress simultaneously (high correlation), the systemic score
    amplifies. When stress is localized, the score is dampened.
    """

    def __init__(self, window_size: int = 500, n_segments: int = 5):
        self.window_size = window_size
        self.n_segments = n_segments  # Number of market segments

        # Rolling windows for each market segment
        # Segments: [Equities, FX, Bonds/Rates, Credit, Volatility]
        self.segment_buffers: Dict[str, deque] = {
            "equities": deque(maxlen=window_size),
            "forex": deque(maxlen=window_size),
            "rates": deque(maxlen=window_size),
            "credit": deque(maxlen=window_size),
            "volatility": deque(maxlen=window_size),
        }
        self._score_history = deque(maxlen=1000)
        self._cached_corr = np.eye(n_segments)
        self._corr_tick_counter = 0

    def update(self, tick_data: dict) -> float:
        """
        Process a market tick and return the updated CISS score.
        
        Args:
            tick_data: Dict with asset-level data from simulator
            
        Returns:
            CISS score in [0, 1]
        """
        assets = tick_data.get("assets", {})
        if not assets:
            return 0.0

        # Extract segment stress indicators
        equity_stress = self._compute_equity_stress(assets)
        fx_stress = self._compute_fx_stress(assets)
        rate_stress = self._compute_rate_stress(assets)
        credit_stress = self._compute_credit_stress(assets)
        vol_stress = self._compute_volatility_stress(assets)

        # Push to buffers
        self.segment_buffers["equities"].append(equity_stress)
        self.segment_buffers["forex"].append(fx_stress)
        self.segment_buffers["rates"].append(rate_stress)
        self.segment_buffers["credit"].append(credit_stress)
        self.segment_buffers["volatility"].append(vol_stress)

        # Need minimum data for CDF transform
        if len(self.segment_buffers["equities"]) < 30:
            return 0.0

        # Step 1: Empirical CDF transform → uniform [0, 1]
        z = np.array([
            self._empirical_cdf("equities"),
            self._empirical_cdf("forex"),
            self._empirical_cdf("rates"),
            self._empirical_cdf("credit"),
            self._empirical_cdf("volatility"),
        ])

        # Step 2: Recompute cross-correlation every 10 ticks (expensive O(n*seg) op)
        self._corr_tick_counter += 1
        if self._corr_tick_counter % 10 == 0:
            self._cached_corr = self._cross_correlation_matrix()
        C = self._cached_corr

        # Step 3: Correlation-weighted quadratic form
        # CISS = sqrt(z^T * C * z) / sqrt(n) to normalize
        ciss_raw = np.sqrt(max(0, z.T @ C @ z)) / np.sqrt(self.n_segments)
        ciss_score = float(np.clip(ciss_raw, 0, 1))

        self._score_history.append(ciss_score)
        return round(ciss_score, 6)

    def _compute_equity_stress(self, assets: dict) -> float:
        """Aggregate equity stress from absolute returns + volume spikes."""
        equity_tickers = ["SPY", "QQQ", "DIA", "IWM", "XLF"]
        stresses = []
        for t in equity_tickers:
            if t in assets:
                stresses.append(abs(assets[t].get("pct_change", 0)))
        return np.mean(stresses) if stresses else 0.0

    def _compute_fx_stress(self, assets: dict) -> float:
        """FX stress from absolute percentage changes."""
        fx_tickers = ["EURUSD", "GBPUSD", "USDJPY"]
        stresses = []
        for t in fx_tickers:
            if t in assets:
                stresses.append(abs(assets[t].get("pct_change", 0)))
        return np.mean(stresses) if stresses else 0.0

    def _compute_rate_stress(self, assets: dict) -> float:
        """Rate/bond stress from yield movements and spread widening."""
        rate_tickers = ["US10Y", "US2Y", "SOFR"]
        stresses = []
        for t in rate_tickers:
            if t in assets:
                stresses.append(abs(assets[t].get("pct_change", 0)))
                stresses.append(assets[t].get("spread_bps", 0) / 100)  # Normalize
        return np.mean(stresses) if stresses else 0.0

    def _compute_credit_stress(self, assets: dict) -> float:
        """Credit stress from financial sector performance."""
        bank_tickers = ["JPM", "GS", "BAC", "C", "MS"]
        stresses = []
        for t in bank_tickers:
            if t in assets:
                # Negative returns = financial stress
                pct = assets[t].get("pct_change", 0)
                stresses.append(max(0, -pct))  # Only negative returns contribute
                stresses.append(assets[t].get("spread_bps", 0) / 50)
        return np.mean(stresses) if stresses else 0.0

    def _compute_volatility_stress(self, assets: dict) -> float:
        """Volatility stress from crypto + rolling vol spikes."""
        vol_tickers = ["BTCUSD", "ETHUSD"]
        stresses = []
        for t in vol_tickers:
            if t in assets:
                stresses.append(abs(assets[t].get("pct_change", 0)))
                stresses.append(assets[t].get("rolling_volatility", 0))
        # Also check overall spread
        all_spreads = [a.get("spread_bps", 0) for a in assets.values()]
        if all_spreads:
            stresses.append(np.mean(all_spreads) / 100)
        return np.mean(stresses) if stresses else 0.0

    def _empirical_cdf(self, segment: str) -> float:
        """Compute empirical CDF value for latest observation."""
        buffer = list(self.segment_buffers[segment])
        if not buffer:
            return 0.0
        latest = buffer[-1]
        rank = rankdata(buffer)[-1]
        return rank / len(buffer)

    def _cross_correlation_matrix(self) -> np.ndarray:
        """Compute rolling cross-correlation between market segments."""
        segments = list(self.segment_buffers.keys())
        n = len(segments)
        min_len = min(len(self.segment_buffers[s]) for s in segments)
        
        if min_len < 10:
            return np.eye(n)

        # Use last min_len observations
        data = np.array([
            list(self.segment_buffers[s])[-min_len:]
            for s in segments
        ])

        # Correlation matrix
        corr = np.corrcoef(data)
        corr = np.nan_to_num(corr, nan=0.0)

        # Ensure positive semi-definite
        corr = np.clip(corr, -1, 1)
        np.fill_diagonal(corr, 1.0)

        return corr

    def get_breakdown(self) -> dict:
        """Get component breakdown for explainability panel."""
        segments = {}
        for name, buf in self.segment_buffers.items():
            if buf:
                cdf_val = self._empirical_cdf(name)
                segments[name] = {
                    "raw_value": round(float(buf[-1]), 6),
                    "cdf_score": round(float(cdf_val), 4),
                    "buffer_size": len(buf),
                }
        
        return {
            "segments": segments,
            "correlation_matrix": self._cross_correlation_matrix().tolist(),
            "score_history": list(self._score_history)[-100:],
        }


# Singleton
ciss_scorer = CISSScorer()
