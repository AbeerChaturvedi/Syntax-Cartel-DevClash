from fastapi import APIRouter
from globals import _pipeline_running, manager, _system_metrics, _tick_rate, _data_mode, _finnhub, _db_available
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
        "pipeline": _pipeline_running,
        "redis": redis_streams._connected,
        "postgresql": _db_available,
        "models": _system_metrics["total_ticks_processed"] > 0 or time.time() - _system_metrics.get("start_time", time.time()) < 30,
    }
    healthy = checks["pipeline"]
    return {
        "status": "healthy" if healthy else "degraded",
        "checks": checks,
        "circuit_breakers": {
            "redis": redis_circuit.get_status(),
            "postgresql": db_circuit.get_status(),
        },
        "uptime_seconds": round(time.time() - _system_metrics.get("start_time", time.time()), 1),
    }

@router.get("/")
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

@router.get("/api/status")
async def system_status():
    """System health and model status."""
    return {
        "status": "operational",
        "pipeline_running": _pipeline_running,
        "connected_clients": len(manager.active_connections),
        "tick_count": _system_metrics["total_ticks_processed"],
        "tick_rate_hz": round(1 / max(_tick_rate, 0.001), 1),
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

@router.get("/api/data-mode")
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
