"""
Run the labeled-crisis backtest and print a scorecard.

  --load-real   restore the real-trained checkpoint first (else models
                lazily auto-train on synthetic data => the 'before' baseline)
  --crises A B  restrict to named windows (default: all)
  --speed S     replay speed multiplier (default 1e9 => no wall-clock sleeps)

Usage:
    python scripts/run_backtest.py                 # synthetic baseline
    python scripts/run_backtest.py --load-real     # real-trained
"""
import argparse
import asyncio
import json
import os
import sys

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND)
from dotenv import load_dotenv
load_dotenv(os.path.join(_BACKEND, "..", ".env"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--load-real", action="store_true")
    ap.add_argument("--crises", nargs="*", default=None)
    ap.add_argument("--speed", type=float, default=1e9)
    args = ap.parse_args()

    tag = "REAL-TRAINED" if args.load_real else "SYNTHETIC (baseline)"
    if args.load_real:
        from utils.model_persistence import get_checkpoint_manager
        res = get_checkpoint_manager().load()
        print(f"[checkpoint load] {res.get('ok')} {res.get('components', res.get('reason'))}")

    from backtesting.harness import BacktestHarness
    result = asyncio.run(BacktestHarness().run(crisis_names=args.crises, speed_multiplier=args.speed))

    print(f"\n===== BACKTEST SCORECARD — {tag} =====")
    per = result.get("per_crisis", result.get("results", []))
    hdr = f"{'crisis':28s} {'AUC':>6s} {'lead_days':>9s} {'FPR_pre':>8s} {'mean_in':>8s} {'peak':>6s}"
    print(hdr)
    print("-" * len(hdr))
    for r in per:
        if not r.get("ok", True):
            print(f"{r.get('name',''):28s}  SKIPPED — {r.get('reason','')}")
            continue
        print(f"{r.get('name',''):28s} "
              f"{_f(r.get('auc')):>6} "
              f"{_f(r.get('lead_days'), 1):>9} "
              f"{_f(r.get('fpr_pre_window'), 3):>8} "
              f"{_f(r.get('mean_score_in_window'), 3):>8} "
              f"{_f(r.get('max_score'), 3):>6}")
    if "summary" in result:
        print("\nsummary:", json.dumps(result["summary"], default=str))
    # dump full JSON for the record
    out = os.path.join(_BACKEND, "data", f"backtest_{'real' if args.load_real else 'synthetic'}.json")
    with open(out, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nfull results -> {out}")


def _f(v, nd=3):
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return "--"


if __name__ == "__main__":
    main()
