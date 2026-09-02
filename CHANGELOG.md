# Changelog

All notable changes to Project Velure will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Versions are not yet tagged — this file is a running history of merged work. The first formal release will cut `v1.0.0`.

## [Unreleased]

### Added
- Twelve Data connector with news-feed fallback for hybrid ingestion mode.
- Model checkpoint persistence (periodic + on-crisis) so the ensemble survives restarts.
- Frozen historical crisis fixtures (2008 Lehman, 2010 Flash Crash, 2015 China deval, 2018 Q4 selloff, 2020 COVID, 2023 SVB) under `crisis-simulation-data/`.
- LSTM Autoencoder retrained on real-data scaling (resolves prior 100%-anomaly false-positive).
- Replay engine with variable speed multiplier and event-time watermarking.
- Alerting sinks: Slack, Discord, PagerDuty, SMTP, generic webhook — with `urllib` fallback when `aiohttp` is unavailable.
- `.env.example` documenting every supported environment variable.

### Changed
- Pipeline micro-batching tuned to 10 ticks / 500 ms for the latency/throughput sweet spot.
- CISS scorer now self-calibrates against rolling baselines; segment gauges reflect the same calibration the combined score uses.
- Merton Distance-to-Default plumbed end-to-end with per-bank PD% and SRISK contribution.
- Postgres port no longer published in `docker-compose.yml` (avoids the WSL `docker-proxy` collision); backend reaches it via Docker DNS.

### Fixed
- `dim_source` persistence: schema column is `provider_name`, not `source_name`.
- `/api/metrics` globals references after merge.
- Backtesting harness pipeline reset between crises (prior version carried state across windows, inflating AUC).
- Ensemble lead time moved from 0 → +7.4 days on labelled crisis windows.
- CORS preflight (`OPTIONS`) accepted by the API router.

### Security
- Production overrides strip the published Postgres port, mount secrets via `env_file` only, and enforce non-root runtime users in both Dockerfiles.

## [0.1.0] — Initial hackathon submission

- Real-time streaming pipeline over Redis Streams (4–25 Hz).
- Six-model ensemble: Isolation Forest, LSTM Autoencoder, ECB-style CISS, Merton DD/SRISK, t-Copula + GARCH, VaR / CVaR.
- Next.js 16 dashboard with ECharts, Three.js contagion graph, and crisis-simulation controls.
- Docker Compose orchestration with health-gated startup order.
