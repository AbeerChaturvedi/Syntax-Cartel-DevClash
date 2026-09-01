"""
Phase-2 diagnostic: replay a crisis through the live ensemble and capture
per-date COMPONENT scores (IF, LSTM, CISS, copula, combined) + label, then
print pre-window vs in-window stats. Reveals why combined stays low / inverts.

Usage: python scripts/diagnose_backtest.py "COVID Crash 2020" "SVB Bank Run 2023"
"""
import asyncio
import os
import sys

import numpy as np

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, "..", ".env"))

from ingestion.replay import HistoricalReplay          # noqa: E402
from models.ensemble import ensemble                    # noqa: E402
from backtesting.historical_crises import get_by_name   # noqa: E402
from utils.model_persistence import get_checkpoint_manager  # noqa: E402

COMPS = ["isolation_forest", "lstm_autoencoder", "ciss", "copula_tail", "merton_bank", "combined_anomaly"]


async def diagnose(name: str):
    crisis = get_by_name(name)
    replay = HistoricalReplay()
    n = replay.load_window(crisis.lookback_start, crisis.window_end)
    if n == 0:
        print(f"{name}: no data"); return

    # reset ensemble smoothing state so runs are independent; process per-tick
    ensemble.reset()
    ensemble.batch_size = 1
    from features.state_builder import state_builder
    from models.ciss_scorer import ciss_scorer as _ciss
    from models.copula_model import copula_model as _cop
    from models.lstm_autoencoder import temporal_detector as _lstm
    state_builder.reset(); _ciss.reset(); _cop.reset(); _lstm.reset_runtime()
    per_date = {}  # date -> {comp: [vals], label}

    async def on_tick(tick):
        result = await ensemble.process_tick(tick)
        if not result:
            return
        d = tick.get("replay_date")
        s = result.get("scores") or {}
        rec = per_date.setdefault(d, {c: [] for c in COMPS})
        for c in COMPS:
            rec[c].append(float(s.get(c, 0.0)))
        rec["label"] = 1 if crisis.window_start <= d <= crisis.window_end else 0

    await replay.start(on_tick, speed_multiplier=1e12)
    while replay.status()["running"]:
        await asyncio.sleep(0.05)
    await replay.stop()

    dates = sorted(per_date.keys())
    pre = [d for d in dates if d < crisis.window_start]
    inw = [d for d in dates if crisis.window_start <= d <= crisis.window_end]

    def stat(dlist, comp, fn):
        vals = [v for d in dlist for v in per_date[d][comp]]
        return fn(vals) if vals else 0.0

    print(f"\n===== {name} =====")
    print(f"lookback {crisis.lookback_start} | window {crisis.window_start}→{crisis.window_end} | trigger {crisis.trigger_date}")
    print(f"{'component':20s} {'pre_mean':>9s} {'pre_max':>8s} {'in_mean':>9s} {'in_max':>8s}  {'discrim':>8s}")
    for c in COMPS:
        pm, px = stat(pre, c, np.mean), stat(pre, c, np.max)
        im, ix = stat(inw, c, np.mean), stat(inw, c, np.max)
        print(f"{c:20s} {pm:9.3f} {px:8.3f} {im:9.3f} {ix:8.3f}  {im - pm:+8.3f}")

    # weekly-sampled combined timeline
    print("  combined timeline (every ~10th day, max/day):")
    line = []
    for i, d in enumerate(dates):
        if i % 10 == 0:
            lbl = "*" if per_date[d]["label"] == 1 else " "
            line.append(f"{d[5:]}{lbl}{max(per_date[d]['combined_anomaly']):.2f}")
    print("    " + "  ".join(line))


async def main():
    names = sys.argv[1:] or ["COVID Crash 2020", "SVB Bank Run 2023"]
    print("[load]", get_checkpoint_manager().load().get("ok"))
    for nm in names:
        await diagnose(nm)


if __name__ == "__main__":
    asyncio.run(main())
