# Project Velure — Implementation Plan (v3 — Production Track)
## Real-Time Financial Crisis Early Warning System
### DevClash 2026 — Syntax Cartel

> **Stance:** this is not a hackathon demo dressed up in production clothes.
> It is a production-grade, institutionally-defensible early warning system
> that happens to be finishable in a 48-hour sprint.

---

## 0. What Changed From v2

v2 delivered the core demo stack (GBM simulator, IF + LSTM + CISS + Merton/SRISK + VaR, Redis Streams, FastAPI/WS, Next.js dashboard, star schema, circuit breakers, Prometheus, Finnhub connector).

v3 closes five gaps that separate "demo" from "deployable":

| # | Gap | v3 Addition |
|---|-----|-------------|
| 1 | No tail-dependence model (Pearson collapses in crises) | **t-Copula + GARCH(1,1)** module producing tail-dependence matrix, lower-tail coefficient, and joint-crash probability |
| 2 | Processing-time pipeline → a single slow API stalls fusion | **Event-Time Watermarking** with bounded lateness + last-known-good patching |
| 3 | Every restart cold-starts IF + LSTM + CDF buffers | **Model persistence layer** (`.pkl`, `.pt`, compressed CDF state) with atomic writes |
| 4 | Alerts are unfalsifiable — no evidence the model would fire on real crises | **Backtesting harness** that replays historical Lehman/COVID/SVB data and computes ROC/AUC on labeled crisis dates |
| 5 | Alerts die on the WebSocket + a Python deque | **Multi-sink alert dispatcher** (Slack / Discord / PagerDuty / generic webhook / email) with severity routing + dedup |

Plus: historical replay mode, portfolio-level VaR for arbitrary user portfolios, TimescaleDB hypertable option, multi-stage Docker, smoke-tested API surface, production env split.

---

## 1. Architecture Blueprint (v3)

```
                ┌──────────────────────────────────────────────────────┐
                │                  DATA SOURCES                        │
                │  Polygon WS · Finnhub WS · FRED REST · Replay CSV    │
                │  Simulator (GBM+Cholesky) · News Sentiment (stub)    │
                └────────────────┬─────────────────────────────────────┘
                                 │ event-time tagged ticks
                                 ▼
                ┌──────────────────────────────────────────────────────┐
                │     INGESTION LAYER (async, back-pressured)           │
                │  · Connection heartbeats, exponential reconnect       │
                │  · Zero-copy normalization → canonical tick schema    │
                │  · Event-time extraction + monotonic clock skew calc  │
                └────────────────┬─────────────────────────────────────┘
                                 ▼
                ┌──────────────────────────────────────────────────────┐
                │   REDIS STREAMS (primary) / asyncio.Queue (fallback)  │
                │   · stream:market_ticks · stream:inference            │
                │   · stream:alerts     · MAX_LEN 10k, XADD ~approx     │
                │   · Circuit breaker → in-process fallback on Redis DN │
                └────────────────┬─────────────────────────────────────┘
                                 ▼
                ┌──────────────────────────────────────────────────────┐
                │   WATERMARKING + WINDOWING (new in v3)                │
                │   · Event-time watermark = max_seen - bounded_latency │
                │   · Holds window open ≤ 300ms for late arrivals       │
                │   · Emits "degraded" flag + LKG patch for stragglers  │
                └────────────────┬─────────────────────────────────────┘
                                 ▼
                ┌──────────────────────────────────────────────────────┐
                │   MICRO-BATCH ML INFERENCE (every 10 ticks or 500ms)  │
                │   ├── Isolation Forest   (global outlier)             │
                │   ├── LSTM Autoencoder   (temporal anomaly)           │
                │   ├── CISS              (ECB systemic stress)         │
                │   ├── t-Copula + GARCH  (tail dependence) ← NEW       │
                │   ├── Merton + SRISK    (credit risk)                 │
                │   ├── VaR / CVaR       (portfolio risk, 3 methods)    │
                │   └── Ensemble weighted fusion + severity classifier  │
                └──────────┬───────────────────────────┬───────────────┘
                           ▼                           ▼
     ┌────────────────────────────┐  ┌─────────────────────────────────┐
     │   ALERT DISPATCHER (NEW)    │  │   PERSISTENCE (dual-write)      │
     │   · Slack / Discord         │  │   · Postgres star schema        │
     │   · PagerDuty Events v2     │  │   · TimescaleDB hypertable opt. │
     │   · Generic webhook         │  │   · Redis score cache (30s TTL) │
     │   · Email (SMTP)            │  │   · Model checkpoint on crisis  │
     │   · Severity routing + dedup│  └─────────────────────────────────┘
     └────────────────────────────┘
                           │
                           ▼
     ┌──────────────────────────────────────────────────────────────┐
     │   FASTAPI (REST + WebSocket)                                  │
     │   · /ws/dashboard broadcast (throttled server-side)           │
     │   · /api/* full REST surface (20+ endpoints)                  │
     │   · /metrics Prometheus text exposition                       │
     │   · /health deep check (CB state, pipeline, replay status)    │
     │   · Rate limiter + optional API key                           │
     └──────────────────────────────┬────────────────────────────────┘
                                    ▼
     ┌──────────────────────────────────────────────────────────────┐
     │   NEXT.JS DASHBOARD (RAF-buffered, 60fps Canvas/ECharts)     │
     │   · 15+ components, glassmorphism theme                       │
     │   · TailDependenceMatrix (new)                                │
     │   · PortfolioBuilder (new — user enters tickers + weights)    │
     │   · BacktestView (new — ROC curves over 2008/COVID/SVB)       │
     │   · ReplayController (new — stream historical data)           │
     └──────────────────────────────────────────────────────────────┘
```

---

## 2. Tech Stack (v3 — unbloated)

| Layer | Technology | Why |
|-------|-----------|-----|
| Ingestion | Python `websockets` + `aiohttp` + `asyncio` | Single async loop, zero thread contention |
| Normalization | Pydantic + canonical tick schema | Schema validation at the boundary |
| Queue | Redis Streams (primary) + `asyncio.Queue` (fallback) | Stream semantics without Kafka overhead |
| Watermarking | In-process event-time tracker | Bounded lateness, explicit LKG patching |
| ML | scikit-learn IF + PyTorch LSTM + NumPy/SciPy (Copula, GARCH, CISS, Merton, VaR) | Mature libs, no framework lock-in |
| Ensemble | Custom weighted fusion + severity classifier | Explainable; each weight auditable |
| Alerting | `aiohttp` POSTs + `smtplib` | No third-party alerting SDK — portable |
| DB | PostgreSQL 16 + asyncpg (default), TimescaleDB (opt) | Star schema default, hypertable for prod scale |
| Cache | Redis (same instance as streams) | One infra dep |
| API | FastAPI + uvicorn | Async, WebSocket-native, auto-docs |
| Frontend | Next.js 16 + React 19 + ECharts 6 + Framer Motion 12 | Server components, Canvas rendering, RAF buffer |
| Infra | Docker Compose + multi-stage Dockerfiles | One-command deploy; slim prod images |
| Observability | Prometheus text exposition + structured JSON logs | Drop into any stack |
| Deployment target | Docker Compose (dev), K8s manifests (prod, optional) | Portable |

**Explicitly rejected:**
- **Kafka** — operationally too heavy for our scale (< 50 events/sec). Redis Streams gives us partitioning + consumer groups + replay with no ZK/KRaft ops burden.
- **Ray / Spark Structured Streaming** — research proposes these. Overkill. One `asyncio` event loop handles 25 Hz comfortably; micro-batching is done in-process.
- **Kubernetes at hackathon** — Compose is faster to demo. K8s manifests ship for the `deploy/k8s/` path so a real deployment is a `kubectl apply -f` away.
- **SHAP on LSTM** — explanations are provided via IF perturbation importance + CISS segment attribution. SHAP on LSTM burns time and the output is harder to defend than a perturbation-importance bar.

---

## 3. Algorithmic Strategy (How Each Model Earns Its Weight)

### 3.1 Isolation Forest (global, cross-sectional anomaly)
- `n_estimators=200`, `contamination=0.05`, min 50 samples warm-up
- **Input:** 72-dim state vector (18 assets × 4 features: return, rolling vol, rolling-mean, max-abs-return)
- **Output:** score ∈ [0,1] + per-feature perturbation importance
- **Why:** captures sudden cross-sectional deviations that temporal models miss (e.g., all FX pairs simultaneously gap)

### 3.2 LSTM Autoencoder (temporal / regime change)
- Encoder LSTM(72→64→32) → Decoder LSTM(32→64→72)
- Sequence length 60 ticks; online training after 200-tick warm-up
- Reconstruction MSE → empirical CDF → [0,1] score
- **Why:** catches slow-building stress patterns (precursor-to-crash regimes) that the IF cross-sectional view misses

### 3.3 CISS (ECB composite stress)
- 5 market segments × empirical CDF → correlation-weighted quadratic form
- `CISS = sqrt(z' × C × z) / sqrt(n)` where `C` is rolling cross-segment correlation
- **Why:** ECB-validated methodology carries institutional credibility; its correlation weighting is already partially copula-like

### 3.4 t-Copula + GARCH(1,1) — NEW IN v3
- **Marginal:** GARCH(1,1) fit per asset class to capture volatility clustering; standardized residuals extracted
- **Joint:** t-copula with estimated degrees of freedom ν; Kendall's τ → copula parameter
- **Output:**
  - Tail-dependence coefficient λ_L ∈ [0,1] per asset pair (lower-tail: probability that asset B crashes given A crashes)
  - Average tail dependence (system-wide)
  - Joint crash probability P(R_1 < VaR_1, R_2 < VaR_2) via copula
- **Why this over Pearson:** Pearson correlation converges to zero at the exact moment (deep tail) where we need to detect contagion. t-copula preserves tail dependence even when bulk correlation is mild.

### 3.5 Merton Distance-to-Default + SRISK
- DD, PD via structural model; SRISK via LRMES × leverage × equity value
- 5 tracked SIFI banks; aggregate SRISK → system capital-shortfall metric
- **Why:** converts abstract anomaly scores into a dollar figure a regulator understands

### 3.6 VaR / CVaR
- Historical, Parametric Gaussian, Cornish-Fisher (skew/kurt-adjusted)
- 99% confidence, 500-observation rolling window
- **NEW in v3:** portfolio-level VaR — user submits `{ticker: weight}`, gets portfolio VaR back

### 3.7 Ensemble Weighted Fusion
- `combined = 0.35·IF + 0.35·LSTM + 0.20·CISS + 0.10·copula_tail` (copula adds 0.10 weight in v3)
- Severity: NORMAL < 0.3 < LOW < 0.5 < MEDIUM < 0.7 < HIGH < 0.85 ≤ CRITICAL
- Alert fires on HIGH+; dispatched through `utils/alerting.py`

---

## 4. Dimensional Data Model (Kimball Star Schema)

### Fact table
- `fact_market_metrics` — one row per (tick, asset): price, change, spread_bps, implied_vol, volume, 4 score columns, DD, PD, `is_degraded` (watermark flag — NEW)

### Dimension tables
- `dim_time` — `epoch_ms, trading_hour, day_of_week, calendar_month, market_session_state` (SCD-1)
- `dim_asset` — `ticker, asset_class, name, currency, jurisdiction, sector` (SCD-2 ready)
- `dim_source` — `provider_name, api_endpoint, latency_tier, protocol`
- `dim_alert` — `alert_type, severity, model_source, description, trigger_time`

### TimescaleDB path (opt-in via `USE_TIMESCALE=1`)
- Convert `fact_market_metrics` into a hypertable partitioned on `time_id`
- 7-day chunk interval, 30-day compression policy
- Continuous aggregate for 1-minute CISS/combined rollups

---

## 5. File Structure (v3)

```
project-velure/
├── docker-compose.yml
├── docker-compose.prod.yml              # prod overlay: multi-stage, no hot reload
├── .env.example
├── README.md / Readme.md
├── IMPLEMENTATION_PLAN.md               # (this file)
├── PLAYBOOK.md                          # 48-hour sprint schedule
├── PRODUCTION_READINESS.md              # gap analysis + deploy checklist
├── RESEARCH.md
│
├── backend/
│   ├── Dockerfile                       # multi-stage, non-root runtime
│   ├── requirements.txt
│   ├── main.py                          # FastAPI entry + pipeline orchestrator
│   ├── ingestion/
│   │   ├── simulator.py
│   │   ├── redis_streams.py
│   │   ├── finnhub_connector.py
│   │   ├── watermark.py                 # NEW — event-time tracker
│   │   └── replay.py                    # NEW — historical CSV replay engine
│   ├── models/
│   │   ├── isolation_forest.py
│   │   ├── lstm_autoencoder.py
│   │   ├── ciss_scorer.py
│   │   ├── merton_model.py
│   │   ├── var_calculator.py
│   │   ├── copula_model.py              # NEW — t-copula + GARCH(1,1)
│   │   └── ensemble.py                  # updated — includes copula in fusion
│   ├── portfolio/
│   │   └── portfolio_var.py             # NEW — user portfolio VaR
│   ├── backtesting/
│   │   ├── harness.py                   # NEW — rolling backtest engine
│   │   └── historical_crises.py         # NEW — labeled crisis windows
│   ├── utils/
│   │   ├── config.py
│   │   ├── logger.py
│   │   ├── circuit_breaker.py
│   │   ├── middleware.py
│   │   ├── alerting.py                  # NEW — webhook/email dispatcher
│   │   └── model_persistence.py         # NEW — atomic checkpoint/restore
│   └── db/
│       ├── schema.sql
│       ├── schema_timescale.sql         # NEW — hypertable variant
│       ├── seed.sql
│       └── connection.py
│
├── frontend/
│   ├── Dockerfile                       # multi-stage, standalone output
│   ├── package.json
│   └── src/
│       ├── lib/useWebSocket.js
│       └── app/
│           ├── layout.js
│           ├── page.js
│           ├── globals.css
│           └── components/
│               ├── CISSGauge.jsx
│               ├── ScoreCards.jsx
│               ├── LiveTicker.jsx
│               ├── AnomalyTimeline.jsx
│               ├── DefaultCards.jsx
│               ├── CorrelationHeatmap.jsx
│               ├── ExplainabilityPanel.jsx
│               ├── AlertBanner.jsx
│               ├── StressTestButton.jsx
│               ├── SRISKPanel.jsx
│               ├── SystemMetrics.jsx
│               ├── StatusFooter.jsx
│               ├── VaRPanel.jsx
│               ├── ContagionNetwork.jsx
│               ├── TailDependenceMatrix.jsx   # NEW
│               ├── PortfolioBuilder.jsx       # NEW
│               ├── BacktestView.jsx           # NEW
│               └── ReplayController.jsx       # NEW
│
├── data/
│   ├── historical/                      # labeled crisis CSVs (2008, 2020, 2023)
│   └── checkpoints/                     # model .pkl / .pt snapshots
│
├── deploy/
│   ├── k8s/                             # Kubernetes manifests (optional)
│   ├── grafana/                         # dashboard JSON
│   └── nginx.conf                       # reverse proxy config
│
└── tests/
    ├── test_ensemble.py
    ├── test_watermark.py
    ├── test_copula.py
    └── test_alerting.py
```

---

## 6. API Surface (v3)

### REST
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/` | System status |
| GET | `/health` | Deep health check (pipeline, Redis, PG, circuit breakers, replay) |
| GET | `/metrics` | Prometheus text exposition |
| GET | `/api/scores` | Latest ML ensemble scores |
| GET | `/api/merton` | Per-institution DD/PD/SRISK |
| GET | `/api/merton/srisk` | Aggregate SRISK |
| GET | `/api/ciss/breakdown` | CISS component decomposition |
| GET | `/api/copula` | **NEW** t-copula tail-dependence matrix + joint crash prob |
| GET | `/api/var` | VaR/CVaR (3 methods) on default asset basket |
| POST | `/api/var/portfolio` | **NEW** VaR on user-supplied `{ticker: weight}` portfolio |
| GET | `/api/alerts` | Recent alerts (in-memory) |
| GET | `/api/metrics` | Pipeline metrics (throughput, latency, watermark lag) |
| GET | `/api/crisis-presets` | Named crisis scenarios |
| GET | `/api/config` | System configuration |
| POST | `/api/stress-test/activate` | Custom crisis injection |
| POST | `/api/stress-test/preset` | Named preset |
| POST | `/api/stress-test/deactivate` | Restore normal |
| POST | `/api/speed/{mode}` | slow/normal/fast/turbo |
| POST | `/api/replay/start` | **NEW** Stream historical crisis data through pipeline |
| POST | `/api/replay/stop` | **NEW** Stop replay |
| GET | `/api/replay/status` | **NEW** Replay progress |
| POST | `/api/backtest/run` | **NEW** Run backtest against labeled crisis dates |
| GET | `/api/backtest/results` | **NEW** Retrieve latest backtest ROC/AUC |
| POST | `/api/alerting/test` | **NEW** Send a test alert through configured sinks |
| POST | `/api/checkpoint/save` | **NEW** Force model checkpoint to disk |
| POST | `/api/checkpoint/load` | **NEW** Restore models from checkpoint |

### WebSocket
| Path | Purpose |
|------|---------|
| `/ws/dashboard` | Live score + market + alert stream |

---

## 7. Production-Readiness Features (v3)

| Concern | Implementation |
|---------|----------------|
| Cold start | `model_persistence.py` atomically writes `.pkl`/`.pt` + CDF/buffer state on SIGTERM and on every CRITICAL alert; restores on boot |
| Alert fan-out | `alerting.py` dispatches to Slack, Discord, PagerDuty v2, generic webhook, SMTP email; severity routing; 5-min dedup key |
| Event-time correctness | `watermark.py` tracks max_seen event timestamp, bounded lateness 300ms, LKG patches missing streams, flags `is_degraded=True` |
| Backtest validation | `backtesting/harness.py` streams labeled historical CSVs through the full ensemble; emits ROC/AUC, false-positive rate, lead time |
| Portfolio support | `portfolio/portfolio_var.py` accepts user portfolio; computes portfolio VaR + component VaR per position |
| TimescaleDB | `schema_timescale.sql` converts fact table to hypertable + continuous aggregates |
| Multi-stage Docker | Slim python:3.12-slim runtime, non-root user, distroless-style |
| K8s path | `deploy/k8s/*.yaml` Deployment/Service/Ingress + PodDisruptionBudget |
| Observability | Prometheus `/metrics` already live; `deploy/grafana/` ships a starter dashboard |
| Tests | `tests/` — pytest for ensemble, watermark, copula, alerting critical paths |

---

## 8. 48-Hour Sprint Schedule

See `PLAYBOOK.md` for the hour-by-hour schedule. High-level phase map:

```
H00-H04  Ingestion + Redis Streams wiring (DONE in v2)
H04-H10  Model stack: IF + LSTM + CISS + Merton + VaR (DONE in v2)
H10-H14  Copula + GARCH + Watermarking (v3 NEW)
H14-H20  FastAPI + WS broadcast + REST (DONE; extend with v3 endpoints)
H20-H28  Next.js dashboard + charts (DONE; add 4 new components)
H28-H32  Alerting + model persistence (v3 NEW)
H32-H36  Backtesting harness + historical replay (v3 NEW)
H36-H40  Portfolio VaR + TimescaleDB path (v3 NEW)
H40-H44  Docker hardening + K8s manifests + Grafana (v3 NEW)
H44-H46  Integration testing + load testing + fix list
H46-H48  Demo rehearsal + pitch deck + demo-video fallback
```

---

## 9. Demo Script (7 Minutes — v3)

1. **[0:00–0:30]** Boot dashboard. Normal market — CISS green, copula tail-λ < 0.2, SRISK near zero, all institutions HEALTHY
2. **[0:30–1:00]** Call out system-metrics panel: live tps, watermark lag, Redis connected, Postgres writes/sec
3. **[1:00–1:30]** Turbo speed (25 Hz) — show system absorbing velocity; no lag; pipeline latency stays < 50 ms
4. **[1:30–3:00]** Click **Lehman 2008** preset → correlations spike → copula tail-dependence matrix turns red → CISS sweeps to red → 5 institutions drop to CRITICAL → SRISK aggregate rockets → HIGH/CRITICAL alerts fire and dispatch to Slack in real time
5. **[3:00–3:45]** Pull up **Backtest View** — show ROC curve over labeled crisis windows (Lehman Sep-15-2008, COVID Mar-09-2020, SVB Mar-10-2023), AUC figures, and lead time histogram
6. **[3:45–4:30]** Open **Portfolio Builder** — paste a user portfolio (e.g., 60% SPY / 30% TLT / 10% GLD), hit compute, show portfolio VaR/CVaR + component VaR
7. **[4:30–5:15]** Trigger **Historical Replay** — stream actual 2008 tick data through the pipeline at 10× speed, watch the models light up on the real event
8. **[5:15–6:00]** Deactivate crisis → models recover → show **model checkpoint saved on crisis** log line → restart backend → models warm-start from disk, no cold-start window
9. **[6:00–7:00]** Architecture deep-dive: copula vs Pearson (why this matters), event-time watermarking (why the system doesn't lie during stragglers), multi-sink alerting, K8s manifests in `deploy/`

---

## 10. Build Status

### ✅ Completed in v2
- [x] Monorepo + Docker Compose + env config
- [x] PostgreSQL star schema (DDL + seed + asyncpg pool)
- [x] Correlated GBM simulator + crisis injection + 4 presets
- [x] Isolation Forest with perturbation feature importance
- [x] LSTM Autoencoder (online training, CDF scoring)
- [x] CISS scorer (5 segments, empirical CDF, correlation-weighted)
- [x] Merton DD + SRISK for 5 SIFI banks
- [x] VaR/CVaR (Historical, Parametric, Cornish-Fisher)
- [x] Ensemble orchestrator (weighted fusion + severity)
- [x] Redis Streams publish/consume + asyncio fallback
- [x] FastAPI server + WebSocket + REST surface
- [x] Stress test + speed control endpoints
- [x] Pipeline health metrics
- [x] Dashboard (15 components, glassmorphism)
- [x] `useWebSocket` RAF-buffered hook
- [x] Circuit breakers + structured JSON logs + rate limiter
- [x] Prometheus `/metrics` + deep `/health`
- [x] Finnhub WebSocket live connector
- [x] Docker health checks

### 🆕 In Progress / v3 Additions
- [ ] `copula_model.py` — t-copula + GARCH(1,1) tail dependence
- [ ] `watermark.py` — event-time watermarking with bounded lateness
- [ ] `model_persistence.py` — atomic checkpoint/restore
- [ ] `alerting.py` — multi-sink dispatcher (Slack/Discord/PD/webhook/email)
- [ ] `replay.py` — historical CSV replay engine
- [ ] `backtesting/harness.py` + `historical_crises.py` — ROC/AUC validation
- [ ] `portfolio/portfolio_var.py` — user portfolio VaR endpoint
- [ ] `schema_timescale.sql` + hypertable migration
- [ ] `TailDependenceMatrix.jsx`, `PortfolioBuilder.jsx`, `BacktestView.jsx`, `ReplayController.jsx`
- [ ] Multi-stage Dockerfile hardening + `docker-compose.prod.yml`
- [ ] `deploy/k8s/` manifests + `deploy/grafana/` dashboard
- [ ] `tests/` — pytest coverage of critical paths
- [ ] `PLAYBOOK.md` + `PRODUCTION_READINESS.md`

---

## 11. Key Design Decisions (with rationale)

| Decision | Why |
|----------|-----|
| Redis Streams over Kafka | Our scale (< 50 ev/s) doesn't justify Kafka ops burden |
| t-copula over vine copulas | Vine copulas are more flexible but need 10× data; t-copula captures the core tail behavior |
| GARCH(1,1) over EGARCH/GJR | (1,1) handles vol clustering; asymmetry captured implicitly by copula |
| In-process watermarking over Flink | Single-asyncio-loop gives us sub-ms dispatch; Flink adds JVM + another service |
| Model persistence to disk (not DB) | Fast, atomic via rename; checkpoints are blobs not records |
| Multi-sink alerting via aiohttp | Zero SDK lock-in; every sink is one POST |
| Backtest replays real CSVs through the live pipeline | Proves the *shipping code* works; not a separate research harness |
| Portfolio VaR on-demand (not streaming) | User-facing; caching is a future optimization |
| TimescaleDB as opt-in | Default to vanilla PG so new contributors aren't blocked |
| No SHAP on LSTM | Kernel SHAP on a recurrent model is slow, fragile, and harder to defend than IF perturbation + CISS attribution |

---

## 12. Out-of-Scope (Explicitly)

- GPU inference: CPU handles 25 Hz comfortably
- Kafka / Spark: rejected above
- Multi-tenant auth: single-tenant is sufficient for the prototype
- Real brokerage integration: not a trading system — it's a monitor
- Mobile-native app: responsive web is enough
- LLM-driven commentary: hallucination risk too high for a risk product

---

## 13. How to Run

### Dev (hot reload)
```bash
docker-compose up --build
# or locally:
cd backend && pip install -r requirements.txt && uvicorn main:app --reload
cd frontend && npm install && npm run dev
```

### Production overlay
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Environment flags (see `.env.example`)
```
DATA_MODE=simulator|finnhub|hybrid|replay
USE_TIMESCALE=0|1
ALERT_SLACK_WEBHOOK=https://hooks.slack.com/...
ALERT_PAGERDUTY_KEY=...
ALERT_EMAIL_FROM/TO/SMTP_...=...
MODEL_CHECKPOINT_DIR=/app/data/checkpoints
MODEL_CHECKPOINT_ON_CRISIS=1
WATERMARK_LATENESS_MS=300
```

---
