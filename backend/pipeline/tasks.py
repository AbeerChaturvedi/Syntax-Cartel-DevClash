import asyncio
import time
from utils.logger import pipeline_log
from utils.config import ENABLE_SIMULATOR, MODEL_CHECKPOINT_PERIODIC_SEC, MODEL_CHECKPOINT_ON_CRISIS
from utils.model_persistence import get_checkpoint_manager

from ingestion.simulator import simulator
from ingestion.redis_streams import redis_streams
from ingestion.watermark import watermark
from models.ensemble import ensemble
from database.persistence import persist_scores
import globals as g

async def _periodic_checkpoint_loop():
    """Save a warm checkpoint every MODEL_CHECKPOINT_PERIODIC_SEC seconds."""
    mgr = get_checkpoint_manager()
    while g._pipeline_running:
        await asyncio.sleep(MODEL_CHECKPOINT_PERIODIC_SEC)
        if not g._pipeline_running:
            return
        try:
            res = mgr.save()
            pipeline_log.info(f"periodic checkpoint saved → {res.get('path')}")
        except Exception as e:
            pipeline_log.warning(f"periodic checkpoint failed: {e}")

async def ingestion_producer():
    if not ENABLE_SIMULATOR:
        pipeline_log.info("Simulator disabled — waiting for Finnhub ticks")
        while g._pipeline_running:
            await asyncio.sleep(1)
        return

    while g._pipeline_running:
        try:
            tick_data = simulator.generate_tick()
            tick_data = watermark.ingest("simulator", tick_data)
            await redis_streams.publish_tick(tick_data)
            await asyncio.sleep(g._tick_rate)
        except Exception as e:
            g._system_metrics["pipeline_errors"] += 1
            pipeline_log.error(f"Producer error: {e}", extra={"component": "producer"})
            await asyncio.sleep(1)

async def _finnhub_tick_handler(tick_data: dict):
    try:
        tick_data = watermark.ingest("finnhub", tick_data)
        await redis_streams.publish_tick(tick_data)
    except Exception as e:
        pipeline_log.error(f"Finnhub tick relay error: {e}")

def _track_pipeline_latency(latency_ms: float):
    samples = g._system_metrics["pipeline_latency_samples"]
    samples.append(latency_ms)
    if len(samples) > 200:
        g._system_metrics["pipeline_latency_samples"] = samples[-200:]
    g._system_metrics["avg_pipeline_latency_ms"] = round(
        sum(g._system_metrics["pipeline_latency_samples"]) / len(g._system_metrics["pipeline_latency_samples"]), 2
    )

async def inference_consumer():
    pipeline_log.info("Warming up ML models...")
    if ENABLE_SIMULATOR:
        warmup_tick = simulator.generate_tick()
    else:
        from features.state_builder import TRACKED_ASSETS
        warmup_tick = {
            "assets": {t: {"price": 100.0, "pct_change": 0.0, "volume": 1000,
                           "spread_bps": 1.0, "rolling_volatility": 0.01,
                           "asset_class": "EQUITY"} for t in TRACKED_ASSETS},
            "tick_id": 0, "crisis_mode": False, "crisis_intensity": 0.0,
        }
    await ensemble.process_tick(warmup_tick)
    pipeline_log.info("Models ready")

    while g._pipeline_running:
        try:
            start = time.monotonic()
            tick_data = await redis_streams.consume_tick(timeout_ms=200)

            if tick_data is None:
                await asyncio.sleep(0.05)
                continue

            result = await ensemble.process_tick(tick_data)

            if result:
                ciss = result.get("scores", {}).get("ciss", 0)
                combined = result.get("scores", {}).get("combined_anomaly", 0)
                if ciss > g._system_metrics["peak_ciss"]:
                    g._system_metrics["peak_ciss"] = round(ciss, 4)
                if combined > g._system_metrics["peak_combined"]:
                    g._system_metrics["peak_combined"] = round(combined, 4)

                sev = result.get("scores", {}).get("severity", "NORMAL")
                if (
                    MODEL_CHECKPOINT_ON_CRISIS
                    and sev in ("HIGH", "CRITICAL")
                    and (time.time() - g._last_crisis_ckpt_ts) > 600
                ):
                    g._last_crisis_ckpt_ts = time.time()
                    async def _crisis_ckpt():
                        try:
                            get_checkpoint_manager().save()
                            pipeline_log.info(f"crisis checkpoint saved (sev={sev})")
                        except Exception as e:
                            pipeline_log.warning(f"crisis checkpoint failed: {e}")
                    asyncio.create_task(_crisis_ckpt())

                await g.manager.broadcast(result)
                g._system_metrics["total_broadcasts"] += 1

                await redis_streams.publish_inference(result)

                alert = result.get("alert")
                if alert:
                    await redis_streams.publish_alert(alert)

                asyncio.create_task(persist_scores(result, tick_data))

            elapsed_ms = (time.monotonic() - start) * 1000
            _track_pipeline_latency(elapsed_ms)
            g._system_metrics["total_ticks_processed"] += 1

        except Exception as e:
            g._system_metrics["pipeline_errors"] += 1
            pipeline_log.error(f"Consumer error: {e}", extra={"component": "consumer"})
            await asyncio.sleep(0.5)

async def data_pipeline():
    await asyncio.gather(
        ingestion_producer(),
        inference_consumer(),
    )
