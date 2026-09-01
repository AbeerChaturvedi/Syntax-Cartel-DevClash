# Project Velure — Model Reference (Phase 1)

**Real-Time Financial Crisis Early-Warning System.** This document explains what the
system does, the feature pipeline, each of the 6 models, how the ensemble fuses them,
and the concrete accuracy-improvement opportunities found while reading the code.

> Scope note: this is a *description of the current code* on branch `dev-omkar`, plus
> findings. No model behaviour has been changed to produce this document.

---

## 1. What the system does

Velure ingests a live market **tick** every ~0.25s (Finnhub WebSocket for equities/crypto
+ Twelve Data REST for FX, with a simulator for crisis injection), tracks **15 assets**,
and on each batch:

1. Builds a **60-dimensional state vector** (features).
2. Runs **6 models** (4 feed a fused "crisis score", 2 render as standalone risk panels).
3. Combines the 4 anomaly/stress signals into a single **`combined_anomaly`** score in `[0,1]`.
4. Raises alerts (Slack/email) at HIGH (≥0.70) / CRITICAL (≥0.85).
5. Streams everything to the Next.js dashboard over WebSocket.

**Data flow:**
```
tick → state_builder (60-dim vector) → ┌─ Isolation Forest ─┐
                                        ├─ LSTM Autoencoder ─┤→ weighted ensemble → combined_anomaly → alerts
   tick.assets ─────────────────────── ├─ CISS Scorer ──────┤
                                        └─ t-Copula (tail) ──┘
   tick.assets ─────────────────────── ├─ Merton DD/SRISK ──→ credit panel (NOT in combined score)
                                        └─ VaR / CVaR ───────→ portfolio-risk panel (NOT in combined score)
```

### The 15 assets (canonical order, `features/state_builder.py`)
`BAC, BTCUSD, C, DIA, ETHUSD, EURUSD, GBPUSD, GS, IWM, JPM, MS, QQQ, SPY, USDJPY, XLF`

| Class | Tickers |
|---|---|
| Banks (5) | JPM, GS, BAC, C, MS |
| Equity index/ETF (4) | SPY, QQQ, DIA, IWM |
| Financial sector (1) | XLF |
| FX (3) | EURUSD, GBPUSD, USDJPY |
| Crypto (2) | BTCUSD, ETHUSD |

### The feature vector (`state_builder.py`)
Per asset, from the log-returns of the last 60 prices: **`[latest_return, vol, mean_return, max_abs_return]`**.
15 assets × 4 features = **60 dims**. NaN/inf sanitized to 0; assets with <10 prices emit zeros.

---

## 2. The 6 models

### Model 1 — Isolation Forest (`models/isolation_forest.py`) — *global / cross-sectional anomaly*
- **Idea:** an unsupervised tree ensemble that isolates outlier state vectors. "Weird" market cross-sections get flagged.
- **Config:** `contamination=0.05`, `n_estimators=200`, `random_state=42`.
- **Score:** `decision_function` → `1/(1+e^{5·raw})` → `[0,1]` (higher = more anomalous).
- **Extras:** per-tick feature importance via vectorized perturbation (zero each feature, measure score delta; top-10).
- **Training:** if no checkpoint, **`_auto_train()` fabricates 5,000 synthetic "calm" rows** from hand-coded Gaussians.
- ⚠️ **Limitations:** trained on synthetic (not real) calm data; hyperparameters hardcoded (`.env` values ignored — see §4); feature-importance runs 60 extra predictions every tick.

### Model 2 — LSTM Autoencoder (`models/lstm_autoencoder.py`) — *temporal anomaly*
- **Idea:** encode→decode a sequence of state vectors; high **reconstruction MSE** = the recent *trajectory* is unusual.
- **Architecture:** 2-layer encoder `60→64→32`, 2-layer decoder `32→64→60`.
- **Scaling:** fixed per-feature-type scales (`×300`/`×10000`) → all features ~`[-1,1]`. *(This is the fix for the old "always 100% anomaly" bug — previously rolling z-scores blew up on slow-moving features.)*
- **Threshold:** adaptive — warm up 200 ticks, set `threshold = P90(mse)·3.0`, then drift slowly (`0.9·old + 0.1·new` every 500 ticks). Score = `sigmoid(4·(mse/threshold − 0.7))`.
- **Training:** **`_auto_train()` fabricates 400 synthetic AR(1) sequences.**
- ⚠️ **Limitations:** trained on synthetic data; **actual `seq_length` is 20, not the 60 in `.env`/docstring** (constructor default is used — see §4); reconstruction quality depends on random init; no validation split.

### Model 3 — CISS Scorer (`models/ciss_scorer.py`) — *systemic stress composite (ECB-style)*
- **Idea:** ECB's Composite Indicator of Systemic Stress, adapted for streaming. 5 segments: **equities, FX, spreads, credit, volatility.**
- **Per-segment stress:** mean |pct_change| for equities/FX/crypto; bid-ask `spread_bps/1000` for spreads; mean of *negative* bank returns for credit.
- **Calibration:** each segment scored vs a **hardcoded "calm reference"** via sigmoid (`ratio=1→0.3, 3→0.7, 5→0.9`).
- **Aggregation:** correlation-weighted quadratic form `CISS = √(zᵀ·C·z)/√n` (C = 5×5 segment correlation, refreshed every 20 ticks), then sigmoid, then **heavy EMA (α=0.03, ~33-tick half-life)**.
- ⚠️ **Limitations:** calm-reference thresholds are guesses, not data-calibrated; the very slow EMA reduces jitter but **lags fast crises**; spread/credit proxies are crude; `_empirical_cdf()` exists but is unused.

### Model 4 — t-Copula + GARCH(1,1) (`models/copula_model.py`) — *tail dependence / contagion*
- **Idea:** captures **correlation breakdown** — during crises, joint *tail* co-movement rises even when linear correlation looks stable. Pearson misses this; a t-copula doesn't.
- **Pipeline:** per-segment GARCH(1,1) → standardized residuals → rank → pseudo-observations → **Kendall's τ → ρ** (`ρ=sin(πτ/2)`, PSD-projected) → **fit ν** on a coarse grid via profile MLE → **lower-tail dependence** `λ_L(i,j)=2·F_{ν+1}(−√((ν+1)(1−ρ)/(1+ρ)))`.
- **Ensemble hook:** `max_tail_dependence` (the hottest segment pair) becomes the copula score; also reports a joint-crash probability.
- **Cost control:** heavy fit only recomputed every 10 ticks.
- ⚠️ **Limitations:** GARCH `α=0.08, β=0.90` are fixed (only `ω` moment-matched); `joint_crash_probability` is a **heuristic proxy** (`q·(1+avg_λ·(n−1))`), not the true copula CDF; operates on 5 segment aggregates, not individual assets.

### Model 5 — Merton Distance-to-Default + SRISK (`models/merton_model.py`) — *bank credit risk*
- **Idea:** treat a bank's equity as a call option on its assets → **Distance-to-Default** `DD=[ln(A/L)+(μ−σ²/2)T]/(σ√T)`, **PD=N(−DD)**, plus **SRISK=k·D−(1−k)(1−LRMES)·E**.
- **Covers 5 banks:** JPM, GS, BAC, C, MS. Vol from EWMA (λ=0.94) of ~37s block returns.
- **Output:** DD, PD, SRISK ($bn), status (HEALTHY/WATCH/WARNING/CRITICAL). Sorted riskiest-first.
- ⚠️ **Limitations:** **balance-sheet profiles (market caps, debt ratios) are hardcoded demo constants** — stale vs today's real filings; annualization uses a guessed `BLOCKS_PER_DAY=632`; LRMES is an Acharya-style approximation; DD clipped to `[-2, 6]`. **Not part of `combined_anomaly`** — renders as its own panel.

### Model 6 — VaR / CVaR (`models/var_calculator.py`) — *portfolio tail risk*
- **Idea:** rolling **Value-at-Risk** at 99% via three methods — Historical, Parametric (normal), **Cornish-Fisher** (skew/kurtosis-adjusted) — plus **CVaR / Expected Shortfall**, on an **equal-weighted** portfolio of all assets.
- **Output:** the three VaRs, CVaR, dollar VaR/CVaR on $1M notional, per-asset marginal VaR, and a vol regime label.
- ⚠️ **Limitations:** equal-weighted only (the *weighted* component-VaR lives in `portfolio/portfolio_var.py` — that's where the "trillion-dollar" double-`notional` bug was, now fixed); annualization assumes `16 ticks/day` (simulator-era) — **wrong for live cadence**. **Not part of `combined_anomaly`.**

---

## 3. The ensemble (`models/ensemble.py`)

```
raw_combined = w_IF·IF + w_LSTM·LSTM + w_CISS·CISS + w_COPULA·copula      (weights renormalized to sum 1)
combined_anomaly = EMA(α=0.05) of raw_combined, then clamped to ±0.03 / tick
```
- **Weights** come from `.env` (`0.35 / 0.35 / 0.20 / 0.10`) — these *are* wired.
- **Smoothing:** EMA (α=0.05) **plus a hard ±3%/tick rate-limiter** on every score.
- **Severity:** LOW ≥0.30, MEDIUM ≥0.50, HIGH ≥0.70, CRITICAL ≥0.85. HIGH/CRITICAL fire alerts (fire-and-forget to Slack/email).
- **Payload** also carries Merton results, aggregate SRISK, VaR metrics, CISS breakdown, feature importance, and the copula snapshot.

**Only 4 of the 6 models drive the crisis score.** Merton and VaR are computed and displayed but do **not** influence `combined_anomaly`.

---

## 4. Cross-cutting findings → accuracy opportunities (prioritized)

| # | Finding | Impact | Where |
|---|---|---|---|
| **1** | **IF + LSTM are trained on *synthetic* data** (`_auto_train`), never on real market history. | 🔴 Highest — the "normal" baseline is fabricated, so anomaly scores aren't grounded in real calm/crisis behaviour. | `isolation_forest.py:119`, `lstm_autoencoder.py:206` |
| **2** | **`.env` ML knobs are dead** — `IF_CONTAMINATION`, `IF_N_ESTIMATORS`, `LSTM_*`, `CISS_WINDOW`, `VAR_*` are defined in `config.py` but **never imported** by the models. LSTM actually runs `seq_length=20`, not the `60` in `.env`. | 🔴 High — the entire tuning surface is inert; can't tune without code edits, and there's a silent config/behaviour mismatch. | `config.py:41-48` vs model constructors |
| **3** | **Hardcoded calibration** — CISS calm-reference thresholds and Merton balance-sheet profiles are hand-set demo constants. | 🟠 Medium-high — scores/PDs drift from reality as markets move. | `ciss_scorer.py:46`, `merton_model.py:36` |
| **4** | **No ground-truth evaluation loop.** There's a `backtesting/harness.py` but no labeled crisis windows wired in, so "accuracy" is currently unmeasurable. | 🔴 High — can't prove any improvement without this. | `backtesting/` (Phase 2) |
| **5** | **Ensemble weights are static.** A learned or regime-adaptive weighting could beat fixed `0.35/0.35/0.20/0.10`. | 🟠 Medium | `ensemble.py:48` |
| **6** | **Merton & VaR are excluded from the fused score.** Two whole models' worth of signal aren't feeding the crisis indicator. | 🟠 Medium | `ensemble.py:147` |
| **7** | **Copula joint-crash prob is a heuristic**, not the true copula CDF; GARCH α/β fixed. | 🟡 Lower | `copula_model.py:146` |
| **8** | **VaR annualization assumes 16 ticks/day** (sim-era) — miscalibrated for the live tick cadence. | 🟡 Lower | `var_calculator.py:111` |

---

## 5. Suggested next steps (Phase 2 — measurement first)

1. **Stand up a scorecard before touching models:** wire `backtesting/harness.py` to labeled crisis windows (2008 Lehman, 2020 COVID, 2023 SVB) and define metrics — **lead time, precision/recall, false-positive rate, AUC-ROC/PR, calibration (Brier)**.
2. **Quick wins (low risk, high value):** wire the `.env` knobs into the models (finding #2), and train IF/LSTM on real historical calm data instead of synthetic (finding #1).
3. **Then iterate** on ensemble fusion (#5/#6), CISS/Merton calibration (#3), and copula rigor (#7) — each validated against the Phase-2 scorecard.

*Decision needed before Phase 2: define what "more accurate" means for the demo — earliest warning (max lead time) vs fewest false alarms (precision) vs best-calibrated probability. These trade off.*
