# Project Velure — System Architecture

## 1. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                     │
│                                                                          │
│  ┌─────────────┐   ┌──────────────┐   ┌──────────────┐                  │
│  │  Simulator   │   │ Finnhub API  │   │  Historical  │                  │
│  │  (GBM Model) │   │ (WebSocket)  │   │   Replay     │                  │
│  │  4 Hz        │   │ Real-time    │   │   CSV/JSON   │                  │
│  └──────┬───────┘   └──────┬───────┘   └──────┬───────┘                  │
│         │                  │                   │                          │
│         └──────────────────┼───────────────────┘                         │
│                            ▼                                             │
│              ┌─────────────────────────┐                                 │
│              │   Event-Time Watermark  │  ← Tags each tick with          │
│              │   (Temporal Alignment)  │    source timestamp,            │
│              └────────────┬────────────┘    detects late/stale data      │
│                           ▼                                              │
└───────────────────────────┼──────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                     MESSAGE QUEUE LAYER                                   │
│                                                                          │
│  ┌─────────────────────────────────────────────────┐                     │
│  │           Redis Streams (XADD / XREADGROUP)     │                     │
│  │                                                 │                     │
│  │  stream:market_ticks  →  Consumer Group          │                     │
│  │  stream:inference     →  Cached results          │                     │
│  │  stream:alerts        →  Crisis alerts           │                     │
│  │                                                 │                     │
│  │  MAXLEN=10,000 │ Exactly-once via XACK          │                     │
│  │                                                 │                     │
│  │  ⚡ Fallback: asyncio.Queue(5000) if Redis down │                     │
│  └─────────────────────────────────────────────────┘                     │
│                                                                          │
└───────────────────────────┬──────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                 ML INFERENCE ENGINE (Ensemble Orchestrator)               │
│                                                                          │
│  Micro-batch: 10 ticks OR 500ms (whichever first)                       │
│                                                                          │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐             │
│  │ Isolation      │  │ LSTM           │  │ CISS Scorer    │             │
│  │ Forest         │  │ Autoencoder    │  │ (ECB Method)   │             │
│  │                │  │                │  │                │             │
│  │ sklearn        │  │ PyTorch        │  │ NumPy/SciPy    │             │
│  │ 200 trees      │  │ 72→64→32→64→72│  │ 5 segments     │             │
│  │                │  │                │  │                │             │
│  │ Weight: 35%    │  │ Weight: 35%    │  │ Weight: 20%    │             │
│  │                │  │                │  │                │             │
│  │ "Is current    │  │ "Has pattern   │  │ "Are ALL       │             │
│  │  state weird?" │  │  changed?"     │  │  markets       │             │
│  │                │  │                │  │  stressed?"    │             │
│  └────────┬───────┘  └────────┬───────┘  └────────┬───────┘             │
│           │                   │                    │                     │
│  ┌────────┴───────┐  ┌───────┴────────┐  ┌───────┴────────┐            │
│  │ t-Copula +     │  │ Merton DD +    │  │ VaR/CVaR       │            │
│  │ GARCH(1,1)     │  │ SRISK          │  │ Calculator     │            │
│  │                │  │                │  │                │            │
│  │ SciPy          │  │ SciPy          │  │ NumPy/SciPy    │            │
│  │ Tail dep.      │  │ Credit risk    │  │ Portfolio risk  │            │
│  │                │  │                │  │                │            │
│  │ Weight: 10%    │  │ (standalone)   │  │ (standalone)   │            │
│  │                │  │                │  │                │            │
│  │ "Would assets  │  │ "How close     │  │ "Worst-case    │            │
│  │  crash         │  │  are banks to  │  │  portfolio     │            │
│  │  together?"    │  │  insolvency?"  │  │  loss?"        │            │
│  └────────┬───────┘  └───────┬────────┘  └───────┬────────┘            │
│           │                  │                    │                     │
│           └──────────────────┼────────────────────┘                     │
│                              ▼                                          │
│              ┌───────────────────────────┐                              │
│              │   Weighted Ensemble       │                              │
│              │   Fusion + EMA Smoothing  │                              │
│              │   + Severity Classification│                              │
│              └────────────┬──────────────┘                              │
│                           │                                             │
└───────────────────────────┼─────────────────────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                        OUTPUT LAYER                                      │
│                                                                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐   │
│  │  WebSocket   │ │  PostgreSQL  │ │ Redis Cache  │ │ Alert        │   │
│  │  Broadcast   │ │  Star Schema │ │ (30s TTL)    │ │ Dispatcher   │   │
│  │              │ │              │ │              │ │              │   │
│  │  All clients │ │  Fact table  │ │ REST fallback│ │ Slack/       │   │
│  │  get scores  │ │  + dims      │ │ for /scores  │ │ Discord/     │   │
│  │  in <200ms   │ │              │ │              │ │ PagerDuty    │   │
│  └──────┬───────┘ └──────────────┘ └──────────────┘ └──────────────┘   │
│         │                                                               │
└─────────┼───────────────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                      FRONTEND (Next.js 16)                               │
│                                                                          │
│  WebSocket → useRef buffer (no re-render per tick)                      │
│           → setInterval 2s flush → useState (display update)            │
│           → 19 React components render live data                        │
│                                                                          │
│  CISS Gauge │ Score Cards │ Bank Cards │ Heatmap │ VaR │ Timeline │ ... │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Data Flow — Step by Step

### Every 250 milliseconds, this happens:

```
Step 1: GENERATE
  Simulator creates a tick:
    → 18 asset prices (GBM random walk + Cholesky correlation)
    → Returns, volatility, volume, bid-ask spread for each

Step 2: WATERMARK
  Tag tick with source event_ms timestamp
    → Detect late-arriving data
    → Substitute Last-Known-Good if a source goes silent

Step 3: QUEUE
  Push to Redis Stream (XADD) or fallback asyncio.Queue
    → Bounded at 10,000 messages (auto-trim)
    → Decouples ingestion from inference

Step 4: CONSUME
  Consumer pulls tick (XREADGROUP + XACK)
    → Exactly-once processing semantics
    → Accumulates into micro-batch (10 ticks / 500ms)

Step 5: INFERENCE (all 6 models run in parallel)
  ┌─ Isolation Forest:  72-dim vector → anomaly score [0,1]
  ├─ LSTM Autoencoder:  60-tick sequence → reconstruction error [0,1]
  ├─ CISS Scorer:       5 segment stresses → systemic score [0,1]
  ├─ t-Copula+GARCH:    5 segment returns → tail dependence matrix
  ├─ Merton DD:         5 bank prices → Distance-to-Default + PD + SRISK
  └─ VaR Calculator:    portfolio returns → VaR/CVaR at 99% confidence

Step 6: FUSE
  Combined = 35%×IF + 35%×LSTM + 20%×CISS + 10%×Copula
  Smooth with EMA (α=0.04)
  Classify severity: NORMAL → LOW → MEDIUM → HIGH → CRITICAL

Step 7: BROADCAST
  WebSocket fan-out to all connected dashboard clients
  Cache in Redis (30s TTL) for REST fallback
  Fire-and-forget write to PostgreSQL star schema
  If severity ≥ HIGH → dispatch alerts to Slack/Discord/PagerDuty
```

### End-to-end latency: **~200ms average** (tick generation → browser render)

---

## 3. How Live Data Processing Works at Speed

**Problem:** 6 ML models running on every tick at 4 Hz would be too slow.

**Solution: Micro-batching + Parallel Architecture**

```
                    4 Hz Input (250ms per tick)
                           │
                           ▼
              ┌─────────────────────────┐
              │   Micro-Batch Buffer    │
              │   Flush every 10 ticks  │
              │   OR every 500ms        │
              └─────────┬───────────────┘
                        │
           ┌────────────┼────────────────┐
           ▼            ▼                ▼
     ┌──────────┐ ┌──────────┐    ┌──────────┐
     │ IF: 2ms  │ │LSTM: 15ms│    │CISS: 1ms │
     └──────────┘ └──────────┘    └──────────┘
           │            │                │
     ┌──────────┐ ┌──────────┐    ┌──────────┐
     │Copula:8ms│ │Merton:3ms│    │VaR: 2ms  │
     └──────────┘ └──────────┘    └──────────┘
           │            │                │
           └────────────┼────────────────┘
                        ▼
              ┌──────────────────┐
              │ Ensemble: <1ms   │
              │ Total: ~30ms     │
              └──────────────────┘
```

**Why it's fast:**
1. **Micro-batching:** Don't run models on every tick — accumulate 10 ticks, run once
2. **O(1) updates:** GARCH, CISS, Merton use online algorithms (update running statistics, don't recalculate from scratch)
3. **Bounded buffers:** All `deque(maxlen=500)` — fixed memory, no growth
4. **Copula recomputation:** Only every 10 ticks (correlation changes slowly)
5. **Async architecture:** `asyncio.gather()` runs producer and consumer concurrently

---

## 4. Model Training & Data Sources

### Overview

| Model | Type | Training Data | Source | When |
|---|---|---|---|---|
| **Isolation Forest** | ML (unsupervised) | 5,000 synthetic calm vectors | Auto-generated at startup | Cold start |
| **LSTM Autoencoder** | Deep Learning | 200 synthetic calm sequences | Auto-generated at startup | Cold start |
| **CISS** | Mathematical formula | No training needed | ECB methodology (2012) | — |
| **Merton DD** | Financial formula | No training needed | Nobel Prize model (1974) | — |
| **t-Copula + GARCH** | Statistical fitting | Online from live stream | Self-calibrating | Continuous |
| **VaR/CVaR** | Rolling statistics | No training needed | J.P. Morgan RiskMetrics | — |

### Isolation Forest Training

```python
# Auto-trains on startup with synthetic "calm market" data
np.random.seed(42)
training_data = np.random.randn(5000, 72) * 0.01
#                                ↑    ↑      ↑
#                          5000 samples  72 features  small values = calm

# 72 features = 18 assets × 4 features per asset:
#   [return, volatility, mean_return, max_|return|] × 18

model = IsolationForest(n_estimators=200, contamination=0.05)
model.fit(StandardScaler().fit_transform(training_data))
```

**At runtime:** Each tick generates a live 72-dim vector from actual market data. The model scores how different it is from the calm baseline → higher = more anomalous.

### LSTM Autoencoder Training

```python
# Architecture: Encoder (72→64→32) + Decoder (32→64→72) using LSTM layers
# Trains on 200 synthetic calm sequences (60 timesteps × 72 features each)

training_data = np.random.randn(200, 60, 72) * 0.01

# 30 epochs of reconstruction training (Adam optimizer, lr=0.001)
for epoch in range(30):
    reconstruction = model(training_data)
    loss = MSE(reconstruction, training_data)  # learn to copy input → output
    loss.backward()
    optimizer.step()

# Adaptive threshold: 95th percentile of recent MSE values
# → auto-adjusts to current volatility regime
```

**At runtime:** Feed last 60 ticks → if reconstruction error > 95th percentile → anomalous.

### CISS — No Training (ECB Published Formula)

```
1. Compute stress per segment: |pct_change| for equities, forex, rates, credit, volatility
2. Empirical CDF transform: rank against last 500 values → [0, 1]
3. Cross-correlation matrix between 5 segments
4. Quadratic form: CISS = √(z' × C × z) / √5
   → Amplifies when ALL segments are stressed AND correlated
```

### Merton — No Training (Structural Formula)

```
DD = [ln(A/L) + (r - σ²/2)T] / (σ√T)     ← Distance-to-Default
PD = Φ(-DD)                                 ← Probability of Default
SRISK = 0.08×Debt - 0.92×(1-LRMES)×Equity  ← Capital shortfall

Where:
  A = Total assets (from equity / (1 - debt_ratio))
  L = Default point (Moody's KMV: ST_debt + 0.5 × LT_debt)
  σ = Asset volatility (from tick-level equity returns)
  Bank balance sheets: hardcoded from SEC 10-K filings
```

### t-Copula — Self-Calibrating (Online)

```
1. GARCH(1,1) filters volatility clustering per segment
2. Rank-transform residuals → pseudo-observations in (0,1)
3. Kendall's τ → copula correlation: ρ = sin(π·τ/2)
4. Fit ν (degrees of freedom) via grid MLE over [3,4,5,6,8,10,15,25,50]
5. Tail dependence: λ = 2·F_{ν+1}(-√((ν+1)(1-ρ)/(1+ρ)))

Needs 50+ ticks to warm up → recalibrates every 10 ticks
```

### Production Upgrade Path

In production, replace auto-training with:
- **Real data:** 6-12 months of historical tick data from Finnhub/Bloomberg
- **Model versioning:** MLflow for A/B testing new models
- **Scheduled retraining:** Monthly pipeline with fresh market data
- **Backtesting:** Run against labeled historical crises (2008, 2020, etc.)

---

## 5. API Reference

### WebSocket (Real-Time)

| Endpoint | Description |
|---|---|
| `ws://host:8000/ws/dashboard` | Live streaming of all scores, assets, models |

**Payload structure (every ~2 seconds):**
```json
{
  "tick_id": 1234,
  "scores": {
    "isolation_forest": 0.37,
    "lstm_autoencoder": 0.36,
    "ciss": 0.89,
    "combined_anomaly": 0.42,
    "severity": "MEDIUM"
  },
  "assets": { "SPY": { "price": 542.1, "pct_change": 0.05 }, ... },
  "merton": [{ "ticker": "JPM", "distance_to_default": 2.36, "prob_default": 0.064 }],
  "var_metrics": { "historical_var": 27.4, "cvar": 28.0 },
  "copula": { "avg_tail_dependence": 0.108, "nu": 8.0 },
  "correlation_matrix": [[1, 0.3, ...], ...],
  "alert": null
}
```

### REST Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | System health + circuit breaker status |
| `GET` | `/api/status` | Full system status |
| `GET` | `/api/scores` | Latest computed risk scores |
| `GET` | `/api/merton` | Bank Distance-to-Default scores |
| `GET` | `/api/merton/srisk` | Aggregate system SRISK |
| `GET` | `/api/ciss/breakdown` | CISS component breakdown |
| `GET` | `/api/var` | Value-at-Risk metrics |
| `GET` | `/api/alerts` | Recent alert history |
| `GET` | `/api/metrics` | Pipeline health + throughput |
| `GET` | `/api/config` | Current system configuration |
| `GET` | `/metrics` | Prometheus exposition format |
| `POST` | `/api/stress-test/activate` | Trigger crisis simulation |
| `POST` | `/api/stress-test/preset` | Trigger named crisis (lehman_2008, covid_2020) |
| `POST` | `/api/stress-test/deactivate` | Stop crisis simulation |
| `POST` | `/api/speed/{mode}` | Change tick rate (slow/normal/fast/turbo) |

---

## 6. Resilience Patterns

```
┌──────────────────────────────────────────┐
│           Circuit Breakers               │
│                                          │
│  Redis:      5 failures → 15s cooldown   │
│  PostgreSQL: 3 failures → 30s cooldown   │
│                                          │
│  States: CLOSED → OPEN → HALF_OPEN      │
│                                          │
│  If Redis dies → asyncio.Queue fallback  │
│  If DB dies → pipeline keeps running     │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│           Alert Deduplication            │
│                                          │
│  5-minute window: same type+severity     │
│  won't fire twice                        │
│                                          │
│  Severity routing:                       │
│    NORMAL/LOW/MEDIUM → dashboard only    │
│    HIGH → Slack + Discord                │
│    CRITICAL → all sinks + PagerDuty      │
└──────────────────────────────────────────┘

┌──────────────────────────────────────────┐
│       Model Checkpointing                │
│                                          │
│  Periodic: every 300 seconds             │
│  On crisis: when severity ≥ HIGH         │
│  On shutdown: best-effort final save     │
│  On startup: warm-start from checkpoint  │
│                                          │
│  Saves: IF model, LSTM weights, CISS     │
│  buffers, Merton history, Copula state   │
└──────────────────────────────────────────┘
```

---

## 7. Tech Stack

| Layer | Technology | Why |
|---|---|---|
| **Backend** | FastAPI (Python) | Native async, WebSocket, auto-docs |
| **ML** | scikit-learn + PyTorch | IF needs sklearn, LSTM needs PyTorch |
| **Math** | NumPy + SciPy | CISS, Merton, Copula, VaR computations |
| **Queue** | Redis Streams | Exactly-once semantics, bounded memory |
| **Database** | PostgreSQL | Star schema for analytical queries |
| **Frontend** | Next.js 16 | React with SSR, Turbopack dev server |
| **Charts** | Recharts + Canvas | GPU-accelerated rendering for heatmap |
| **Animation** | Framer Motion | Smooth gauge and score card transitions |
| **Container** | Docker Compose | One-command deployment |
