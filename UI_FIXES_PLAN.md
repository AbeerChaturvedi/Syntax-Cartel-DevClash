# Velure UI — Pragmatic Implementation Plan
**Date:** 2026-09-02 | **Scope:** User-reported + audit-discovered UI/UX issues

This plan covers:
1. **BAC fields flickering** (user-reported)
2. **ContagionNetwork missing interconnections** (user-reported)
3. **Redis status showing Offline** (user mid-session report)
4. **Audit-discovered UI bugs** from the same review

All fixes are pragmatic — minimal code changes that target root causes.

---

## ISSUE 1 — BAC Feature Importance Flicker

**Symptom:** BAC Return / Volatility / Mean Return / Max |Return| fields show 0.0000 most of the time, with a brief "loading" value flash before going back to 0.

**Root cause (verified by live probe):**
- `backend/models/isolation_forest.py:117` — `get_feature_importance()` returns **only the top 10** features by importance score.
- `backend/models/ensemble.py:195` — calls `get_feature_importance(state_vector)` **without passing feature_names**, so all keys come back as `feature_0`...`feature_9`.
- `frontend/.../ExplainabilityPanel.jsx:11-24` — `FEATURE_LABELS` maps `feature_0` to `BAC Return`, `feature_1` to `BAC Volatility`, etc. So IF the model deems BAC features less important than other assets', they get pruned from the top 10 and the frontend shows 0 for them.
- Each new tick recomputes top 10 → React renders new bars → old BAC features momentarily appear with stale values, then disappear.

**Fix:** Return **all 60 features** (not top 10), and pass `feature_names` so the frontend gets properly-labeled keys.

**Files:**
- `backend/models/isolation_forest.py` (line 117)
- `backend/models/ensemble.py` (line 195)
- `backend/features/state_builder.py` (need to expose `FEATURE_NAMES` constant)

**Effort:** 20 min

---

## ISSUE 2 — ContagionNetwork Missing Interconnections

**Symptom:** ContagionNetwork shows nodes but no edges/wires between them.

**Root cause (verified by live probe):**
- `backend/models/ensemble.py:242` — pulls `correlation_matrix` from the incoming `tick`.
- `backend/ingestion/simulator.py:185` — only the simulator computes and emits `correlation_matrix`.
- After Phase 1 fix (heartbeat path), when in hybrid mode, the simulator doesn't run continuously → no correlation matrix in ticks → `correlation_matrix: []` in inference.
- The ContagionNetwork component reads the empty matrix and renders no edges (its threshold is `|corr| > 0.1`).

**Fix:** Compute correlation matrix in the **state_builder** (it already ingests all prices) and pass it via the inference tick. This makes correlation data flow from a real-data source, not just simulation.

**Files:**
- `backend/features/state_builder.py` — compute matrix on each tick, attach to result
- `backend/models/ensemble.py:242` — read from state_builder instead of tick
- `backend/ingestion/simulator.py:185,188` — keep for simulator mode but don't depend on it

**Effort:** 25 min

---

## ISSUE 3 — Redis Status Shows "Offline" in UI

**Symptom:** Redis dot in SystemMetrics panel shows offline even though `/api/metrics` returns `redis_connected: true`.

**Root cause (verified):**
- `frontend/.../SystemMetrics.jsx:63` — `const redis = metrics.redis || {};` reads `metrics.redis.redis_connected`.
- `backend/Routes/system.py:123` — returns `redis_connected` at **top level**, not nested under `redis`.
- Field name mismatch → `redis = {}` always → UI always shows "Offline".

**Fix:** Return the Redis metrics as a nested `redis` object in `/api/metrics` AND keep `redis_connected` at top level for backward compatibility.

**Files:**
- `backend/Routes/system.py` (around line 123)
- Optionally simplify frontend to read `metrics.redis_connected` directly

**Effort:** 10 min

---

## AUDIT-DISCOVERED UI BUGS

While reviewing the three reported issues, I found these additional bugs worth fixing in the same pass:

### AUDIT-A — `feature_importance` keys are unlabeled (`feature_0` etc.)
**Same root cause as Issue 1.** Passing `feature_names` to `get_feature_importance()` also fixes the ExplainabilityPanel showing "F0", "F1" instead of "SPY Return", "SPY Volatility".

**Effort:** covered by Issue 1 fix.

### AUDIT-B — `peak_combined` and `peak_ciss` show stale values forever
`/api/metrics` shows `peak_combined` and `peak_ciss` as ever-increasing values that never decay. Once a tick produces a spike, it stays even after the system calms down.

**Files:** `backend/Routes/system.py:117-118` or `backend/globals.py` peak tracking
**Effort:** 15 min — add a 60-second rolling peak window

### AUDIT-C — Empty correlation matrix causes `avg_correlation: 0` to flash
When correlation_matrix is `[]` (heartbeat path), `avg_correlation` is `0` even when assets are correlated. UI shows "ρ̄ = 0.000" briefly between real ticks.

**Files:** `backend/Routes/system.py` (where avg_correlation is computed), or compute rolling avg in state_builder
**Effort:** covered by Issue 2 fix.

### AUDIT-D — `useWebSocket` doesn't reconnect on backend restart
If the backend container restarts, the frontend shows "Disconnected" forever. No automatic reconnect.

**Files:** `frontend/src/lib/useWebSocket.js`
**Effort:** 20 min — add exponential-backoff reconnect

### AUDIT-E — StatusFooter still shows "NORMAL · 4 Hz" hardcoded
After my Phase 5 fix, the footer shows hardcoded `4 Hz` even when the actual tick rate is `5.0` (from heartbeat).

**Files:** `frontend/src/app/components/StatusFooter.jsx`
**Effort:** 10 min — read actual rate from `metrics.ticks_per_second`

---

## EXECUTION ORDER

```
1. Issue 3 (Redis status)            ← simplest, 1-line backend fix, immediate UI win
2. Issue 1 (BAC flicker)             ← 3-file fix, affects explainability panel UX
3. Issue 2 (ContagionNetwork edges)  ← architectural fix, makes network meaningful
4. AUDIT-A (feature labels)          ← covered by Issue 1
5. AUDIT-B (stale peaks)             ← cosmetic but ops-facing
6. AUDIT-C (rolling avg)             ← covered by Issue 2
7. AUDIT-D (WS reconnect)            ← resilience
8. AUDIT-E (footer tick rate)        ← cosmetic
```

**Total effort:** ~90 minutes for all 8 issues (Issues 1-3 + AUDIT-A,B,C,D,E).

---

## POST-FIX VERIFICATION CHECKLIST

```bash
docker compose up -d --build backend frontend
sleep 45

# 1. Redis status fix
curl -s http://localhost:8000/api/metrics | grep -E "redis_connected|redis\":"
# Expect: redis_connected: true AND a nested redis object

# 2. BAC features show real values
docker compose exec backend python -c "
import asyncio, json
from ingestion.redis_streams import redis_streams
async def p():
    await redis_streams.connect()
    res = await redis_streams._redis.xrevrange('stream:inference', count=1)
    p = json.loads(res[0][1]['data'].decode())
    fi = p.get('feature_importance', {})
    print('feature count:', len(fi))
    print('BAC keys:', [k for k in fi if 'BAC' in k])
asyncio.run(p())
"
# Expect: 60 features, BAC Return/Volatility/Mean/Max|Return all present

# 3. ContagionNetwork has edges
curl -s http://localhost:8000/api/metrics | grep -o "correlation_matrix"
docker compose exec backend python /tmp/probe_corr.py
# Expect: matrix 15x15 with non-zero off-diagonal entries, avg_correlation > 0.1
```

---

## SKILLS TO USE

- `clean-code` — keep patches minimal, avoid architectural rewrites
- `high-perf-browser` — for Issue 2 (Three.js correlation matrix updates)