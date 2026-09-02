# Velure Fix Implementation Plan
**Generated:** 2026-09-02 | **Status:** Ready for execution

---

## Phase 0: BOOT BLOCKER (must fix first — system doesn't work without these)

### 0.1 Docker Compose Postgres Port Conflict (WSL)
- **Status:** FIXED
- **What:** Ghost docker-proxy holds port 5432, preventing postgres from joining the network.
- **Fix Applied:** Commented out `ports: "5432:5432"` in docker-compose.yml — postgres is internal-only, backend connects via Docker DNS.

### 0.2 Hybrid Mode Produces Zero Ticks Without API Keys
- **Files:** `backend/pipeline/tasks.py` (line 36), `.env`
- **Root Cause:** `ingestion_producer()` only generates simulator ticks when `DATA_MODE=simulator` OR `crisis_mode=True`. In `hybrid` mode with no Finnhub key, the producer sleeps forever → zero ticks → pipeline never runs → health reports `degraded`.
- **Fix:**
  1. **Immediate (env):** Change `.env` to `DATA_MODE=simulator` for local dev.
  2. **Proper (code):** Update `ingestion_producer()` to fall back to simulator ticks when in hybrid mode and no live feed is connected.
- **Effort:** 10 min

---

## Phase 1: CRITICAL Backend Fixes (6 issues — application crashes / wrong results)

### 1.1 ~~Missing `GET /api/metrics` Endpoint~~ — ALREADY EXISTS
- **Status:** NOT A BUG. `system.py` already has `/api/metrics` at line 91. The FIXES_REQUIRED.md was written before this was added.

### 1.2 CISS Segment Breakdown Contract Mismatch
- **Files:** `frontend/src/app/components/ExplainabilityPanel.jsx` (line 74)
- **Root Cause:** Frontend reads `data.cdf_score` but backend sends `data.calibrated_score`. All CISS segment gauges render 0%.
- **Fix:** Change `data.cdf_score` → `data.calibrated_score` in ExplainabilityPanel.jsx.
- **Effort:** 5 min

### 1.3 Portfolio VaR Double-Multiplication Bug
- **Files:** `backend/portfolio/portfolio_var.py` (line 78)
- **Root Cause:** `notional` multiplied twice → produces trillions on a $1M portfolio.
- **Fix:** Remove the second `* notional` from the component_dollar formula.
- **Effort:** 5 min

### 1.4 Historical Replay & Backtesting — Missing Data + Format Disconnect
- **Files:** `backend/ingestion/historical_loader.py`, `backend/ingestion/replay.py`, `backend/backtesting/harness.py`
- **Root Cause:** loader writes JSON, replay/harness expect CSV. `data/historical/` dir empty.
- **Fix:**
  1. Update loader to write CSV alongside JSON.
  2. Provide a synthetic data generator for crisis windows (2008, 2020, 2023) as fallback.
  3. Ensure `data/historical/` exists and is seeded on first boot.
- **Effort:** 45 min

### 1.5 Alert Dispatcher aiohttp Fallback
- **Files:** `backend/utils/alerting.py`
- **Root Cause:** When aiohttp import fails, ALL webhook alerts silently disabled.
- **Fix:** Add `urllib.request` fallback wrapped in `asyncio.to_thread()` when aiohttp is None.
- **Effort:** 15 min

### 1.6 Missing uvloop in requirements.txt
- **Files:** `backend/requirements.txt`, `backend/Dockerfile`
- **Root Cause:** Dockerfile uses `--loop uvloop` but uvloop not in requirements.
- **Fix:** Add `uvloop>=0.19.0; sys_platform != "win32"` to requirements.txt, or change Dockerfile to `--loop auto`.
- **Effort:** 5 min

---

## Phase 2: HIGH — Model & Data Contract Fixes (7 issues — wrong data shown)

### 2.1 Feature Importance Label Mapping Mismatch
- **Files:** `frontend/src/app/components/ExplainabilityPanel.jsx`
- **Root Cause:** FEATURE_LABELS hardcoded for 18-asset schema (with bonds/rates) but state_builder uses 15 assets alphabetically.
- **Fix:** Dynamically generate FEATURE_LABELS from TRACKED_ASSETS × METRICS.
- **Effort:** 15 min

### 2.2 Correlation Heatmap 18-vs-15 Dimensions
- **Files:** `frontend/src/app/components/CorrelationHeatmap.jsx`
- **Root Cause:** LABELS array has 18 entries, backend sends 15×15 matrix.
- **Fix:** Update LABELS to match the 15 assets from state_builder.
- **Effort:** 10 min

### 2.3 Finnhub Free-Tier Forex WebSocket Failures
- **Files:** `backend/ingestion/finnhub_connector.py`, `backend/pipeline/tasks.py`
- **Root Cause:** OANDA FX symbols need paid tier. Free keys get silent failures. Missing assets → 0-vectors → broken covariance matrices.
- **Fix:** In hybrid/finnhub mode, backfill missing assets with simulator LKG prices per tick.
- **Effort:** 30 min

### 2.4 NewsData.io API Query Format
- **Files:** `backend/Routes/news.py`
- **Root Cause:** `category=business,top` returns 422; uses deprecated `get_event_loop()`.
- **Fix:** Use `category=business`, switch to `asyncio.get_running_loop()`, keep mock fallback.
- **Effort:** 10 min

### 2.5 Model Lineage Table Migration & Foreign Key Constraint
- **Files:** `backend/lifecycle.py`, `backend/database/persistence.py`
- **Root Cause:** `model_lineage` table may not exist; `source_id=5` hardcoded.
- **Fix:** Ensure audit migration runs during `init_db()`. Source_id already dynamic (persistence.py was patched) — verify.
- **Effort:** 15 min

### 2.6 Checkpoint Manager Scaler Deserialization
- **Files:** `backend/utils/model_persistence.py`
- **Root Cause:** Unfitted scaler triggers `_auto_train()` which discards loaded model.
- **Fix:** Validate both model+scaler state together before deciding to retrain.
- **Effort:** 15 min

---

## Phase 3: MEDIUM — Frontend & Cleanup (6 issues — visual bugs / tech debt)

### 3.1 Three.js WebGL Memory Leak in ContagionNetwork
- **Files:** `frontend/src/app/components/ContagionNetwork.jsx`
- **Root Cause:** New canvas+texture per tick without disposing old ones.
- **Fix:** Pool sprite textures, update positions in-place, dispose on unmount.
- **Effort:** 30 min

### 3.2 Next.js SSR Hydration Flash in useClock
- **Files:** `frontend/src/app/page.js` (line ~104)
- **Root Cause:** `useState('')` causes SSR/client mismatch.
- **Fix:** Add `suppressHydrationWarning` on the time container.
- **Effort:** 5 min

### 3.3 Speed Control Race Condition
- **Files:** `frontend/.../SpeedControl.jsx`, `frontend/.../StatusFooter.jsx`
- **Root Cause:** Both components independently call `/api/speed/{mode}` with different state.
- **Fix:** Consolidate speed state into a shared context or use a single source of truth.
- **Effort:** 20 min

### 3.4 Duplicate Singleton in harness.py
- **Files:** `backend/backtesting/harness.py`
- **Fix:** Remove duplicate `backtest_harness = BacktestHarness()`.
- **Effort:** 2 min

### 3.5 Stale Refactor Scripts
- **Files:** `backend/fix_imports.py`, `backend/fix_main.py`, `backend/refactor.py`
- **Fix:** Delete them or move to `scripts/maintenance/`.
- **Effort:** 2 min

### 3.6 JSON vs CSV Historical Format Mismatch
- Covered by 1.4 above.

---

## Phase 4: LOW — Polish (3 issues)

### 4.1 Case-Colliding Readme Files
- **Fix:** Delete `Readme.md`, keep `README.md`.
- **Effort:** 1 min

### 4.2 Deprecated Event Loop References
- **Fix:** Replace `asyncio.get_event_loop()` → `asyncio.get_running_loop()` globally.
- **Effort:** 5 min

### 4.3 Missing WebSocket Error Boundaries
- **Fix:** Add React Error Boundary wrapper around WS-dependent components.
- **Effort:** 15 min

---

## Execution Order (dependency-aware)

```
Phase 0.2  Fix hybrid mode tick generation    ← MUST DO FIRST, pipeline won't run
  ↓
Phase 1.6  Add uvloop / fix Dockerfile        ← prevents boot failures in fresh builds
Phase 1.3  Fix VaR double-multiplication      ← wrong financial calculations
Phase 1.2  Fix CISS contract mismatch         ← broken dashboard gauges
Phase 1.5  Add alerting fallback              ← alerts silently fail
  ↓
Phase 2.1  Fix feature labels                 ← wrong asset names in UI
Phase 2.2  Fix heatmap dimensions             ← heatmap misrendered
Phase 2.3  Fix Finnhub FX fallback            ← hybrid mode data gaps
Phase 2.4  Fix NewsData.io API                ← news feed broken
Phase 2.5  Fix model lineage migration        ← DB errors on startup
Phase 2.6  Fix checkpoint scaler              ← warm restart discards models
  ↓
Phase 1.4  Historical replay + data seeding   ← largest change, needs testing
  ↓
Phase 3.1  Fix WebGL memory leak              ← browser perf
Phase 3.2  Fix hydration flash                ← quick
Phase 3.3  Fix speed control race             ← UX
Phase 3.4  Remove duplicate singleton         ← trivial
Phase 3.5  Remove stale scripts               ← trivial
  ↓
Phase 4.*  Polish items                       ← last
```

---

## Skills to Use Per Phase

| Phase | Skills |
|-------|--------|
| 0.2, 1.x | systematic-debugging, clean-code |
| 1.4 | working-with-legacy-code, test-driven-development |
| 2.x | refactoring-patterns, clean-code |
| 3.1 | high-perf-browser |
| 3.3 | refactoring-patterns |
| Final | requesting-code-review, hermaguard |

---

## Verification After Each Phase

- `docker compose down && docker compose up -d --build`
- `curl http://localhost:8000/health` → all checks `true`
- `curl http://localhost:8000/api/metrics` → `ticks_per_second > 0`
- Open `http://localhost:3000` → dashboard renders with live data
- Run crisis simulation via UI → CISS gauge responds
