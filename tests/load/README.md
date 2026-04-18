# Load tests

## What this exercises

`k6_dashboard_load.js` is a sustained, multi-scenario k6 load test that
hits the backend exactly the way a real deployment would:

| Scenario | Profile | Why |
|----------|---------|-----|
| `rest_pollers`   | 50 constant VUs hitting random REST endpoints @ 1 req/s for 5 minutes | Dashboards + automated quant pollers |
| `ws_dashboards`  | Ramp 0 → 200 WS clients in 1 min, hold 4 min, drain 30 s | Multiple operators with the dashboard open |
| `burst_api`      | Two 30-second waves of 100 RPS into `/api/var/portfolio` and stress-test endpoints | Research team running ad-hoc what-ifs while system is loaded |

## Pass criteria (k6 thresholds — fails the run if breached)

- `rest_latency_ms`        p95 < 500ms,  p99 < 1500ms
- `ws_inter_frame_ms`      p95 < 3500ms (server flushes every 2s + slack)
- `ws_connect_success_rate` > 99%
- `rest_errors` count < 10
- `http_req_failed` rate < 1%

## Running

```bash
# Local dev
k6 run \
  -e BASE_URL=http://127.0.0.1:8000 \
  -e WS_URL=ws://127.0.0.1:8000/ws/dashboard \
  tests/load/k6_dashboard_load.js

# Against the prod compose (with API key set)
k6 run \
  -e BASE_URL=https://velure.example.com \
  -e WS_URL=wss://velure.example.com/ws/dashboard \
  -e API_KEY=$VELURE_API_KEY \
  tests/load/k6_dashboard_load.js
```

## Interpreting the output

- **Inter-frame latency p95 above 3.5s** → the dashboard flush loop is
  blocked somewhere. Check the inference consumer and the broadcast fan-out.
- **REST p99 above 1.5s under load** → start with the slowest endpoint in
  the per-endpoint breakdown; usually it's `/api/var/portfolio` (CPU bound)
  or one that touches Postgres on every request.
- **`ws_connect_success_rate` < 99%** → either rate limiting or a backend
  resource exhaustion. Check `velure_pipeline_errors_total` and the WS
  middleware logs.

## Acceptance

A passing run on the production-equivalent compose stack is a prerequisite
for the §2.4 blocking gap in [PRODUCTION_READINESS.md](../../PRODUCTION_READINESS.md).
Capture the JSON summary (`--summary-export=summary.json`) and attach it to
the deploy ticket.
