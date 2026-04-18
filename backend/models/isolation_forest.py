"""
Isolation Forest — Unsupervised Global Anomaly Detector
Detects cross-sectional outliers in market state vectors.
"""
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
import joblib
import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "models", "isolation_forest.pkl")
SCALER_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "models", "if_scaler.pkl")


class AnomalyDetectorIF:
    """
    Isolation Forest anomaly detector.
    Trained on 'normal' market conditions to detect anomalous state vectors.
    """

    def __init__(self, contamination: float = 0.05, n_estimators: int = 200):
        self.model = IsolationForest(
            contamination=contamination,
            n_estimators=n_estimators,
            max_samples='auto',
            random_state=42,
            n_jobs=-1,
        )
        self.scaler = StandardScaler()
        self.is_fitted = False

    def train(self, normal_data: np.ndarray):
        """Train on historical 'calm' market data."""
        scaled = self.scaler.fit_transform(normal_data)
        self.model.fit(scaled)
        self.is_fitted = True

    @staticmethod
    def _sanitize(arr: np.ndarray) -> np.ndarray:
        """Replace NaN/inf with 0 to prevent sklearn crashes."""
        return np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)

    def predict(self, state_vector: np.ndarray) -> float:
        """
        Returns anomaly score in [0, 1].
        Higher = more anomalous.
        """
        if not self.is_fitted:
            # Auto-train on synthetic normal data if no model loaded
            self._auto_train()

        if state_vector.ndim == 1:
            state_vector = state_vector.reshape(1, -1)

        state_vector = self._sanitize(state_vector)
        try:
            scaled = self.scaler.transform(state_vector)
        except Exception:
            # Checkpoint may have saved an unfitted scaler — retrain
            self._auto_train()
            scaled = self.scaler.transform(state_vector)

        # decision_function returns negative for anomalies
        raw_score = self.model.decision_function(scaled)[0]

        # Normalize: raw_score is typically in [-0.5, 0.5]
        # Map to [0, 1] where 1 = most anomalous
        anomaly_score = 1.0 / (1.0 + np.exp(5 * raw_score))  # Sigmoid transform

        return float(np.clip(anomaly_score, 0, 1))

    def predict_batch(self, state_vectors: np.ndarray) -> np.ndarray:
        """Batch prediction for micro-batching."""
        if not self.is_fitted:
            self._auto_train()

        state_vectors = self._sanitize(state_vectors)
        try:
            scaled = self.scaler.transform(state_vectors)
        except Exception:
            self._auto_train()
            scaled = self.scaler.transform(state_vectors)
        raw_scores = self.model.decision_function(scaled)
        anomaly_scores = 1.0 / (1.0 + np.exp(5 * raw_scores))
        return np.clip(anomaly_scores, 0, 1)

    def get_feature_importance(self, state_vector: np.ndarray, feature_names: list = None) -> dict:
        """
        Approximate feature importance using vectorized perturbation analysis.
        Returns dict of feature_name -> contribution_score (top 10).
        """
        if not self.is_fitted:
            self._auto_train()

        if state_vector.ndim == 1:
            state_vector = state_vector.reshape(1, -1)

        n_features = state_vector.shape[1]
        base_score = self.predict(state_vector[0])

        # Build all perturbations at once (N × features matrix)
        # instead of calling predict() N times
        perturbed_batch = np.tile(state_vector, (n_features, 1))
        for i in range(n_features):
            perturbed_batch[i, i] = 0.0

        batch_scores = self.predict_batch(perturbed_batch)
        diffs = np.abs(base_score - batch_scores)

        # Build result dict — top 10 only
        pairs = []
        for i in range(n_features):
            name = feature_names[i] if feature_names and i < len(feature_names) else f"feature_{i}"
            pairs.append((name, round(float(diffs[i]), 6)))

        pairs.sort(key=lambda x: x[1], reverse=True)
        return dict(pairs[:10])

    def _auto_train(self):
        """Generate synthetic normal data and train."""
        np.random.seed(42)
        # 72 features: 18 assets × 4 features each
        n_features = 72
        n_samples = 5000

        # Simulate calm market: small returns, low vol
        normal_data = np.random.randn(n_samples, n_features) * 0.01
        self.train(normal_data)

    def save(self, model_path: str = None, scaler_path: str = None):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump(self.model, model_path or MODEL_PATH)
        joblib.dump(self.scaler, scaler_path or SCALER_PATH)

    def load(self, model_path: str = None, scaler_path: str = None):
        mp = model_path or MODEL_PATH
        sp = scaler_path or SCALER_PATH
        if os.path.exists(mp) and os.path.exists(sp):
            self.model = joblib.load(mp)
            self.scaler = joblib.load(sp)
            self.is_fitted = True
            return True
        return False


# Singleton
anomaly_detector_if = AnomalyDetectorIF()
