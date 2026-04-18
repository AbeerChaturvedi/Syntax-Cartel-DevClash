# Project Velure — 48-Hour Hackathon Execution Playbook
## DevClash 2026 — Team Syntax Cartel

> **Operating principle:** every hour either moves the critical path forward,
> kills a risk, or buys insurance for the demo. Nothing else.

---

## The Golden Path (Critical Demo Arc)

If *everything else* fails, these must still work end-to-end:

1. User opens the dashboard → live ticks stream at 4 Hz → CISS gauge green
2. User clicks **Lehman 2008** preset → within 5 seconds, CISS sweeps red, SRISK spikes, alert banner fires
3. User opens **Backtest View** → ROC curve on 2008/COVID/SVB labels renders with AUC ≥ 0.8
4. Judge asks "is this real data?" → demonstrate **Historical Replay** with 2008 CSV
5. Judge asks "how does it scale?" → point at **TimescaleDB hypertable + Prometheus Grafana**

Everything else is garnish. If you're three hours in and the golden path is shaky, stop adding features.

---

## Phase Map

| Phase | Hours | Focus | Exit Criteria |
|-------|-------|-------|---------------|
| 0. Setup | 0–2 | Scaffold, env, Docker, sanity | `docker-compose up` lights up Redis + PG + empty backend |
| 1. Ingestion | 2–6 | Simulator, Redis Streams, schemas | Ticks flow end-to-end into Redis, visible via `XRANGE` |
| 2. Storage | 6–8 | Star schema + asyncpg pool | First fact-table INSERT succeeds |
| 3. Core ML | 8–16 | IF, LSTM, CISS, Merton, VaR | `/api/scores` returns all 4 scores + Merton list |
| 4. Advanced Quant | 16–20 | **Copula + GARCH + Watermarking** | Tail-dependence matrix + `is_degraded` flag in payload |
| 5. API + WS | 20–22 | FastAPI surface complete | All 20+ endpoints return 200 under smoke test |
| 6. Frontend Core | 22–30 | 15-component dashboard | Dashboard renders live at 60 fps, crisis preset works |
| 7. Frontend v3 | 30–34 | **TailDependenceMatrix, PortfolioBuilder, BacktestView, ReplayController** | New components render and wire to endpoints |
| 8. Alerting + Persistence | 34–38 | **Webhook dispatcher + model checkpoints** | Slack test alert received; crash-restart warm-starts models |
| 9. Backtest + Replay | 38–42 | **Historical CSVs + replay engine** | ROC/AUC computed; 2008 replay runs through pipeline |
| 10. Prod Hardening | 42–45 | Multi-stage Docker, TimescaleDB, K8s manifests | `docker-compose.prod.yml` boots cleanly; `kubectl apply -f deploy/k8s/` is valid |
| 11. Test + Fix | 45–46 | Load test + fix list | 5-minute load test at turbo speed, no leaks |
| 12. Demo Prep | 46–48 | Rehearsal, video capture, pitch | 7-minute demo run cold, twice |

---

## Hour-by-Hour

### Setup (H00 – H02) — Risk: low
**H00** Clone scaffold · init git · write `.env.example` · create `docker-compose.yml` skeleton with Redis 7, Postgres 16, backend, frontend services · verify `docker-compose up` starts Redis + PG
**H01** Backend Dockerfile skeleton · install `requirements.txt` · frontend `create-next-app` · `next dev` loads empty page · verify CORS is open for local

### Ingestion (H02 – H06) — Risk: medium
**H02** Write `ingestion/simulator.py` — correlated GBM with Cholesky decomposition, 18 assets across 5 asset classes
**H03** Add crisis injection mode (amplified vol + correlation spike) + 4 presets (Lehman, COVID, SVB, Flash Crash)
**H04** Write `ingestion/redis_streams.py` — `publish_tick` / `consume_tick` with consumer groups; `asyncio.Queue` fallback on Redis disconnect
**H05** End-to-end smoke: simulator → Redis stream → manual `XRANGE` shows ticks queued. Celebrate. Commit.

### Storage (H06 – H08) — Risk: low
**H06** Write `db/schema.sql` — `fact_market_metrics` + 4 dimension tables (time, asset, source, alert); add `is_degraded BOOLEAN` column for watermark flagging
**H07** `db/connection.py` asyncpg pool + `get_or_create_time_id` + `insert_alert` helpers. Smoke insert one row from REPL.

### Core ML (H08 – H16) — Risk: high (this is most of the IP)
**H08** `models/isolation_forest.py` — 200 estimators, contamination 0.05, feature importance via perturbation. Warm-up 50 samples.
**H09** `models/lstm_autoencoder.py` — encoder(72→64→32) + decoder(32→64→72), online training, CDF-normalized reconstruction score
**H10** `models/ciss_scorer.py` — 5 segments × empirical CDF → cross-correlation-weighted quadratic form
**H11** `models/merton_model.py` — DD, PD for 5 SIFI banks; SRISK with LRMES via leverage-adjusted beta proxy
**H12** `models/var_calculator.py` — Historical + Parametric + Cornish-Fisher; CVaR via expected shortfall
**H13** `models/ensemble.py` — micro-batch accumulator (10 ticks OR 500 ms), weighted fusion, severity classifier, alert generator
**H14** Integration: backend `main.py` producer+consumer loop feeding ensemble. Verify payload shape matches spec.
**H15** Persist scores to PG fire-and-forget. Verify `fact_market_metrics` is filling.

### Advanced Quant (H16 – H20) — Risk: medium
**H16** `models/copula_model.py` — GARCH(1,1) marginal fit → standardized residuals → t-copula fit (estimate ν via profile MLE) → tail-dependence λ_L matrix
**H17** Plug copula into ensemble: `combined = 0.35·IF + 0.35·LSTM + 0.20·CISS + 0.10·λ_L_avg`. Sanity-check tail-λ climbs under crisis preset.
**H18** `ingestion/watermark.py` — event-time tracker; 300 ms bounded lateness; last-known-good patch; `is_degraded` flag propagates through payload
**H19** Wire watermark into consumer loop. Test: kill FRED poller mid-stream → watch `is_degraded` flip + LKG patch fill the hole without pipeline stalling.

### API + WS (H20 – H22) — Risk: low
**H20** Full FastAPI surface: scores, merton, merton/srisk, ciss/breakdown, copula (new), var, var/portfolio (new), alerts, metrics, crisis-presets, config
**H21** WebSocket `/ws/dashboard` broadcast + `/health` + `/metrics` (Prometheus). Smoke all endpoints. Commit.

### Frontend Core (H22 – H30) — Risk: medium (visual polish is time sink)
**H22** `lib/useWebSocket.js` — `useRef` buffer + `requestAnimationFrame` flush. Verify no reconciler thrash under Turbo.
**H23** `globals.css` — glassmorphism dark theme, CSS grid layout, severity colors
**H24** CISSGauge (SVG arc) + ScoreCards + LiveTicker
**H25** AnomalyTimeline (ECharts canvas, 4 series) + CorrelationHeatmap (Canvas 2D)
**H26** DefaultCards (Merton) + SRISKPanel + ExplainabilityPanel
**H27** AlertBanner + StressTestButton (4 preset grid) + StatusFooter (speed controls)
**H28** SystemMetrics (throughput / latency / watermark lag) + VaRPanel
**H29** ContagionNetwork (force-directed Canvas)

### Frontend v3 (H30 – H34) — Risk: medium
**H30** `TailDependenceMatrix.jsx` — Canvas 2D heatmap of λ_L matrix; red = strong tail coupling
**H31** `PortfolioBuilder.jsx` — input ticker + weight, submit to `/api/var/portfolio`, display portfolio VaR/CVaR + component VaR bars
**H32** `BacktestView.jsx` — ROC curves via ECharts; AUC per crisis window; lead-time histogram
**H33** `ReplayController.jsx` — start/stop replay, progress bar, current replay timestamp, speed slider

### Alerting + Persistence (H34 – H38) — Risk: low
**H34** `utils/alerting.py` — Slack/Discord/PagerDuty/webhook/email dispatchers, severity routing, 5-minute dedup key
**H35** Wire to ensemble: on HIGH/CRITICAL alert, fan out async. Smoke test with webhook.site.
**H36** `utils/model_persistence.py` — atomic save/load for IF (`.pkl`), LSTM (`.pt`), CDF buffers (`.npz`)
**H37** Hook persistence: save on crisis, save on SIGTERM, auto-restore on boot if checkpoint exists. Test: crash backend → restart → models don't cold-start.

### Backtest + Replay (H38 – H42) — Risk: medium (data wrangling can bite)
**H38** Gather historical CSVs into `data/historical/`: SPY/XLF/TLT/GLD daily 2007-2009, 2019-2020, 2022-2023. Label crisis windows in `backtesting/historical_crises.py`.
**H39** `ingestion/replay.py` — CSV reader → canonical tick schema → Redis Streams, configurable speed-up (1× to 1000×)
**H40** `backtesting/harness.py` — stream labeled data through the full live ensemble, compute ROC/AUC + false-positive rate + lead-time histogram
**H41** Endpoint wiring: `/api/replay/start|stop|status` + `/api/backtest/run|results`. Verify 2008 replay fires alerts on Sep-15.

### Prod Hardening (H42 – H45) — Risk: low
**H42** Multi-stage Dockerfiles (backend and frontend), non-root runtime user, slim base images, `.dockerignore` cleanups
**H43** `docker-compose.prod.yml` overlay (no reload, restart policies, resource limits), `schema_timescale.sql` (hypertable + continuous aggregates + retention)
**H44** `deploy/k8s/` — Deployment + Service + Ingress + PodDisruptionBudget for backend and frontend; `deploy/grafana/` dashboard JSON importable to any Grafana 9+ instance
**H45** `deploy/nginx.conf` reverse proxy for WS sticky sessions + TLS termination stub

### Test + Fix (H45 – H46) — Risk: high (this is where things break)
**H45** 5-minute load test at Turbo (25 Hz) — watch memory, FDs, Redis stream length. Fix leaks.
**H46** Smoke the full demo script twice. Fix anything that stutters.

### Demo Prep (H46 – H48) — Risk: low
**H46** Pitch deck — 6 slides: problem, architecture, models, demo, backtest results, roadmap
**H47** Record a demo video as live-failure insurance (2 takes)
**H48** Final dress rehearsal. Sleep if any remains.

---

## Risk Register

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Redis OOM at Turbo | Medium | Catastrophic | `MAX_STREAM_LEN=10000`, `maxmemory` + `allkeys-lru` in redis.conf |
| PG connection pool exhaustion | Low | High | asyncpg pool max 20; fact-table writes are fire-and-forget |
| LSTM training loop blocks event loop | High | High | Training runs in `asyncio.to_thread`; inference only on main loop |
| Copula fit fails with too few samples | Medium | Medium | Fall back to Pearson for first 200 ticks; flag `copula_warmup=True` |
| WebSocket backpressure on slow client | Medium | Medium | Drop dead connections; server-side throttle to 60 Hz max broadcast |
| Historical CSV data is dirty | High | Medium | Robust parser with `NaN` drop + forward-fill; sanity log row counts |
| Demo laptop Docker Desktop crashes | Medium | Catastrophic | Record demo video; second laptop on standby with pre-built images |
| Live API keys expire | Low | Medium | Simulator + replay modes work without any keys |
| Judge wants to see code | Low | Low | Clean repo, helpful README, labeled commits |

---

## Stop-Losses (Cut Features If Behind)

Cut in this order, in this order only:

1. **H20 behind?** Drop K8s manifests — demo runs on Compose
2. **H30 behind?** Drop Grafana dashboard JSON — Prometheus `/metrics` is enough
3. **H34 behind?** Drop PagerDuty + Discord sinks — keep Slack + webhook
4. **H38 behind?** Drop backtesting harness — the historical replay alone is impressive
5. **H42 behind?** Drop multi-stage Dockerfiles — single-stage still runs
6. **H44 behind?** Drop `ReplayController` UI — backend endpoints are enough
7. **Never cut:** golden path (CISS, SRISK, crisis preset, alerts)

---

## What Success Looks Like At Each Phase Gate

**At H06:** you can run `redis-cli XRANGE stream:market_ticks - +` and see ticks streaming.
**At H16:** you can hit `GET /api/scores` and get 4 scores + Merton list back.
**At H20:** you can hit `GET /api/copula` and get a tail-dependence matrix.
**At H30:** the dashboard lights up end-to-end; crisis preset visibly sweeps the gauge.
**At H42:** you can `docker-compose -f docker-compose.yml -f docker-compose.prod.yml up` and it boots cleanly.
**At H46:** you can run the demo twice in a row without hitting a single error.

If a gate fails, stop and fix before moving forward. Technical debt compounds viciously under 48-hour constraints.
