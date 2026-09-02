"""
Source-Agnostic State Builder for Project Velure.

Replaces the hard coupling to `simulator.get_state_vector()` in the ensemble.
Accepts tick data from ANY source (simulator, Finnhub, replay) and builds
the same 60-dimensional state vector for ML models.

State vector format: [latest_return, vol, mean_return, max_abs_return] x 15 assets
"""
import numpy as np
from collections import deque
from typing import Dict, Optional

from utils.config import NUM_ASSETS, STATE_VECTOR_DIM

# Canonical asset ordering -- MUST match across all modules
TRACKED_ASSETS = [
    "BAC", "BTCUSD", "C", "DIA", "ETHUSD",
    "EURUSD", "GBPUSD", "GS", "IWM", "JPM",
    "MS", "QQQ", "SPY", "USDJPY", "XLF",
]

# Per-ticker feature names. 4 metrics x 15 tickers = 60 features.
# Order MUST match the layout in get_state_vector().
FEATURE_NAMES = ["Return", "Volatility", "Mean Return", "Max |Return|"]


class StateBuilder:
    """
    Source-agnostic 60-dim state vector builder.

    Accepts tick data from ANY source (simulator, Finnhub, replay) and builds
    the same 60-dimensional state vector for ML models.

    Strategy: keep BOTH a price history (for correlation matrix) and a
    pre-computed feature history (for the state vector).  The feature
    history is populated from the heartbeat's pct_change/rolling_volatility
    fields, which are non-zero even when the price series is flat
    (e.g. during off-hours when only a seed price is available).
    """

    def __init__(self, history_len: int = 300):
        self.history_len = history_len
        self._history: Dict[str, deque] = {
            t: deque(maxlen=history_len) for t in TRACKED_ASSETS
        }
        # Per-asset feature history: deque of (pct_change, rolling_volatility)
        self._feature_history: Dict[str, deque] = {
            t: deque(maxlen=history_len) for t in TRACKED_ASSETS
        }
        self._tick_count = 0
        self._latest_pct: Dict[str, float] = {t: 0.0 for t in TRACKED_ASSETS}
        self._latest_vol: Dict[str, float] = {t: 0.0 for t in TRACKED_ASSETS}

    @property
    def tracked_assets(self) -> list:
        return TRACKED_ASSETS

    def ingest(self, tick_data: dict) -> None:
        """
        Ingest a tick and update internal state.

        Accepts tick_data with format:
            {"assets": {"SPY": {"price": 542.0, "pct_change": 0.001,
                                 "rolling_volatility": 0.01}, ...}}
        """
        assets = tick_data.get("assets", {})
        for ticker in TRACKED_ASSETS:
            if ticker in assets:
                adata = assets[ticker]
                price = adata.get("price")
                if price is not None and np.isfinite(price) and price > 0:
                    self._history[ticker].append(float(price))
                # Capture pre-computed features when present (from heartbeat)
                pct = adata.get("pct_change")
                vol = adata.get("rolling_volatility")
                if pct is not None and np.isfinite(float(pct)):
                    self._latest_pct[ticker] = float(pct)
                if vol is not None and np.isfinite(float(vol)):
                    self._latest_vol[ticker] = float(vol)
                # Append (pct, vol) pair to feature history -- both may be 0
                # when not provided but they always have a value.
                self._feature_history[ticker].append(
                    (self._latest_pct[ticker], self._latest_vol[ticker])
                )
        self._tick_count += 1

    def get_state_vector(self, tick_data: Optional[dict] = None) -> np.ndarray:
        """
        Build a 60-dimensional feature vector from current state.

        If tick_data is provided, ingests it first (convenience method).
        Format: [latest_return, vol, mean_return, max_abs_return] x 15 assets

        Returns:
            np.ndarray of shape (60,) with dtype float32
        """
        if tick_data is not None:
            self.ingest(tick_data)

        features = []
        for ticker in TRACKED_ASSETS:
            # Prefer price-derived returns when prices actually vary;
            # otherwise fall back to the feature history (which captures
            # pct_change/rolling_volatility from the heartbeat even when
            # prices are flat -- e.g. during off-hours).
            hist = list(self._history[ticker])
            feat_hist = list(self._feature_history[ticker])

            prices_vary = len(hist) >= 10 and len(set(hist[-10:])) > 1

            if prices_vary:
                prices = hist[-60:]
                returns = np.diff(np.log(np.array(prices, dtype=np.float64)))
                if len(returns) == 0:
                    returns = np.array([0.0])
                latest_return = float(returns[-1]) if len(returns) > 0 else 0.0
                vol = float(np.std(returns)) if len(returns) > 1 else 0.0
                mean_return = float(np.mean(returns))
                max_abs_return = float(np.max(np.abs(returns)))
            elif len(feat_hist) >= 5:
                # Use the heartbeat-provided pct/vol; build mean and max
                # from the recent feature history.
                pcts = [p for p, _ in feat_hist[-30:]]
                vols = [v for _, v in feat_hist[-30:]]
                latest_return = float(pcts[-1]) if pcts else 0.0
                vol = float(np.mean(vols)) if vols else 0.0
                mean_return = float(np.mean(pcts)) if pcts else 0.0
                max_abs_return = float(np.max(np.abs(pcts))) if pcts else 0.0
            else:
                # Genuinely cold start -- no data anywhere
                features.extend([0.0, 0.0, 0.0, 0.0])
                continue

            features.extend([latest_return, vol, mean_return, max_abs_return])

        vec = np.array(features, dtype=np.float32)
        # Sanitize: replace NaN/inf with 0
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

        assert vec.shape == (STATE_VECTOR_DIM,), (
            f"State vector dimension mismatch: expected {STATE_VECTOR_DIM}, got {vec.shape[0]}"
        )
        return vec

    def compute_correlation_matrix(self, lookback: int = 30) -> tuple:
        """Compute the cross-asset Pearson correlation matrix from recent
        returns.  Returns ``(matrix, avg_correlation)`` where ``matrix``
        is a 15x15 list-of-lists and ``avg_correlation`` is the mean of
        the upper-triangle absolute values.

        Returns a zero matrix if any ticker has < lookback points, so
        callers can use the result unconditionally.
        """
        returns_matrix = []
        for t in TRACKED_ASSETS:
            # Prefer price-derived returns; fall back to heartbeat pct_changes
            hist = list(self._history[t])
            feat_hist = list(self._feature_history[t])

            prices_vary = len(hist) >= lookback + 1 and len(set(hist[-(lookback+1):])) > 1

            if prices_vary:
                log_prices = np.log(np.array(hist[-(lookback + 1):], dtype=np.float64))
                returns = np.diff(log_prices)
            elif len(feat_hist) >= lookback:
                returns = np.array([p for p, _ in feat_hist[-lookback:]], dtype=np.float64)
            else:
                return [], 0.0

            returns_matrix.append(returns)

        returns_matrix = np.array(returns_matrix)
        corr = np.corrcoef(returns_matrix)
        corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
        np.fill_diagonal(corr, 1.0)

        upper = corr[np.triu_indices_from(corr, k=1)]
        avg = float(np.mean(np.abs(upper))) if upper.size > 0 else 0.0

        return corr.tolist(), round(avg, 4)

    def has_data(self) -> bool:
        """True if we have at least some price or feature history."""
        return any(len(h) >= 10 for h in self._history.values()) or \
               any(len(h) >= 5 for h in self._feature_history.values())


# Singleton -- shared across ensemble and features pipeline
state_builder = StateBuilder()