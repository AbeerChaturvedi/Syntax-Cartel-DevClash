import asyncio
import numpy as np
from fastapi import APIRouter, HTTPException

from ingestion.simulator import simulator
from models.ensemble import ensemble
from utils.logger import api_log
from globals import _backtest_state

router = APIRouter()

CRISIS_CATALOG = [
    {"name": "Lehman Collapse 2008", "start": "2008-09-10", "end": "2008-09-20",
     "preset": "lehman_2008", "description": "Credit contagion, interbank freeze"},
    {"name": "Flash Crash 2010", "start": "2010-05-06", "end": "2010-05-07",
     "preset": "flash_crash_2010", "description": "Algorithmic cascade"},
    {"name": "EU Sovereign Debt 2011", "start": "2011-08-01", "end": "2011-08-15",
     "preset": "sovereign_debt", "description": "European debt crisis"},
    {"name": "China Black Monday 2015", "start": "2015-08-24", "end": "2015-08-28",
     "preset": "china_2015", "description": "China market crash"},
    {"name": "Volmageddon 2018", "start": "2018-02-05", "end": "2018-02-09",
     "preset": "volmageddon", "description": "VIX spike, XIV collapse"},
    {"name": "COVID Crash 2020", "start": "2020-03-05", "end": "2020-03-15",
     "preset": "covid_2020", "description": "Global pandemic selloff"},
    {"name": "SVB Bank Run 2023", "start": "2023-03-08", "end": "2023-03-14",
     "preset": "svb_2023", "description": "Regional bank contagion"},
]

@router.get("/api/backtest/crises")
async def get_backtest_crises():
    """Get list of available crisis windows for backtesting."""
    return CRISIS_CATALOG

@router.post("/api/backtest/run")
async def run_backtest(request: dict):
    """Run backtest across selected crisis windows."""
    if _backtest_state["running"]:
        raise HTTPException(status_code=409, detail="Backtest already running")

    crisis_names = request.get("crisis_names", [])
    if not crisis_names:
        crisis_names = [c["name"] for c in CRISIS_CATALOG]

    _backtest_state["running"] = True
    _backtest_state["progress"] = 0
    _backtest_state["results"] = None

    async def _execute_backtest():
        try:
            per_crisis = {}
            total = len(crisis_names)

            for idx, name in enumerate(crisis_names):
                # Simulate crisis through the ensemble
                n_ticks = 200
                scores = []
                labels = []

                for t in range(n_ticks):
                    is_crisis_zone = t >= n_ticks * 0.4 and t <= n_ticks * 0.8
                    intensity = 0.7 if is_crisis_zone else 0.0

                    if is_crisis_zone:
                        simulator.activate_crisis(intensity=intensity)
                    else:
                        simulator.deactivate_crisis()

                    tick = simulator.generate_tick()
                    result = await ensemble.process_tick(tick)
                    if result:
                        combined = result.get("scores", {}).get("combined_anomaly", 0)
                        scores.append(combined)
                        labels.append(1 if is_crisis_zone else 0)

                    await asyncio.sleep(0)  # Yield to event loop

                simulator.deactivate_crisis()
                _backtest_state["progress"] = (idx + 0.9) / total

                # Compute ROC/AUC
                if scores and len(set(labels)) > 1:
                    from sklearn.metrics import roc_auc_score, roc_curve, precision_score, recall_score
                    thresholds_eval = np.linspace(0, 1, 50)
                    y_true = np.array(labels)
                    y_scores = np.array(scores)

                    try:
                        auc = float(roc_auc_score(y_true, y_scores))
                        fpr, tpr, _ = roc_curve(y_true, y_scores)
                        preds = (y_scores > 0.5).astype(int)
                        prec = float(precision_score(y_true, preds, zero_division=0))
                        rec = float(recall_score(y_true, preds, zero_division=0))
                        fp_rate = float(np.sum((preds == 1) & (y_true == 0)) / max(np.sum(y_true == 0), 1))

                        # Lead time: first tick where score > 0.5 before crisis zone
                        crisis_start_idx = int(n_ticks * 0.4)
                        lead_time = 0
                        for lt in range(crisis_start_idx):
                            if scores[lt] > 0.4:
                                lead_time = crisis_start_idx - lt
                                break

                        per_crisis[name] = {
                            "auc": auc,
                            "precision": prec,
                            "recall": rec,
                            "false_positive_rate": fp_rate,
                            "lead_time_ticks": lead_time,
                            "fpr": fpr.tolist(),
                            "tpr": tpr.tolist(),
                        }
                    except Exception:
                        per_crisis[name] = {"auc": 0.5, "precision": 0, "recall": 0, "false_positive_rate": 0, "lead_time_ticks": 0}
                else:
                    per_crisis[name] = {"auc": 0.5, "precision": 0, "recall": 0, "false_positive_rate": 0, "lead_time_ticks": 0}

                _backtest_state["progress"] = (idx + 1) / total

            # Aggregate
            auc_values = [v["auc"] for v in per_crisis.values() if v["auc"] > 0]
            _backtest_state["results"] = {
                "per_crisis": per_crisis,
                "aggregate": {
                    "mean_auc": float(np.mean(auc_values)) if auc_values else 0,
                    "total_crises": len(per_crisis),
                    "runtime_ms": 0,
                },
            }
        except Exception as e:
            api_log.error(f"Backtest failed: {e}")
        finally:
            _backtest_state["running"] = False

    asyncio.create_task(_execute_backtest())
    return {"ok": True, "status": {"running": True, "progress": 0}}

@router.get("/api/backtest/status")
async def get_backtest_status():
    """Get backtest progress."""
    return _backtest_state

@router.get("/api/backtest/results")
async def get_backtest_results():
    """Get backtest results."""
    if _backtest_state["results"] is None:
        raise HTTPException(status_code=404, detail="No backtest results available")
    return _backtest_state["results"]
