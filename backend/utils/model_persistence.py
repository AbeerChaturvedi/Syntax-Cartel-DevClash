"""
Unified model persistence: atomic checkpoint + warm-start for the full
ensemble (IF, LSTM, CISS CDF buffers, Merton vol buffers, copula
residuals, watermark state).

Why we need this:
    · Cold-starting IF + LSTM takes ~30s each time the pod restarts.
    · CDF buffers in CISS and copula take ~500 ticks (2 minutes @4Hz)
      to warm, during which stress scores are meaningless.
    · In production, pod restarts for deploys, rescheduling, OOM
      protection, etc.  Users shouldn't see a 2-minute dead zone.

Strategy:
    · Each stateful object exposes `__getstate__` / `__setstate__` or
      is handled explicitly here.
    · Writes go to a temp file inside the checkpoint dir, then rename
      atomically — so a partial write cannot corrupt the checkpoint.
    · A manifest.json records sizes, timestamps, and a version tag so
      we can refuse to load a checkpoint from an incompatible schema.
"""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict, Any

import numpy as np


CHECKPOINT_VERSION = "v3.0"


class CheckpointManager:
    """Atomic checkpoint manager for the full ensemble state."""

    def __init__(self, checkpoint_dir: str):
        self.dir = Path(checkpoint_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

    # ── save ────────────────────────────────────────────────────────
    def save(self) -> Dict[str, Any]:
        """Snapshot all stateful components atomically."""
        tmp = Path(tempfile.mkdtemp(prefix="velure_ckpt_", dir=str(self.dir)))
        try:
            manifest = {
                "version": CHECKPOINT_VERSION,
                "created_ts": time.time(),
                "components": [],
            }

            self._save_isolation_forest(tmp, manifest)
            self._save_lstm_autoencoder(tmp, manifest)
            self._save_ciss(tmp, manifest)
            self._save_merton(tmp, manifest)
            self._save_copula(tmp, manifest)

            # Write manifest last; readers check manifest existence as "ready"
            (tmp / "manifest.json").write_text(json.dumps(manifest, indent=2))

            # Atomically promote temp dir to `current`
            final = self.dir / "current"
            if final.exists():
                # Keep one backup
                backup = self.dir / "previous"
                if backup.exists():
                    shutil.rmtree(backup)
                final.rename(backup)
            tmp.rename(final)
            return {"ok": True, "path": str(final), "manifest": manifest}

        except Exception as e:
            # Clean up temp on failure; never corrupt `current`
            shutil.rmtree(tmp, ignore_errors=True)
            raise RuntimeError(f"Checkpoint save failed: {e}") from e

    # ── load ────────────────────────────────────────────────────────
    def load(self) -> Dict[str, Any]:
        """Restore state from the latest `current` checkpoint."""
        src = self.dir / "current"
        manifest_path = src / "manifest.json"
        if not manifest_path.exists():
            return {"ok": False, "reason": "no checkpoint"}

        manifest = json.loads(manifest_path.read_text())
        if manifest.get("version") != CHECKPOINT_VERSION:
            return {"ok": False, "reason": f"version mismatch: {manifest.get('version')}"}

        results = {}
        results["isolation_forest"] = self._load_isolation_forest(src)
        results["lstm_autoencoder"] = self._load_lstm_autoencoder(src)
        results["ciss"] = self._load_ciss(src)
        results["merton"] = self._load_merton(src)
        results["copula"] = self._load_copula(src)

        return {"ok": True, "manifest": manifest, "components": results}

    # ── per-component ──────────────────────────────────────────────
    def _save_isolation_forest(self, tmp: Path, manifest: dict):
        try:
            from models.isolation_forest import anomaly_detector_if
            import joblib
            joblib.dump(anomaly_detector_if.model, tmp / "if_model.pkl")
            joblib.dump(anomaly_detector_if.scaler, tmp / "if_scaler.pkl")
            manifest["components"].append({
                "name": "isolation_forest",
                "files": ["if_model.pkl", "if_scaler.pkl"],
                "fitted": anomaly_detector_if.is_fitted,
            })
        except Exception as e:
            manifest["components"].append({"name": "isolation_forest", "error": str(e)})

    def _load_isolation_forest(self, src: Path) -> bool:
        try:
            from models.isolation_forest import anomaly_detector_if
            import joblib
            mp = src / "if_model.pkl"
            sp = src / "if_scaler.pkl"
            if not (mp.exists() and sp.exists()):
                return False
            anomaly_detector_if.model = joblib.load(mp)
            anomaly_detector_if.scaler = joblib.load(sp)
            anomaly_detector_if.is_fitted = True
            return True
        except Exception:
            return False

    def _save_lstm_autoencoder(self, tmp: Path, manifest: dict):
        try:
            import torch
            from models.lstm_autoencoder import temporal_detector
            torch.save({
                "model_state_dict": temporal_detector.model.state_dict(),
                "threshold": float(temporal_detector.threshold),
                "mse_history": list(temporal_detector._mse_history)[-500:],
            }, tmp / "lstm_autoencoder.pt")
            manifest["components"].append({
                "name": "lstm_autoencoder",
                "files": ["lstm_autoencoder.pt"],
                "fitted": temporal_detector.is_fitted,
            })
        except Exception as e:
            manifest["components"].append({"name": "lstm_autoencoder", "error": str(e)})

    def _load_lstm_autoencoder(self, src: Path) -> bool:
        try:
            import torch
            from models.lstm_autoencoder import temporal_detector
            p = src / "lstm_autoencoder.pt"
            if not p.exists():
                return False
            ckpt = torch.load(p, map_location=temporal_detector.device)
            temporal_detector.model.load_state_dict(ckpt["model_state_dict"])
            temporal_detector.threshold = float(ckpt.get("threshold", 0.1))
            temporal_detector._mse_history = list(ckpt.get("mse_history", []))
            temporal_detector.model.eval()
            temporal_detector.is_fitted = True
            return True
        except Exception:
            return False

    def _save_ciss(self, tmp: Path, manifest: dict):
        try:
            from models.ciss_scorer import ciss_scorer
            payload = {
                seg: np.asarray(list(buf), dtype=np.float64)
                for seg, buf in ciss_scorer.segment_buffers.items()
            }
            payload["_score_history"] = np.asarray(list(ciss_scorer._score_history), dtype=np.float64)
            np.savez(tmp / "ciss_buffers.npz", **payload)
            manifest["components"].append({
                "name": "ciss",
                "files": ["ciss_buffers.npz"],
                "min_len": min(len(b) for b in ciss_scorer.segment_buffers.values()),
            })
        except Exception as e:
            manifest["components"].append({"name": "ciss", "error": str(e)})

    def _load_ciss(self, src: Path) -> bool:
        try:
            from models.ciss_scorer import ciss_scorer
            from collections import deque
            p = src / "ciss_buffers.npz"
            if not p.exists():
                return False
            data = np.load(p)
            for seg, buf in ciss_scorer.segment_buffers.items():
                if seg in data:
                    arr = data[seg].tolist()
                    ciss_scorer.segment_buffers[seg] = deque(arr, maxlen=buf.maxlen)
            if "_score_history" in data:
                ciss_scorer._score_history = deque(
                    data["_score_history"].tolist(),
                    maxlen=ciss_scorer._score_history.maxlen,
                )
            return True
        except Exception:
            return False

    def _save_merton(self, tmp: Path, manifest: dict):
        try:
            from models.merton_model import merton_model
            payload = {}
            for ticker, buf in merton_model._vol_buffers.items():
                payload[f"vol_{ticker}"] = np.asarray(list(buf), dtype=np.float64)
            for ticker, buf in merton_model._price_buffers.items():
                payload[f"price_{ticker}"] = np.asarray(list(buf), dtype=np.float64)
            np.savez(tmp / "merton_buffers.npz", **payload)
            manifest["components"].append({"name": "merton", "files": ["merton_buffers.npz"]})
        except Exception as e:
            manifest["components"].append({"name": "merton", "error": str(e)})

    def _load_merton(self, src: Path) -> bool:
        try:
            from models.merton_model import merton_model
            from collections import deque
            p = src / "merton_buffers.npz"
            if not p.exists():
                return False
            data = np.load(p)
            for ticker, buf in merton_model._vol_buffers.items():
                key = f"vol_{ticker}"
                if key in data:
                    merton_model._vol_buffers[ticker] = deque(data[key].tolist(), maxlen=buf.maxlen)
            for ticker, buf in merton_model._price_buffers.items():
                key = f"price_{ticker}"
                if key in data:
                    merton_model._price_buffers[ticker] = deque(data[key].tolist(), maxlen=buf.maxlen)
            return True
        except Exception:
            return False

    def _save_copula(self, tmp: Path, manifest: dict):
        try:
            from models.copula_model import copula_model
            payload = {}
            for seg, buf in copula_model._residuals.items():
                payload[f"resid_{seg}"] = np.asarray(list(buf), dtype=np.float64)
            payload["nu"] = np.asarray([copula_model._nu])
            payload["rho"] = copula_model._rho
            payload["lambda_L"] = copula_model._lambda_L
            np.savez(tmp / "copula_state.npz", **payload)
            manifest["components"].append({
                "name": "copula",
                "files": ["copula_state.npz"],
                "warm": copula_model._warm,
            })
        except Exception as e:
            manifest["components"].append({"name": "copula", "error": str(e)})

    def _load_copula(self, src: Path) -> bool:
        try:
            from models.copula_model import copula_model
            from collections import deque
            p = src / "copula_state.npz"
            if not p.exists():
                return False
            data = np.load(p)
            for seg, buf in copula_model._residuals.items():
                key = f"resid_{seg}"
                if key in data:
                    copula_model._residuals[seg] = deque(data[key].tolist(), maxlen=buf.maxlen)
            if "nu" in data:
                copula_model._nu = float(data["nu"][0])
            if "rho" in data:
                copula_model._rho = data["rho"]
            if "lambda_L" in data:
                copula_model._lambda_L = data["lambda_L"]
            min_len = min(len(b) for b in copula_model._residuals.values())
            copula_model._warm = min_len >= 50
            return True
        except Exception:
            return False


# Singleton configured via env var (utils.config reads MODEL_CHECKPOINT_DIR)
def get_checkpoint_manager() -> CheckpointManager:
    from utils.config import MODEL_CHECKPOINT_DIR
    return CheckpointManager(MODEL_CHECKPOINT_DIR)
