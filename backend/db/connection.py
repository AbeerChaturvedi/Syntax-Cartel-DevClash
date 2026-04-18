"""
Database connection module for Project Velure.
Async PostgreSQL connection pool using asyncpg.
"""
import asyncpg
import os
from contextlib import asynccontextmanager

_pool = None


async def get_pool():
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "localhost"),
            port=int(os.getenv("POSTGRES_PORT", 5432)),
            database=os.getenv("POSTGRES_DB", "velure"),
            user=os.getenv("POSTGRES_USER", "velure"),
            password=os.getenv("POSTGRES_PASSWORD", "velure_hackathon_2026"),
            min_size=2,
            max_size=10,
        )
    return _pool


async def close_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def get_connection():
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def insert_market_metric(conn, data: dict):
    """Insert a computed market metric into the fact table."""
    await conn.execute("""
        INSERT INTO fact_market_metrics 
        (time_id, asset_id, source_id, price, price_change, spread_bps,
         implied_vol, volume, anomaly_score_if, anomaly_score_lstm,
         anomaly_score_combined, ciss_score, distance_default, prob_default, is_degraded)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
    """, data.get('time_id', 1), data.get('asset_id', 1), data.get('source_id', 1),
        data.get('price', 0), data.get('price_change', 0), data.get('spread_bps', 0),
        data.get('implied_vol', 0), data.get('volume', 0),
        data.get('anomaly_score_if', 0), data.get('anomaly_score_lstm', 0),
        data.get('anomaly_score_combined', 0), data.get('ciss_score', 0),
        data.get('distance_default', 0), data.get('prob_default', 0),
        data.get('is_degraded', False))


async def insert_alert(conn, alert_type: str, severity: str, model_source: str,
                       description: str, asset_id: int, score_value: float):
    """Insert a crisis alert into dim_alert."""
    await conn.execute("""
        INSERT INTO dim_alert (alert_type, severity, model_source, description, asset_id, score_value)
        VALUES ($1, $2, $3, $4, $5, $6)
    """, alert_type, severity, model_source, description, asset_id, score_value)


async def insert_audit_log(
    conn,
    actor: str,
    event_type: str,
    severity: str,
    model_version: str,
    payload: dict,
) -> dict:
    """
    Append a hash-chained row to audit_log.

    Reads the previous row's this_hash inside the same transaction so the
    chain is continuous under concurrent writes (audit_id ordering + the
    locked SELECT prevents holes).
    """
    import hashlib
    import json as _json
    async with conn.transaction():
        prev = await conn.fetchrow(
            "SELECT this_hash FROM audit_log ORDER BY audit_id DESC LIMIT 1 FOR UPDATE"
        )
        prev_hash = prev["this_hash"] if prev else None

        canonical = _json.dumps(
            {
                "actor": actor,
                "event_type": event_type,
                "severity": severity,
                "model_version": model_version,
                "payload": payload,
            },
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        h = hashlib.sha256(((prev_hash or "") + canonical).encode("utf-8")).hexdigest()

        row = await conn.fetchrow(
            """
            INSERT INTO audit_log
                (actor, event_type, severity, model_version, payload, prev_hash, this_hash)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
            RETURNING audit_id, occurred_at, this_hash
            """,
            actor, event_type, severity, model_version, _json.dumps(payload, default=str),
            prev_hash, h,
        )
        return dict(row)


async def upsert_model_lineage(
    conn,
    model_version: str,
    checkpoint_hash: str,
    components: dict,
    ensemble_weights: dict,
) -> dict:
    """Register the active model version. No-op if (version, hash) already known."""
    import json as _json
    row = await conn.fetchrow(
        """
        INSERT INTO model_lineage
            (model_version, checkpoint_hash, components, ensemble_weights)
        VALUES ($1, $2, $3::jsonb, $4::jsonb)
        ON CONFLICT (model_version, checkpoint_hash) DO UPDATE
            SET activated_at = COALESCE(model_lineage.activated_at, NOW())
        RETURNING lineage_id, model_version, checkpoint_hash, activated_at
        """,
        model_version, checkpoint_hash,
        _json.dumps(components, default=str),
        _json.dumps(ensemble_weights, default=str),
    )
    return dict(row)


async def get_or_create_time_id(conn, epoch_ms: int, timestamp_utc):
    """Get or create a time dimension entry. Uses INSERT ON CONFLICT to avoid redundant SELECT."""
    row = await conn.fetchrow("""
        INSERT INTO dim_time (epoch_ms, timestamp_utc, trading_hour, day_of_week, calendar_month, market_session)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (epoch_ms) DO NOTHING
        RETURNING time_id
    """, epoch_ms, timestamp_utc,
        timestamp_utc.hour, timestamp_utc.weekday(), timestamp_utc.month,
        'OPEN' if 9 <= timestamp_utc.hour <= 16 else 'CLOSED')
    if row:
        return row['time_id']
    # ON CONFLICT hit — row already existed, fetch it
    row = await conn.fetchrow(
        "SELECT time_id FROM dim_time WHERE epoch_ms = $1", epoch_ms
    )
    return row['time_id']
