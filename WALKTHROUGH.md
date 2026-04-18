# Project Velure — Technical Walkthrough

> **Real-Time Financial Crisis Early Warning System**
> DevClash 2026 · Team Syntax Cartel

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Architecture Blueprint](#architecture-blueprint)
3. [ML Ensemble Pipeline](#ml-ensemble-pipeline)
4. [Backend Services](#backend-services)
5. [Frontend Dashboard](#frontend-dashboard)
6. [Crisis Simulation Engine](#crisis-simulation-engine)
7. [v3 Production Features](#v3-production-features)
8. [Data Flow](#data-flow)
9. [Running the System](#running-the-system)
10. [5-Minute Demo Script](#5-minute-demo-script)

---

## System Overview

Project Velure is a **production-grade, event-driven prototype** that detects financial systemic risk in real-time. It processes live streaming market data through a 6-model ML ensemble, computing anomaly scores, systemic stress indices, and institutional default probabilities — all broadcast to a GPU-accelerated dashboard via WebSocket at up to 25 Hz.

### Why It Matters

Traditional risk monitoring relies on batch processing with hours of latency. Velure operates on **tick-level data** (4 Hz default, 25 Hz turbo), detecting contagion patterns that only emerge in tail events — the exact scenarios where Pearson correlation breaks down and institutions need answers in seconds, not hours.

### Tech Stack

| Layer | Technology |
|-------|-----------|
| **Ingestion** | Python `asyncio` + `websockets` + `aiohttp` |
| **Queuing** | Redis Streams (primary) · `asyncio.Queue` (fallback) |
| **ML Ensemble** | scikit-learn (IF) · PyTorch (LSTM) · NumPy/SciPy (CISS, Merton, t-Copula+GARCH) |
| **API** | FastAPI with WebSocket broadcasting + 36 REST endpoints |
| **Frontend** | Next.js 16 / React 19 · ECharts (Canvas) · Framer Motion |
| **Persistence** | PostgreSQL 16 (Star Schema) · TimescaleDB (optional) |
| **Infrastructure** | Docker Compose · Redis 7 · Prometheus metrics |

---

## Architecture Blueprint

```
┌──────────────────────────────────────────────────────────────┐
│                    DATA INGESTION LAYER                       │
│                                                              │
│   Simulator (GBM)  ──┐                                      │
│   Finnhub WebSocket ──┼──▶  Redis Streams  ──▶  asyncio.Queue│
│   Historical Replay ──┘     (buffered)         (fallback)    │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│              MICRO-BATCH INFERENCE ENGINE                     │
│              (10 ticks / 500ms flush)                         │
│                                                              │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│   │  Isolation   │  │    LSTM     │  │    CISS     │         │
│   │   Forest     │  │ Autoencoder │  │   Scorer    │         │
│   │  (200 trees) │  │ (72→32→72) │  │ (5 segments)│         │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│          │                │                │                 │
│   ┌──────┴──────┐  ┌──────┴──────┐  ┌──────┴──────┐         │
│   │   Merton    │  │  t-Copula   │  │    VaR      │         │
│   │  DD + SRISK │  │ + GARCH(1,1)│  │   /CVaR     │         │
│   │  (5 banks)  │  │ (tail dep.) │  │ (3 methods) │         │
│   └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │
│          │                │                │                 │
│          └───────────┬────┴────────────────┘                 │
│                      ▼                                       │
│           Ensemble Orchestrator                              │
│     IF(0.35) + LSTM(0.35) + CISS(0.20) + Copula(0.10)      │
│              → combined_anomaly ∈ [0, 1]                     │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────┐
│                    BROADCAST LAYER                            │
│                                                              │
│   FastAPI WebSocket ──▶  N clients (RAF-buffered, 60fps)     │
│   REST API (36 endpoints)                                    │
│   Multi-sink Alerting (Slack / Discord / PagerDuty / SMTP)   │
│   PostgreSQL Star Schema (dimensional persistence)           │
└──────────────────────────────────────────────────────────────┘
```

---

## ML Ensemble Pipeline

### Model 1: Isolation Forest (Cross-Sectional Anomaly Detection)

**File:** `backend/models/isolation_forest.py`

- **Purpose:** Detects outliers in the current market state vector
- **Input:** 72-dim vector (18 assets × 4 features: price, pct_change, spread_bps, rolling_vol)
- **Output:** Anomaly score ∈ [0, 1] via sigmoid transform of decision function
- **Key:** Auto-trains on synthetic calm data if no pre-trained model exists
- **Weight:** 35% of ensemble

### Model 2: LSTM Autoencoder (Temporal Anomaly Detection)

**File:** `backend/models/lstm_autoencoder.py`

- **Purpose:** Detects sequential pattern deviations via reconstruction error
- **Architecture:** 2-layer encoder (72→64→32) + 2-layer decoder (32→64→72)
- **Input:** 60-tick sliding window of state vectors
- **Output:** MSE-based anomaly score with adaptive 95th percentile thresholding
- **Key:** Higher reconstruction error = more anomalous (the model learned "normal")
- **Weight:** 35% of ensemble

### Model 3: CISS Scorer (Systemic Stress Index)

**File:** `backend/models/ciss_scorer.py`

- **Purpose:** ECB-style Composite Indicator of Systemic Stress
- **Method:** Empirical CDF normalization → correlation-weighted quadratic form
- **Segments:** Equities, FX, Rates, Credit, Volatility
- **Key insight:** When all 5 segments stress simultaneously (high cross-correlation), the score amplifies non-linearly. Localized stress is dampened.
- **Weight:** 20% of ensemble

### Model 4: Merton Distance-to-Default + SRISK

**File:** `backend/models/merton_model.py`

- **Purpose:** Structural credit risk — treats equity as a call option on firm assets
- **Tracks:** JPM, GS, BAC, C, MS (5 major banks)
- **Outputs:** Distance-to-Default (DD), Probability of Default (PD), SRISK, LRMES
- **Key equation:** `DD = [ln(A/L) + (μ - σ²/2)T] / (σ√T)`
- **SRISK:** `k·D - (1-k)·(1-LRMES)·E` (Acharya et al. systemic risk measure)

### Model 5: t-Copula + GARCH(1,1) (Tail Dependence)

**File:** `backend/models/copula_model.py`

- **Purpose:** Detects contagion that Pearson correlation misses — co-crashes in the tail
- **Method:** GARCH(1,1) standardized residuals → t-copula fit → lower-tail λ_L coefficients
- **Output:** 5×5 tail dependence matrix across market segments
- **Key metric:** `λ_L = 2·t_{ν+1}(-√((ν+1)(1-ρ)/(1+ρ)))` — probability of joint crash
- **Weight:** 10% of ensemble

### Model 6: Value-at-Risk / CVaR

**File:** `backend/models/var_calculator.py`

- **Purpose:** Portfolio-level tail risk quantification
- **Methods:** Historical Simulation, Parametric (Normal), Cornish-Fisher (skew/kurtosis adjusted)
- **Output:** VaR%, CVaR% (Expected Shortfall), Dollar VaR, risk regime classification

### Ensemble Orchestration

**File:** `backend/models/ensemble.py`

The ensemble orchestrator implements **micro-batching**: it buffers incoming ticks and flushes inference every 10 ticks or 500ms (whichever comes first). This prevents the system from crashing under high-velocity data while keeping latency bounded.

```python
combined = (
    w_if   * isolation_forest_score +
    w_lstm * lstm_autoencoder_score +
    w_ciss * ciss_score +
    w_cop  * copula_tail_score
)
# Default: 0.35 + 0.35 + 0.20 + 0.10 = 1.0
```

---

## Backend Services

### API Surface (36 Routes)

| Category | Endpoints |
|----------|----------|
| **Health** | `GET /`, `GET /health`, `GET /api/metrics` |
| **Pipeline** | `GET /api/state`, `GET /api/scores`, `GET /api/assets` |
| **Merton** | `GET /api/merton`, `GET /api/merton/{ticker}` |
| **CISS** | `GET /api/ciss`, `GET /api/ciss/breakdown` |
| **Copula** | `GET /api/copula` |
| **VaR** | `GET /api/var`, `POST /api/var/portfolio` |
| **Stress Test** | `POST /api/stress-test/activate`, `POST /api/stress-test/deactivate`, `POST /api/stress-test/preset` |
| **Speed** | `POST /api/speed/{mode}` |
| **Replay** | `POST /api/replay/start`, `POST /api/replay/stop`, `GET /api/replay/status` |
| **Backtest** | `POST /api/backtest/run`, `GET /api/backtest/status`, `GET /api/backtest/results`, `GET /api/backtest/crises` |
| **Alerts** | `GET /api/alerts`, `GET /api/alerts/history` |
| **WebSocket** | `WS /ws/dashboard` |

### Data Ingestion Modes

| Mode | Source | Use Case |
|------|--------|----------|
| `simulator` | GBM (Geometric Brownian Motion) | Default — self-contained demo |
| `finnhub` | Finnhub WebSocket API | Live market data |
| `hybrid` | Finnhub + simulator fallback | Production with fallback |
| `replay` | Historical CSV files | Crisis replay / backtesting |

### Infrastructure Services

- **Redis Streams** — Primary ingestion queue with `XADD`/`XREADGROUP`, auto-trimmed at 10K entries. Falls back to `asyncio.Queue` when Redis is unavailable.
- **PostgreSQL** — Star schema (Kimball methodology) with `dim_time`, `dim_asset`, `dim_source`, `dim_alert`, `fact_market_metrics`. Optional TimescaleDB hypertable.
- **Event-Time Watermarking** — Handles bounded lateness (300ms) and flags straggler data as "degraded" for downstream consumers.
- **Circuit Breaker** — Protects external API calls with configurable failure thresholds and recovery windows.

---

## Frontend Dashboard

### Component Architecture (19 Components)

| Component | Purpose | Rendering |
|-----------|---------|-----------|
| `CISSGauge` | Animated arc gauge with dynamic color | SVG + Framer Motion |
| `ScoreCards` | IF, LSTM, Combined, CISS scores | DOM with CSS transitions |
| `LiveTicker` | Scrolling price strip (18 assets) | DOM with CSS animations |
| `AnomalyTimeline` | Multi-series anomaly chart | ECharts Canvas (60fps) |
| `ContagionNetwork` | Force-directed correlation graph | Canvas 2D |
| `DefaultCards` | Merton DD/PD per bank | DOM with status badges |
| `SRISKPanel` | Aggregate systemic risk bars | DOM + CSS bars |
| `TailDependenceMatrix` | 5×5 λ_L heatmap | HTML table with color mapping |
| `VaRPanel` | VaR/CVaR across 3 methods | DOM grid |
| `CorrelationHeatmap` | Cross-asset correlation matrix | Canvas 2D |
| `ExplainabilityPanel` | Feature importance + CISS breakdown | DOM bars |
| `StressTestButton` | Crisis preset selector | Framer Motion dropdown |
| `SpeedControl` | Pipeline tick-rate control | DOM buttons |
| `AlertBanner` | Full-width crisis alert | Framer Motion slide |
| `SystemMetrics` | Throughput, latency, infra health | DOM with polling |
| `PortfolioBuilder` | Custom portfolio VaR calculator | DOM form + results grid |
| `BacktestView` | ROC curves + AUC metrics | Canvas 2D + DOM |
| `ReplayController` | Historical replay interface | DOM with progress bar |
| `StatusFooter` | Sticky footer with connection status | Fixed DOM |

### Performance Architecture

```
WebSocket ──▶ useRef buffer (no re-render)
                    │
                    ▼
         requestAnimationFrame flush
                    │
                    ▼
            useState (capped 60fps)
                    │
                    ▼
          ECharts / Canvas rendering
```

This architecture prevents React re-renders at 25 Hz from thrashing the DOM. The RAF-buffered hook batches WebSocket messages and only triggers setState on animation frames.

---

## Crisis Simulation Engine

### Available Presets

| Preset | Intensity | Duration | Scenario |
|--------|-----------|----------|----------|
| **Lehman 2008** | 95% | 60s | Credit contagion, interbank freeze, equity crash |
| **COVID 2020** | 80% | 45s | Liquidity crisis, circuit breakers, VIX spike to 82 |
| **SVB 2023** | 65% | 30s | Regional bank contagion, rate sensitivity shock |
| **Flash Crash** | 90% | 20s | HFT-driven liquidity vacuum, 6-minute 1000pt drop |

### What Happens During Crisis

1. **Simulator** injects correlated negative shocks across all 18 assets
2. **Isolation Forest** detects cross-sectional outliers (score spikes)
3. **LSTM** flags temporal pattern deviation (reconstruction error rises)
4. **CISS** amplifies as all 5 segments stress simultaneously (cross-correlation → 1)
5. **t-Copula** reveals tail dependence (λ_L coefficients surge)
6. **Merton DD** drops for all 5 banks (approaching default barrier)
7. **VaR/CVaR** regime shifts from NORMAL → EXTREME
8. **Alert system** fires if combined score > 0.7 (HIGH) or > 0.85 (CRITICAL)
9. **Model checkpoint** auto-saves crisis-state snapshots to disk

---

## v3 Production Features

### Event-Time Watermarking
Handles out-of-order data with bounded lateness (300ms). Straggler ticks are still processed but flagged as `is_degraded=true` for downstream consumers to handle appropriately.

### Multi-Sink Alerting
Dispatches alerts to Slack, Discord, PagerDuty, generic webhooks, and SMTP email. Includes deduplication window (default 300s) to prevent alert storms during sustained crises.

### Model Persistence
Atomic `.pkl`/`.pt` checkpointing to disk. Auto-saves on crisis detection (`MODEL_CHECKPOINT_ON_CRISIS=1`) and periodically (default 300s). Enables warm-starts when restarting the pipeline.

### Historical Replay
Replays crisis-era market data through the live pipeline at configurable speeds (1× to 500×). Preloaded crisis windows: Lehman 2008, COVID 2020, SVB 2023.

### Backtesting Harness
Runs labeled crisis CSVs through the ensemble and computes ROC/AUC, precision, recall, lead-time (how many ticks before the crisis the system alerted), and false positive rate.

### Portfolio VaR Engine
Custom portfolio construction with ticker + weight inputs. Computes Historical, Parametric, and Cornish-Fisher VaR plus CVaR (Expected Shortfall) with component-level VaR breakdown.

---

## Data Flow

```
Tick #N arrives (every 250ms default)
    │
    ├─▶ Update Isolation Forest state vector
    ├─▶ Add to LSTM temporal buffer
    ├─▶ Update CISS segment buffers
    ├─▶ Update Merton price/vol buffers
    ├─▶ Update VaR return history
    ├─▶ Update Copula GARCH residuals
    │
    ▼
Micro-batch triggers (10 ticks OR 500ms)
    │
    ├─▶ IF.predict(state_vector) → 0.37
    ├─▶ LSTM.predict() → 0.50
    ├─▶ CISS.update(tick) → 0.55
    ├─▶ Copula.update() → tail_matrix
    ├─▶ Merton.compute_all() → [DD, PD, SRISK]
    ├─▶ VaR.update() → {hist, param, cf, cvar}
    │
    ▼
Ensemble: 0.35(0.37) + 0.35(0.50) + 0.20(0.55) + 0.10(tail_avg)
    = combined_anomaly = 0.437
    │
    ├─▶ WebSocket broadcast → all connected clients
    ├─▶ Alert check (> 0.7 HIGH, > 0.85 CRITICAL)
    ├─▶ PostgreSQL INSERT (if connected)
    └─▶ Prometheus counter increment
```

---

## Running the System

### Quick Start (No Docker)

```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
cp ../.env.example ../.env
python -m uvicorn main:app --host 0.0.0.0 --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```

Open **http://localhost:3000** — the dashboard will connect via WebSocket and start streaming live data.

### Docker Compose (Full Stack)

```bash
docker compose up --build
```

This starts Redis, PostgreSQL, Backend, and Frontend. Dashboard available at **http://localhost:3000**.

### Environment Variables

See [`.env.example`](.env.example) for the complete list of 60+ configurable parameters covering infrastructure, ML tuning, ensemble weights, alerting, persistence, and replay.

---

## 5-Minute Demo Script

### Minute 0–1: System Overview
- Show the dashboard in normal state
- Point out: CISS gauge, 4 model scores, live ticker, Merton DD cards
- Explain the architecture: "6 models, micro-batched at 500ms, 36 API endpoints"

### Minute 1–2: The ML Ensemble
- Click on a Merton card to show DD/PD/SRISK details
- Scroll to the Anomaly Timeline — explain the 4 time-series
- Show the Tail Dependence Matrix — "this is what Pearson misses"

### Minute 2–3: Crisis Simulation
- Click **🔥 Simulate Crisis** → Select **2008 Lehman**
- Watch in real-time as:
  - CISS gauge climbs from ~50% → 100% CRITICAL
  - Merton cards degrade: HEALTHY → WATCH → WARNING
  - Anomaly timeline breaches the alert threshold
  - Ticker strip turns red (negative returns)
  - Footer shows "⚠ CRISIS ACTIVE"

### Minute 3–4: Risk Analysis
- Scroll to **Portfolio Builder** — compute VaR for a 60/40 portfolio
- Show the **Historical Replay** section — explain replay-through-live-pipeline
- Show **Backtest Validation** — explain ROC/AUC validation methodology

### Minute 4–5: Architecture Deep Dive
- Show `docker-compose.yml` — Redis + PostgreSQL + Backend + Frontend
- Explain dimensional modeling (Star Schema)
- Show the `.env.example` — "every parameter is tunable"
- Click **✓ Restore Normal** to end the crisis
- Close with: "This system processes 25 ticks/second through 6 ML models with sub-100ms inference latency"

---

## File Structure

```
Syntax-Cartel-DevClash/
├── backend/
│   ├── main.py                    # FastAPI app + pipeline orchestration (36 routes)
│   ├── requirements.txt           # Python dependencies
│   ├── Dockerfile                 # Multi-stage container build
│   ├── models/
│   │   ├── ensemble.py            # Micro-batch orchestrator
│   │   ├── isolation_forest.py    # IF anomaly detector
│   │   ├── lstm_autoencoder.py    # LSTM temporal detector
│   │   ├── ciss_scorer.py         # CISS systemic stress
│   │   ├── merton_model.py        # DD + SRISK
│   │   ├── copula_model.py        # t-Copula + GARCH tail dependence
│   │   └── var_calculator.py      # VaR / CVaR engine
│   ├── ingestion/
│   │   ├── simulator.py           # GBM data generator
│   │   ├── redis_streams.py       # Redis stream manager
│   │   ├── watermark.py           # Event-time watermarking
│   │   ├── replay.py              # Historical replay engine
│   │   └── finnhub_ws.py          # Live data connector
│   ├── utils/
│   │   ├── config.py              # Centralized configuration
│   │   ├── logger.py              # Structured JSON logging
│   │   ├── circuit_breaker.py     # Fault tolerance
│   │   ├── middleware.py          # Request logging + timing
│   │   ├── alerting.py            # Multi-sink dispatcher
│   │   └── model_persistence.py   # Checkpoint manager
│   ├── db/
│   │   ├── schema.sql             # Star schema DDL
│   │   ├── connection.py          # asyncpg pool manager
│   │   └── seed.sql               # Dimension seed data
│   ├── backtesting/
│   │   ├── harness.py             # Backtest runner
│   │   └── crises.py              # Labeled crisis windows
│   └── data/
│       ├── historical/            # Crisis replay CSVs
│       ├── models/                # Pre-trained model artifacts
│       └── checkpoints/           # Runtime checkpoints
├── frontend/
│   ├── src/app/
│   │   ├── page.js                # Main dashboard (19 components)
│   │   ├── layout.js              # Root layout + metadata
│   │   ├── globals.css            # 2100+ lines design system
│   │   ├── components/
│   │   │   ├── CISSGauge.jsx
│   │   │   ├── ScoreCards.jsx
│   │   │   ├── LiveTicker.jsx
│   │   │   ├── AnomalyTimeline.jsx
│   │   │   ├── DefaultCards.jsx
│   │   │   ├── ContagionNetwork.jsx
│   │   │   ├── SRISKPanel.jsx
│   │   │   ├── TailDependenceMatrix.jsx
│   │   │   ├── VaRPanel.jsx
│   │   │   ├── CorrelationHeatmap.jsx
│   │   │   ├── ExplainabilityPanel.jsx
│   │   │   ├── StressTestButton.jsx
│   │   │   ├── SpeedControl.jsx
│   │   │   ├── AlertBanner.jsx
│   │   │   ├── SystemMetrics.jsx
│   │   │   ├── PortfolioBuilder.jsx
│   │   │   ├── BacktestView.jsx
│   │   │   ├── ReplayController.jsx
│   │   │   └── StatusFooter.jsx
│   │   └── lib/
│   │       └── useWebSocket.js    # RAF-buffered WebSocket hook
│   ├── package.json
│   └── Dockerfile
├── docker-compose.yml
├── .env.example
├── IMPLEMENTATION_PLAN.md
├── WALKTHROUGH.md                 # ← You are here
└── Readme.md
```

---

*Built for DevClash 2026 by Team Syntax Cartel.*
