"""
Ensemble Orchestrator — Combines all models into a unified scoring pipeline.
Implements micro-batch inference with weighted ensemble scoring.
"""
import numpy as np
import asyncio
import time
from typing import Dict, List, Optional
from collections import deque

from models.isolation_forest import anomaly_detector_if
from models.lstm_autoencoder import temporal_detector
from models.ciss_scorer import ciss_scorer
from models.merton_model import merton_model
from models.var_calculator import var_calculator
from models.copula_model import copula_model
from utils.config import (
    ENSEMBLE_IF_WEIGHT,
    ENSEMBLE_LSTM_WEIGHT,
    ENSEMBLE_CISS_WEIGHT,
    ENSEMBLE_COPULA_WEIGHT,
)


class EnsembleOrchestrator:
    """
    Orchestrates all ML models in a micro-batch pipeline.
    
    Flow:
        1. Accumulate state vectors in buffer
        2. Every N ticks or T milliseconds, flush the batch
        3. Run IF (global anomaly) + LSTM (temporal anomaly)
        4. Compute CISS (systemic stress) + Merton (default probability)
        5. Weight and combine into final risk scores
        6. Return unified dashboard payload
    """

    def __init__(self, batch_size: int = 10, flush_interval_ms: int = 500):
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self._batch_buffer: List[dict] = []
        self._last_flush = time.time()
        self._latest_scores: Dict = {}
        self._alert_history: deque = deque(maxlen=100)
        
        # Ensemble weights — pulled from config so .env tuning applies
        self.if_weight = ENSEMBLE_IF_WEIGHT
        self.lstm_weight = ENSEMBLE_LSTM_WEIGHT
        self.ciss_weight = ENSEMBLE_CISS_WEIGHT
        self.copula_weight = ENSEMBLE_COPULA_WEIGHT

        # Alert thresholds
        self.ALERT_THRESHOLDS = {
            "LOW": 0.3,
            "MEDIUM": 0.5,
            "HIGH": 0.7,
            "CRITICAL": 0.85,
        }

    async def process_tick(self, tick_data: dict) -> Optional[Dict]:
        """
        Process a single market tick.
        Buffers data and returns scores when batch is ready.
        """
        self._batch_buffer.append(tick_data)
        
        now = time.time()
        elapsed_ms = (now - self._last_flush) * 1000
        
        # Flush on batch size OR time interval (whichever comes first)
        if len(self._batch_buffer) >= self.batch_size or elapsed_ms >= self.flush_interval_ms:
            return await self._flush_batch()
        
        return None

    async def _flush_batch(self) -> Dict:
        """Process accumulated batch through all models."""
        if not self._batch_buffer:
            return self._latest_scores

        # Use latest tick for current state
        latest_tick = self._batch_buffer[-1]
        assets = latest_tick.get("assets", {})

        # 1. Isolation Forest — global anomaly detection
        from ingestion.simulator import simulator
        state_vector = simulator.get_state_vector()
        try:
            if_score = anomaly_detector_if.predict(state_vector)
        except Exception:
            if_score = 0.0

        # 2. LSTM Autoencoder — temporal anomaly detection
        try:
            temporal_detector.add_to_buffer(state_vector)
            lstm_score = temporal_detector.predict()
        except Exception:
            lstm_score = 0.0

        # 3. CISS — systemic stress index
        try:
            ciss_score_val = ciss_scorer.update(latest_tick)
        except Exception:
            ciss_score_val = 0.0

        # 4. Merton — distance to default for institutions
        try:
            merton_results = merton_model.compute_all(assets)
        except Exception:
            merton_results = []

        # 4b. t-Copula tail dependence — cross-segment contagion signal
        try:
            copula_snap = copula_model.update(assets)
        except Exception:
            copula_snap = {"warmup": True, "avg_tail_dependence": 0.0, "max_tail_dependence": 0.0}
        # Derive a [0,1] copula score from max tail-dependence (most concerning pair).
        copula_score = float(copula_snap.get("max_tail_dependence", 0.0) or 0.0)

        # 5. Weighted ensemble
        combined_anomaly = (
            self.if_weight * if_score +
            self.lstm_weight * lstm_score +
            self.ciss_weight * ciss_score_val +
            self.copula_weight * copula_score
        )

        # 6. Determine alert level
        severity = "NORMAL"
        for level, threshold in sorted(self.ALERT_THRESHOLDS.items(), key=lambda x: x[1], reverse=True):
            if combined_anomaly >= threshold:
                severity = level
                break

        # 7. Generate alert if needed
        alert = None
        if severity in ("HIGH", "CRITICAL"):
            alert = {
                "type": "SYSTEMIC_STRESS",
                "severity": severity,
                "score": round(combined_anomaly, 4),
                "timestamp": latest_tick.get("timestamp", ""),
                "message": f"Systemic stress detected: combined score {combined_anomaly:.2%}",
                "components": {
                    "isolation_forest": round(if_score, 4),
                    "lstm_reconstruction": round(lstm_score, 4),
                    "ciss": round(ciss_score_val, 4),
                    "copula_tail": round(copula_score, 4),
                },
            }
            self._alert_history.append(alert)
            # v3: dispatch to external sinks (Slack/Discord/PagerDuty/webhook/SMTP).
            # Fire-and-forget: we don't want a slow webhook blocking the pipeline.
            try:
                from utils.alerting import alert_dispatcher
                asyncio.create_task(alert_dispatcher.dispatch(alert))
            except Exception:
                pass

        # 8. Feature importance for explainability
        feature_importance = anomaly_detector_if.get_feature_importance(state_vector)

        # 9. Compute aggregate SRISK
        total_srisk = sum(m.get("srisk_bn", 0) for m in merton_results)

        # 10. VaR/CVaR computation
        try:
            var_metrics = var_calculator.update(assets)
        except Exception:
            var_metrics = {}

        # 11. Build dashboard payload
        self._latest_scores = {
            "timestamp": latest_tick.get("timestamp", ""),
            "epoch_ms": latest_tick.get("epoch_ms", 0),
            "tick_id": latest_tick.get("tick_id", 0),
            "crisis_mode": latest_tick.get("crisis_mode", False),

            # Core scores
            "scores": {
                "isolation_forest": round(if_score, 6),
                "lstm_autoencoder": round(lstm_score, 6),
                "ciss": round(ciss_score_val, 6),
                "copula_tail": round(copula_score, 6),
                "combined_anomaly": round(combined_anomaly, 6),
                "severity": severity,
            },
            # Copula snapshot — tail dependence matrix + joint-crash prob
            "copula": copula_snap,

            # Asset prices (simplified for WS payload)
            "assets": {
                ticker: {
                    "price": data.get("price", 0),
                    "pct_change": data.get("pct_change", 0),
                    "volume": data.get("volume", 0),
                    "spread_bps": data.get("spread_bps", 0),
                    "rolling_volatility": data.get("rolling_volatility", 0),
                    "asset_class": data.get("asset_class", ""),
                }
                for ticker, data in assets.items()
            },

            # Cross-asset correlation
            "avg_correlation": latest_tick.get("avg_correlation", 0),
            "correlation_matrix": latest_tick.get("correlation_matrix", []),

            # Merton results
            "merton": merton_results,

            # Aggregate SRISK
            "system_srisk": {
                "total_bn": round(total_srisk, 2),
                "status": "CRITICAL" if total_srisk > 50 else "WARNING" if total_srisk > 20 else "ELEVATED" if total_srisk > 5 else "HEALTHY",
            },

            # VaR/CVaR risk metrics
            "var_metrics": var_metrics,

            # Current alert
            "alert": alert,

            # CISS breakdown for explainability
            "ciss_breakdown": ciss_scorer.get_breakdown(),

            # Feature importance
            "feature_importance": feature_importance,

            # Recent alerts
            "recent_alerts": list(self._alert_history)[-10:],
        }

        # Reset batch
        self._batch_buffer = []
        self._last_flush = time.time()

        return self._latest_scores

    def get_latest_scores(self) -> Dict:
        """Return the most recent computed scores."""
        return self._latest_scores


# Singleton
ensemble = EnsembleOrchestrator()
