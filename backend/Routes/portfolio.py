from fastapi import APIRouter, HTTPException
import numpy as np
from scipy.stats import norm, skew, kurtosis

from ingestion.simulator import simulator
from features.state_builder import state_builder

router = APIRouter()

@router.post("/api/var/portfolio")
async def compute_portfolio_var(request: dict):
    """
    Compute portfolio VaR/CVaR from live price data.
    Expects: { "weights": {"SPY": 0.4, "QQQ": 0.2, ...}, "notional": 1000000, "confidence": 0.99 }
    """
    weights = request.get("weights", {})
    notional = request.get("notional", 1_000_000)
    confidence = request.get("confidence", 0.99)

    if not weights:
        raise HTTPException(status_code=400, detail="No portfolio weights provided")

    # Gather returns from state_builder's price history, fall back to simulator
    all_returns = {}
    for ticker, weight in weights.items():
        hist = list(state_builder._history.get(ticker, []))
        if len(hist) < 10:
            sim_hist = list(simulator._history.get(ticker, []))
            hist = sim_hist if len(sim_hist) >= 10 else hist
        if len(hist) >= 10:
            prices = np.array(hist, dtype=np.float64)
            rets = np.diff(np.log(prices))
            all_returns[ticker] = rets

    if not all_returns:
        raise HTTPException(status_code=400, detail="Insufficient price history for VaR computation")

    # Align return series to same length
    min_len = min(len(r) for r in all_returns.values())
    tickers_used = list(all_returns.keys())
    w_vec = np.array([weights.get(t, 0) for t in tickers_used])
    w_vec = w_vec / w_vec.sum()  # Normalize

    returns_matrix = np.column_stack([all_returns[t][-min_len:] for t in tickers_used])
    portfolio_returns = returns_matrix @ w_vec

    # 1. Historical VaR
    hist_var = float(np.percentile(portfolio_returns, (1 - confidence) * 100))

    # 2. Parametric VaR (Gaussian)
    mu = np.mean(portfolio_returns)
    sigma = np.std(portfolio_returns)
    z = norm.ppf(1 - confidence)
    param_var = float(mu + z * sigma)

    # 3. Cornish-Fisher VaR (skew/kurtosis adjusted)
    s = float(skew(portfolio_returns)) if len(portfolio_returns) > 10 else 0
    k = float(kurtosis(portfolio_returns, fisher=True)) if len(portfolio_returns) > 10 else 0
    cf_z = z + (z**2 - 1) * s / 6 + (z**3 - 3*z) * k / 24 - (2*z**3 - 5*z) * s**2 / 36
    cf_var = float(mu + cf_z * sigma)

    # 4. CVaR (Expected Shortfall)
    tail = portfolio_returns[portfolio_returns <= hist_var]
    cvar = float(np.mean(tail)) if len(tail) > 0 else hist_var

    # 5. Component VaR
    cov_matrix = np.cov(returns_matrix, rowvar=False)
    marginal_contrib = cov_matrix @ w_vec
    component_var = {}
    total_var_abs = abs(hist_var) if hist_var != 0 else 1e-8
    for i, t in enumerate(tickers_used):
        contrib = float(w_vec[i] * marginal_contrib[i])
        component_var[t] = {
            "weight": float(w_vec[i]),
            "contribution_pct": round(contrib / total_var_abs * 100, 2),
            "marginal_var": round(float(marginal_contrib[i]) * 100, 4),
        }

    # Risk regime
    if abs(hist_var) < 0.01:
        regime = "LOW"
    elif abs(hist_var) < 0.03:
        regime = "MODERATE"
    elif abs(hist_var) < 0.06:
        regime = "HIGH"
    else:
        regime = "EXTREME"

    return {
        "historical_var": round(hist_var * 100, 4),
        "parametric_var": round(param_var * 100, 4),
        "cornish_fisher_var": round(cf_var * 100, 4),
        "cvar": round(cvar * 100, 4),
        "dollar_var": round(abs(hist_var) * notional, 2),
        "dollar_cvar": round(abs(cvar) * notional, 2),
        "component_var": component_var,
        "confidence": confidence,
        "regime": regime,
        "data_points": min_len,
        "tickers_used": tickers_used,
    }
