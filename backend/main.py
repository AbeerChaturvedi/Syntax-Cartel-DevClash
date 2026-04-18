"""
Project Velure — FastAPI Backend (Production-Grade)
Real-Time Financial Crisis Early Warning System

Main application server:
- WebSocket endpoint for live dashboard streaming
- REST endpoints for historical data and configuration
- Redis Streams event-driven pipeline with graceful fallback
- PostgreSQL star schema persistence for fact table writes
- Circuit breakers for graceful degradation
- Structured JSON logging for observability
- Rate limiting and optional API key auth
- Hybrid data mode: Simulator | Finnhub Live | Both
- Background task: data source → Redis → ML inference → broadcast
"""
import asyncio
import json
import time
from datetime import datetime, timezone
from typing import List
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from utils.config import (
    CORS_ORIGINS, API_KEY, RATE_LIMIT_PER_MINUTE, DEFAULT_TICK_RATE,
    CRISIS_PRESETS, SPEED_PRESETS, DATA_MODE, FINNHUB_API_KEY,
    MODEL_CHECKPOINT_ON_CRISIS, MODEL_CHECKPOINT_PERIODIC_SEC,
    ENABLE_SIMULATOR,
)
from utils.logger import pipeline_log, ws_log, db_log, api_log
from utils.circuit_breaker import redis_circuit, db_circuit
from utils.middleware import SecurityMiddleware

from ingestion.simulator import simulator
from ingestion.redis_streams import redis_streams
from ingestion.watermark import watermark
from models.ensemble import ensemble
from utils.alerting import alert_dispatcher
from utils.model_persistence import get_checkpoint_manager, CHECKPOINT_VERSION


# ── Model lineage + audit hook ──────────────────────────────────────
# We compute an opaque hash over the active checkpoint so that every
# audit_log row stamps the *exact* model state that produced it. If no
# checkpoint exists yet (cold start) the hash is "cold-start".
def _compute_model_version_and_hash() -> tuple[str, str, dict]:
    """Return (model_version, checkpoint_hash, components_dict)."""
    import hashlib
    from pathlib import Path
    from utils.config import MODEL_CHECKPOINT_DIR
    cur = Path(MODEL_CHECKPOINT_DIR) / "current"
    components = {
        "if": True, "lstm": True, "ciss": True, "merton": True, "copula": True,
    }
    if not cur.exists():
        return (CHECKPOINT_VERSION, "cold-start", components)
    h = hashlib.sha256()
    for f in sorted(cur.glob("*")):
        if f.is_file():
            h.update(f.name.encode())
            h.update(b"\0")
            h.update(f.read_bytes())
    return (CHECKPOINT_VERSION, h.hexdigest(), components)


_active_model_version = CHECKPOINT_VERSION
_active_checkpoint_hash = "cold-start"


# ── Connection Manager ──────────────────────────────────────────────
class ConnectionManager:
    """Manages WebSocket connections for live dashboard broadcasting."""

    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        ws_log.info("Client connected", extra={"client_count": len(self.active_connections)})

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            ws_log.info("Client disconnected", extra={"client_count": len(self.active_connections)})

    async def broadcast(self, data: dict):
        """Broadcast to all connected clients — serialize once, fan out."""
        if not self.active_connections:
            return
        
        message = json.dumps(data, default=str)
        dead_connections = []
        
        # Fan out concurrently instead of sequentially — reduces latency
        # when multiple clients are connected
        async def _send(conn):
            try:
                await conn.send_text(message)
            except (WebSocketDisconnect, Exception):
                dead_connections.append(conn)
        
        await asyncio.gather(*[_send(c) for c in self.active_connections])
        
        for conn in dead_connections:
            self.disconnect(conn)


manager = ConnectionManager()


# ── System Metrics ──────────────────────────────────────────────────
_system_metrics = {
    "start_time": time.time(),
    "pipeline_errors": 0,
    "total_ticks_processed": 0,
    "total_broadcasts": 0,
    "avg_pipeline_latency_ms": 0.0,
    "pipeline_latency_samples": [],
    "db_writes": 0,
    "db_errors": 0,
    "peak_ciss": 0.0,
    "peak_combined": 0.0,
    "crisis_events": 0,
}


def _track_pipeline_latency(latency_ms: float):
    samples = _system_metrics["pipeline_latency_samples"]
    samples.append(latency_ms)
    if len(samples) > 200:
        _system_metrics["pipeline_latency_samples"] = samples[-200:]
    _system_metrics["avg_pipeline_latency_ms"] = round(
        sum(_system_metrics["pipeline_latency_samples"]) / len(_system_metrics["pipeline_latency_samples"]), 2
    )


# ── PostgreSQL Persistence ──────────────────────────────────────────
_db_pool = None
_db_available = False
_asset_id_cache: dict = {}  # ticker → asset_id, populated once


async def init_db():
    """Initialize PostgreSQL connection pool. Graceful if unavailable."""
    global _db_pool, _db_available
    try:
        from db.connection import get_pool
        _db_pool = await get_pool()
        _db_available = True
        db_log.info("PostgreSQL connected")
    except Exception as e:
        db_log.warning(f"PostgreSQL unavailable ({e}), running without persistence")
        _db_available = False


async def persist_scores(result: dict, tick_data: dict):
    """Persist computed scores to fact table (non-blocking, best-effort)."""
    if not _db_available or not _db_pool or not db_circuit.is_available:
        return

    try:
        from db.connection import get_or_create_time_id
        epoch_ms = tick_data.get("epoch_ms", int(time.time() * 1000))
        ts = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)

        async with _db_pool.acquire() as conn:
            time_id = await get_or_create_time_id(conn, epoch_ms, ts)
            scores = result.get("scores", {})

            # Batch insert for all assets — use a single transaction
            assets = result.get("assets", {})
            if assets:
                # Populate asset_id cache once (saves 18 queries per tick)
                if not _asset_id_cache:
                    rows_all = await conn.fetch("SELECT asset_id, ticker FROM dim_asset")
                    for r in rows_all:
                        _asset_id_cache[r["ticker"]] = r["asset_id"]

                rows = []
                for ticker, adata in assets.items():
                    asset_id = _asset_id_cache.get(ticker)
                    if asset_id is None:
                        continue
                    rows.append((
                        time_id, asset_id, 5,  # source_id=5 (Simulator)
                        adata.get("price", 0),
                        adata.get("pct_change", 0) / 100 if adata.get("pct_change") else 0,
                        adata.get("spread_bps", 0),
                        adata.get("rolling_volatility", 0),
                        adata.get("volume", 0),
                        scores.get("isolation_forest", 0),
                        scores.get("lstm_autoencoder", 0),
                        scores.get("combined_anomaly", 0),
                        scores.get("ciss", 0),
                        0, 0, False,
                    ))

                if rows:
                    await conn.executemany("""
                        INSERT INTO fact_market_metrics 
                        (time_id, asset_id, source_id, price, price_change, spread_bps,
                         implied_vol, volume, anomaly_score_if, anomaly_score_lstm,
                         anomaly_score_combined, ciss_score, distance_default, prob_default, is_degraded)
                        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
                    """, rows)
                    _system_metrics["db_writes"] += len(rows)

            # Persist alerts
            alert = result.get("alert")
            if alert and alert.get("severity") in ("HIGH", "CRITICAL"):
                from db.connection import insert_alert
                await insert_alert(
                    conn,
                    alert_type=alert.get("type", "SYSTEMIC_STRESS"),
                    severity=alert.get("severity", "HIGH"),
                    model_source="ensemble",
                    description=alert.get("message", ""),
                    asset_id=1,
                    score_value=alert.get("score", 0),
                )
                _system_metrics["crisis_events"] += 1

        db_circuit.record_success()

    except Exception as e:
        db_circuit.record_failure()
        _system_metrics["db_errors"] += 1
        if _system_metrics["db_errors"] <= 5:
            db_log.error(f"Persist error: {e}", extra={"error_type": type(e).__name__})


# ── Background Pipeline ─────────────────────────────────────────────
_pipeline_task = None
_checkpoint_task = None
_pipeline_running = False
_tick_rate = DEFAULT_TICK_RATE
_data_mode = DATA_MODE  # "simulator" | "finnhub" | "hybrid"
_finnhub = None
_last_crisis_ckpt_ts = 0.0


async def _periodic_checkpoint_loop():
    """Save a warm checkpoint every MODEL_CHECKPOINT_PERIODIC_SEC seconds
    so a crash/restart doesn't cost the operator 2 minutes of warmup.
    """
    mgr = get_checkpoint_manager()
    while _pipeline_running:
        await asyncio.sleep(MODEL_CHECKPOINT_PERIODIC_SEC)
        if not _pipeline_running:
            return
        try:
            res = mgr.save()
            pipeline_log.info(f"periodic checkpoint saved → {res.get('path')}")
        except Exception as e:
            pipeline_log.warning(f"periodic checkpoint failed: {e}")


async def ingestion_producer():
    """
    Producer: Generates ticks from simulator and pushes to Redis Streams.
    In hybrid mode, Finnhub also feeds into the same stream via callback.
    When ENABLE_SIMULATOR is false, producer sleeps (ticks come from Finnhub).
    Tags every tick with event-time watermark metadata so the consumer
    can reason about freshness/degraded state.
    """
    if not ENABLE_SIMULATOR:
        # In finnhub-only mode, ticks arrive via _finnhub_tick_handler callback.
        # Producer just stays alive.
        pipeline_log.info("Simulator disabled — waiting for Finnhub ticks")
        while _pipeline_running:
            await asyncio.sleep(1)
        return

    while _pipeline_running:
        try:
            tick_data = simulator.generate_tick()
            tick_data = watermark.ingest("simulator", tick_data)
            await redis_streams.publish_tick(tick_data)
            await asyncio.sleep(_tick_rate)
        except Exception as e:
            _system_metrics["pipeline_errors"] += 1
            pipeline_log.error(f"Producer error: {e}", extra={"component": "producer"})
            await asyncio.sleep(1)


async def _finnhub_tick_handler(tick_data: dict):
    """Callback: when Finnhub emits a tick, push it into the same Redis stream."""
    try:
        tick_data = watermark.ingest("finnhub", tick_data)
        await redis_streams.publish_tick(tick_data)
    except Exception as e:
        pipeline_log.error(f"Finnhub tick relay error: {e}")


async def inference_consumer():
    """
    Consumer: Reads ticks from Redis Streams, runs ML inference, broadcasts.
    Handles backpressure by consuming at its own pace.
    """
    pipeline_log.info("Warming up ML models...")
    # Generate a warmup tick — use simulator if available, else synthetic
    if ENABLE_SIMULATOR:
        warmup_tick = simulator.generate_tick()
    else:
        # Synthetic warmup tick with zero prices to initialize model buffers
        from features.state_builder import TRACKED_ASSETS
        warmup_tick = {
            "assets": {t: {"price": 100.0, "pct_change": 0.0, "volume": 1000,
                           "spread_bps": 1.0, "rolling_volatility": 0.01,
                           "asset_class": "EQUITY"} for t in TRACKED_ASSETS},
            "tick_id": 0, "crisis_mode": False, "crisis_intensity": 0.0,
        }
    await ensemble.process_tick(warmup_tick)
    pipeline_log.info("Models ready")

    while _pipeline_running:
        try:
            start = time.monotonic()

            # Consume from Redis Stream (or fallback queue)
            tick_data = await redis_streams.consume_tick(timeout_ms=200)

            if tick_data is None:
                # No data available — brief sleep
                await asyncio.sleep(0.05)
                continue

            # Process through ensemble
            result = await ensemble.process_tick(tick_data)

            if result:
                # Track peak scores
                ciss = result.get("scores", {}).get("ciss", 0)
                combined = result.get("scores", {}).get("combined_anomaly", 0)
                if ciss > _system_metrics["peak_ciss"]:
                    _system_metrics["peak_ciss"] = round(ciss, 4)
                if combined > _system_metrics["peak_combined"]:
                    _system_metrics["peak_combined"] = round(combined, 4)

                # v3: crisis-triggered checkpoint (rate-limited to 10 min).
                # Freezes the warmed-up state exactly when it matters most —
                # ops can diff a post-incident checkpoint against baseline.
                global _last_crisis_ckpt_ts
                sev = result.get("scores", {}).get("severity", "NORMAL")
                if (
                    MODEL_CHECKPOINT_ON_CRISIS
                    and sev in ("HIGH", "CRITICAL")
                    and (time.time() - _last_crisis_ckpt_ts) > 600
                ):
                    _last_crisis_ckpt_ts = time.time()
                    async def _crisis_ckpt():
                        try:
                            get_checkpoint_manager().save()
                            pipeline_log.info(f"crisis checkpoint saved (sev={sev})")
                        except Exception as e:
                            pipeline_log.warning(f"crisis checkpoint failed: {e}")
                    asyncio.create_task(_crisis_ckpt())

                # Broadcast to WebSocket clients
                await manager.broadcast(result)
                _system_metrics["total_broadcasts"] += 1

                # Publish inference results to Redis (for caching)
                await redis_streams.publish_inference(result)

                # Publish alerts to Redis stream
                alert = result.get("alert")
                if alert:
                    await redis_streams.publish_alert(alert)

                # Persist to PostgreSQL (fire-and-forget)
                asyncio.create_task(persist_scores(result, tick_data))

            elapsed_ms = (time.monotonic() - start) * 1000
            _track_pipeline_latency(elapsed_ms)
            _system_metrics["total_ticks_processed"] += 1

        except Exception as e:
            _system_metrics["pipeline_errors"] += 1
            pipeline_log.error(f"Consumer error: {e}", extra={"component": "consumer"})
            await asyncio.sleep(0.5)


async def data_pipeline():
    """
    Core pipeline: runs producer and consumer concurrently.
    Producer pushes to Redis Streams, Consumer pulls and processes.
    """
    global _pipeline_running
    _pipeline_running = True

    # Run both concurrently
    await asyncio.gather(
        ingestion_producer(),
        inference_consumer(),
    )


# ── App Lifecycle ────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background pipeline on app startup, stop on shutdown."""
    global _pipeline_task, _checkpoint_task, _pipeline_running, _finnhub

    # Initialize Redis Streams
    await redis_streams.connect()

    # Initialize PostgreSQL
    await init_db()

    # v3: Attempt warm-start from disk checkpoint.  Safe to fail — an
    # empty/missing checkpoint just means cold start.
    try:
        ck = get_checkpoint_manager().load()
        if ck.get("ok"):
            pipeline_log.info(f"checkpoint loaded: {ck.get('components')}")
        else:
            pipeline_log.info(f"no checkpoint ({ck.get('reason')}); cold start")
    except Exception as e:
        pipeline_log.warning(f"checkpoint load failed: {e}")

    # v4: stamp the active model version + checkpoint hash, register it
    # in model_lineage if Postgres is reachable.
    global _active_model_version, _active_checkpoint_hash
    _active_model_version, _active_checkpoint_hash, _components = _compute_model_version_and_hash()
    pipeline_log.info(
        f"model lineage: version={_active_model_version} hash={_active_checkpoint_hash[:12]}…"
    )
    if _db_available and _db_pool:
        try:
            from db.connection import upsert_model_lineage
            async with _db_pool.acquire() as conn:
                await upsert_model_lineage(
                    conn,
                    model_version=_active_model_version,
                    checkpoint_hash=_active_checkpoint_hash,
                    components=_components,
                    ensemble_weights={
                        "if":   ensemble.if_weight,
                        "lstm": ensemble.lstm_weight,
                        "ciss": ensemble.ciss_weight,
                        "copula": ensemble.copula_weight,
                    },
                )
        except Exception as e:
            db_log.warning(f"model_lineage upsert failed: {e}")

    # v4: wire the audit sink so every dispatched alert is recorded in
    # the tamper-evident audit_log.
    async def _audit_alert(alert: dict, dispatch_result: dict):
        if not (_db_available and _db_pool):
            return
        try:
            from db.connection import insert_audit_log
            payload = {
                **alert,
                "sinks": dispatch_result.get("sinks", {}),
                "delivered": dispatch_result.get("delivered", False),
            }
            async with _db_pool.acquire() as conn:
                await insert_audit_log(
                    conn,
                    actor="alert_dispatcher",
                    event_type="ALERT_DISPATCH",
                    severity=(alert.get("severity") or "INFO").upper(),
                    model_version=_active_model_version,
                    payload=payload,
                )
        except Exception as e:
            db_log.warning(f"audit_log insert failed: {e}")

    alert_dispatcher.set_audit_sink(_audit_alert)

    # Initialize Finnhub live data (if configured)
    if _data_mode in ("finnhub", "hybrid") and FINNHUB_API_KEY:
        try:
            from ingestion.finnhub_connector import get_finnhub_connector
            _finnhub = get_finnhub_connector(FINNHUB_API_KEY)
            started = await _finnhub.start(on_tick=_finnhub_tick_handler)
            if started:
                pipeline_log.info("Finnhub live data connector active", extra={"component": "finnhub"})
        except Exception as e:
            pipeline_log.warning(f"Finnhub init failed ({e}), using simulator only")

    _pipeline_task = asyncio.create_task(data_pipeline())
    # v3: start periodic checkpoint loop
    _checkpoint_task = asyncio.create_task(_periodic_checkpoint_loop())

    pipeline_log.info("Crisis Early Warning System Online")
    pipeline_log.info(f"Redis: {'Connected' if redis_streams._connected else 'Fallback mode'}")
    pipeline_log.info(f"PostgreSQL: {'Connected' if _db_available else 'Offline'}")
    pipeline_log.info(f"Data mode: {_data_mode}")

    yield

    # Graceful shutdown
    _pipeline_running = False
    # v3: best-effort final checkpoint on shutdown
    try:
        get_checkpoint_manager().save()
        pipeline_log.info("final checkpoint saved on shutdown")
    except Exception as e:
        pipeline_log.warning(f"final checkpoint failed: {e}")
    if _finnhub:
        await _finnhub.stop()
    for t in (_pipeline_task, _checkpoint_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    await redis_streams.disconnect()
    if _db_pool:
        await _db_pool.close()
    pipeline_log.info("System shutdown complete")


# ── FastAPI App ──────────────────────────────────────────────────────
app = FastAPI(
    title="Project Velure — Crisis Early Warning System",
    description="Real-time financial crisis detection using ML ensemble (IF + LSTM + CISS + Merton + VaR)",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — configurable origins.
# Production assertion: if VELURE_API_KEY is set we treat this as prod and
# refuse a wildcard origin. Defence in depth — operators can still
# misconfigure via env, but the process won't boot in an unsafe state.
_cors_origins = [o.strip() for o in CORS_ORIGINS.split(",")] if CORS_ORIGINS != "*" else ["*"]
if API_KEY and "*" in _cors_origins:
    raise RuntimeError(
        "Refusing to start: CORS_ORIGINS='*' with an API key set is unsafe. "
        "Set CORS_ORIGINS to an explicit comma-separated list of HTTPS origins."
    )
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Rate limiting + optional API key auth
app.add_middleware(SecurityMiddleware, rate_limit=RATE_LIMIT_PER_MINUTE, api_key=API_KEY)


# ── Health Check (for Docker / Load Balancers) ──────────────────────
@app.get("/health")
async def health_check():
    """Deep health check — verifies all dependencies."""
    checks = {
        "pipeline": _pipeline_running,
        "redis": redis_streams._connected,
        "postgresql": _db_available,
        "models": _system_metrics["total_ticks_processed"] > 0 or time.time() - _system_metrics["start_time"] < 30,
    }
    healthy = checks["pipeline"]
    return {
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
        "uptime_seconds": round(time.time() - _system_metrics["start_time"], 1),
    }


# ── WebSocket Endpoint ──────────────────────────────────────────────
@app.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket):
    """
    Live dashboard WebSocket — streams ML scores + market data.

    Auth: when API_KEY is set the client must present it via either:
      · `X-API-Key` request header (preferred — proxies forward it)
      · `?api_key=…` query string (fallback for browser clients that
        cannot set custom headers on `new WebSocket(...)`)

    A bad/missing key closes the socket with policy-violation 1008
    *before* it is registered with the connection manager — so
    unauthenticated clients can't grow our memory footprint.
    """
    if API_KEY:
        provided = (
            websocket.headers.get("x-api-key")
            or websocket.query_params.get("api_key", "")
        )
        if provided != API_KEY:
            ws_log.warning(
                "ws auth rejected",
                extra={"client": websocket.client.host if websocket.client else "?"},
            )
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, handle client messages
            data = await websocket.receive_text()
            msg = json.loads(data)

            # Handle client commands
            if msg.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)


# ── REST Endpoints ───────────────────────────────────────────────────

class StressTestRequest(BaseModel):
    intensity: float = Field(default=0.8, ge=0.1, le=1.0)
    duration_seconds: int = Field(default=30, ge=5, le=300)


class CrisisPresetRequest(BaseModel):
    scenario: str
    intensity: float = Field(default=0.8, ge=0.1, le=1.0)
    duration_seconds: int = Field(default=45, ge=5, le=300)


# REST Endpoints use CRISIS_PRESETS from utils.config


@app.get("/")
async def root():
    return {
        "system": "Project Velure",
        "version": "3.0.0",
        "status": "operational",
        "pipeline_running": _pipeline_running,
        "connected_clients": len(manager.active_connections),
        "tick_count": _system_metrics["total_ticks_processed"],
        "crisis_mode": simulator.crisis_mode if ENABLE_SIMULATOR else False,
        "data_mode": _data_mode,
        "redis_mode": "streams" if redis_streams._connected else "in-process",
        "db_connected": _db_available,
    }


@app.get("/api/status")
async def system_status():
    """System health and model status."""
    return {
        "status": "operational",
        "pipeline_running": _pipeline_running,
        "connected_clients": len(manager.active_connections),
        "tick_count": _system_metrics["total_ticks_processed"],
        "tick_rate_hz": round(1 / _tick_rate, 1),
        "crisis_mode": simulator.crisis_mode if ENABLE_SIMULATOR else False,
        "crisis_intensity": simulator.crisis_intensity if ENABLE_SIMULATOR else 0.0,
        "data_mode": _data_mode,
        "simulator_enabled": ENABLE_SIMULATOR,
        "models": {
            "isolation_forest": "active",
            "lstm_autoencoder": "active",
            "ciss_scorer": "active",
            "merton_model": "active",
            "var_calculator": "active",
            "copula_model": "active",
        },
        "tracked_assets": 15,
        "infrastructure": {
            "redis": "connected" if redis_streams._connected else "fallback",
            "postgresql": "connected" if _db_available else "offline",
            "finnhub": _finnhub.get_status() if _finnhub else "disabled",
        },
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
    }


@app.get("/api/scores")
async def get_latest_scores():
    """Get latest computed risk scores (REST fallback)."""
    scores = ensemble.get_latest_scores()
    if not scores:
        return {"status": "warming_up", "message": "Models are calibrating..."}
    return scores


@app.get("/api/merton")
async def get_merton_scores():
    """Get Distance-to-Default scores for all tracked institutions."""
    scores = ensemble.get_latest_scores()
    return scores.get("merton", [])


@app.get("/api/merton/srisk")
async def get_system_srisk():
    """Get aggregate System SRISK — total capital shortfall across all institutions."""
    scores = ensemble.get_latest_scores()
    merton = scores.get("merton", [])
    total_srisk = sum(inst.get("srisk_bn", 0) for inst in merton)
    institutions = [
        {
            "ticker": inst["ticker"],
            "name": inst["name"],
            "srisk_bn": inst.get("srisk_bn", 0),
            "dd": inst.get("distance_to_default", 0),
            "pd": inst.get("prob_default", 0),
            "lrmes": inst.get("lrmes", 0),
            "status": inst.get("status", "UNKNOWN"),
        }
        for inst in merton
    ]
    return {
        "total_srisk_bn": round(total_srisk, 2),
        "institutions": institutions,
        "system_status": "CRITICAL" if total_srisk > 500 else "WARNING" if total_srisk > 200 else "HEALTHY",
    }


@app.get("/api/ciss/breakdown")
async def get_ciss_breakdown():
    """Get CISS component breakdown for explainability."""
    from models.ciss_scorer import ciss_scorer
    return ciss_scorer.get_breakdown()


@app.get("/api/var")
async def get_var_metrics():
    """Get Value-at-Risk and Conditional VaR metrics."""
    scores = ensemble.get_latest_scores()
    return scores.get("var_metrics", {})




@app.get("/api/alerts")
async def get_recent_alerts():
    """Get recent alert history."""
    scores = ensemble.get_latest_scores()
    return scores.get("recent_alerts", [])


@app.get("/api/crisis-presets")
async def get_crisis_presets():
    """Get available crisis simulation presets."""
    return CRISIS_PRESETS


@app.post("/api/stress-test/activate")
async def activate_stress_test(request: StressTestRequest):
    """
    Activate crisis simulation.
    Injects 2008-style correlation breakdown and volatility spike.
    Requires ENABLE_SIMULATOR=true.
    """
    if not ENABLE_SIMULATOR:
        raise HTTPException(status_code=400, detail="Crisis simulation requires ENABLE_SIMULATOR=true")
    simulator.activate_crisis(intensity=request.intensity)
    
    # Auto-deactivate after duration
    async def auto_deactivate():
        await asyncio.sleep(request.duration_seconds)
        simulator.deactivate_crisis()
    
    asyncio.create_task(auto_deactivate())

    api_log.info(
        f"Stress test activated: intensity={request.intensity}, duration={request.duration_seconds}s",
    )

    return {
        "status": "crisis_activated",
        "intensity": request.intensity,
        "duration_seconds": request.duration_seconds,
        "message": f"Stress test active. Correlations spiking to {request.intensity:.0%}. "
                   f"Auto-deactivating in {request.duration_seconds}s.",
    }


@app.post("/api/stress-test/preset")
async def activate_crisis_preset(request: CrisisPresetRequest):
    """Activate a named crisis scenario preset."""
    if not ENABLE_SIMULATOR:
        raise HTTPException(status_code=400, detail="Crisis simulation requires ENABLE_SIMULATOR=true")
    preset = CRISIS_PRESETS.get(request.scenario)
    if not preset and request.scenario != "custom":
        raise HTTPException(status_code=400, detail=f"Unknown preset: {request.scenario}")

    intensity = request.intensity if request.scenario == "custom" else preset["intensity"]
    duration = request.duration_seconds if request.scenario == "custom" else preset["duration_seconds"]

    simulator.activate_crisis(intensity=intensity)

    async def auto_deactivate():
        await asyncio.sleep(duration)
        simulator.deactivate_crisis()

    asyncio.create_task(auto_deactivate())

    return {
        "status": "crisis_activated",
        "scenario": request.scenario,
        "name": preset["name"] if preset else "Custom",
        "description": preset["description"] if preset else "User-defined parameters",
        "intensity": intensity,
        "duration_seconds": duration,
    }


@app.post("/api/stress-test/deactivate")
async def deactivate_stress_test():
    """Manually deactivate crisis simulation."""
    simulator.deactivate_crisis()
    return {"status": "crisis_deactivated", "message": "Markets returning to normal conditions."}


@app.get("/api/metrics")
async def get_system_metrics():
    """Get real-time system health metrics for dashboard."""
    uptime = time.time() - _system_metrics["start_time"]
    tps = _system_metrics["total_ticks_processed"] / max(1, uptime)

    redis_metrics = redis_streams.get_metrics()
    stream_info = await redis_streams.get_stream_info()

    return {
        "uptime_seconds": round(uptime, 1),
        "ticks_per_second": round(tps, 2),
        "total_ticks_processed": _system_metrics["total_ticks_processed"],
        "total_broadcasts": _system_metrics["total_broadcasts"],
        "pipeline_errors": _system_metrics["pipeline_errors"],
        "avg_pipeline_latency_ms": _system_metrics["avg_pipeline_latency_ms"],
        "db_writes": _system_metrics["db_writes"],
        "db_errors": _system_metrics["db_errors"],
        "peak_ciss": _system_metrics["peak_ciss"],
        "peak_combined": _system_metrics["peak_combined"],
        "crisis_events": _system_metrics["crisis_events"],
        "connected_clients": len(manager.active_connections),
        "data_mode": _data_mode,
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
        "redis": redis_metrics,
        "stream": stream_info,
    }


@app.get("/api/config")
async def get_config():
    """Get system configuration."""
    return {
        "tick_rate_hz": round(1 / _tick_rate, 1),
        "batch_size": ensemble.batch_size,
        "flush_interval_ms": ensemble.flush_interval_ms,
        "alert_thresholds": ensemble.ALERT_THRESHOLDS,
        "ensemble_weights": {
            "isolation_forest": ensemble.if_weight,
            "lstm_autoencoder": ensemble.lstm_weight,
            "ciss": ensemble.ciss_weight,
            "copula_tail": ensemble.copula_weight,
        },
        "tracked_assets": list(simulator.ASSETS.keys()) if ENABLE_SIMULATOR else [],
        "crisis_presets": list(CRISIS_PRESETS.keys()),
        "data_mode": _data_mode,
        "infrastructure": {
            "redis": "connected" if redis_streams._connected else "fallback",
            "postgresql": "connected" if _db_available else "offline",
            "finnhub": "active" if (_finnhub and _finnhub.connected) else "disabled",
        },
    }


# ── Speed Control ───────────────────────────────────────────────────


@app.post("/api/speed/{mode}")
async def set_pipeline_speed(mode: str):
    """Adjust pipeline tick rate for demo purposes."""
    global _tick_rate
    rate = SPEED_PRESETS.get(mode)
    if rate is None:
        raise HTTPException(status_code=400, detail=f"Unknown speed: {mode}. Use: {list(SPEED_PRESETS.keys())}")
    _tick_rate = rate
    api_log.info(f"Speed changed to {mode} ({round(1/rate, 1)} Hz)")
    return {"speed": mode, "tick_rate_hz": round(1 / rate, 1)}


# ── Prometheus-Compatible Metrics ───────────────────────────────────
@app.get("/metrics")
async def prometheus_metrics():
    """
    Prometheus text exposition format.
    Scrape at /metrics for Grafana/Alertmanager integration.
    """
    from fastapi.responses import PlainTextResponse

    uptime = time.time() - _system_metrics["start_time"]
    tps = _system_metrics["total_ticks_processed"] / max(1, uptime)
    scores = ensemble.get_latest_scores()
    s = scores.get("scores", {})

    lines = [
        "# HELP velure_uptime_seconds System uptime in seconds",
        "# TYPE velure_uptime_seconds gauge",
        f"velure_uptime_seconds {uptime:.1f}",
        "",
        "# HELP velure_ticks_total Total ticks processed",
        "# TYPE velure_ticks_total counter",
        f"velure_ticks_total {_system_metrics['total_ticks_processed']}",
        "",
        "# HELP velure_ticks_per_second Current throughput",
        "# TYPE velure_ticks_per_second gauge",
        f"velure_ticks_per_second {tps:.2f}",
        "",
        "# HELP velure_broadcasts_total Total WebSocket broadcasts",
        "# TYPE velure_broadcasts_total counter",
        f"velure_broadcasts_total {_system_metrics['total_broadcasts']}",
        "",
        "# HELP velure_pipeline_errors_total Total pipeline errors",
        "# TYPE velure_pipeline_errors_total counter",
        f"velure_pipeline_errors_total {_system_metrics['pipeline_errors']}",
        "",
        "# HELP velure_pipeline_latency_ms Average pipeline latency in milliseconds",
        "# TYPE velure_pipeline_latency_ms gauge",
        f"velure_pipeline_latency_ms {_system_metrics['avg_pipeline_latency_ms']:.2f}",
        "",
        "# HELP velure_connected_clients Current WebSocket clients",
        "# TYPE velure_connected_clients gauge",
        f"velure_connected_clients {len(manager.active_connections)}",
        "",
        "# HELP velure_db_writes_total Total PostgreSQL writes",
        "# TYPE velure_db_writes_total counter",
        f"velure_db_writes_total {_system_metrics['db_writes']}",
        "",
        "# HELP velure_db_errors_total Total PostgreSQL errors",
        "# TYPE velure_db_errors_total counter",
        f"velure_db_errors_total {_system_metrics['db_errors']}",
        "",
        "# HELP velure_crisis_events_total Total crisis events detected",
        "# TYPE velure_crisis_events_total counter",
        f"velure_crisis_events_total {_system_metrics['crisis_events']}",
        "",
        "# HELP velure_score_ciss Current CISS systemic stress score",
        "# TYPE velure_score_ciss gauge",
        f"velure_score_ciss {s.get('ciss', 0):.6f}",
        "",
        "# HELP velure_score_combined Current combined anomaly score",
        "# TYPE velure_score_combined gauge",
        f"velure_score_combined {s.get('combined_anomaly', 0):.6f}",
        "",
        "# HELP velure_score_isolation_forest Current IF anomaly score",
        "# TYPE velure_score_isolation_forest gauge",
        f"velure_score_isolation_forest {s.get('isolation_forest', 0):.6f}",
        "",
        "# HELP velure_score_lstm Current LSTM reconstruction anomaly score",
        "# TYPE velure_score_lstm gauge",
        f"velure_score_lstm {s.get('lstm_autoencoder', 0):.6f}",
        "",
        "# HELP velure_peak_ciss Peak CISS score observed",
        "# TYPE velure_peak_ciss gauge",
        f"velure_peak_ciss {_system_metrics['peak_ciss']:.6f}",
        "",
        "# HELP velure_peak_combined Peak combined score observed",
        "# TYPE velure_peak_combined gauge",
        f"velure_peak_combined {_system_metrics['peak_combined']:.6f}",
        "",
        "# HELP velure_circuit_breaker_state Circuit breaker state (0=closed, 1=open, 2=half-open)",
        "# TYPE velure_circuit_breaker_state gauge",
    ]

    _cb_map = {"CLOSED": 0, "OPEN": 1, "HALF_OPEN": 2}
    redis_cb = _cb_map.get(redis_circuit.get_status()["state"], 0)
    db_cb = _cb_map.get(db_circuit.get_status()["state"], 0)
    lines.append(f'velure_circuit_breaker_state{{service="redis"}} {redis_cb}')
    lines.append(f'velure_circuit_breaker_state{{service="postgresql"}} {db_cb}')
    lines.append("")

    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4; charset=utf-8")


# ══════════════════════════════════════════════════════════════════════
# v3 ENDPOINTS — copula · portfolio VaR · replay · backtest · alerting ·
# checkpoint · watermark
# ══════════════════════════════════════════════════════════════════════

# ── Copula / Tail-Dependence ────────────────────────────────────────
@app.get("/api/copula")
async def get_copula_snapshot():
    """t-Copula tail-dependence snapshot: ρ matrix, λ_L matrix, ν, hot pair."""
    from models.copula_model import copula_model
    return copula_model.get_snapshot()


# ── Portfolio VaR ───────────────────────────────────────────────────
@app.post("/api/var/portfolio")
async def compute_portfolio_var(request: dict):
    """
    Compute portfolio VaR/CVaR from live price data.
    Expects: { "weights": {"SPY": 0.4, "QQQ": 0.2, ...}, "notional": 1000000, "confidence": 0.99 }
    """
    import numpy as np
    from scipy.stats import norm, skew, kurtosis
    from features.state_builder import state_builder

    weights = request.get("weights", {})
    notional = request.get("notional", 1_000_000)
    confidence = request.get("confidence", 0.99)

    if not weights:
        raise HTTPException(status_code=400, detail="No portfolio weights provided")

    # Gather returns from state_builder's price history, fall back to simulator
    all_returns = {}
    for ticker, weight in weights.items():
        hist = list(state_builder._history.get(ticker, []))
        if len(hist) < 10:
            sim_hist = list(simulator._history.get(ticker, []))
            hist = sim_hist if len(sim_hist) >= 10 else hist
        if len(hist) >= 10:
            prices = np.array(hist, dtype=np.float64)
            rets = np.diff(np.log(prices))
            all_returns[ticker] = rets

    if not all_returns:
        raise HTTPException(status_code=400, detail="Insufficient price history for VaR computation")

    # Align return series to same length
    min_len = min(len(r) for r in all_returns.values())
    tickers_used = list(all_returns.keys())
    w_vec = np.array([weights.get(t, 0) for t in tickers_used])
    w_vec = w_vec / w_vec.sum()  # Normalize

    returns_matrix = np.column_stack([all_returns[t][-min_len:] for t in tickers_used])
    portfolio_returns = returns_matrix @ w_vec

    # 1. Historical VaR
    hist_var = float(np.percentile(portfolio_returns, (1 - confidence) * 100))

    # 2. Parametric VaR (Gaussian)
    mu = np.mean(portfolio_returns)
    sigma = np.std(portfolio_returns)
    z = norm.ppf(1 - confidence)
    param_var = float(mu + z * sigma)

    # 3. Cornish-Fisher VaR (skew/kurtosis adjusted)
    s = float(skew(portfolio_returns)) if len(portfolio_returns) > 10 else 0
    k = float(kurtosis(portfolio_returns, fisher=True)) if len(portfolio_returns) > 10 else 0
    cf_z = z + (z**2 - 1) * s / 6 + (z**3 - 3*z) * k / 24 - (2*z**3 - 5*z) * s**2 / 36
    cf_var = float(mu + cf_z * sigma)

    # 4. CVaR (Expected Shortfall)
    tail = portfolio_returns[portfolio_returns <= hist_var]
    cvar = float(np.mean(tail)) if len(tail) > 0 else hist_var

    # 5. Component VaR
    cov_matrix = np.cov(returns_matrix, rowvar=False)
    marginal_contrib = cov_matrix @ w_vec
    component_var = {}
    total_var_abs = abs(hist_var) if hist_var != 0 else 1e-8
    for i, t in enumerate(tickers_used):
        contrib = float(w_vec[i] * marginal_contrib[i])
        component_var[t] = {
            "weight": float(w_vec[i]),
            "contribution_pct": round(contrib / total_var_abs * 100, 2),
            "marginal_var": round(float(marginal_contrib[i]) * 100, 4),
        }

    # Risk regime
    if abs(hist_var) < 0.01:
        regime = "LOW"
    elif abs(hist_var) < 0.03:
        regime = "MODERATE"
    elif abs(hist_var) < 0.06:
        regime = "HIGH"
    else:
        regime = "EXTREME"

    return {
        "historical_var": round(hist_var * 100, 4),
        "parametric_var": round(param_var * 100, 4),
        "cornish_fisher_var": round(cf_var * 100, 4),
        "cvar": round(cvar * 100, 4),
        "dollar_var": round(abs(hist_var) * notional, 2),
        "dollar_cvar": round(abs(cvar) * notional, 2),
        "component_var": component_var,
        "confidence": confidence,
        "regime": regime,
        "data_points": min_len,
        "tickers_used": tickers_used,
    }



# ── Alerting ────────────────────────────────────────────────────────
@app.get("/api/alerting/status")
async def alerting_status():
    return alert_dispatcher.status()


@app.post("/api/alerting/test")
async def alerting_test(severity: str = "HIGH"):
    """Send a synthetic alert through every configured sink."""
    return await alert_dispatcher.test_alert(severity=severity)


# ── Checkpoint ──────────────────────────────────────────────────────
@app.post("/api/checkpoint/save")
async def checkpoint_save():
    """Manually snapshot the full ensemble state to disk."""
    try:
        res = get_checkpoint_manager().save()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/checkpoint/load")
async def checkpoint_load():
    """Restore ensemble state from the latest on-disk checkpoint."""
    try:
        res = get_checkpoint_manager().load()
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Watermark observability ─────────────────────────────────────────
@app.get("/api/watermark")
async def watermark_status():
    """Event-time watermark + per-source staleness stats."""
    return watermark.status()


# ── Audit log + lineage (v4) ────────────────────────────────────────
@app.get("/api/audit")
async def audit_log(limit: int = 50, event_type: str = None):
    """
    Recent audit_log rows (most recent first).
    Empty result if Postgres is unavailable — callers should treat that
    as "audit unavailable", not "no events".
    """
    if not (_db_available and _db_pool):
        return {"available": False, "rows": []}
    limit = max(1, min(limit, 500))
    async with _db_pool.acquire() as conn:
        if event_type:
            rows = await conn.fetch(
                """
                SELECT audit_id, occurred_at, actor, event_type, severity,
                       model_version, payload, prev_hash, this_hash
                FROM audit_log
                WHERE event_type = $1
                ORDER BY audit_id DESC LIMIT $2
                """,
                event_type, limit,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT audit_id, occurred_at, actor, event_type, severity,
                       model_version, payload, prev_hash, this_hash
                FROM audit_log
                ORDER BY audit_id DESC LIMIT $1
                """,
                limit,
            )
        return {"available": True, "count": len(rows), "rows": [dict(r) for r in rows]}


@app.get("/api/audit/verify")
async def audit_verify(scan_limit: int = 1000):
    """
    Walk the most recent N audit rows and verify the hash chain is intact.
    Returns the first broken row (if any) so an operator can investigate.
    Cheap: pure read, ~O(N) sha256 hashes.
    """
    import hashlib
    import json as _json
    if not (_db_available and _db_pool):
        return {"available": False}
    scan_limit = max(10, min(scan_limit, 10000))
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT audit_id, actor, event_type, severity, model_version,
                   payload, prev_hash, this_hash
            FROM audit_log
            ORDER BY audit_id ASC
            LIMIT $1
            """,
            scan_limit,
        )
    if not rows:
        return {"available": True, "scanned": 0, "intact": True}

    prev_hash = None
    for r in rows:
        canonical = _json.dumps(
            {
                "actor":         r["actor"],
                "event_type":    r["event_type"],
                "severity":      r["severity"],
                "model_version": r["model_version"],
                "payload":       (r["payload"] if isinstance(r["payload"], dict)
                                  else _json.loads(r["payload"])),
            },
            sort_keys=True, separators=(",", ":"), default=str,
        )
        h = hashlib.sha256(((prev_hash or "") + canonical).encode("utf-8")).hexdigest()
        if h != r["this_hash"] or r["prev_hash"] != prev_hash:
            return {
                "available": True,
                "scanned": len(rows),
                "intact": False,
                "broken_at_id": r["audit_id"],
                "expected_hash": h,
                "stored_hash":   r["this_hash"],
            }
        prev_hash = r["this_hash"]

    return {"available": True, "scanned": len(rows), "intact": True}


@app.get("/api/lineage")
async def model_lineage_list():
    """Active model versions known to the system."""
    if not (_db_available and _db_pool):
        return {"available": False, "active": {
            "model_version": _active_model_version,
            "checkpoint_hash": _active_checkpoint_hash,
        }}
    async with _db_pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT lineage_id, model_version, checkpoint_hash, components,
                   ensemble_weights, activated_at, deactivated_at
            FROM model_lineage
            ORDER BY activated_at DESC
            LIMIT 50
        """)
        return {
            "available": True,
            "active": {
                "model_version": _active_model_version,
                "checkpoint_hash": _active_checkpoint_hash,
            },
            "history": [dict(r) for r in rows],
        }


# ══════════════════════════════════════════════════════════════════════
# v4 ENDPOINTS — Finnhub live · historical backfill · data mode
# ══════════════════════════════════════════════════════════════════════

@app.get("/api/finnhub/status")
async def finnhub_status():
    """Get Finnhub WebSocket connection status and live data metrics."""
    if not _finnhub:
        return {"enabled": False, "reason": "No Finnhub API key configured"}
    return {"enabled": True, **_finnhub.get_status()}


@app.post("/api/historical/backfill")
async def trigger_backfill(
    start_date: str = "2019-01-01",
    end_date: str = None,
):
    """
    Trigger historical data backfill from Polygon.io.
    Runs in background; check status via GET /api/historical/status.
    """
    from ingestion.historical_loader import historical_loader

    async def _run_backfill():
        try:
            await historical_loader.backfill(start_date=start_date, end_date=end_date)
        except Exception as e:
            api_log.error(f"Backfill error: {e}")

    asyncio.create_task(_run_backfill())
    return {"ok": True, "message": "Backfill started in background", "start_date": start_date}


@app.get("/api/historical/status")
async def historical_status():
    """Get historical data cache status."""
    from ingestion.historical_loader import historical_loader
    return historical_loader.get_status()


@app.get("/api/data-mode")
async def get_data_mode():
    """Get current data mode and source information."""
    from features.state_builder import state_builder
    return {
        "mode": _data_mode,
        "simulator_enabled": ENABLE_SIMULATOR,
        "finnhub_connected": _finnhub.connected if _finnhub else False,
        "state_builder_has_data": state_builder.has_data(),
        "tracked_assets": state_builder.tracked_assets,
    }


# ── Backtest API ──────────────────────────────────────────────────────

_backtest_state = {"running": False, "progress": 0, "results": None}

CRISIS_CATALOG = [
    {"name": "Lehman Collapse 2008", "start": "2008-09-10", "end": "2008-09-20",
     "preset": "lehman_2008", "description": "Credit contagion, interbank freeze"},
    {"name": "Flash Crash 2010", "start": "2010-05-06", "end": "2010-05-07",
     "preset": "flash_crash_2010", "description": "Algorithmic cascade"},
    {"name": "EU Sovereign Debt 2011", "start": "2011-08-01", "end": "2011-08-15",
     "preset": "sovereign_debt", "description": "European debt crisis"},
    {"name": "China Black Monday 2015", "start": "2015-08-24", "end": "2015-08-28",
     "preset": "china_2015", "description": "China market crash"},
    {"name": "Volmageddon 2018", "start": "2018-02-05", "end": "2018-02-09",
     "preset": "volmageddon", "description": "VIX spike, XIV collapse"},
    {"name": "COVID Crash 2020", "start": "2020-03-05", "end": "2020-03-15",
     "preset": "covid_2020", "description": "Global pandemic selloff"},
    {"name": "SVB Bank Run 2023", "start": "2023-03-08", "end": "2023-03-14",
     "preset": "svb_2023", "description": "Regional bank contagion"},
]


@app.get("/api/backtest/crises")
async def get_backtest_crises():
    """Get list of available crisis windows for backtesting."""
    return CRISIS_CATALOG


@app.post("/api/backtest/run")
async def run_backtest(request: dict):
    """Run backtest across selected crisis windows."""
    import numpy as np
    global _backtest_state

    if _backtest_state["running"]:
        raise HTTPException(status_code=409, detail="Backtest already running")

    crisis_names = request.get("crisis_names", [])
    if not crisis_names:
        crisis_names = [c["name"] for c in CRISIS_CATALOG]

    _backtest_state = {"running": True, "progress": 0, "results": None}

    async def _execute_backtest():
        global _backtest_state
        try:
            per_crisis = {}
            total = len(crisis_names)

            for idx, name in enumerate(crisis_names):
                # Simulate crisis through the ensemble
                n_ticks = 200
                scores = []
                labels = []

                for t in range(n_ticks):
                    is_crisis_zone = t >= n_ticks * 0.4 and t <= n_ticks * 0.8
                    intensity = 0.7 if is_crisis_zone else 0.0

                    if is_crisis_zone:
                        simulator.activate_crisis(intensity=intensity)
                    else:
                        simulator.deactivate_crisis()

                    tick = simulator.generate_tick()
                    result = await ensemble.process_tick(tick)
                    if result:
                        combined = result.get("scores", {}).get("combined_anomaly", 0)
                        scores.append(combined)
                        labels.append(1 if is_crisis_zone else 0)

                    await asyncio.sleep(0)  # Yield to event loop

                simulator.deactivate_crisis()
                _backtest_state["progress"] = (idx + 0.9) / total

                # Compute ROC/AUC
                if scores and len(set(labels)) > 1:
                    from sklearn.metrics import roc_auc_score, roc_curve, precision_score, recall_score
                    thresholds_eval = np.linspace(0, 1, 50)
                    y_true = np.array(labels)
                    y_scores = np.array(scores)

                    try:
                        auc = float(roc_auc_score(y_true, y_scores))
                        fpr, tpr, _ = roc_curve(y_true, y_scores)
                        preds = (y_scores > 0.5).astype(int)
                        prec = float(precision_score(y_true, preds, zero_division=0))
                        rec = float(recall_score(y_true, preds, zero_division=0))
                        fp_rate = float(np.sum((preds == 1) & (y_true == 0)) / max(np.sum(y_true == 0), 1))

                        # Lead time: first tick where score > 0.5 before crisis zone
                        crisis_start_idx = int(n_ticks * 0.4)
                        lead_time = 0
                        for lt in range(crisis_start_idx):
                            if scores[lt] > 0.4:
                                lead_time = crisis_start_idx - lt
                                break

                        per_crisis[name] = {
                            "auc": auc,
                            "precision": prec,
                            "recall": rec,
                            "false_positive_rate": fp_rate,
                            "lead_time_ticks": lead_time,
                            "fpr": fpr.tolist(),
                            "tpr": tpr.tolist(),
                        }
                    except Exception:
                        per_crisis[name] = {"auc": 0.5, "precision": 0, "recall": 0, "false_positive_rate": 0, "lead_time_ticks": 0}
                else:
                    per_crisis[name] = {"auc": 0.5, "precision": 0, "recall": 0, "false_positive_rate": 0, "lead_time_ticks": 0}

                _backtest_state["progress"] = (idx + 1) / total

            # Aggregate
            auc_values = [v["auc"] for v in per_crisis.values() if v["auc"] > 0]
            _backtest_state["results"] = {
                "per_crisis": per_crisis,
                "aggregate": {
                    "mean_auc": float(np.mean(auc_values)) if auc_values else 0,
                    "total_crises": len(per_crisis),
                    "runtime_ms": 0,
                },
            }
        except Exception as e:
            api_log.error(f"Backtest failed: {e}")
        finally:
            _backtest_state["running"] = False

    asyncio.create_task(_execute_backtest())
    return {"ok": True, "status": {"running": True, "progress": 0}}


@app.get("/api/backtest/status")
async def get_backtest_status():
    """Get backtest progress."""
    return _backtest_state


@app.get("/api/backtest/results")
async def get_backtest_results():
    """Get backtest results."""
    if _backtest_state["results"] is None:
        raise HTTPException(status_code=404, detail="No backtest results available")
    return _backtest_state["results"]


# ── Replay API ──────────────────────────────────────────────────────

_replay_state = {"running": False, "progress": 0, "frames_processed": 0, "total_frames": 0}


@app.post("/api/replay/start")
async def start_replay(request: dict):
    """Start historical replay through the live pipeline using the simulator."""
    global _replay_state

    if _replay_state["running"]:
        raise HTTPException(status_code=409, detail="Replay already running")

    start_date = request.get("start_date", "2008-09-10")
    end_date = request.get("end_date", "2008-09-20")
    speed_mult = request.get("speed_multiplier", 60)

    # Simulate N days of tick data
    from datetime import datetime
    d0 = datetime.strptime(start_date, "%Y-%m-%d")
    d1 = datetime.strptime(end_date, "%Y-%m-%d")
    n_days = max(1, (d1 - d0).days)
    total_frames = n_days * 390 * 4  # 4Hz × 390 min/day
    delay = max(0.001, 0.25 / speed_mult)

    _replay_state = {"running": True, "progress": 0, "frames_processed": 0, "total_frames": total_frames}

    async def _run_replay():
        global _replay_state
        try:
            # Simulate a crisis ramp during replay
            for frame in range(total_frames):
                progress = frame / total_frames
                # Ramp crisis intensity: 0→peak→decay
                if progress < 0.3:
                    intensity = 0.0
                elif progress < 0.7:
                    intensity = min(0.9, (progress - 0.3) * 2.5)
                else:
                    intensity = max(0, 0.9 - (progress - 0.7) * 3)

                if intensity > 0.05:
                    simulator.activate_crisis(intensity=intensity)
                else:
                    simulator.deactivate_crisis()

                tick = simulator.generate_tick()
                await ensemble.process_tick(tick)

                _replay_state["frames_processed"] = frame + 1
                _replay_state["progress"] = (frame + 1) / total_frames

                if frame % 20 == 0:
                    await asyncio.sleep(delay)

            simulator.deactivate_crisis()
        except Exception as e:
            api_log.error(f"Replay failed: {e}")
        finally:
            _replay_state["running"] = False

    asyncio.create_task(_run_replay())
    return {"ok": True, "status": _replay_state}


@app.get("/api/replay/status")
async def get_replay_status():
    """Get replay progress."""
    return _replay_state


@app.post("/api/replay/stop")
async def stop_replay():
    """Stop ongoing replay."""
    global _replay_state
    _replay_state["running"] = False
    simulator.deactivate_crisis()
    return {"ok": True}
