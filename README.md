# Project Velure

**A real time financial crisis early warning system.**

Velure streams live global market data through a six model machine learning
ensemble and fuses the results into a single, calibrated crisis score. It
watches equities, currencies, banks and crypto together and raises the alarm
when the signals collectively point toward a systemic breakdown, before the
crash fully unfolds.

Backtested on seven real crises from 2008 to 2023: mean area under the curve
**0.905**, with the COVID 2020 crash detected **seven days early** and zero
false alarms in calm periods for six of the seven windows.

---

## Table of contents

1. [What is inside](#what-is-inside)
2. [Requirements](#requirements)
3. [Quick start with Docker](#quick-start-with-docker)
4. [Run it locally for development](#run-it-locally-for-development)
5. [Train the models on real data](#train-the-models-on-real-data)
6. [Run the crisis backtest](#run-the-crisis-backtest)
7. [Project structure](#project-structure)
8. [Further documentation](#further-documentation)

---

## What is inside

| Layer | Technology |
|---|---|
| Backend | FastAPI, Python 3.13, async pipeline |
| Machine learning | PyTorch, scikit learn, SciPy, NumPy |
| Data and cache | PostgreSQL, Redis |
| Market feeds | Finnhub, Twelve Data, Alpha Vantage |
| Frontend | Next.js 16, React 19, ECharts, Three.js |
| Delivery | Docker Compose, WebSocket streaming |

The six models are the Isolation Forest, the LSTM Autoencoder, the CISS stress
index, the Merton distance to default model, the Student t Copula with GARCH,
and the Value at Risk engine. See [MODELS.md](MODELS.md) for the full breakdown.

---

## Requirements

* **Docker Desktop** (for the quick start, and for Redis plus PostgreSQL)
* **Python 3.13** and **Node 20** (only for the local development path)
* Free API keys for the live feeds (see the environment step below)

---

## Quick start with Docker

This builds and runs everything: Redis, PostgreSQL, the backend and the
frontend, with one command.

**1. Create your environment file** from the template and add your keys:

```bash
cp .env.example .env
```

Open `.env` and fill in the live data keys. `FINNHUB_API_KEY`,
`TWELVE_DATA_API_KEY` and `ALPHAVANTAGE_API_KEY` drive the live market and news
feeds. Every key degrades gracefully, so the system still starts without them
using the built in simulator.

**2. Start the whole stack:**

```bash
docker compose up --build
```

**3. Open the dashboard:**

* Dashboard: http://localhost:3000
* Backend API: http://localhost:8000
* Health check: http://localhost:8000/health
* Live metrics: http://localhost:8000/api/metrics

Stop everything with `docker compose down`.

---

## Run it locally for development

The fastest way to run everything locally with hot reload, from **one
terminal**. This starts Redis and PostgreSQL in Docker and runs the FastAPI
backend and the Next.js frontend together, with live reload on both.

**Start:**

```bash
./dev.sh
```

Then open **http://localhost:3000**. The first run automatically creates the
backend virtualenv, installs backend and frontend dependencies, and writes
`frontend/.env.local`, so there is nothing else to set up.

**Stop:**

Press **Ctrl+C** in the same terminal to stop the backend and frontend. For a
full stop that also shuts down the Docker services:

```bash
./stop.sh
```

> **Port note:** if you already run a local PostgreSQL on port 5432, it will
> shadow the Docker one. Publish the container on another port and set
> `POSTGRES_PORT` in `.env` to match, or stop the local service.

---

## Train the models on real data

The Isolation Forest and the LSTM Autoencoder ship trained on real calm market
history. To retrain them yourself, from the `backend` directory:

```bash
python scripts/fetch_historical.py
python scripts/train_on_real.py
```

`fetch_historical.py` pulls daily history for the fifteen tracked assets and
`train_on_real.py` trains both models and saves the checkpoint the runtime
warm starts from.

---

## Run the crisis backtest

Score the ensemble against the seven labelled historical crises, from the
`backend` directory:

```bash
python scripts/run_backtest.py --load-real
```

This prints a scorecard with area under the curve, lead time and false alarm
rate per crisis.

---

## Project structure

```
Syntax-Cartel-DevClash/
├── backend/
│   ├── main.py                 FastAPI application entry point
│   ├── lifecycle.py            Startup, checkpoint warm start, shutdown
│   ├── globals.py              Shared runtime state
│   ├── Routes/                 API routes (system, models, stress, news, ...)
│   ├── models/                 The six models plus the ensemble
│   ├── features/               State vector builder
│   ├── ingestion/              Finnhub, Twelve Data, simulator, replay
│   ├── pipeline/               The streaming task loop
│   ├── portfolio/              Portfolio Value at Risk
│   ├── backtesting/            Labelled crisis harness
│   ├── db/                     Connection, schema, migrations, persistence
│   ├── utils/                  Config, alerting, checkpoints, logging
│   └── scripts/                Data fetch, training, backtest tools
├── frontend/
│   └── src/app/                Next.js dashboard, components and styles
├── deploy/                     Deployment assets
├── dev.sh                      Start everything locally with one command
├── stop.sh                     Stop everything (backend, frontend, Docker)
├── docker-compose.yml          Full stack (redis, postgres, backend, frontend)
└── docs (see below)
```

---

## Further documentation

| Document | What it covers |
|---|---|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | What Velure is, why it exists, how it works |
| [MODELS.md](MODELS.md) | The six models, the ensemble and design notes |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and data flow |
| [DEPLOY.md](DEPLOY.md) | Production deployment guide |
| [SECURITY.md](SECURITY.md) | Security model and hardening |
| [RESEARCH.md](RESEARCH.md) | Research references |

---

*Project Velure · Team Syntax Cartel · MIT Academy of Engineering*
