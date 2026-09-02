import time
from datetime import datetime, timezone
from utils.logger import db_log
from utils.circuit_breaker import db_circuit
import globals as g

# Maps tick source string → dim_source source_id (populated on first DB write)
_source_id_cache: dict = {}

# Human-readable source names matching what the .env DATA_MODE produces
_SOURCE_NAME_MAP = {
    "finnhub_live":  "Finnhub",
    "twelve_data":   "Twelve Data",
    "simulator":     "Simulator",
    "hybrid":        "Finnhub",   # hybrid ticks come from Finnhub connector
    "replay":        "Replay",
}

async def init_db():
    try:
        from db.connection import get_pool
        g._db_pool = await get_pool()
        g._db_available = True
        db_log.info("PostgreSQL connected")
    except Exception as e:
        db_log.warning(f"PostgreSQL unavailable ({e}), running without persistence")
        g._db_available = False

async def _ensure_source_cache(conn):
    """Populate _source_id_cache from dim_source; upsert any missing rows."""
    global _source_id_cache
    if _source_id_cache:
        return

    # Load existing rows
    rows = await conn.fetch("SELECT source_id, provider_name FROM dim_source")
    for r in rows:
        _source_id_cache[r["provider_name"]] = r["source_id"]

    # Ensure required provider rows exist (may be new since seed was written)
    required = {"Finnhub", "Twelve Data", "Simulator", "Replay"}
    for name in required:
        if name not in _source_id_cache:
            try:
                sid = await conn.fetchval(
                    """INSERT INTO dim_source (provider_name)
                       VALUES ($1)
                       ON CONFLICT (provider_name) DO UPDATE SET provider_name=EXCLUDED.provider_name
                       RETURNING source_id""",
                    name,
                )
                _source_id_cache[name] = sid
                db_log.info(f"dim_source: ensured row for '{name}' (id={sid})")
            except Exception as e:
                db_log.warning(f"dim_source upsert for '{name}' failed: {e}")

def _resolve_source_id(tick_source: str) -> int:
    """Map a tick source string to a dim_source source_id, fallback to 1."""
    friendly = _SOURCE_NAME_MAP.get(tick_source, "Simulator")
    return _source_id_cache.get(friendly, 1)

async def persist_scores(result: dict, tick_data: dict):
    """Persist computed scores to fact table (non-blocking, best-effort)."""
    if not g._db_pool or not db_circuit.is_available:
        return

    try:
        from db.connection import get_or_create_time_id
        epoch_ms = tick_data.get("epoch_ms", int(time.time() * 1000))
        # Postgres TIMESTAMP column is naive — strip tz to avoid the
        # "can't subtract offset-naive and offset-aware datetimes" error
        # raised by asyncpg when the wire encoding hits the driver.
        ts = datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).replace(tzinfo=None)

        async with g._db_pool.acquire() as conn:
            # If we reached the pool successfully, the DB is alive —
            # keep _db_available in sync with reality (it can get stuck
            # False from a failed first-boot attempt).
            if not g._db_available:
                g._db_available = True
            time_id = await get_or_create_time_id(conn, epoch_ms, ts)
            scores = result.get("scores", {})

            # Batch insert for all assets — use a single transaction
            assets = result.get("assets", {})
            if assets:
                # Populate asset_id cache once (saves 15 queries per tick)
                if not g._asset_id_cache:
                    rows_all = await conn.fetch("SELECT asset_id, ticker FROM dim_asset")
                    for r in rows_all:
                        g._asset_id_cache[r["ticker"]] = r["asset_id"]

                # Populate source_id cache (dynamic, no more hardcoded 5)
                await _ensure_source_cache(conn)

                tick_source = tick_data.get("source", "simulator")
                source_id = _resolve_source_id(tick_source)

                rows = []
                for ticker, adata in assets.items():
                    asset_id = g._asset_id_cache.get(ticker)
                    if asset_id is None:
                        continue
                    # FX prices come from Twelve Data — use their source_id
                    asset_source_id = (
                        _source_id_cache.get("Twelve Data", source_id)
                        if adata.get("source") == "twelve_data"
                        else source_id
                    )
                    rows.append((
                        time_id, asset_id, asset_source_id,
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
                        ON CONFLICT DO NOTHING
                    """, rows)
                    g._system_metrics["db_writes"] += len(rows)

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
                g._system_metrics["crisis_events"] += 1

        db_circuit.record_success()

    except Exception as e:
        db_circuit.record_failure()
        g._system_metrics["db_errors"] += 1
        if g._system_metrics["db_errors"] <= 5:
            db_log.error(f"Persist error: {e}", extra={"error_type": type(e).__name__})

