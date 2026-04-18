"""
Historical Crisis Replay Engine.

Streams real, historical market data (CSV) through the live pipeline at
a configurable speed multiplier. Used for:
    1. Demo credibility: "here's what our system would have done on
       Sep 15 2008 — watch the alerts fire on the actual event".
    2. Backtesting: the harness in `backtesting/harness.py` drives this
       replay and labels outcomes against known crisis windows.

Expected CSV format (per asset):
    data/historical/<TICKER>.csv
    date,open,high,low,close,volume
    2008-09-10,1240.24,1256.00,1234.56,1247.03,4621000000
    ...

Tickers expected to cover our default basket (SPY, XLF, TLT, etc.).
Missing tickers are silently skipped; replay proceeds with whatever
coverage is available.

The engine emits ticks in the canonical simulator format so downstream
code (ensemble, watermark, persistence) needs zero changes.
"""
import asyncio
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional

import numpy as np

from utils.config import REPLAY_DATA_DIR, REPLAY_SPEED_MULTIPLIER
from utils.logger import pipeline_log


class HistoricalReplay:
    """Replays CSV-stored OHLCV bars through the live pipeline."""

    def __init__(self, data_dir: Optional[str] = None):
        self.data_dir = Path(data_dir or REPLAY_DATA_DIR)
        self._running = False
        self._current_frame: Optional[Dict] = None
        self._frames: List[Dict] = []
        self._index = 0
        self._tick_count = 0
        self._task: Optional[asyncio.Task] = None
        self._speed_multiplier = float(REPLAY_SPEED_MULTIPLIER)
        self._start_date: Optional[str] = None
        self._end_date: Optional[str] = None
        self._asset_classes = {
            "SPY": "EQUITY", "QQQ": "EQUITY", "DIA": "EQUITY", "IWM": "EQUITY",
            "XLF": "EQUITY", "JPM": "EQUITY", "GS": "EQUITY", "BAC": "EQUITY",
            "C": "EQUITY", "MS": "EQUITY",
            "TLT": "BOND",
            "GLD": "COMMODITY",
            "VIX": "VOLATILITY",
            "EURUSD": "FX", "GBPUSD": "FX", "USDJPY": "FX",
            "BTCUSD": "CRYPTO", "ETHUSD": "CRYPTO",
        }

    # ── loading ────────────────────────────────────────────────────
    def load_window(self, start_date: str, end_date: str, tickers: Optional[List[str]] = None) -> int:
        """Load OHLCV data for a date window into memory."""
        self._start_date = start_date
        self._end_date = end_date

        if tickers is None:
            tickers = list(self._asset_classes.keys())

        # { date: { ticker: close_price } }
        per_date: Dict[str, Dict[str, float]] = {}
        prev_close: Dict[str, float] = {}

        loaded_tickers = []
        for t in tickers:
            path = self.data_dir / f"{t}.csv"
            if not path.exists():
                continue
            try:
                rows = _read_csv(path)
            except Exception as e:
                pipeline_log.warning(f"replay: failed to read {path}: {e}")
                continue
            loaded_tickers.append(t)
            for row in rows:
                d = row.get("date", "")
                if not (start_date <= d <= end_date):
                    continue
                try:
                    close = float(row["close"])
                except (KeyError, ValueError):
                    continue
                per_date.setdefault(d, {})[t] = close

        if not per_date:
            return 0

        sorted_dates = sorted(per_date.keys())
        self._frames = []
        for d in sorted_dates:
            frame = {"date": d, "closes": per_date[d]}
            self._frames.append(frame)

        self._index = 0
        self._tick_count = 0
        pipeline_log.info(
            f"replay: loaded {len(self._frames)} bars across {len(loaded_tickers)} tickers "
            f"({start_date} → {end_date})",
            extra={"tickers": loaded_tickers, "frames": len(self._frames)},
        )
        return len(self._frames)

    # ── streaming ──────────────────────────────────────────────────
    async def start(self, on_tick: Callable[[dict], "asyncio.Future"], speed_multiplier: Optional[float] = None):
        """Kick off the replay task."""
        if self._running:
            return False
        if not self._frames:
            raise RuntimeError("no frames loaded; call load_window() first")
        self._running = True
        if speed_multiplier is not None:
            self._speed_multiplier = float(speed_multiplier)
        self._task = asyncio.create_task(self._run(on_tick))
        return True

    async def stop(self):
        self._running = False
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=2.0)
            except Exception:
                pass
            self._task = None

    def status(self) -> Dict:
        total = len(self._frames)
        return {
            "running": self._running,
            "frames_total": total,
            "frames_emitted": self._index,
            "progress": round(self._index / total, 4) if total else 0.0,
            "tick_count": self._tick_count,
            "speed_multiplier": self._speed_multiplier,
            "start_date": self._start_date,
            "end_date": self._end_date,
            "current_frame": self._current_frame,
        }

    # ── internal run loop ──────────────────────────────────────────
    async def _run(self, on_tick: Callable[[dict], "asyncio.Future"]):
        prev_close: Dict[str, float] = {}
        # For each daily close we synthesize `intra_ticks` intraday ticks
        # so the ensemble has enough samples per day to compute rolling
        # statistics.  Path is a cosmetic random-walk whose endpoints
        # are the previous close → current close.
        intra_ticks_per_bar = 4
        # Sleep budget per emitted intraday tick
        # 1 trading day at 1× = 1 day wall-time (too slow).  Default
        # speed_multiplier (60) → 1 day = 24 min; judges can crank to
        # 1000× for a full crisis window in minutes.
        base_day_seconds = 86400.0

        while self._running and self._index < len(self._frames):
            frame = self._frames[self._index]
            self._current_frame = {"date": frame["date"], "index": self._index}

            closes = frame["closes"]
            if not closes:
                self._index += 1
                continue

            # Interpolate intraday path
            for step in range(intra_ticks_per_bar):
                if not self._running:
                    break
                t = (step + 1) / intra_ticks_per_bar
                assets_payload = {}
                for ticker, close in closes.items():
                    prev = prev_close.get(ticker, close)
                    # Linear blend + small gaussian jitter (annualized vol ~20%)
                    mid = prev + (close - prev) * t
                    jitter = np.random.normal(0, abs(mid) * 0.002)
                    px = float(mid + jitter)
                    pct = 0.0
                    if prev > 0:
                        pct = ((px - prev) / prev) * 100.0
                    spread = abs(px) * 0.0005
                    assets_payload[ticker] = {
                        "price": round(px, 6),
                        "price_change": round(px - prev, 6),
                        "pct_change": round(pct, 4),
                        "volume": int(np.random.exponential(100_000)),
                        "bid": round(px - spread, 6),
                        "ask": round(px + spread, 6),
                        "spread_bps": round((2 * spread / max(px, 1e-9)) * 10_000, 2),
                        "rolling_volatility": abs(pct) / 100.0 * np.sqrt(252),
                        "asset_class": self._asset_classes.get(ticker, "EQUITY"),
                    }

                # Build canonical tick payload
                self._tick_count += 1
                epoch_ms = int(datetime.strptime(frame["date"], "%Y-%m-%d")
                               .replace(tzinfo=timezone.utc).timestamp() * 1000
                               + step * 3_600_000 * 6)  # 6-hour-ish spacing within day
                tick = {
                    "timestamp": datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).isoformat(),
                    "epoch_ms": epoch_ms,
                    "tick_id": self._tick_count,
                    "crisis_mode": False,
                    "crisis_intensity": 0.0,
                    "source": "replay",
                    "replay_date": frame["date"],
                    "assets": assets_payload,
                }

                try:
                    await on_tick(tick)
                except Exception as e:
                    pipeline_log.error(f"replay: on_tick error: {e}")

                # Sleep between intraday ticks
                per_tick_sleep = (base_day_seconds / intra_ticks_per_bar) / max(self._speed_multiplier, 1e-6)
                await asyncio.sleep(min(per_tick_sleep, 2.0))  # cap to keep demo responsive

            # Advance to next bar
            for ticker, close in closes.items():
                prev_close[ticker] = close
            self._index += 1

        self._running = False


def _read_csv(path: Path) -> List[Dict[str, str]]:
    """Light-weight CSV reader (no pandas dep)."""
    import csv
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        # normalise header case
        return [{k.lower(): v for k, v in row.items()} for row in reader]


# Singleton
replay_engine = HistoricalReplay()
