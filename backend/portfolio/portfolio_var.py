"""
Portfolio-level VaR for user-supplied portfolios.

The existing `VaRCalculator` computes equal-weighted VaR across the
default basket.  This module accepts a user portfolio ({ticker: weight})
and computes:
    · Portfolio VaR (Historical, Parametric, Cornish-Fisher)
    · Portfolio CVaR
    · Component VaR per position (contribution to total risk)
    · Marginal VaR per position
    · Diversification benefit (sum(individual VaR) − portfolio VaR)

Inputs draw from the live simulator / replay price history, so results
reflect current market state.  For an institutional use case, weights
would come from a real portfolio holdings feed.
"""
import numpy as np
from scipy import stats
from typing import Dict, List

from ingestion.simulator import simulator


class PortfolioRisk:
    """Arbitrary-portfolio VaR engine.

    Pulls return history from the live simulator's `_history` buffers.
    """

    def __init__(self, window: int = 500):
        self.window = window

    def compute(self, weights: Dict[str, float], notional: float = 1_000_000.0, confidence: float = 0.99) -> Dict:
        """Compute portfolio VaR on user-supplied weights."""
        # Normalise weights so they sum to 1 (long-only, no shorts)
        cleaned = self._clean_weights(weights)
        if not cleaned:
            return {"ok": False, "reason": "no valid tickers supplied"}

        tickers = list(cleaned.keys())
        w = np.array([cleaned[t] for t in tickers], dtype=np.float64)

        # Pull historical returns
        returns_matrix = self._pull_returns(tickers)
        if returns_matrix is None:
            return {"ok": False, "reason": "insufficient return history (warming up)"}

        # Portfolio returns: element-wise ( R @ w )
        port_returns = returns_matrix @ w

        # VaR methods
        alpha = 1.0 - confidence
        hist_var = float(-np.percentile(port_returns, alpha * 100))
        mu = float(np.mean(port_returns))
        sigma = float(np.std(port_returns, ddof=1)) if len(port_returns) > 1 else 0.0
        sigma = max(sigma, 1e-10)
        z = float(stats.norm.ppf(confidence))
        param_var = float(-(mu - z * sigma))
        skew = float(stats.skew(port_returns))
        kurt = float(stats.kurtosis(port_returns))
        z_cf = (z
                + (z**2 - 1) * skew / 6
                + (z**3 - 3*z) * kurt / 24
                - (2*z**3 - 5*z) * skew**2 / 36)
        cf_var = float(-(mu - z_cf * sigma))

        threshold = np.percentile(port_returns, alpha * 100)
        tail = port_returns[port_returns <= threshold]
        cvar = float(-np.mean(tail)) if tail.size else hist_var

        # Component VaR — Euler allocation via Cov * w
        cov = np.cov(returns_matrix, rowvar=False)
        port_var_gaussian = float(np.sqrt(max(w @ cov @ w, 1e-20)))
        # marginal: dσp/dw_i = (Σw)_i / σp
        marginal = cov @ w / port_var_gaussian
        component_var = w * marginal  # contribution to σp (sums to σp)
        # Scale to dollar VaR at given confidence
        component_dollar = (component_var * z) * notional / port_var_gaussian * param_var * notional if port_var_gaussian > 0 else component_var

        # Individual-asset VaR
        ind_var = {}
        for i, t in enumerate(tickers):
            r = returns_matrix[:, i]
            v = float(-np.percentile(r, alpha * 100))
            ind_var[t] = round(v * 100, 4)

        sum_individual = float(np.sum([cleaned[t] * ind_var[t] / 100.0 for t in tickers]))
        diversification_benefit = float(max(0.0, sum_individual - hist_var))

        return {
            "ok": True,
            "confidence": confidence,
            "notional": notional,
            "window": int(returns_matrix.shape[0]),
            "portfolio": {
                "weights": {t: round(cleaned[t], 4) for t in tickers},
                "historical_var_pct": round(hist_var * 100, 4),
                "parametric_var_pct": round(param_var * 100, 4),
                "cornish_fisher_var_pct": round(cf_var * 100, 4),
                "cvar_pct": round(cvar * 100, 4),
                "dollar_var": round(hist_var * notional, 0),
                "dollar_cvar": round(cvar * notional, 0),
                "volatility_annual_pct": round(float(sigma) * np.sqrt(252 * 390) * 100, 4),
                "skewness": round(skew, 4),
                "kurtosis": round(kurt, 4),
                "sum_individual_var_pct": round(sum_individual * 100, 4),
                "diversification_benefit_pct": round(diversification_benefit * 100, 4),
            },
            "components": [
                {
                    "ticker": t,
                    "weight": round(cleaned[t], 4),
                    "individual_var_pct": ind_var[t],
                    "component_var_pct": round(float(component_var[i]) * 100, 4),
                    "marginal_var_pct": round(float(marginal[i]) * 100, 4),
                    "component_dollar": round(float(component_dollar[i]), 0),
                }
                for i, t in enumerate(tickers)
            ],
        }

    # ── internals ──────────────────────────────────────────────────
    def _clean_weights(self, weights: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for t, w in (weights or {}).items():
            t = str(t).upper()
            if t not in simulator.ASSETS:
                continue
            try:
                ww = float(w)
            except (TypeError, ValueError):
                continue
            if ww <= 0:
                continue
            out[t] = ww
        total = sum(out.values())
        if total <= 0:
            return {}
        for t in list(out.keys()):
            out[t] = out[t] / total
        return out

    def _pull_returns(self, tickers: List[str]) -> np.ndarray:
        cols = []
        for t in tickers:
            hist = simulator._history.get(t, [])
            if len(hist) < 40:
                return None
            r = np.diff(np.log(np.asarray(hist, dtype=np.float64)[-self.window:]))
            cols.append(r)
        min_len = min(len(c) for c in cols)
        cols = [c[-min_len:] for c in cols]
        return np.column_stack(cols)


# Singleton
portfolio_risk = PortfolioRisk()
