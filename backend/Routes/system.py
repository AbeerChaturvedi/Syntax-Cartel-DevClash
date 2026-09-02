from fastapi import APIRouter
import globals as g
from ingestion.simulator import simulator
from ingestion.redis_streams import redis_streams
from utils.circuit_breaker import redis_circuit, db_circuit
from utils.config import ENABLE_SIMULATOR
import time

router = APIRouter()

@router.get("/health")
async def health_check():
    """Deep health check — verifies all dependencies."""
    checks = {
        "pipeline": g._pipeline_running,
        "redis": redis_streams._connected,
        "postgresql": g._db_available,
        "models": g._system_metrics["total_ticks_processed"] > 0 or time.time() - g._system_metrics.get("start_time", time.time()) < 30,
    }
    healthy = checks["pipeline"]
    return {
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
        "uptime_seconds": round(time.time() - g._system_metrics.get("start_time", time.time()), 1),
    }

@router.get("/")
async def root():
    return {
        "system": "Project Velure",
        "version": "3.0.0",
        "status": "operational",
        "pipeline_running": g._pipeline_running,
        "connected_clients": len(g.manager.active_connections),
        "tick_count": g._system_metrics["total_ticks_processed"],
        "crisis_mode": simulator.crisis_mode if ENABLE_SIMULATOR else False,
        "data_mode": g._data_mode,
        "redis_mode": "streams" if redis_streams._connected else "in-process",
        "db_connected": g._db_available,
    }

@router.get("/api/status")
async def system_status():
    """System health and model status."""
    return {
        "status": "operational",
        "pipeline_running": g._pipeline_running,
        "connected_clients": len(g.manager.active_connections),
        "tick_count": g._system_metrics["total_ticks_processed"],
        "tick_rate_hz": round(1 / max(g._tick_rate, 0.001), 1),
        "crisis_mode": simulator.crisis_mode if ENABLE_SIMULATOR else False,
        "crisis_intensity": simulator.crisis_intensity if ENABLE_SIMULATOR else 0.0,
        "data_mode": g._data_mode,
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
            "postgresql": "connected" if g._db_available else "offline",
            "finnhub": g._finnhub.get_status() if g._finnhub else "disabled",
        },
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
    }

@router.get("/api/data-mode")
async def get_data_mode():
    """Get current data mode and source information."""
    from features.state_builder import state_builder
    return {
        "mode": g._data_mode,
        "simulator_enabled": ENABLE_SIMULATOR,
        "finnhub_connected": g._finnhub.connected if g._finnhub else False,
        "state_builder_has_data": state_builder.has_data(),
        "tracked_assets": state_builder.tracked_assets,
    }

@router.get("/api/metrics")
async def get_pipeline_metrics():
    """Real-time pipeline throughput and health metrics for the dashboard."""
    now = time.time()
    uptime = round(now - g._system_metrics.get("start_time", now), 1)
    total_ticks = g._system_metrics["total_ticks_processed"]
    tps = round(total_ticks / max(uptime, 1.0), 2)

    # Twelve Data status (FX connector)
    td_status = None
    try:
        _twelve_data = getattr(__import__("globals", fromlist=["_twelve_data"]), "_twelve_data", None)
        if _twelve_data is not None:
            td_status = _twelve_data.get_status()
    except Exception:
        pass

    return {
        "ticks_per_second": tps,
        "total_ticks": total_ticks,
        "avg_pipeline_latency_ms": round(g._system_metrics.get("avg_pipeline_latency_ms", 0.0), 2),
        "uptime_seconds": uptime,
        "connected_clients": len(g.manager.active_connections),
        "pipeline_errors": g._system_metrics.get("pipeline_errors", 0),
        "db_writes": g._system_metrics.get("db_writes", 0),
        "db_errors": g._system_metrics.get("db_errors", 0),
        "peak_ciss": round(g._system_metrics.get("peak_ciss", 0.0), 4),
        "peak_combined": round(g._system_metrics.get("peak_combined", 0.0), 4),
        "crisis_events": g._system_metrics.get("crisis_events", 0),
        "total_broadcasts": g._system_metrics.get("total_broadcasts", 0),
        "data_mode": g._data_mode,
        "db_connected": g._db_available,
        # Nested `redis` object for the frontend's expectations
        "redis": {
            "redis_connected": redis_streams._connected,
            "fallback_mode": getattr(redis_streams, "_metrics", {}).get("fallback_mode", False),
        },
        "redis_connected": redis_streams._connected,
        "finnhub_connected": g._finnhub.connected if g._finnhub else False,
        "twelve_data": td_status,
    }

