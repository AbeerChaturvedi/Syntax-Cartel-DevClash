import asyncio
import time
from typing import Optional, Dict
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

def _build_heartbeat_tick() -> Optional[dict]:
    """Build a tick carrying the latest real prices from Finnhub + Twelve Data.

    Used in hybrid mode when no live trades are flowing (e.g. US market is
    closed) so the pipeline keeps ticking instead of going idle. Returns
    None if no real prices are available at all (caller will fall back to
    the simulator).
    """
    import numpy as np
    assets: Dict[str, dict] = {}
    # Equities + crypto from Finnhub
    try:
        from ingestion.finnhub_connector import FINNHUB_SYMBOL_MAP
        finnhub = g._finnhub
        if finnhub and getattr(finnhub, "_price_history", None):
            for sym, hist in list(finnhub._price_history.items()):
                if hist and len(hist) > 0:
                    price = float(hist[-1])
                    internal = FINNHUB_SYMBOL_MAP.get(sym, sym) or sym
                    asset_class = "CRYPTO" if sym.startswith("BINANCE:") else "EQUITY"
                    # Derive pct_change and rolling_volatility from history
                    # so the inference pipeline has signal even when the
                    # market is closed and no live trades flow.
                    pct_change = 0.0
                    rolling_vol = 0.0
                    if len(hist) >= 2:
                        prev = float(hist[-2])
                        if prev > 0:
                            pct_change = (price - prev) / prev
                        if len(hist) >= 5:
                            recent = list(hist)[-30:]
                            returns = [
                                (recent[i] - recent[i-1]) / recent[i-1]
                                for i in range(1, len(recent))
                                if recent[i-1] > 0
                            ]
                            if returns:
                                rolling_vol = float(np.std(returns))
                    assets[internal] = {
                        "price": price,
                        "asset_class": asset_class,
                        "pct_change": round(pct_change, 6),
                        "rolling_volatility": round(rolling_vol, 6),
                        "volume": 0,
                        "spread_bps": 1.0,
                    }
    except Exception:
        pass

    # FX from Twelve Data
    try:
        td = getattr(g, "_twelve_data", None)
        if td and getattr(td, "latest_prices", None):
            for sym, entry in list(td.latest_prices.items()):
                # TwelveData stores a dict per symbol; pull the actual price.
                price = entry.get("price") if isinstance(entry, dict) else entry
                if price:
                    assets[sym] = {
                        "price": float(price),
                        "asset_class": "FX",
                        "pct_change": float(entry.get("pct_change", 0) / 100) if isinstance(entry, dict) else 0.0,
                        "rolling_volatility": 0.0,  # TD has no per-tick history
                        "volume": 0,
                        "spread_bps": float(entry.get("spread_bps", 1.0)) if isinstance(entry, dict) else 1.0,
                    }
    except Exception:
        pass

    if not assets:
        return None

    from datetime import datetime, timezone
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epoch_ms": int(time.time() * 1000),
        "tick_id": simulator.tick_count + 1,
        "source": "heartbeat",
        "crisis_mode": simulator.crisis_mode,
        "crisis_intensity": round(simulator.crisis_intensity, 4),
        "assets": assets,
    }


async def ingestion_producer():
    if not ENABLE_SIMULATOR:
        pipeline_log.info("Simulator disabled — waiting for Finnhub ticks")
        while g._pipeline_running:
            await asyncio.sleep(1)
        return

    while g._pipeline_running:
        try:
            tick_data = None
            if simulator.crisis_mode:
                # Crisis overrides everything; simulator drives the chaos
                tick_data = simulator.generate_tick()
            elif g._data_mode == "simulator":
                tick_data = simulator.generate_tick()
            else:
                # Hybrid: try heartbeat (real last-known prices) first,
                # fall back to simulator when no real data is available yet
                tick_data = _build_heartbeat_tick()
                if tick_data is None:
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
        if ENABLE_SIMULATOR and simulator.crisis_mode:
            return  # Drop live data during crisis injection
            
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
                now_ts = time.time()
                # Rolling-window peak with 60s decay. After 60s without a
                # higher reading, peak decays toward current value so the
                # metric reflects recent state instead of all-time high.
                peak_window_sec = 60.0
                for peak_key, current_val in [("peak_ciss", ciss), ("peak_combined", combined)]:
                    last_ts_key = f"{peak_key}_ts"
                    last_ts = g._system_metrics.get(last_ts_key, 0.0)
                    if current_val > g._system_metrics[peak_key]:
                        g._system_metrics[peak_key] = round(current_val, 4)
                        g._system_metrics[last_ts_key] = now_ts
                    elif now_ts - last_ts > peak_window_sec:
                        # Decay toward current value over the window length
                        old = g._system_metrics[peak_key]
                        decay = max(0.0, (now_ts - last_ts - peak_window_sec) / peak_window_sec)
                        new_val = old - (old - current_val) * min(decay, 1.0) * 0.1
                        g._system_metrics[peak_key] = round(max(new_val, current_val), 4)
                        if current_val >= old:
                            g._system_metrics[last_ts_key] = now_ts

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
