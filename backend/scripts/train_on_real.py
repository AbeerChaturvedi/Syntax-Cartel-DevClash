"""
Train the Isolation Forest and LSTM Autoencoder on REAL calm-market data
instead of the fabricated synthetic distributions in each model's
`_auto_train()`.

Method (train == serve == backtest):
  · Replay real daily CSVs (scripts/fetch_historical.py) through the SAME
    HistoricalReplay + StateBuilder the live pipeline and backtest use, so
    the 60-dim feature vectors are at the identical tick scale.
  · Only CALM windows are used for training (labeled crisis spans from
    backtesting/historical_crises.py are excluded). Window start is 2018+
    so all 15 assets — including ETH — actually exist.
  · Fit IF on the real vectors; train the LSTM autoencoder to reconstruct
    real calm sequences; then persist BOTH via the checkpoint manager into
    data/checkpoints/current/, which the runtime warm-starts from.

Usage:  python scripts/train_on_real.py
"""
import os
import sys
import asyncio
from datetime import date, datetime, timedelta

import numpy as np
import torch
import torch.nn as nn

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
sys.path.insert(0, _BACKEND)
from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, "..", ".env"))

from ingestion.replay import HistoricalReplay          # noqa: E402
from features.state_builder import StateBuilder          # noqa: E402
from models.isolation_forest import anomaly_detector_if  # noqa: E402
from models.lstm_autoencoder import temporal_detector, _scale  # noqa: E402
from backtesting.historical_crises import HISTORICAL_CRISES     # noqa: E402
from utils.model_persistence import get_checkpoint_manager      # noqa: E402

TRAIN_START = "2018-03-01"          # all 15 assets exist from here
TRAIN_END = date.today().isoformat()
WARMUP_SKIP = 20                    # drop each window's leading warmup ticks
MAX_LSTM_SEQUENCES = 2500           # cap for CPU-friendly training
LSTM_EPOCHS = 30

np.random.seed(42)
torch.manual_seed(42)


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def calm_windows(start: str, end: str):
    """Return calm [start,end] sub-ranges = [start,end] minus every crisis
    [lookback_start, window_end] span."""
    lo, hi = _d(start), _d(end)
    crises = sorted((_d(c.lookback_start), _d(c.window_end)) for c in HISTORICAL_CRISES)
    out, cur = [], lo
    for cs, ce in crises:
        if ce < lo or cs > hi:
            continue
        cs, ce = max(cs, lo), min(ce, hi)
        if cs > cur:
            out.append((cur, cs - timedelta(days=1)))
        cur = max(cur, ce + timedelta(days=1))
    if cur < hi:
        out.append((cur, hi))
    return [(s.isoformat(), e.isoformat()) for s, e in out if s < e]


async def collect_window(ws: str, we: str):
    """Replay one calm window; return list of 60-dim state vectors."""
    replay = HistoricalReplay()
    n = replay.load_window(ws, we)
    if n == 0:
        return []
    sb = StateBuilder()
    vecs = []

    async def on_tick(tick):
        sb.ingest(tick)
        vecs.append(sb.get_state_vector())

    replay._running = True
    replay._speed_multiplier = 1e12          # no wall-clock sleeps
    await replay._run(on_tick)
    return vecs[WARMUP_SKIP:] if len(vecs) > WARMUP_SKIP else []


async def gather_data():
    windows = calm_windows(TRAIN_START, TRAIN_END)
    print(f"Calm training windows ({len(windows)}):")
    for ws, we in windows:
        print(f"  {ws} → {we}")

    all_vecs, seqs = [], []
    seq_len = temporal_detector.seq_length
    for ws, we in windows:
        vecs = await collect_window(ws, we)
        if not vecs:
            continue
        all_vecs.extend(vecs)
        # overlapping length-seq_len sequences of RAW vectors WITHIN this window
        # (normalized later, once the fitted normalizer is known)
        for i in range(0, len(vecs) - seq_len + 1, 2):   # stride 2 to thin overlap
            seqs.append(np.stack(vecs[i:i + seq_len]).astype(np.float32))
        print(f"    {ws}: {len(vecs)} vectors, running seq total={len(seqs)}")
    return np.array(all_vecs, dtype=np.float32), seqs


def train_lstm(sequences: np.ndarray):
    m = temporal_detector.model
    dev = temporal_detector.device
    m.train()
    opt = torch.optim.Adam(m.parameters(), lr=1e-3)
    data = torch.FloatTensor(sequences).to(dev)
    N, bs = len(sequences), 64
    for ep in range(LSTM_EPOCHS):
        idx = np.random.permutation(N)
        tot = 0.0
        for s in range(0, N, bs):
            b = data[idx[s:s + bs]]
            opt.zero_grad()
            loss = nn.MSELoss()(m(b), b)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(m.parameters(), 1.0)
            opt.step()
            tot += loss.item() * len(b)
        if ep % 5 == 0 or ep == LSTM_EPOCHS - 1:
            print(f"    LSTM epoch {ep:2d}/{LSTM_EPOCHS}  train MSE={tot / N:.6f}")
    m.eval()
    temporal_detector.is_fitted = True
    with torch.no_grad():
        mses = torch.mean((data - m(data)) ** 2, dim=(1, 2)).cpu().numpy()
    # Prior threshold; adaptive calibration re-fits on the first 200 live/replay ticks
    temporal_detector.threshold = max(float(np.percentile(mses, 90)) * 3.0, 1e-6)
    temporal_detector._threshold_calibrated = False
    temporal_detector._tick_count = 0
    temporal_detector._warmup_mses = []
    print(f"    LSTM prior threshold={temporal_detector.threshold:.6f}")


def main():
    vecs, seqs = asyncio.run(gather_data())
    print(f"\nCollected {len(vecs)} feature vectors, {len(seqs)} sequences.")
    if len(vecs) < 100 or len(seqs) < 50:
        print("ERROR: not enough data — did fetch_historical.py run?")
        sys.exit(1)

    # ── Isolation Forest on real vectors ──────────────────────────────
    print("\nTraining Isolation Forest on real calm vectors...")
    anomaly_detector_if.train(vecs)
    print(f"  IF fitted: contamination={anomaly_detector_if.model.contamination}, "
          f"n_estimators={anomaly_detector_if.model.n_estimators}")

    # ── LSTM autoencoder on real sequences ────────────────────────────
    # Fit the data-driven normalizer on real calm vectors, then normalize
    # each sequence with it (replaces the miscalibrated fixed feature scales).
    temporal_detector.fit_normalizer(vecs)
    print(f"\nFitted LSTM normalizer: mean|std ranges "
          f"[{temporal_detector._norm_mean.min():.2e},{temporal_detector._norm_mean.max():.2e}] | "
          f"[{temporal_detector._norm_std.min():.2e},{temporal_detector._norm_std.max():.2e}]")
    if len(seqs) > MAX_LSTM_SEQUENCES:
        pick = np.random.choice(len(seqs), MAX_LSTM_SEQUENCES, replace=False)
        seqs = [seqs[i] for i in pick]
    norm_seqs = np.stack([
        np.stack([temporal_detector._normalize(v) for v in seq]) for seq in seqs
    ]).astype(np.float32)
    print(f"Training LSTM autoencoder on {len(norm_seqs)} real sequences "
          f"(seq_len={temporal_detector.seq_length})...")
    train_lstm(norm_seqs)

    # ── Persist as the runtime's warm-start checkpoint ────────────────
    print("\nSaving checkpoint (data/checkpoints/current/)...")
    res = get_checkpoint_manager().save()
    print(f"  checkpoint: {res}")
    print("\nDone. IF + LSTM now trained on REAL calm-market data.")


if __name__ == "__main__":
    main()
