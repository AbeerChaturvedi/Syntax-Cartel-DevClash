<div align="center">

# Project Velure

**A Real-Time Financial Crisis Early Warning System**

*Multi-model streaming AI that detects systemic risk before it cascades — built for the DevClash 2026 hackathon by Team Syntax Cartel.*

[![Live Demo](https://img.shields.io/badge/demo-running-2ea043?style=for-the-badge)](https://github.com/AbeerChaturvedi/Syntax-Cartel-DevClash)
[![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20Next.js%2016%20%7C%20Postgres%2016%20%7C%20Redis%207-1f6feb?style=for-the-badge)](#tech-stack)
[![Python 3.11](https://img.shields.io/badge/python-3.11-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/release/python-3110/)
[![Next.js 16](https://img.shields.io/badge/next.js-16-black?style=for-the-badge&logo=next.js&logoColor=white)](https://nextjs.org)

</div>

---

## Why Velure

Financial crises are not unpredictable. They follow recognizable patterns — correlation spikes, volatility clustering, tail-dependence surges, credit-spread widening, liquidity dry-ups. The problem is never a lack of data, it is the inability to process that data fast enough, through the right models, and present it clearly enough for humans to act on.

Velure solves all three:

| Dimension | What Velure does |
|-----------|------------------|
| **Speed** | 4–25 Hz tick processing with sub-100 ms inference |
| **Intelligence** | Six complementary ML models covering every dimension of systemic risk |
| **Clarity** | A premium, real-time dashboard that makes complex risk instantly understandable |

It ingests live market data from **18 financial instruments across 5 segments** (equities, FX, rates, credit, crypto), streams it through a six-model ensemble — Isolation Forest, LSTM Autoencoder, ECB-style CISS stress, Merton Distance-to-Default, t-Copula tail-dependence, and parametric + historical + Cornish-Fisher VaR/CVaR — and fuses their outputs into a single 0→1 systemic-risk score with severity tiers (NORMAL → ELEVATED → HIGH → SEVERE → CRITICAL).

---

## Table of Contents

1. [Architecture at a glance](#architecture-at-a-glance)
2. [Tech stack](#tech-stack)
3. [Repository layout](#repository-layout)
4. [Quick start (Docker, recommended)](#quick-start-docker-recommended)
5. [Quick start (manual / local development)](#quick-start-manual--local-development)
6. [Environment configuration](#environment-configuration)
7. [Useful endpoints](#useful-endpoints)
8. [Crisis simulation](#crisis-simulation)
9. [Documentation index](#documentation-index)
10. [Testing](#testing)
11. [Deployment](#deployment)
12. [Project status](#project-status)
13. [Team](#team)
14. [License](#license)

---

## Architecture at a glance

```
                 ┌────────────────────────────────────────────────────────┐
                 │                   Live Market Data                      │
                 │   Finnhub WS  •  Polygon REST  •  Twelve Data  •  News  │
                 └───────────────────────────┬────────────────────────────┘
                                             │
                                             ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                  Ingestion Layer (async producers)                       │
  │   • Rate-limited REST fetchers  • WebSocket listener  • Simulator (GBM)   │
  │   • Watermarking (event-time)  • Replay engine                           │
  └──────────────────────────────┬───────────────────────────────────────────┘
                                 │ Redis Streams (per-asset partitions)
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                    Feature & State Pipeline                              │
  │   • Rolling windows (returns, vol, spreads)  • Z-score normalization      │
  │   • Cross-asset covariance updates  • Micro-batching (10 ticks / 500ms)   │
  └──────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                    Six-Model Ensemble (parallel)                         │
  │  Isolation Forest  •  LSTM Autoencoder  •  CISS Stress                   │
  │  Merton DD/SRISK   •  t-Copula/GARCH     •  VaR / CVaR                    │
  └──────────────────────────────┬───────────────────────────────────────────┘
                                 │ Weighted fusion (35 / 35 / 20 / 10)
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │                    Postgres Persistence Layer                            │
  │   • Audit trail  • Model checkpoints  • Replay archives                   │
  │   • Crisis-window labels  • Per-bank Merton history                      │
  └──────────────────────────────┬───────────────────────────────────────────┘
                                 │ WebSocket fan-out (FastAPI)
                                 ▼
  ┌──────────────────────────────────────────────────────────────────────────┐
  │              Next.js 16 Dashboard  (60 fps, ECharts, Three.js)            │
  │   • CISS gauge  • Score cards  • Anomaly timeline  • Merton tiles         │
  │   • Tail-dependence heatmap  • Contagion network  • VaR bars              │
  │   • Live ticker  • Crisis-simulation controls                            │
  └──────────────────────────────────────────────────────────────────────────┘
```

Full design rationale and trade-offs live in [ARCHITECTURE.md](./ARCHITECTURE.md).

---

## Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Backend | **FastAPI** + **uvicorn** + **uvloop** | Async-native, type-safe, sub-100 ms p99 latency |
| Streaming bus | **Redis 7 Streams** | Native event-time ordering, consumer groups, replay |
| Persistence | **PostgreSQL 16** (TimescaleDB opt-in) | ACID for audit + checkpoints, time-series for telemetry |
| ML / numerics | **scikit-learn**, **PyTorch (CPU)**, **NumPy**, **SciPy** | All CPU-only for portability, no GPU dependency |
| Frontend | **Next.js 16** (standalone, App Router) | React 19 + Server Components, tini + non-root runtime |
| Visualisation | **ECharts**, **Three.js**, **Framer Motion**, **lucide-react** | High-density real-time charts, animated 3D contagion graph |
| Orchestration | **Docker Compose** | One-command full stack with health-gated startup |
| Alerting | Slack / Discord / PagerDuty / SMTP / generic webhook | Pluggable sinks via aiohttp (urllib fallback) |

---

## Repository layout

```
.
├── README.md                      ← you are here
├── ARCHITECTURE.md                ← system design & trade-offs
├── DEPLOY.md                      ← Render / Fly.io / TLS / prod hardening
├── PLAYBOOK.md                    ← operator runbook
├── SECURITY.md                    ← threat model, secrets, hardening
├── PRODUCTION_READINESS.md        ← gap analysis & rollout plan
├── FIXES_REQUIRED.md              ← historical defect ledger
├── IMPLEMENTATION_PLAN.md         ← forward roadmap
├── PROJECT_OVERVIEW.md            ← product narrative (audience, use cases)
├── WALKTHROUGH.md                 ← guided demo script
├── docker-compose.yml             ← default local stack (Redis + Postgres + backend + frontend)
├── docker-compose.prod.yml        ← production overrides
├── docker-compose.tls.yml         ← TLS termination layer
├── docker-compose.observability.yml ← Prometheus / Grafana add-on
├── .env.example                   ← every supported environment variable
├── backend/                       ← FastAPI service (Python 3.11)
│   ├── Dockerfile                 ← multi-stage, non-root, tini PID-1
│   ├── main.py                    ← FastAPI app, router wiring, health
│   ├── lifecycle.py               ← startup / shutdown orchestration
│   ├── Routes/                    ← HTTP + WebSocket endpoints
│   ├── ingestion/                 ← Finnhub / Twelve Data / Polygon / Simulator / Replay
│   ├── pipeline/                  ← micro-batch tasks, watermarking, calibration
│   ├── features/                  ← state builder & technical indicators
│   ├── models/                    ← the six-model ensemble
│   ├── backtesting/               ← historical crisis harness + labelled events
│   ├── database/                  ← async Postgres persistence
│   ├── db/                        ← schema.sql, seed.sql, migrations/
│   ├── portfolio/                 ← portfolio VaR / CVaR calculator
│   └── utils/                     ← config, alerting, model persistence, logger, middleware
├── frontend/                      ← Next.js 16 dashboard
│   ├── Dockerfile                 ← standalone output, non-root, tini PID-1
│   ├── AGENTS.md / CLAUDE.md      ← frontend agent rules
│   └── src/app/                   ← App Router pages & components
├── deploy/                        ← deployment helpers (Render, Fly, backup)
├── tests/                         ← pytest harness (checkpoint recovery, load)
└── crisis-simulation-data/        ← frozen historical crisis fixtures & scripts
```

---

## Quick start (Docker, recommended)

The fastest way to get the full stack — Redis, Postgres, backend, frontend — running on a laptop.

### Prerequisites

| Tool | Minimum version | Check |
|------|-----------------|-------|
| **Docker Engine** | 24.0+ | `docker --version` |
| **Docker Compose** | v2.20+ | `docker compose version` |
| **Git** | 2.30+ | `git --version` |
| Free ports | `3000`, `8000`, `6379` | `ss -tlnp \| grep -E '3000\|8000\|6379'` |

Optional for live data:

| Tool | Where to get it |
|------|-----------------|
| **Finnhub API key** | <https://finnhub.io> (free tier — WebSocket unlimited, 60 REST/min) |
| **Twelve Data API key** | <https://twelvedata.com> (free tier available) |
| **Polygon API key** | <https://polygon.io> (5 REST/min on free) |

### 1. Clone

```bash
git clone https://github.com/AbeerChaturvedi/Syntax-Cartel-DevClash.git
cd Syntax-Cartel-DevClash
```

### 2. Configure

```bash
cp .env.example .env
```

Open `.env` and decide your data mode:

| `DATA_MODE` | Behaviour | API key needed? |
|-------------|-----------|-----------------|
| `simulator` | Pure synthetic GBM stream. Zero external dependency. **Best for first run.** | No |
| `hybrid`    | Prefer live feeds; fall back to simulator when feeds are absent. | Optional |
| `finnhub` / `twelvedata` / `polygon` | Pull from a specific provider only. | Yes |

For a zero-friction first boot, leave `DATA_MODE=simulator`. To use live data, paste your key:

```env
DATA_MODE=hybrid
FINNHUB_API_KEY=your_key_here
```

### 3. Build and run

```bash
docker compose up --build
```

First boot pulls images, installs CPU-only PyTorch (≈ 250 MB), builds the Next.js standalone output, runs the Postgres schema, and starts everything. Wait for the line:

```
backend-1  | Application startup complete.
frontend-1 | ▲ Next.js 16 ... ready in ...
```

### 4. Open the dashboard

| URL | What you'll see |
|-----|-----------------|
| <http://localhost:3000> | The live dashboard with charts, gauges, and crisis controls |
| <http://localhost:8000/health> | Backend liveness probe (returns `{"status":"ok"}`) |
| <http://localhost:8000/docs> | Interactive FastAPI / OpenAPI explorer |
| <http://localhost:8000/api/metrics> | Current snapshot of every model score |

You should see the **CISS gauge** drifting gently between NORMAL and ELEVATED as synthetic ticks arrive at ~4 Hz.

### 5. Tear down

```bash
docker compose down            # stop, keep volumes
docker compose down -v         # stop AND wipe Postgres + model checkpoints
```

---

## Quick start (manual / local development)

Useful when you want hot-reload on the backend, or when Docker is not available (e.g. native Windows).

### Prerequisites

| Tool | Version |
|------|---------|
| **Python** | 3.11 |
| **Node.js** | 22+ (Next.js 16 requires ≥ 18.18) |
| **Redis** | 7+ |
| **PostgreSQL** | 16+ |
| **uv** (recommended) or pip | latest |

### Backend

```bash
cd backend

# Create a venv
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install CPU-only PyTorch first (saves ~1.7 GB), then the rest
pip install torch==2.4.0 --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt

# Point at locally-running services
export REDIS_HOST=localhost
export POSTGRES_HOST=localhost
export DATA_MODE=simulator

# Load the schema once
psql "postgresql://velure:velure_hackathon_2026@localhost:5432/velure" \
     -f db/schema.sql

# Run
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

Backend now serves on `http://localhost:8000`. Hot-reload picks up changes to anything under `backend/`.

### Frontend

```bash
cd frontend

npm install
npm run dev
```

Dashboard is at `http://localhost:3000`. The dev server proxies API/WebSocket calls to the backend on port 8000 by default — see `next.config.mjs` if you need to override.

---

## Environment configuration

All configuration is read from environment variables. The full schema lives in [`.env.example`](./.env.example). Key groups:

| Group | Purpose | Examples |
|-------|---------|----------|
| **Infrastructure** | Redis + Postgres endpoints | `REDIS_HOST`, `POSTGRES_HOST`, `POSTGRES_PASSWORD` |
| **Data mode** | Where ticks originate | `DATA_MODE`, `ENABLE_SIMULATOR` |
| **Live data** | API keys & rate limits | `FINNHUB_API_KEY`, `TWELVE_DATA_API_KEY`, `POLYGON_API_KEY` |
| **Pipeline tuning** | Throughput vs latency | `TICK_RATE`, `BATCH_SIZE`, `FLUSH_INTERVAL_MS` |
| **ML tuning** | Model hyperparameters | `IF_CONTAMINATION`, `LSTM_HIDDEN_DIM`, `CISS_WINDOW` |
| **Ensemble weights** | Fusion formula (must sum to 1.0) | `ENSEMBLE_IF_WEIGHT`, `ENSEMBLE_LSTM_WEIGHT`, … |
| **Alert thresholds** | Severity boundaries | `ALERT_THRESHOLD_HIGH`, `ALERT_THRESHOLD_CRITICAL` |
| **Alerting** | Webhook sinks | `ALERT_SLACK_WEBHOOK`, `ALERT_EMAIL_SMTP_HOST` |
| **Model persistence** | Checkpoint cadence | `MODEL_CHECKPOINT_ON_CRISIS`, `MODEL_CHECKPOINT_PERIODIC_SEC` |
| **Replay** | Historical playback | `REPLAY_DATA_DIR`, `REPLAY_SPEED_MULTIPLIER` |
| **Frontend** | Public URLs baked at build time | `NEXT_PUBLIC_WS_URL`, `NEXT_PUBLIC_API_URL` |

> ⚠️ Anything starting with `NEXT_PUBLIC_` is inlined into the JS bundle at **build time**. Restart `npm run dev` (or `docker compose build frontend`) after changing them.

---

## Useful endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/health` | Liveness — `{"status":"ok"}` |
| `GET` | `/api/metrics` | Current snapshot of every model + combined score |
| `GET` | `/api/system/status` | Component health (Redis, Postgres, models, producer) |
| `GET` | `/api/models` | Per-model metadata, weights, training timestamps |
| `GET` | `/api/stress/ciss` | Latest CISS sub-segments |
| `GET` | `/api/portfolio/var` | VaR / CVaR / component contributions |
| `GET` | `/api/replay/crises` | Available historical crisis windows |
| `POST` | `/api/replay/start` | Begin replay of a labelled crisis |
| `POST` | `/api/crisis/trigger` | Inject a simulated crisis pattern into the live stream |
| `POST` | `/api/speed` | Adjust `TICK_RATE` preset (`slow` / `normal` / `fast` / `turbo`) |
| `WS` | `/ws/dashboard` | Streaming snapshot feed for the frontend |
| `WS` | `/ws/alerts` | Real-time alert dispatch (Slack/Discord/etc. mirror) |

Full request/response schemas and live "try it" UI are at <http://localhost:8000/docs>.

---

## Crisis simulation

Click any **crisis button** in the dashboard (`2008 Lehman`, `2020 COVID`, `2023 SVB`, …). The simulator:

1. Injects a historically-calibrated shock pattern into the live data stream using correlated Geometric Brownian Motion with regime-switched parameters.
2. Lets the six models react in real time — you watch CISS climb, Merton DD shrink, the tail-dependence matrix light up, and VaR regime flip to EXTREME.
3. Restores normality over ~30 seconds after the crisis window closes.

For labelled backtesting against frozen fixtures, see `crisis-simulation-data/` and `backend/backtesting/`.

---

## Documentation index

| Doc | Audience | What it covers |
|-----|----------|----------------|
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Engineers | Component design, data flow, model contracts, schema |
| [PROJECT_OVERVIEW.md](./PROJECT_OVERVIEW.md) | Stakeholders | What, why, who it's for, differentiators |
| [WALKTHROUGH.md](./WALKTHROUGH.md) | Demonstrators | Step-by-step demo script with talking points |
| [DEPLOY.md](./DEPLOY.md) | Operators | Render, Fly.io, TLS, observability, prod hardening |
| [SECURITY.md](./SECURITY.md) | Security review | Threat model, secrets, network policy, rate limiting |
| [PRODUCTION_READINESS.md](./PRODUCTION_READINESS.md) | SRE / leads | Gap analysis, rollout checklist, SLOs |
| [PLAYBOOK.md](./PLAYBOOK.md) | On-call | Incident triage, common failures, recovery steps |
| [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) | Maintainers | Forward roadmap, open work |
| [FIXES_REQUIRED.md](./FIXES_REQUIRED.md) | Maintainers | Historical defect ledger |
| [crisis-simulation-data/README.md](./crisis-simulation-data/README.md) | Quants / data scientists | Frozen crisis fixtures & loader scripts |
| [frontend/README.md](./frontend/README.md) | Frontend devs | Next.js-specific notes |
| [tests/load/README.md](./tests/load/README.md) | Performance | Load test scenarios |

---

## Testing

```bash
# Backend unit + integration tests
cd backend
pytest -q

# Checkpoint recovery / replay tests
cd tests
pytest -q test_checkpoint_recovery.py

# Load tests (requires the full stack running)
cd tests/load
# see tests/load/README.md
```

A writeable `data/` directory is required for model checkpoint tests; it is gitignored.

---

## Deployment

Docker-first, cloud-agnostic. Reference manifests:

| File | Use it for |
|------|------------|
| [`docker-compose.yml`](./docker-compose.yml) | Local dev, CI, single-node prod |
| [`docker-compose.prod.yml`](./docker-compose.prod.yml) | Production overrides (resource limits, restart policy, no exposed DB port) |
| [`docker-compose.tls.yml`](./docker-compose.tls.yml) | TLS termination in front of the frontend |
| [`docker-compose.observability.yml`](./docker-compose.observability.yml) | Prometheus + Grafana sidecars |
| [`deploy/postgres-backup/`](./deploy/postgres-backup) | Scheduled Postgres backup container |
| [`deploy/`](./deploy) | Render / Fly.io helper manifests |

Step-by-step production rollout, including secrets management, TLS, and observability, is in [DEPLOY.md](./DEPLOY.md).

---

## Project status

DevClash 2026 hackathon submission. The system has been end-to-end exercised against synthetic streams and labelled historical crisis fixtures (2008, 2010, 2015, 2018, 2020, 2023) with documented lead-time and AUC metrics in [`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md). Production hardening, formal SLOs, and additional asset coverage are tracked in [`PRODUCTION_READINESS.md`](./PRODUCTION_READINESS.md).

---

## Team

Built by **Team Syntax Cartel** for DevClash 2026.

- Aaditya
- Abeer Chaturvedi
- Omkar
- Parth Mande

---

## License

This project is released under the **MIT License**. See [LICENSE](./LICENSE) for the full text.

Third-party data feeds (Finnhub, Polygon, Twelve Data) are subject to their respective providers' terms of service — supply your own API keys and respect rate limits.

---

<div align="center">

**The next financial crisis will happen. The question is whether we'll see it coming.**

*Velure makes sure we do.*

</div>
