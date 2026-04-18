"""
Source-Agnostic State Builder for Project Velure.

Replaces the hard coupling to `simulator.get_state_vector()` in the ensemble.
Accepts tick data from ANY source (simulator, Finnhub, replay) and builds
the same 60-dimensional state vector for ML models.

State vector format: [latest_return, vol, mean_return, max_abs_return] × 15 assets
"""
import numpy as np
from collections import deque
from typing import Dict, Optional

from utils.config import NUM_ASSETS, STATE_VECTOR_DIM

# Canonical asset ordering — MUST match across all modules
TRACKED_ASSETS = [
    "BAC", "BTCUSD", "C", "DIA", "ETHUSD",
    "EURUSD", "GBPUSD", "GS", "IWM", "JPM",
    "MS", "QQQ", "SPY", "USDJPY", "XLF",
]


class StateBuilder:
    """
    Source-agnostic 60-dim state vector builder.

    Maintains its own price history and computes features from any tick
    source (simulator, Finnhub live, historical replay). Drop-in
    replacement for `simulator.get_state_vector()`.
    """

    def __init__(self, history_len: int = 300):
        self.history_len = history_len
        self._history: Dict[str, deque] = {
            t: deque(maxlen=history_len) for t in TRACKED_ASSETS
        }
        self._tick_count = 0

    @property
    def tracked_assets(self) -> list:
        return TRACKED_ASSETS

    def ingest(self, tick_data: dict) -> None:
        """
        Ingest a tick and update internal price history.

        Accepts tick_data with format:
            {"assets": {"SPY": {"price": 542.0, ...}, ...}}
        """
        assets = tick_data.get("assets", {})
        for ticker in TRACKED_ASSETS:
            if ticker in assets:
                price = assets[ticker].get("price")
                if price is not None and np.isfinite(price) and price > 0:
                    self._history[ticker].append(float(price))
        self._tick_count += 1

    def get_state_vector(self, tick_data: Optional[dict] = None) -> np.ndarray:
        """
        Build a 60-dimensional feature vector from current state.

        If tick_data is provided, ingests it first (convenience method).
        Format: [latest_return, vol, mean_return, max_abs_return] × 15 assets

        Returns:
            np.ndarray of shape (60,) with dtype float32
        """
        if tick_data is not None:
            self.ingest(tick_data)

        features = []
        for ticker in TRACKED_ASSETS:
            hist = self._history[ticker]
            if len(hist) < 10:
                features.extend([0.0, 0.0, 0.0, 0.0])
                continue

            prices = list(hist)[-60:]
            returns = np.diff(np.log(prices))

            if len(returns) == 0:
                features.extend([0.0, 0.0, 0.0, 0.0])
                continue

            latest_return = float(returns[-1]) if len(returns) > 0 else 0.0
            vol = float(np.std(returns)) if len(returns) > 1 else 0.0
            mean_return = float(np.mean(returns))
            max_abs_return = float(np.max(np.abs(returns)))

            features.extend([latest_return, vol, mean_return, max_abs_return])

        vec = np.array(features, dtype=np.float32)
        # Sanitize: replace NaN/inf with 0
        vec = np.nan_to_num(vec, nan=0.0, posinf=0.0, neginf=0.0)

        assert vec.shape == (STATE_VECTOR_DIM,), (
            f"State vector dimension mismatch: expected {STATE_VECTOR_DIM}, got {vec.shape[0]}"
        )
        return vec

    def has_data(self) -> bool:
        """True if we have at least some price history."""
        return any(len(h) >= 10 for h in self._history.values())


# Singleton — shared across ensemble and features pipeline
state_builder = StateBuilder()
