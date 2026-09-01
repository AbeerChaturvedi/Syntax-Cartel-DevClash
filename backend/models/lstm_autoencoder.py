"""
LSTM Autoencoder — Temporal Anomaly Detector
Detects sequential pattern deviations in market time series.
Uses reconstruction error as anomaly signal.

NORMALIZATION STRATEGY
----------------------
State vector from state_builder.py contains 4 features per asset:
  [latest_return, vol, mean_return, max_abs_return] × 15 assets = 60 dims

Measured distributions from live Finnhub data:
  - return:       range ±0.003,  scale by 300
  - vol:          range 0–0.003, scale by 300
  - mean_return:  range ±0.0001, scale by 10000
  - max_abs_ret:  range 0–0.003, scale by 300

We apply these fixed per-feature-type scales so every feature lands in ~[-1, 1].
This eliminates the rolling Z-score instability (non-zero-mean features,
near-zero std on slow-moving features) that caused the model to always output 100%.

THRESHOLD STRATEGY
------------------
Fixed training threshold is unreliable because the model's reconstruction quality
depends on random weight initialization. Instead we use an ADAPTIVE threshold:
- Collect the first 200 real MSE observations (warm-up phase)
- Set threshold = 90th percentile of warm-up MSEs × 1.5
- Update threshold slowly (every 500 ticks) using a long EWM window
- Result: "calm = low score, anomaly = high score" relative to recent baseline
"""
import numpy as np
import torch
import torch.nn as nn
import os
from collections import deque

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "models", "lstm_autoencoder.pt")

# ── Fixed normalizer scales per feature slot (index mod 4) ──────────────────
# Based on measured live data distributions. Brings all features to ~[-1, 1].
_FEATURE_SCALES = np.array([
    300.0,    # slot 0: latest_return   (±0.003 → ±0.9)
    300.0,    # slot 1: vol             (0–0.003 → 0–0.9)
    10000.0,  # slot 2: mean_return     (±0.0001 → ±1.0)
    300.0,    # slot 3: max_abs_return  (0–0.003 → 0–0.9)
] * 15, dtype=np.float32)  # repeat for all 15 assets = 60 dims


def _scale(vec: np.ndarray) -> np.ndarray:
    """Apply fixed per-feature-type scaling. Returns vector in ~[-1, 1]."""
    return vec * _FEATURE_SCALES


class LSTMAutoencoder(nn.Module):
    """
    LSTM Autoencoder for time-series anomaly detection.
    Architecture: 2-layer encoder (60→64→32) + 2-layer decoder (32→64→60)
    """

    def __init__(self, input_dim: int = 60, hidden_dim: int = 64, latent_dim: int = 32):
        super().__init__()
        self.input_dim = input_dim
        self.hidden_dim = hidden_dim
        self.latent_dim = latent_dim

        # Encoder
        self.encoder_lstm1 = nn.LSTM(input_dim, hidden_dim, batch_first=True)
        self.encoder_lstm2 = nn.LSTM(hidden_dim, latent_dim, batch_first=True)

        # Decoder
        self.decoder_lstm1 = nn.LSTM(latent_dim, hidden_dim, batch_first=True)
        self.decoder_lstm2 = nn.LSTM(hidden_dim, input_dim, batch_first=True)

    def forward(self, x):
        enc1, _ = self.encoder_lstm1(x)
        enc2, _ = self.encoder_lstm2(enc1)
        dec1, _ = self.decoder_lstm1(enc2)
        dec2, _ = self.decoder_lstm2(dec1)
        return dec2


class TemporalAnomalyDetector:
    """
    Wraps LSTM Autoencoder for anomaly detection via reconstruction error.
    Higher reconstruction error = more anomalous.
    """

    # How many real ticks to collect before computing the adaptive threshold
    WARMUP_TICKS = 200
    # Number of ticks between adaptive threshold updates
    THRESHOLD_UPDATE_INTERVAL = 500

    def __init__(self, input_dim: int = 60, seq_length: int = 20):
        self.input_dim = input_dim
        self.seq_length = seq_length
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = LSTMAutoencoder(input_dim=input_dim).to(self.device)
        self.model.eval()

        self.is_fitted = False
        # Threshold: set initially high. Will be calibrated after WARMUP_TICKS real ticks.
        self.threshold = 1.0
        self._threshold_calibrated = False
        self._tick_count = 0

        # Raw state vector buffer (stores scaled vectors)
        self._buffer: deque = deque(maxlen=seq_length * 3)
        # MSE history for adaptive thresholding
        self._mse_history: deque = deque(maxlen=1000)
        # Warmup MSE collection for initial calibration
        self._warmup_mses: list = []

    def add_to_buffer(self, state_vector: np.ndarray):
        """Add a state vector to the temporal buffer (with fixed scaling)."""
        clean = np.nan_to_num(state_vector, nan=0.0, posinf=0.0, neginf=0.0)
        scaled = _scale(clean)
        self._buffer.append(scaled.astype(np.float32))

    def predict(self) -> float:
        """
        Compute anomaly score from current buffer.
        Returns score in [0, 1]. Higher = more anomalous.
        """
        if len(self._buffer) < self.seq_length:
            return 0.0  # Not enough data yet

        if not self.is_fitted:
            self._auto_train()

        buf_list = list(self._buffer)
        sequence = np.array(buf_list[-self.seq_length:], dtype=np.float32)
        x = torch.FloatTensor(sequence).unsqueeze(0).to(self.device)  # [1, seq, features]

        with torch.no_grad():
            reconstruction = self.model(x)
            mse = torch.mean((x - reconstruction) ** 2).item()

        self._mse_history.append(mse)
        self._tick_count += 1

        # ── Adaptive threshold calibration ──────────────────────────────────
        if not self._threshold_calibrated:
            self._warmup_mses.append(mse)
            if len(self._warmup_mses) >= self.WARMUP_TICKS:
                # Set threshold = 90th percentile × 3.0 safety margin.
                # This means calm ticks score ~25-35%, true crashes score >70%.
                self.threshold = float(np.percentile(self._warmup_mses, 90)) * 3.0
                self.threshold = max(self.threshold, 1e-6)
                self._threshold_calibrated = True
            # During warmup, return a neutral low score
            return 0.1

        # Periodically update threshold using recent MSE history (slow adaptation)
        if self._tick_count % self.THRESHOLD_UPDATE_INTERVAL == 0 and len(self._mse_history) >= 100:
            # Use 90th pct of recent history × 3.0. This drifts slowly with
            # market regime changes but won't instantly collapse on a crash.
            candidate = float(np.percentile(list(self._mse_history)[-500:], 90)) * 3.0
            # Blend 90% old threshold + 10% new candidate to prevent sudden jumps
            self.threshold = 0.9 * self.threshold + 0.1 * candidate
            self.threshold = max(self.threshold, 1e-6)
        # ── Score: sigmoid of (mse / threshold) ─────────────────────────────
        # With 3x threshold, ratio for calm = ~0.33, ratio for crash = >>1
        # ratio=0.33 → score ~0.19  (calm normal)  
        # ratio=0.67 → score ~0.38  (mild stress)
        # ratio=1.00 → score ~0.60  (borderline anomaly)
        # ratio=2.00 → score ~0.90  (strong anomaly)
        ratio = mse / self.threshold
        anomaly_score = 1.0 / (1.0 + np.exp(-4.0 * (ratio - 0.7)))

        return float(np.clip(anomaly_score, 0.0, 1.0))

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        """Batch prediction for multiple sequences."""
        if not self.is_fitted:
            self._auto_train()

        x = torch.FloatTensor(sequences).to(self.device)
        with torch.no_grad():
            reconstruction = self.model(x)
            mse_per_sample = torch.mean((x - reconstruction) ** 2, dim=(1, 2)).cpu().numpy()

        scores = 1.0 / (1.0 + np.exp(-4.0 * (mse_per_sample / max(self.threshold, 1e-8) - 0.8)))
        return np.clip(scores, 0, 1)

    def get_reconstruction_details(self) -> dict:
        """Get detailed reconstruction info for explainability."""
        if len(self._buffer) < self.seq_length:
            return {"status": "buffering", "buffer_fill": len(self._buffer) / self.seq_length}

        buf_list = list(self._buffer)
        sequence = np.array(buf_list[-self.seq_length:], dtype=np.float32)
        x = torch.FloatTensor(sequence).unsqueeze(0).to(self.device)

        with torch.no_grad():
            reconstruction = self.model(x)
            per_feature_mse = torch.mean((x - reconstruction) ** 2, dim=1).squeeze().cpu().numpy()

        return {
            "status": "active",
            "overall_mse": float(torch.mean((x - reconstruction) ** 2).item()),
            "per_feature_mse": per_feature_mse.tolist(),
            "threshold": self.threshold,
            "threshold_calibrated": self._threshold_calibrated,
            "buffer_fill": 1.0,
        }

    def _auto_train(self):
        """
        Train on synthetic calm-market data that matches the SCALED feature distribution.

        After scaling, each feature lives in roughly [-1, 1].
        We generate AR(1) sequences with that same range so the model
        learns to reconstruct the temporal structure of normal market data.
        """
        self.model.train()
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.001)

        np.random.seed(42)
        n_sequences = 400

        # Each sequence is 4 feature types × 15 assets, all in scaled space.
        # Returns/vol/max: AR(1) with std ~ 0.5 (normal market has ~0.5 after scaling)
        # Mean return:    AR(1) with std ~ 0.3 (tends to be smaller)
        data = np.zeros((n_sequences, self.seq_length, self.input_dim), dtype=np.float32)
        for seq_idx in range(n_sequences):
            for asset_idx in range(15):
                for feat_slot in range(4):
                    col = asset_idx * 4 + feat_slot
                    phi = 0.7 + 0.2 * np.random.random()  # AR persistence 0.7–0.9
                    # Targets ~unit variance in scaled space
                    target_std = 0.4 if feat_slot == 2 else 0.6  # mean_ret is tighter
                    noise_scale = target_std * np.sqrt(1.0 - phi ** 2)
                    x = 0.0
                    for t in range(self.seq_length):
                        x = phi * x + np.random.normal(0.0, noise_scale)
                        # vol and max_abs_ret are always positive: clip to [0, ∞)
                        if feat_slot in (1, 3):
                            x = abs(x)
                        data[seq_idx, t, col] = x

        dataset = torch.FloatTensor(data).to(self.device)

        # Train in mini-batches for stability
        batch_size = 32
        n_epochs = 80
        for epoch in range(n_epochs):
            idx = np.random.permutation(n_sequences)
            for start in range(0, n_sequences, batch_size):
                batch = dataset[idx[start:start + batch_size]]
                optimizer.zero_grad()
                output = self.model(batch)
                loss = nn.MSELoss()(output, batch)
                loss.backward()
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
                optimizer.step()

        self.model.eval()
        self.is_fitted = True

        # Set a preliminary threshold from training data.
        # This will be REPLACED by the adaptive calibration after WARMUP_TICKS real ticks.
        with torch.no_grad():
            output = self.model(dataset)
            mse_values = torch.mean((dataset - output) ** 2, dim=(1, 2)).cpu().numpy()
            self.threshold = float(np.percentile(mse_values, 90)) * 3.0
            self.threshold = max(self.threshold, 1e-6)

    def save(self, path: str = None):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        torch.save({
            "model_state_dict": self.model.state_dict(),
            "threshold": self.threshold,
            "threshold_calibrated": self._threshold_calibrated,
        }, path or MODEL_PATH)

    def load(self, path: str = None):
        p = path or MODEL_PATH
        if os.path.exists(p):
            checkpoint = torch.load(p, map_location=self.device, weights_only=False)
            self.model.load_state_dict(checkpoint["model_state_dict"])
            self.threshold = checkpoint.get("threshold", 1.0)
            self._threshold_calibrated = checkpoint.get("threshold_calibrated", False)
            self.model.eval()
            self.is_fitted = True
            return True
        return False


# Singleton
temporal_detector = TemporalAnomalyDetector()
