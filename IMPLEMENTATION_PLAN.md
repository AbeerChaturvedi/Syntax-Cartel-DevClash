# Velure — Master Implementation Plan (Audit + Active Issues)
**Date:** 2026-09-02 | **Scope:** All backend, frontend, deployment, runtime issues observed

This plan combines:
1. Re-verification of every item in `FIXES_REQUIRED.md` (22 issues)
2. New issues found during live operation (real-data mode, off-hours tick collapse, missing error boundaries)

Items marked ✅ are already fixed. Items marked 🔴 remain open and must be done in the order shown.

---

## STATUS OF ORIGINAL 22 ISSUES (FIXES_REQUIRED.md)

| # | Issue | Severity | Status | Where |
|---|-------|----------|--------|-------|
| 1.1 | Missing `/api/metrics` endpoint | CRITICAL | ✅ FIXED | `backend/Routes/system.py:91` |
| 1.2 | CISS `cdf_score` vs `calibrated_score` | CRITICAL | ✅ FIXED (both keys emitted) | `backend/models/ciss_scorer.py:229,231` |
| 1.3 | Portfolio VaR double-multiplication | CRITICAL | ✅ FIXED | `backend/portfolio/portfolio_var.py:79` |
| 1.4 | Historical data JSON vs CSV + empty dir | CRITICAL | ✅ FIXED (CSV sibling + 7812 seeder bars) | `backend/ingestion/historical_loader.py` |
| 1.5 | aiohttp alerting fallback | CRITICAL | ✅ FIXED (urllib fallback present) | `backend/utils/alerting.py:270-287` |
| 1.6 | Missing uvloop dependency | CRITICAL | ✅ FIXED (in reqs + Dockerfile) | `backend/requirements.txt:18`, `Dockerfile:46` |
| 2.1 | Feature label misalignment | HIGH | ✅ FIXED (dynamic from 15 assets × 4 metrics) | `frontend/.../ExplainabilityPanel.jsx:11-24` |
| 2.2 | Heatmap 18-vs-15 dimensions | HIGH | ✅ FIXED (15 assets matching state_builder) | `frontend/.../CorrelationHeatmap.jsx:11-15` |
| 2.3 | Finnhub free-tier Forex failures | HIGH | ✅ FIXED (uses Twelve Data for FX) | `backend/ingestion/finnhub_connector.py:33,273` |
| 2.4 | NewsData.io query errors | HIGH | ✅ FIXED (uses `category=business`, `get_running_loop`) | `backend/Routes/news.py:68,124` |
| 2.5 | DB foreign key hardcoding | HIGH | ✅ FIXED (dynamic `_source_id_cache`) | `backend/database/persistence.py:30-55` |
| 2.6 | Checkpoint scaler deserialization | HIGH | ✅ FIXED (preserves loaded model) | `backend/utils/model_persistence.py:128-137` |
| 3.1 | Three.js WebGL memory leak | MEDIUM | ✅ FIXED (5 dispose calls present) | `frontend/.../ContagionNetwork.jsx` |
| 3.2 | Next.js SSR hydration flash | MEDIUM | ✅ FIXED (`suppressHydrationWarning` on clock) | `frontend/src/app/page.js:393` |
| 3.3 | Speed control race condition | MEDIUM | ✅ FIXED (removed duplicate controls) | `frontend/.../StatusFooter.jsx` |
| 3.4 | Duplicate singleton in harness.py | MEDIUM | ✅ FIXED (1 instance) | `backend/backtesting/harness.py:232` |
| 3.5 | Stale refactor scripts | MEDIUM | ✅ FIXED (files don't exist) | n/a |
| 3.6 | JSON vs CSV format mismatch | MEDIUM | ✅ FIXED (CSV sibling + synthetic seeder) | `backend/ingestion/historical_loader.py` |
| 4.1 | Case-colliding Readme files | LOW | ✅ FIXED (only README.md exists) | n/a |
| 4.2 | Deprecated event loop refs | LOW | ✅ FIXED (no `get_event_loop()` calls) | grep clean |
| 4.3 | Missing WS error boundaries | LOW | ❌ NOT FIXED | n/a |

**Scorecard:** 21/22 fixed. Only **4.3 (Error Boundaries)** remains from FIXES_REQUIRED.md.

---

## NEW ISSUES FOUND DURING LIVE OPERATION

These were not in FIXES_REQUIRED.md — they surfaced when the system was verified end-to-end with real API keys.

### NEW-A: Tick pipeline stops when no trades flow (off-hours bug) — CRITICAL
- **Symptom:** Live tick rate dropped from 3.94 Hz → **0.99 Hz** after real connectors activated.
- **Cause:** `ingestion_producer()` in `pipeline/tasks.py` skips simulator generation when `live_connected=True`. Finnhub WebSocket only emits ticks when a real trade happens. When US market is closed (~21 hours/day), zero trades → no ticks → pipeline idle → models still report stale scores.
- **Impact:** Models continue to print `combined_anomaly: 0.6476` from the last BTC trade but don't refresh for hours. Dashboard appears frozen.
- **Fix:** Switch from "either/or" to "merge": always run simulator at low rate for filler ticks, override prices with real trades as they arrive. Concretely: emit a "heartbeat" tick every 2s using last-known real prices, intersperse with real-trade ticks.
- **File:** `backend/pipeline/tasks.py:34-44`
- **Effort:** 20 min

### NEW-B: Simulator ticks have `source: None` — LOW
- **Symptom:** Probed ticks show `"source": null` (cosmetic). Finnhub ticks correctly say `"finnhub_live"`.
- **Cause:** `MarketSimulator.generate_tick()` doesn't include `"source"` key.
- **Impact:** Cannot distinguish simulator vs real data when debugging. `db_connected: false` flag also stale (set False on first boot failure, never reset after recovery).
- **Fix:** Add `"source": "simulator"` to simulator output dict. Reset `_db_available` after first successful query.
- **Files:** `backend/ingestion/simulator.py:130-135`, `backend/database/persistence.py`
- **Effort:** 10 min

### NEW-C: Finnhub key may be malformed — UNKNOWN
- **Symptom:** `"dabu9apr01qvvgl6tmp0dabu9apr01qvvgl6tmpg"` is 40 chars. Real Finnhub keys are typically 32 alphanumeric chars from `finnhub.io` dashboard.
- **Cause:** Key was provided by user; may have been copy-pasted twice or truncated.
- **Impact:** Auth may work initially (Finnhub accepts malformed keys with HTTP 401 errors that get silently swallowed) but fail mid-session.
- **Fix:** Ask user to regenerate at finnhub.io and verify against expected length/format.
- **Effort:** 5 min (verification only)

### NEW-D: `_db_available` flag stuck False after recovery — LOW (cosmetic)
- **Symptom:** `/api/metrics` reports `"db_connected": false` while circuit breaker shows 81+ successful writes.
- **Cause:** `init_db()` sets `_db_available=True` on first success, but if the very first attempt failed (port-5432 ghost proxy from earlier in the session), the flag stays False forever.
- **Impact:** Health endpoint shows `degraded` even when DB is fully functional. Misleading for ops.
- **Fix:** Reset flag to True on each successful DB query in `persist_scores()`.
- **File:** `backend/database/persistence.py:64`
- **Effort:** 5 min

### NEW-E: No Finnhub REST snapshot at boot — MEDIUM
- **Symptom:** US equities show `null` when market is closed. Cannot replay-backtest with current real prices.
- **Cause:** `finnhub_connector.py` is WebSocket-only. No `/quote` REST call at startup to seed initial prices.
- **Fix:** Add `_seed_initial_quotes()` method that hits `https://finnhub.io/api/v1/quote?symbol=XXX&token=YYY` for each symbol on startup.
- **File:** `backend/ingestion/finnhub_connector.py`
- **Effort:** 25 min

### NEW-F: No WebSocket error boundaries — LOW
- **Symptom:** WebSocket-dependent components (ScoreCards, LiveTicker, etc.) can crash the whole dashboard if a single bad message arrives.
- **Fix:** Add React Error Boundary wrapper around WS-rendered children.
- **File:** new `frontend/src/app/components/ErrorBoundary.jsx` + wrap in `page.js`
- **Effort:** 15 min

---

## EXECUTION ORDER (dependency-aware)

```
Phase 1: NEW-A (off-hours tick collapse)          ← pipeline freezes without it
Phase 2: NEW-E (Finnhub REST snapshot)            ← equities show null otherwise
Phase 3: NEW-D (_db_available stale flag)        ← cosmetic but ops-facing
Phase 4: NEW-B (simulator source tag)             ← cosmetic
Phase 5: 4.3 (WS error boundaries)                ← last item from FIXES_REQUIRED.md
Phase 6: NEW-C (Finnhub key validation)           ← user-action verification only
```

---

## PHASE 1 — NEW-A: Off-Hours Tick Collapse

**File:** `backend/pipeline/tasks.py`

**Change:** In `ingestion_producer()`, when live feeds are connected, still emit "heartbeat" ticks every 2 seconds using the latest real prices from `_finnhub._price_history` and `_twelve_data.latest_prices`. Real trade ticks continue to fire as they arrive and override.

```python
# New logic: always emit; simulator fills gaps when no real data
while g._pipeline_running:
    try:
        tick_data = None
        if simulator.crisis_mode:
            tick_data = simulator.generate_tick()
        elif g._data_mode == "simulator":
            tick_data = simulator.generate_tick()
        else:
            # Hybrid: prefer real data; fall back to heartbeat using last-known real prices
            tick_data = _build_heartbeat_tick()  # NEW: uses last Finnhub/Twelve Data prices

        if tick_data:
            tick_data = watermark.ingest("simulator", tick_data)
            await redis_streams.publish_tick(tick_data)
        await asyncio.sleep(g._tick_rate)
```

The new `_build_heartbeat_tick()` helper in tasks.py queries `g._finnhub._price_history` and `g._twelve_data.latest_prices`, falls back to simulator anchor prices for any missing ticker.

**Verification:**
- During off-hours: ticks continue at `_tick_rate` (0.25s = 4 Hz)
- Prices reflect last-known real values, not new random walks
- `peak_combined` updates every few seconds instead of freezing

**Effort:** 20 min

---

## PHASE 2 — NEW-E: Finnhub REST Snapshot at Boot

**File:** `backend/ingestion/finnhub_connector.py`

**Add:** New method `_seed_initial_quotes()` called from `start()` after WebSocket connect:

```python
async def _seed_initial_quotes(self):
    """REST /quote snapshot for every symbol. Populates _price_history
    so the state builder has real values even when WebSocket has no trades."""
    if not self._api_key:
        return
    for finnhub_sym in FINNHUB_SYMBOL_MAP:
        try:
            data = await self._rest_get(f"https://finnhub.io/api/v1/quote?symbol={finnhub_sym}&token={self._api_key}")
            if data and data.get("c"):  # 'c' = current price
                self._price_history[finnhub_sym].append(float(data["c"]))
        except Exception:
            pass  # silently skip; WebSocket will fill in eventually
```

**Verification:** After boot, US equities show real values even before first trade.

**Effort:** 25 min

---

## PHASE 3 — NEW-D: `_db_available` Stale Flag

**File:** `backend/database/persistence.py`

**Change:** After first successful DB query in `persist_scores()`:

```python
async def persist_scores(result: dict, tick_data: dict):
    if not g._db_available or not g._db_pool or not db_circuit.is_available:
        return
    try:
        ...
        async with g._db_pool.acquire() as conn:
            # If we got here, the pool is working — ensure the flag reflects reality
            if not g._db_available:
                g._db_available = True
            ...
```

**Verification:** `/api/metrics` shows `"db_connected": true` after first DB write.

**Effort:** 5 min

---

## PHASE 4 — NEW-B: Simulator Source Tag

**File:** `backend/ingestion/simulator.py`

**Change:** Add `"source": "simulator"` to `generate_tick()` output dict (line ~130):

```python
tick_data = {
    "timestamp": now.isoformat(),
    "epoch_ms": epoch_ms,
    "tick_id": self.tick_count,
    "source": "simulator",       # NEW
    "crisis_mode": self.crisis_mode,
    ...
}
```

**Verification:** `peek.py` shows `"source": "simulator"` for simulator ticks; `"finnhub_live"` for real trades; `"twelve_data"` for FX.

**Effort:** 10 min

---

## PHASE 5 — 4.3: WebSocket Error Boundaries

**New file:** `frontend/src/app/components/ErrorBoundary.jsx`

```jsx
'use client';
import React from 'react';

export default class ErrorBoundary extends React.Component {
  state = { hasError: false, error: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    console.error('Velure ErrorBoundary:', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div style={{ padding: 16, color: '#ef4444', fontSize: 12 }}>
          Component failed: {String(this.state.error?.message ?? this.state.error)}
        </div>
      );
    }
    return this.props.children;
  }
}
```

**Wrap in `page.js`:** Wrap each WS-dependent component (ScoreCards, LiveTicker, AnomalyTimeline, etc.) with `<ErrorBoundary>...</ErrorBoundary>`.

**Verification:** If any single component throws, dashboard stays alive with a localized error message.

**Effort:** 15 min

---

## PHASE 6 — NEW-C: Finnhub Key Validation

**Action:** Ask user to verify the key at finnhub.io/dashboard. Expected format: 32 lowercase alphanumeric chars. The provided key `dabu9apr01qvvgl6tmp0dabu9apr01qvvgl6tmpg` is 40 chars — may be a typo or paste duplication.

**Verification:** User confirms key regenerates correctly; auth doesn't fail mid-session.

**Effort:** 5 min

---

## TOTAL EFFORT ESTIMATE

| Phase | Effort | Cumulative |
|-------|--------|-----------|
| 1: Off-hours ticks | 20 min | 20 min |
| 2: Finnhub REST | 25 min | 45 min |
| 3: db flag | 5 min | 50 min |
| 4: source tag | 10 min | 60 min |
| 5: ErrorBoundary | 15 min | 75 min |
| 6: Key verify | 5 min | 80 min |

**All phases fit in ~80 minutes.**

---

## SKILLS TO USE

- `systematic-debugging` — Phase 1 (off-hours collapse is a runtime behavior issue)
- `clean-code` — All phases (keep patches minimal and readable)
- `high-perf-browser` — Phase 5 (ErrorBoundary pattern in Next.js 16)
- `release-it` — Phase 2 (defensive fallback patterns)

---

## POST-FIX VERIFICATION CHECKLIST

```
docker compose down && docker compose up -d --build
sleep 60

# Models working
curl http://localhost:8000/api/metrics | grep -E "ticks_per_second|peak_combined"
# Expect: ticks_per_second ~4.0, peak_combined > 0.0

# Prices are real
docker compose exec backend python /tmp/peek.py | grep -E "EURUSD|BTCUSD|source"
# Expect: EURUSD ~1.16, BTCUSD from Binance, source: "finnhub_live" or "twelve_data"

# DB alive
curl http://localhost:8000/api/metrics | grep db_connected
# Expect: db_connected: true (after first write)

# ErrorBoundary in place
grep -c ErrorBoundary frontend/src/app/page.js
# Expect: > 0
```