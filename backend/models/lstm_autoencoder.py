"""
LSTM Autoencoder — Temporal Anomaly Detector
Detects sequential pattern deviations in market time series.
Uses reconstruction error as anomaly signal.
"""
import numpy as np
import torch
import torch.nn as nn
import os
from collections import deque

MODEL_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "models", "lstm_autoencoder.pt")


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
        # Encode
        enc1, _ = self.encoder_lstm1(x)
        enc2, _ = self.encoder_lstm2(enc1)

        # Decode
        dec1, _ = self.decoder_lstm1(enc2)
        dec2, _ = self.decoder_lstm2(dec1)

        return dec2


class TemporalAnomalyDetector:
    """
    Wraps LSTM Autoencoder for anomaly detection via reconstruction error.
    Higher reconstruction error = more anomalous.
    """

    def __init__(self, input_dim: int = 60, seq_length: int = 20):
        self.input_dim = input_dim
        self.seq_length = seq_length
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = LSTMAutoencoder(input_dim=input_dim).to(self.device)
        self.model.eval()

        self.is_fitted = False
        self.threshold = 0.1  # MSE threshold for anomaly
        self._buffer = deque(maxlen=seq_length * 2)  # Accumulate state vectors
        self._mse_history = deque(maxlen=500)  # Track MSE for adaptive thresholding

    def add_to_buffer(self, state_vector: np.ndarray):
        """Add a state vector to the temporal buffer."""
        clean = np.nan_to_num(state_vector, nan=0.0, posinf=0.0, neginf=0.0)
        self._buffer.append(clean)

    def predict(self) -> float:
        """
        Compute anomaly score from current buffer.
        Returns score in [0, 1]. Higher = more anomalous.
        """
        if len(self._buffer) < self.seq_length:
            return 0.0  # Not enough data yet

        if not self.is_fitted:
            self._auto_train()

        # Get last seq_length vectors (deque doesn't support slicing in Python 3.14+)
        buf_list = list(self._buffer)
        sequence = np.array(buf_list[-self.seq_length:], dtype=np.float32)
        x = torch.FloatTensor(sequence).unsqueeze(0).to(self.device)  # [1, seq, features]

        with torch.no_grad():
            reconstruction = self.model(x)
            mse = torch.mean((x - reconstruction) ** 2).item()

        # Track MSE for adaptive thresholding
        self._mse_history.append(mse)

        # Use FIXED threshold from training (don't adapt — that causes score=0 always)
        # Adaptive threshold tracks recent MSE too closely, normalizing everything to 0.
        # The training threshold represents "normal reconstruction error".
        
        # Score: how does current MSE compare to training baseline?
        if self.threshold > 0:
            ratio = mse / self.threshold
            # Gentler sigmoid: ratio=0.5 → ~0.15, ratio=1.0 → ~0.5, ratio=2.0 → ~0.85
            anomaly_score = 1.0 / (1.0 + np.exp(-3 * (ratio - 0.8)))
        else:
            anomaly_score = 0.0

        return float(np.clip(anomaly_score, 0, 1))

    def predict_batch(self, sequences: np.ndarray) -> np.ndarray:
        """Batch prediction for multiple sequences."""
        if not self.is_fitted:
            self._auto_train()

        x = torch.FloatTensor(sequences).to(self.device)
        with torch.no_grad():
            reconstruction = self.model(x)
            mse_per_sample = torch.mean((x - reconstruction) ** 2, dim=(1, 2)).cpu().numpy()

        scores = 1.0 / (1.0 + np.exp(-5 * (mse_per_sample / max(self.threshold, 1e-8) - 1)))
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
            "buffer_fill": 1.0,
        }

    def _auto_train(self):
        """Train on synthetic calm-market data with realistic temporal structure.
        
        Key insight: iid noise trains the model to output zeros (trivial reconstruction).
        Instead, we generate smoothly auto-correlated sequences that the model learns
        as "normal". Real market data will produce non-trivial reconstruction error,
        enabling actual anomaly detection.
        """
        self.model.train()
        optimizer = torch.optim.Adam(self.model.parameters(), lr=0.002)

        np.random.seed(42)
        n_sequences = 300

        # Generate structured temporal sequences (not iid noise!)
        data = np.zeros((n_sequences, self.seq_length, self.input_dim), dtype=np.float32)
        for seq_idx in range(n_sequences):
            for feat_idx in range(self.input_dim):
                # AR(1) process with momentum: x_t = phi * x_{t-1} + eps
                phi = 0.85 + 0.1 * np.random.random()  # persistence
                noise_scale = 0.003 + 0.002 * np.random.random()
                x = 0.0
                for t in range(self.seq_length):
                    x = phi * x + np.random.normal(0, noise_scale)
                    data[seq_idx, t, feat_idx] = x

        dataset = torch.FloatTensor(data).to(self.device)

        # Train for 50 epochs — enough to learn temporal structure
        for epoch in range(50):
            optimizer.zero_grad()
            output = self.model(dataset)
            loss = nn.MSELoss()(output, dataset)
            loss.backward()
            optimizer.step()

        self.model.eval()
        self.is_fitted = True

        # Compute threshold from training data — 95th percentile of MSE
        with torch.no_grad():
            output = self.model(dataset)
            mse_values = torch.mean((dataset - output) ** 2, dim=(1, 2)).cpu().numpy()
            self.threshold = float(np.percentile(mse_values, 95))
            # Ensure threshold is not near-zero (safety floor)
            self.threshold = max(self.threshold, 1e-6)

    def save(self, path: str = None):
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        torch.save({
            'model_state_dict': self.model.state_dict(),
            'threshold': self.threshold,
        }, path or MODEL_PATH)

    def load(self, path: str = None):
        p = path or MODEL_PATH
        if os.path.exists(p):
            checkpoint = torch.load(p, map_location=self.device)
            self.model.load_state_dict(checkpoint['model_state_dict'])
            self.threshold = checkpoint.get('threshold', 0.1)
            self.model.eval()
            self.is_fitted = True
            return True
        return False


# Singleton
temporal_detector = TemporalAnomalyDetector()
