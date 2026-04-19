import asyncio
from fastapi import FastAPI
from contextlib import asynccontextmanager

from utils.logger import pipeline_log, db_log
from utils.config import FINNHUB_API_KEY, DATA_MODE
from utils.alerting import alert_dispatcher
from utils.model_persistence import get_checkpoint_manager, CHECKPOINT_VERSION
from ingestion.redis_streams import redis_streams
from models.ensemble import ensemble
import globals as g

from database.persistence import init_db
from pipeline.tasks import data_pipeline, _periodic_checkpoint_loop, _finnhub_tick_handler

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

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background pipeline on app startup, stop on shutdown."""
    
    g._pipeline_running = True

    # Initialize Redis Streams
    await redis_streams.connect()

    # Initialize PostgreSQL
    await init_db()

    # v3: Attempt warm-start from disk checkpoint.  Safe to fail.
    try:
        ck = get_checkpoint_manager().load()
        if ck.get("ok"):
            pipeline_log.info(f"checkpoint loaded: {ck.get('components')}")
        else:
            pipeline_log.info(f"no checkpoint ({ck.get('reason')}); cold start")
    except Exception as e:
        pipeline_log.warning(f"checkpoint load failed: {e}")

    # v4: stamp the active model version + checkpoint hash, register it
    g._active_model_version, g._active_checkpoint_hash, _components = _compute_model_version_and_hash()
    pipeline_log.info(
        f"model lineage: version={g._active_model_version} hash={g._active_checkpoint_hash[:12]}…"
    )
    if g._db_available and g._db_pool:
        try:
            from db.connection import upsert_model_lineage
            async with g._db_pool.acquire() as conn:
                await upsert_model_lineage(
                    conn,
                    model_version=g._active_model_version,
                    checkpoint_hash=g._active_checkpoint_hash,
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

    # v4: wire the audit sink
    async def _audit_alert(alert: dict, dispatch_result: dict):
        if not (g._db_available and g._db_pool):
            return
        try:
            from db.connection import insert_audit_log
            payload = {
                **alert,
                "sinks": dispatch_result.get("sinks", {}),
                "delivered": dispatch_result.get("delivered", False),
            }
            async with g._db_pool.acquire() as conn:
                await insert_audit_log(
                    conn,
                    actor="alert_dispatcher",
                    event_type="ALERT_DISPATCH",
                    severity=(alert.get("severity") or "INFO").upper(),
                    model_version=g._active_model_version,
                    payload=payload,
                )
        except Exception as e:
            db_log.warning(f"audit_log insert failed: {e}")

    alert_dispatcher.set_audit_sink(_audit_alert)

    # Initialize Finnhub live data (if configured)
    if g._data_mode in ("finnhub", "hybrid") and FINNHUB_API_KEY:
        try:
            from ingestion.finnhub_connector import get_finnhub_connector
            g._finnhub = get_finnhub_connector(FINNHUB_API_KEY)
            started = await g._finnhub.start(on_tick=_finnhub_tick_handler)
            if started:
                pipeline_log.info("Finnhub live data connector active", extra={"component": "finnhub"})
        except Exception as e:
            pipeline_log.warning(f"Finnhub init failed ({e}), using simulator only")

    g._pipeline_task = asyncio.create_task(data_pipeline())
    g._checkpoint_task = asyncio.create_task(_periodic_checkpoint_loop())

    pipeline_log.info("Crisis Early Warning System Online")
    pipeline_log.info(f"Redis: {'Connected' if redis_streams._connected else 'Fallback mode'}")
    pipeline_log.info(f"PostgreSQL: {'Connected' if g._db_available else 'Offline'}")
    pipeline_log.info(f"Data mode: {g._data_mode}")

    yield

    # Graceful shutdown
    g._pipeline_running = False
    try:
        get_checkpoint_manager().save()
        pipeline_log.info("final checkpoint saved on shutdown")
    except Exception as e:
        pipeline_log.warning(f"final checkpoint failed: {e}")
    if g._finnhub:
        await g._finnhub.stop()
    for t in (g._pipeline_task, g._checkpoint_task):
        if t:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
    await redis_streams.disconnect()
    if g._db_pool:
        await g._db_pool.close()
    pipeline_log.info("System shutdown complete")
