"""
Rolling-window backtest harness.

Streams labeled historical data through the *live* ensemble and scores
the resulting sequence against the known crisis label.  Outputs:
    · ROC curve (fpr, tpr)
    · AUC
    · Lead time: days between first HIGH/CRITICAL alert and
      `trigger_date` (negative = model is late)
    · False-positive rate before the window starts

Design:
    · The harness runs the *actual shipping ensemble*, not a shadow
      model.  This means a passing backtest is evidence the production
      code works — not just the research code.
    · Runs are async-friendly so the FastAPI event loop isn't blocked;
      caller awaits the task.
    · Results cached on disk for fast retrieval.
"""
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np

from backtesting.historical_crises import HISTORICAL_CRISES, CrisisWindow, get_by_name
from ingestion.replay import HistoricalReplay
from models.ensemble import ensemble
from utils.config import REPLAY_DATA_DIR
from utils.logger import pipeline_log


RESULTS_PATH = Path(REPLAY_DATA_DIR).parent / "backtest_results.json"


class BacktestHarness:
    """Runs the live ensemble against labeled crisis windows."""

    def __init__(self):
        self._last_results: Dict = {}
        self._running = False

    async def run(self, crisis_names: Optional[List[str]] = None, speed_multiplier: float = 5000.0) -> Dict:
        """Backtest against one or more crisis windows.  Blocks until done."""
        if self._running:
            return {"ok": False, "reason": "backtest already running"}
        self._running = True

        try:
            windows = self._select_windows(crisis_names)
            results = []
            for w in windows:
                pipeline_log.info(f"backtest: starting {w.name}")
                r = await self._run_single(w, speed_multiplier=speed_multiplier)
                results.append(r)

            summary = self._summarize(results)
            out = {
                "ok": True,
                "completed_at": time.time(),
                "speed_multiplier": speed_multiplier,
                "per_crisis": results,
                "summary": summary,
            }
            self._last_results = out
            try:
                RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
                RESULTS_PATH.write_text(json.dumps(out, indent=2, default=str))
            except Exception as e:
                pipeline_log.warning(f"backtest: failed to persist results: {e}")
            return out

        finally:
            self._running = False

    def latest(self) -> Dict:
        if self._last_results:
            return self._last_results
        if RESULTS_PATH.exists():
            try:
                return json.loads(RESULTS_PATH.read_text())
            except Exception:
                pass
        return {"ok": False, "reason": "no backtest has been run"}

    def status(self) -> Dict:
        return {"running": self._running, "has_results": bool(self._last_results) or RESULTS_PATH.exists()}

    # ── per-crisis execution ───────────────────────────────────────
    async def _run_single(self, crisis: CrisisWindow, speed_multiplier: float) -> Dict:
        replay = HistoricalReplay()
        frames_loaded = replay.load_window(
            start_date=crisis.lookback_start,
            end_date=crisis.window_end,
        )
        if frames_loaded == 0:
            return {
                "name": crisis.name,
                "ok": False,
                "reason": "no historical data available in data/historical/ for this window",
            }

        # Collect date-indexed scores + labels
        per_date_scores: Dict[str, float] = {}
        per_date_labels: Dict[str, int] = {}
        first_alert_date: Optional[str] = None

        async def on_tick(tick: dict):
            nonlocal first_alert_date
            # Run full ensemble inference
            result = await ensemble.process_tick(tick)
            if not result:
                return
            d = tick.get("replay_date")
            if not d:
                return
            score = (result.get("scores") or {}).get("combined_anomaly", 0.0)
            # Keep the *max* score per day (the model's strongest signal that day)
            prev = per_date_scores.get(d, 0.0)
            per_date_scores[d] = max(prev, float(score))
            # Label: 1 if inside crisis window
            per_date_labels[d] = 1 if crisis.window_start <= d <= crisis.window_end else 0
            # First HIGH alert date
            sev = (result.get("scores") or {}).get("severity", "NORMAL")
            if first_alert_date is None and sev in ("HIGH", "CRITICAL"):
                first_alert_date = d

        await replay.start(on_tick, speed_multiplier=speed_multiplier)
        # Poll until replay completes
        while replay.status()["running"]:
            await asyncio.sleep(0.2)
        await replay.stop()

        # Compute ROC/AUC
        if not per_date_scores:
            return {"name": crisis.name, "ok": False, "reason": "no scores produced"}

        dates = sorted(per_date_scores.keys())
        scores = np.array([per_date_scores[d] for d in dates], dtype=np.float64)
        labels = np.array([per_date_labels[d] for d in dates], dtype=np.int32)

        fpr, tpr, thr = _roc_curve(labels, scores)
        auc = _auc(fpr, tpr)

        # Lead time: trigger_date minus first alert (positive = ahead of event)
        lead_days: Optional[int] = None
        if first_alert_date is not None:
            try:
                import datetime as _dt
                d1 = _dt.date.fromisoformat(crisis.trigger_date)
                d2 = _dt.date.fromisoformat(first_alert_date)
                lead_days = (d1 - d2).days
            except Exception:
                pass

        # False-positive rate in the pre-window period
        pre_mask = np.array([d < crisis.window_start for d in dates])
        alerts_pre = np.sum(scores[pre_mask] > 0.7) if pre_mask.any() else 0
        fpr_pre_window = float(alerts_pre / max(1, pre_mask.sum()))

        return {
            "name": crisis.name,
            "ok": True,
            "trigger_date": crisis.trigger_date,
            "window_start": crisis.window_start,
            "window_end": crisis.window_end,
            "n_frames": len(dates),
            "auc": round(float(auc), 4),
            "roc": {
                "fpr": [round(float(v), 4) for v in fpr],
                "tpr": [round(float(v), 4) for v in tpr],
            },
            "first_alert_date": first_alert_date,
            "lead_days": lead_days,
            "fpr_pre_window": round(fpr_pre_window, 4),
            "max_score": round(float(np.max(scores)), 4),
            "mean_score_in_window": round(float(np.mean(scores[labels == 1])) if (labels == 1).any() else 0.0, 4),
            "mean_score_pre_window": round(float(np.mean(scores[pre_mask])) if pre_mask.any() else 0.0, 4),
        }

    # ── helpers ────────────────────────────────────────────────────
    def _select_windows(self, names: Optional[List[str]]) -> List[CrisisWindow]:
        if not names:
            return list(HISTORICAL_CRISES)
        return [get_by_name(n) for n in names]

    def _summarize(self, results: List[dict]) -> Dict:
        valid = [r for r in results if r.get("ok")]
        if not valid:
            return {"n": 0, "mean_auc": None, "median_lead_days": None}
        aucs = [r["auc"] for r in valid]
        leads = [r["lead_days"] for r in valid if r.get("lead_days") is not None]
        return {
            "n": len(valid),
            "mean_auc": round(float(np.mean(aucs)), 4),
            "median_auc": round(float(np.median(aucs)), 4),
            "mean_lead_days": round(float(np.mean(leads)), 2) if leads else None,
            "median_lead_days": int(np.median(leads)) if leads else None,
            "mean_fpr_pre_window": round(float(np.mean([r["fpr_pre_window"] for r in valid])), 4),
        }


# ── ROC/AUC (no sklearn dependency to keep this importable at boot) ─
def _roc_curve(labels: np.ndarray, scores: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    order = np.argsort(-scores)
    y = labels[order]
    s = scores[order]
    # Cumulative TP/FP
    pos = np.sum(y == 1)
    neg = np.sum(y == 0)
    if pos == 0 or neg == 0:
        return np.array([0.0, 1.0]), np.array([0.0, 1.0]), np.array([0.0, 1.0])
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    tpr = tp / pos
    fpr = fp / neg
    # Prepend origin
    fpr = np.concatenate([[0.0], fpr])
    tpr = np.concatenate([[0.0], tpr])
    thr = np.concatenate([[np.inf], s])
    return fpr, tpr, thr


def _auc(fpr: np.ndarray, tpr: np.ndarray) -> float:
    # Trapezoidal integration
    return float(np.trapz(tpr, fpr))


# Singleton
backtest_harness = BacktestHarness()
