"""
Event-Time Watermarking for stream alignment.

The problem: heterogeneous feeds arrive at different frequencies and with
different latencies.  Equity ticks can arrive sub-second while FRED macro
indicators arrive every 15 minutes.  If the inference pipeline compares
a *stale* bond yield with a *fresh* equity price, the copula and LSTM
models will misinterpret the temporal drift as correlation breakdown and
emit false-positive crisis alerts — the exact failure mode the research
paper calls out as the single biggest point of failure.

The fix:
    1. Tag every ingested tick with its SOURCE event_ms (not wall-clock
       processing time).
    2. Track a global watermark = max_event_ms - bounded_lateness_ms.
       Anything arriving with event_ms < watermark is "late"; we do NOT
       retroactively re-fire inference for it.
    3. For each source, remember the last-known-good (LKG) tick.  When
       a window is ready to emit but a source has gone silent past the
       watermark, substitute the LKG value and set is_degraded=True so
       downstream can reason about partial-truth state.

This module is intentionally in-process and lock-free (asyncio-safe) —
no Kafka / Flink dependency.
"""
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class _SourceState:
    last_event_ms: int = 0
    last_seen_wall: float = field(default_factory=time.time)
    lkg_tick: Optional[dict] = None  # last-known-good payload
    count: int = 0
    late_count: int = 0
    degraded: bool = False


class EventTimeWatermark:
    """Watermark tracker + LKG patcher for multi-source streams.

    Usage in the ingestion loop:

        wm = EventTimeWatermark(lateness_ms=300)
        wm.register_source("equities", stale_after_ms=2000)
        wm.register_source("macro_fred", stale_after_ms=900_000)

        # on each incoming tick:
        tick = wm.ingest(source="equities", tick_data=payload)
        # tick now carries:
        #   tick["watermark_ms"]         -> global watermark timestamp
        #   tick["is_degraded"]          -> True if any source is stale
        #   tick["degraded_sources"]     -> list of stale source names
    """

    def __init__(self, lateness_ms: int = 300):
        self.lateness_ms = int(lateness_ms)
        self._sources: Dict[str, _SourceState] = {}
        self._source_staleness_ms: Dict[str, int] = {}
        self._max_event_ms: int = 0
        # Rolling window of observed lateness for observability
        self._lateness_samples: deque = deque(maxlen=500)

    def register_source(self, name: str, stale_after_ms: int = 5000):
        """Declare a source and how long is 'too long' between ticks."""
        self._sources.setdefault(name, _SourceState())
        self._source_staleness_ms[name] = int(stale_after_ms)

    # ── core ingest ─────────────────────────────────────────────────
    def ingest(self, source: str, tick_data: dict) -> dict:
        """Tag a tick with event-time watermark metadata.

        Mutates and returns `tick_data`.  If the source is previously
        unknown, it's auto-registered with a 10-second staleness bound.
        """
        if source not in self._sources:
            self.register_source(source, stale_after_ms=10_000)

        state = self._sources[source]
        event_ms = int(tick_data.get("epoch_ms") or (time.time() * 1000))

        # Late event? — watermark has already passed it.
        if event_ms < self._max_event_ms - self.lateness_ms:
            state.late_count += 1
            tick_data["is_late"] = True
        else:
            tick_data["is_late"] = False
            state.last_event_ms = event_ms
            state.last_seen_wall = time.time()
            state.lkg_tick = tick_data

        state.count += 1
        self._max_event_ms = max(self._max_event_ms, event_ms)

        # Observability
        wall_ms = int(time.time() * 1000)
        self._lateness_samples.append(max(0, wall_ms - event_ms))

        # Compute global watermark + degraded-source list
        watermark_ms = self._max_event_ms - self.lateness_ms
        degraded = self._check_staleness()

        tick_data["watermark_ms"] = int(watermark_ms)
        tick_data["is_degraded"] = bool(degraded)
        tick_data["degraded_sources"] = degraded
        return tick_data

    # ── LKG patching ────────────────────────────────────────────────
    def patch_with_lkg(self, sources: List[str]) -> Dict[str, Optional[dict]]:
        """Return LKG ticks for the listed sources (used when a window
        is ready to emit but a source has gone silent)."""
        return {s: self._sources[s].lkg_tick if s in self._sources else None for s in sources}

    # ── observability ───────────────────────────────────────────────
    def status(self) -> Dict:
        now_wall = time.time()
        now_ms = int(now_wall * 1000)
        sources = {}
        for name, st in self._sources.items():
            stale_ms = self._source_staleness_ms.get(name, 10_000)
            age_wall_ms = int((now_wall - st.last_seen_wall) * 1000)
            sources[name] = {
                "ticks": st.count,
                "late_ticks": st.late_count,
                "age_ms": age_wall_ms,
                "stale_after_ms": stale_ms,
                "degraded": age_wall_ms > stale_ms,
                "last_event_ms": st.last_event_ms,
            }
        samples = list(self._lateness_samples)
        return {
            "watermark_ms": max(0, self._max_event_ms - self.lateness_ms),
            "max_event_ms": self._max_event_ms,
            "wall_ms": now_ms,
            "lateness_ms_bound": self.lateness_ms,
            "lateness_p50": int(_percentile(samples, 0.50)) if samples else 0,
            "lateness_p95": int(_percentile(samples, 0.95)) if samples else 0,
            "lateness_p99": int(_percentile(samples, 0.99)) if samples else 0,
            "sources": sources,
        }

    # ── internals ───────────────────────────────────────────────────
    def _check_staleness(self) -> List[str]:
        now = time.time()
        stale: List[str] = []
        for name, st in self._sources.items():
            if st.count == 0:
                continue
            bound_ms = self._source_staleness_ms.get(name, 10_000)
            age_ms = (now - st.last_seen_wall) * 1000
            if age_ms > bound_ms:
                st.degraded = True
                stale.append(name)
            else:
                st.degraded = False
        return stale


def _percentile(data: List[float], q: float) -> float:
    if not data:
        return 0.0
    s = sorted(data)
    idx = int(q * (len(s) - 1))
    return float(s[idx])


# Singleton — shared across ingestion producers
watermark = EventTimeWatermark(lateness_ms=300)
watermark.register_source("simulator", stale_after_ms=5_000)
watermark.register_source("finnhub", stale_after_ms=10_000)
watermark.register_source("replay", stale_after_ms=60_000)
watermark.register_source("fred_macro", stale_after_ms=900_000)  # 15 min
