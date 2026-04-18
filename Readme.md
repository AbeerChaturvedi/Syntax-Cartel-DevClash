# 🛡️ Project Velure

### Real-Time Financial Crisis Early Warning System

> **DevClash 2026 — Team Syntax Cartel**

An event-driven, production-grade system that detects systemic financial crises **in real-time** using an ensemble of four ML/quant models processing **18 correlated assets at 4–25 Hz**, with Redis Streams event-driven architecture, PostgreSQL star-schema persistence, and a 60fps WebSocket-driven dashboard.

---

## Why This Matters

The 2008 crisis, COVID crash, and SVB collapse all shared a pattern: **systemic risk signals existed days before markets collapsed**, but no unified system combined cross-asset anomaly detection, credit risk models, and correlation analysis in real-time.

**Velure solves this.** It fuses four complementary models into one system that gives portfolio managers, regulators, and risk desks a single pane of glass showing when markets transition from noise to contagion.

---

## System Architecture

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  GBM Simulator   │     │   Redis Streams   │     │   ML Ensemble       │
│  18 assets, 4Hz  │────▶│   (Event Queue)   │────▶│   Micro-Batch       │
│  Correlated Mkt  │     │   Backpressure    │     │   IF + LSTM + CISS  │
│  Crisis Injection│     │   Fallback Queue  │     │   + Merton DD       │
└─────────────────┘     └──────────────────┘     └────────┬────────────┘
                                                           │
                    ┌──────────────────────────────────────┘
                    │
          ┌────────▼─────────┐     ┌─────────────────────┐
          │  FastAPI + WS    │     │  Next.js Dashboard   │
          │  REST + WebSocket│────▶│  ECharts + Canvas    │
          │  CORS + Lifecycle│     │  60fps RAF Buffer    │
          └────────┬─────────┘     └─────────────────────┘
                   │
          ┌────────▼─────────┐
          │  PostgreSQL 16   │
          │  Star Schema     │
          │  Kimball DW      │
          └──────────────────┘
```

## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| **Simulation** | Geometric Brownian Motion + Cholesky decomp | Realistic correlated multi-asset returns |
| **Live Data** | Finnhub WebSocket (11 symbols) | Real-time equities, FX, crypto with OHLCV aggregation |
| **Message Queue** | Redis 7 Streams + asyncio.Queue fallback | Event-driven decoupling with backpressure |
| **Anomaly Detection** | scikit-learn Isolation Forest (200 trees) | Cross-sectional anomaly scoring |
| **Temporal Detection** | PyTorch LSTM Autoencoder (72→32→72) | Regime-change detection via reconstruction error |
| **Systemic Stress** | ECB CISS methodology (SciPy) | Correlation-weighted composite stress index |
| **Credit Risk** | Merton structural model + SRISK | Distance-to-Default + systemic capital shortfall |
| **API** | FastAPI + uvicorn async | Sub-ms routing, native WebSocket support |
| **Database** | PostgreSQL 16 + asyncpg | Star schema fact tables, dimension modeling |
| **Frontend** | Next.js 16 + React 19 | Server components, Turbopack |
| **Charts** | ECharts 6 (Canvas) + Canvas 2D API | GPU-accelerated 60fps rendering |
| **Animation** | Framer Motion 12 | Physics-based UI transitions |
| **Infra** | Docker Compose (4 services) | One-command deployment |

## ML Models

| Model | Architecture | Input | Output | Purpose |
|-------|-------------|-------|--------|---------|
| **Isolation Forest** | 200 estimators, contamination=0.05 | 72-dim state vector (18 assets × 4 features) | Anomaly score [0,1] | Detects cross-asset statistical outliers |
| **LSTM Autoencoder** | Encoder: LSTM(72→64→32), Decoder: LSTM(32→64→72) | 60-tick sequence window | Reconstruction error → score [0,1] | Detects temporal regime changes |
| **CISS** | Empirical CDF + correlation-weighted quadratic form | 5 market segments (equity, FX, rates, credit, vol) | Systemic stress [0,1] | ECB-inspired composite stress index |
| **Merton DD** | Structural: DD = [ln(A/L) + (μ-σ²/2)T] / σ√T | Per-institution equity vol, leverage | Distance-to-Default, P(Default), SRISK | Institutional credit risk |

**Ensemble weights:** IF (0.4) + LSTM (0.4) + CISS (0.2) → Combined anomaly score

**Alert thresholds:** Combined > 0.7 → HIGH | > 0.85 → CRITICAL

## Key Features

- **Real-time pipeline** — 4–25 Hz configurable tick rate, sub-100ms inference latency
- **4-model ML ensemble** — Micro-batch processing (flush every 10 ticks or 500ms)
- **CISS Gauge** — SVG arc gauge with severity color transitions
- **Merton Distance-to-Default** — 5 tracked institutions (JPM, GS, BAC, C, MS)
- **System SRISK** — Aggregate capital shortfall with per-institution breakdown
- **Crisis Presets** — One-click Lehman 2008, COVID 2020, SVB 2023, Flash Crash scenarios
- **Speed Control** — Slow (2 tps) / Normal (4) / Fast (10) / Turbo (25) for demo
- **Anomaly Timeline** — ECharts canvas with 4 overlaid model score series
- **Correlation Heatmap** — Canvas 2D rendered cross-asset matrix
- **Explainability (XAI)** — Feature importance + CISS segment breakdown
- **Pipeline Health** — Live throughput, latency, Redis/PostgreSQL status monitoring
- **Star Schema** — Kimball fact/dimension tables with time, asset, source, alert dims
- **Graceful degradation** — Redis down → in-process queue; DB down → continues without persistence
- **VaR/CVaR Calculator** — 3 methods (Historical, Parametric, Cornish-Fisher) with risk regime detection
- **Contagion Network** — Force-directed graph showing cross-asset correlation propagation
- **Finnhub Live Connector** — Real-time WebSocket data from 11 symbols (equities, FX, crypto)
- **Circuit Breakers** — 3-state (CLOSED/OPEN/HALF_OPEN) for Redis and PostgreSQL fault isolation
- **Structured JSON Logging** — Per-component loggers with timestamp, level, and context fields
- **Rate Limiting** — Sliding-window per-IP rate limiter (configurable via env)
- **Prometheus Metrics** — `/metrics` endpoint with 16 metric families for Grafana/Alertmanager
- **Deep Health Check** — `/health` endpoint with circuit breaker status and component readiness

## Quick Start

### Option 1: Docker (Recommended)
```bash
docker-compose up --build
```
Open **http://localhost:3000**

### Option 2: Local Development
```bash
# Terminal 1 — Backend
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm install
npm run dev
```
Open **http://localhost:3000**

## Demo Script (5 Minutes)

1. **[0:00–0:30] Normal Markets** — Show live streaming data, CISS gauge at green, all models scoring low
2. **[0:30–1:00] Explain Architecture** — Point to pipeline health panel showing tps, Redis Streams, DB writes
3. **[1:00–2:00] Trigger Lehman 2008** — Click preset, watch correlations spike, CISS gauge sweep to red, Merton DD collapse
4. **[2:00–3:00] Show SRISK Panel** — Total capital shortfall climbing, per-institution bars filling, CRITICAL status
5. **[3:00–3:30] Explainability** — Show which features drove the alert, CISS segment breakdown
6. **[3:30–4:00] Recovery** — Deactivate crisis, watch models return to baseline, demonstrate adaptive thresholding
7. **[4:00–5:00] Architecture Deep-Dive** — Redis Streams decoupling, micro-batch inference, star schema, RAF pattern

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | System status |
| `GET` | `/health` | Deep health check (pipeline, Redis, PostgreSQL, circuit breakers) |
| `GET` | `/metrics` | Prometheus text exposition metrics (Grafana/Alertmanager compatible) |
| `GET` | `/api/scores` | Latest ML scores |
| `GET` | `/api/merton` | Institution DD scores |
| `GET` | `/api/merton/srisk` | Aggregate SRISK |
| `GET` | `/api/ciss/breakdown` | CISS component decomposition |
| `GET` | `/api/var` | VaR/CVaR risk metrics (Historical, Parametric, Cornish-Fisher) |
| `GET` | `/api/alerts` | Recent alert history |
| `GET` | `/api/metrics` | Pipeline health metrics |
| `GET` | `/api/crisis-presets` | Available crisis scenarios |
| `GET` | `/api/config` | System configuration |
| `POST` | `/api/stress-test/activate` | Custom crisis injection |
| `POST` | `/api/stress-test/preset` | Named crisis scenario |
| `POST` | `/api/stress-test/deactivate` | Restore normal markets |
| `POST` | `/api/speed/{mode}` | Set pipeline speed (slow/normal/fast/turbo) |
| `WS` | `/ws/dashboard` | Live streaming WebSocket |

## Database Schema

**Kimball Star Schema** with fact/dimension modeling:

- `fact_market_metrics` — 15 measures per tick (price, vol, scores, anomaly flags)
- `dim_time` — Time hierarchy (hour, day, session, market state)
- `dim_asset` — 20 assets across 5 classes (equity, FX, bonds, crypto, rates)
- `dim_source` — 5 data providers
- `dim_alert` — Crisis alerts with severity, model source, scores

## Project Structure

```
├── docker-compose.yml          # 4-service orchestration
├── backend/
│   ├── main.py                 # FastAPI + pipeline orchestrator (~700 lines)
│   ├── ingestion/
│   │   ├── simulator.py        # Correlated GBM market generator
│   │   ├── redis_streams.py    # Event queue with fallback
│   │   └── finnhub_connector.py# Live Finnhub WebSocket connector (11 symbols)
│   ├── models/
│   │   ├── ensemble.py         # Micro-batch ML orchestrator (fault-isolated)
│   │   ├── isolation_forest.py # Unsupervised anomaly detection
│   │   ├── lstm_autoencoder.py # Temporal pattern detection
│   │   ├── ciss_scorer.py      # ECB systemic stress index
│   │   ├── merton_model.py     # Structural credit risk
│   │   └── var_calculator.py   # VaR/CVaR (3 methods) + risk regime
│   ├── utils/
│   │   ├── config.py           # Centralized env-based configuration
│   │   ├── logger.py           # Structured JSON logging
│   │   ├── circuit_breaker.py  # 3-state circuit breakers (Redis/PostgreSQL)
│   │   └── middleware.py       # Rate limiter + API key auth
│   └── db/
│       ├── schema.sql          # Star schema DDL
│       ├── seed.sql            # Dimension data
│       └── connection.py       # asyncpg pool
└── frontend/
    └── src/app/
        ├── page.js             # Dashboard compositor
        ├── components/         # 15 specialized components
        └── lib/useWebSocket.js # RAF-buffered WS hook
```

## Team

**Syntax Cartel** — DevClash 2026
