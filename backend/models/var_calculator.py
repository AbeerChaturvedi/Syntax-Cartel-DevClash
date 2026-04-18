"""
Value-at-Risk (VaR) & Conditional VaR (CVaR/Expected Shortfall) Calculator.

Implements three VaR methodologies:
1. Historical Simulation — empirical quantile of returns
2. Parametric (Variance-Covariance) — assumes normal distribution
3. Cornish-Fisher — adjusts for skewness and kurtosis

Also computes CVaR (Expected Shortfall) for tail risk quantification.
"""
import numpy as np
from scipy import stats
from collections import deque
from typing import Dict, Optional


class VaRCalculator:
    """
    Portfolio Value-at-Risk engine with rolling window.
    
    Updates each tick with new returns, maintains a rolling window,
    and computes VaR/CVaR at configurable confidence levels.
    """

    def __init__(self, window_size: int = 500, confidence: float = 0.99):
        self.window_size = window_size
        self.confidence = confidence
        self._returns_history: deque = deque(maxlen=window_size)
        self._asset_returns: Dict[str, deque] = {}
        self._portfolio_value = 1_000_000  # $1M notional

    def update(self, assets: Dict) -> Dict:
        """
        Update with latest asset data and compute VaR metrics.
        
        Args:
            assets: Dict of ticker -> {price, pct_change, ...}
            
        Returns:
            VaR metrics dict
        """
        # Collect per-asset returns
        returns = []
        for ticker, data in assets.items():
            pct = data.get("pct_change", 0)
            returns.append(pct)

            if ticker not in self._asset_returns:
                self._asset_returns[ticker] = deque(maxlen=self.window_size)
            self._asset_returns[ticker].append(pct)

        if not returns:
            return self._empty_result()

        # Equal-weighted portfolio return
        port_return = np.mean(returns)
        self._returns_history.append(port_return)

        if len(self._returns_history) < 30:
            return self._empty_result()

        arr = np.array(self._returns_history, dtype=np.float64)
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        return self._compute_var(arr)

    def _compute_var(self, returns: np.ndarray) -> Dict:
        """Compute VaR using three methods + CVaR."""
        alpha = 1 - self.confidence  # e.g., 0.01 for 99%

        # ── Historical VaR ──
        hist_var = -np.percentile(returns, alpha * 100)

        # ── Parametric VaR (Normal) ──
        mu = np.mean(returns)
        sigma = np.std(returns, ddof=1) if len(returns) > 1 else np.std(returns)
        sigma = max(sigma, 1e-10)  # prevent division by zero
        z = stats.norm.ppf(self.confidence)
        param_var = -(mu - z * sigma)

        # ── Cornish-Fisher VaR ──
        skew = float(stats.skew(returns))
        kurt = float(stats.kurtosis(returns))
        # Cornish-Fisher expansion for adjusted z-score
        z_cf = (z +
                (z**2 - 1) * skew / 6 +
                (z**3 - 3*z) * kurt / 24 -
                (2*z**3 - 5*z) * skew**2 / 36)
        cf_var = -(mu - z_cf * sigma)

        # ── CVaR (Expected Shortfall) ──
        # Average of returns below VaR threshold
        threshold = np.percentile(returns, alpha * 100)
        tail_returns = returns[returns <= threshold]
        cvar = -np.mean(tail_returns) if len(tail_returns) > 0 else hist_var

        # ── Dollar VaR ──
        dollar_var = hist_var * self._portfolio_value
        dollar_cvar = cvar * self._portfolio_value

        # ── Per-asset contribution to VaR (marginal VaR) ──
        asset_var = {}
        for ticker, ret_deque in self._asset_returns.items():
            if len(ret_deque) >= 30:
                a = np.array(ret_deque)
                asset_var[ticker] = {
                    "var_pct": round(float(-np.percentile(a, alpha * 100)) * 100, 4),
                    "vol": round(float(np.std(a, ddof=1)) * 100, 4),
                }

        # ── Risk regime classification ──
        vol_annual = sigma * np.sqrt(252 * 16)  # annualized (assuming 16 ticks/day for sim)
        if vol_annual > 0.40:
            regime = "EXTREME"
        elif vol_annual > 0.25:
            regime = "HIGH"
        elif vol_annual > 0.15:
            regime = "ELEVATED"
        else:
            regime = "NORMAL"

        return {
            "historical_var": round(float(hist_var) * 100, 4),
            "parametric_var": round(float(param_var) * 100, 4),
            "cornish_fisher_var": round(float(cf_var) * 100, 4),
            "cvar": round(float(cvar) * 100, 4),
            "dollar_var": round(float(dollar_var), 0),
            "dollar_cvar": round(float(dollar_cvar), 0),
            "confidence": self.confidence,
            "window": len(self._returns_history),
            "volatility_annual": round(float(vol_annual) * 100, 2),
            "skewness": round(skew, 4),
            "kurtosis": round(kurt, 4),
            "regime": regime,
            "asset_var": asset_var,
        }

    def _empty_result(self) -> Dict:
        return {
            "historical_var": 0,
            "parametric_var": 0,
            "cornish_fisher_var": 0,
            "cvar": 0,
            "dollar_var": 0,
            "dollar_cvar": 0,
            "confidence": self.confidence,
            "window": len(self._returns_history),
            "volatility_annual": 0,
            "skewness": 0,
            "kurtosis": 0,
            "regime": "NORMAL",
            "asset_var": {},
        }


# Singleton
var_calculator = VaRCalculator()
