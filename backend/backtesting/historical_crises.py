"""
Labeled historical crisis windows for backtesting.

Each entry defines:
    · name         — human label
    · trigger_date — the single "event date" (the crash itself)
    · window       — (start, end) inclusive, used for labeling y=1
    · lookback     — how far before `window.start` the backtest should
                     start feeding data (so models warm up)
    · description  — one-line context

Labels are binary-by-day: any day inside `window` is 1, everything else
is 0.  The harness computes ROC/AUC treating the ensemble's combined
anomaly score as a continuous classifier.
"""
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class CrisisWindow:
    name: str
    trigger_date: str
    window_start: str
    window_end: str
    lookback_start: str
    description: str


HISTORICAL_CRISES: List[CrisisWindow] = [
    CrisisWindow(
        name="Lehman Collapse 2008",
        trigger_date="2008-09-15",
        window_start="2008-09-08",
        window_end="2008-10-31",
        lookback_start="2008-06-01",
        description="Bankruptcy filing triggers global interbank freeze; S&P -38%, VIX to 80",
    ),
    CrisisWindow(
        name="Flash Crash 2010",
        trigger_date="2010-05-06",
        window_start="2010-05-04",
        window_end="2010-05-14",
        lookback_start="2010-03-01",
        description="HFT liquidity vacuum; DJIA -9% intraday in 6 minutes",
    ),
    CrisisWindow(
        name="EU Sovereign Debt 2011",
        trigger_date="2011-08-05",
        window_start="2011-07-25",
        window_end="2011-10-15",
        lookback_start="2011-04-01",
        description="S&P U.S. credit downgrade, Italy/Spain spreads blow out",
    ),
    CrisisWindow(
        name="China Black Monday 2015",
        trigger_date="2015-08-24",
        window_start="2015-08-18",
        window_end="2015-09-10",
        lookback_start="2015-05-01",
        description="CNY devaluation, Chinese growth fears, global equity selloff",
    ),
    CrisisWindow(
        name="Volmageddon 2018",
        trigger_date="2018-02-05",
        window_start="2018-02-01",
        window_end="2018-02-15",
        lookback_start="2017-10-01",
        description="Short-vol ETP unwind; XIV liquidation, VIX spike +117%",
    ),
    CrisisWindow(
        name="COVID Crash 2020",
        trigger_date="2020-03-09",
        window_start="2020-02-20",
        window_end="2020-04-10",
        lookback_start="2019-11-01",
        description="Pandemic lockdowns; S&P -34% in 23 trading days, VIX to 82",
    ),
    CrisisWindow(
        name="SVB Bank Run 2023",
        trigger_date="2023-03-10",
        window_start="2023-03-06",
        window_end="2023-03-31",
        lookback_start="2022-12-01",
        description="Silicon Valley Bank collapse; regional bank contagion, Credit Suisse rescue",
    ),
]


def get_by_name(name: str) -> CrisisWindow:
    for c in HISTORICAL_CRISES:
        if c.name == name:
            return c
    raise KeyError(f"unknown crisis window: {name}")


def list_all() -> List[dict]:
    return [
        {
            "name": c.name,
            "trigger_date": c.trigger_date,
            "window_start": c.window_start,
            "window_end": c.window_end,
            "lookback_start": c.lookback_start,
            "description": c.description,
        }
        for c in HISTORICAL_CRISES
    ]
