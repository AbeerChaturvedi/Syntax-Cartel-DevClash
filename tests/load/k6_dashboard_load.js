// ─────────────────────────────────────────────────────────────────────
//  Project Velure — sustained load test (k6)
//
//  Purpose: drive both REST and WebSocket surfaces under load that
//  approximates a real ingestion peak (multiple dashboards open + REST
//  pollers + a steady stream of API hits) for a meaningful duration so
//  that p99 latency, error rate, and pipeline backpressure are visible.
//
//  Run:
//    k6 run \
//      -e BASE_URL=http://127.0.0.1:8000 \
//      -e WS_URL=ws://127.0.0.1:8000/ws/dashboard \
//      -e API_KEY=$VELURE_API_KEY \
//      tests/load/k6_dashboard_load.js
//
//  Pass thresholds → exit code 0 = ship.  Failures → exit code 99.
// ─────────────────────────────────────────────────────────────────────

import http from "k6/http";
import ws   from "k6/ws";
import { check, sleep, fail } from "k6";
import { Counter, Trend, Rate } from "k6/metrics";

// ── Config ──────────────────────────────────────────────────────────
const BASE_URL = __ENV.BASE_URL || "http://127.0.0.1:8000";
const WS_URL   = __ENV.WS_URL   || "ws://127.0.0.1:8000/ws/dashboard";
const API_KEY  = __ENV.API_KEY  || "";

const REST_HEADERS = API_KEY
  ? { "Content-Type": "application/json", "X-API-Key": API_KEY }
  : { "Content-Type": "application/json" };

// ── Custom metrics ─────────────────────────────────────────────────
const wsMessages    = new Counter("ws_messages_received");
const wsConnects    = new Counter("ws_connect_attempts");
const wsConnectOk   = new Rate("ws_connect_success_rate");
const restErrors    = new Counter("rest_errors");
const wsFrameTrend  = new Trend("ws_inter_frame_ms", true);
const restLatency   = new Trend("rest_latency_ms", true);

// ── Scenarios ──────────────────────────────────────────────────────
//
//  rest_pollers   — 50 VUs hitting REST endpoints at ~1 req/s each
//                  for 5 minutes.  Simulates dashboard background polling
//                  + an automated quant pulling /api/scores every second.
//
//  ws_dashboards  — ramps from 0 → 200 concurrent WS clients over 1 minute,
//                  then holds for 4 minutes.  Each client stays subscribed
//                  for the duration and counts received frames.
//
//  burst_api      — every 30s, 100 VUs hammer /api/var/portfolio + a
//                  stress-test trigger.  Simulates a research team running
//                  ad-hoc what-if scenarios while the system is loaded.
//
export const options = {
  scenarios: {
    rest_pollers: {
      executor: "constant-vus",
      vus: 50,
      duration: "5m",
      exec: "restPoller",
      tags: { scenario: "rest_pollers" },
    },
    ws_dashboards: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "1m",  target: 200 },
        { duration: "4m",  target: 200 },
        { duration: "30s", target: 0   },
      ],
      exec: "wsDashboard",
      tags: { scenario: "ws_dashboards" },
    },
    burst_api: {
      executor: "ramping-arrival-rate",
      startRate: 0,
      timeUnit: "1s",
      preAllocatedVUs: 100,
      maxVUs: 200,
      stages: [
        { duration: "1m", target: 0 },
        { duration: "10s", target: 100 },
        { duration: "20s", target: 100 },
        { duration: "10s", target: 0 },
        { duration: "1m",  target: 0 },
        { duration: "10s", target: 100 },
        { duration: "20s", target: 100 },
        { duration: "10s", target: 0 },
      ],
      exec: "burstApi",
      tags: { scenario: "burst_api" },
    },
  },

  thresholds: {
    "rest_latency_ms":            ["p(95)<500", "p(99)<1500"],
    "ws_inter_frame_ms":          ["p(95)<3500"],   // 2s nominal flush + slack
    "ws_connect_success_rate":    ["rate>0.99"],
    "rest_errors":                ["count<10"],
    "http_req_failed":            ["rate<0.01"],
  },
};

// ── REST poller ────────────────────────────────────────────────────
export function restPoller() {
  const endpoints = [
    "/health",
    "/api/status",
    "/api/scores",
    "/api/metrics",
    "/api/copula",
    "/api/var",
    "/api/merton/srisk",
    "/api/ciss/breakdown",
    "/api/watermark",
  ];
  const path = endpoints[Math.floor(Math.random() * endpoints.length)];

  const r = http.get(`${BASE_URL}${path}`, { headers: REST_HEADERS });
  restLatency.add(r.timings.duration);
  if (r.status !== 200) {
    restErrors.add(1);
  }
  check(r, {
    "rest 200":      (res) => res.status === 200,
    "json body":     (res) => res.body && res.body.length > 0,
  });
  sleep(1);
}

// ── WebSocket dashboard ────────────────────────────────────────────
export function wsDashboard() {
  wsConnects.add(1);
  const headers = API_KEY ? { "X-API-Key": API_KEY } : {};
  let lastFrameTs = 0;

  const res = ws.connect(WS_URL, { headers }, (socket) => {
    wsConnectOk.add(true);

    socket.on("message", (msg) => {
      const now = Date.now();
      if (lastFrameTs > 0) {
        wsFrameTrend.add(now - lastFrameTs);
      }
      lastFrameTs = now;
      wsMessages.add(1);
    });

    socket.on("error", (e) => {
      console.error(`ws error: ${e.error()}`);
    });

    // Keep the socket open for the scenario duration; ping every 20s
    // to mimic a real dashboard.
    socket.setInterval(() => {
      socket.send(JSON.stringify({ type: "ping" }));
    }, 20000);

    // Stay subscribed for ~4 minutes per VU
    socket.setTimeout(() => socket.close(), 240000);
  });

  if (!res || res.status !== 101) {
    wsConnectOk.add(false);
  }
}

// ── Burst API (heavy POSTs + stress trigger) ───────────────────────
export function burstApi() {
  // 70% portfolio VaR (CPU-heavy), 30% stress preset toggle
  if (Math.random() < 0.7) {
    const body = JSON.stringify({
      weights:    { SPY: 0.6, TLT: 0.3, GLD: 0.1 },
      notional:   1_000_000,
      confidence: 0.99,
    });
    const r = http.post(`${BASE_URL}/api/var/portfolio`, body, { headers: REST_HEADERS });
    restLatency.add(r.timings.duration);
    if (r.status !== 200) restErrors.add(1);
  } else {
    const body = JSON.stringify({ scenario: "svb_2023", intensity: 0.6, duration_seconds: 10 });
    const r = http.post(`${BASE_URL}/api/stress-test/preset`, body, { headers: REST_HEADERS });
    restLatency.add(r.timings.duration);
    // 200 (activated) or 400 (already active) are both fine
    if (![200, 400].includes(r.status)) restErrors.add(1);
  }
}

// ── Lifecycle hooks ────────────────────────────────────────────────
export function setup() {
  // Smoke check: is the system even reachable?
  const r = http.get(`${BASE_URL}/health`, { headers: REST_HEADERS, timeout: "5s" });
  if (r.status !== 200) {
    fail(`backend not reachable at ${BASE_URL} (status=${r.status})`);
  }
  console.log(`load test starting against ${BASE_URL} / ${WS_URL}`);
}

export function teardown() {
  // Best-effort: deactivate any lingering stress test from the burst scenario
  http.post(`${BASE_URL}/api/stress-test/deactivate`, null, { headers: REST_HEADERS });
}
