-- ============================================
-- Project Velure — TimescaleDB Migration (v3)
-- Enables hypertables + compression + continuous aggregates
-- on top of the existing star schema (schema.sql).
--
-- Idempotent: safe to re-run.  Requires the `timescaledb`
-- extension to be installed in the target Postgres.
--
-- Apply order:
--   1) schema.sql   (base star schema)
--   2) schema_timescale.sql   (this file)
-- ============================================

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ------------------------------------------------------------
-- 1. Convert fact_market_metrics → hypertable on created_at
-- ------------------------------------------------------------
-- We partition on created_at (wall-clock ingestion time) rather
-- than time_id so retention + compression policies can use
-- interval syntax directly.
--
-- Chunk interval: 7 days (balances pruning cost vs. chunk count
-- at ~10K writes/sec).  Migrate existing rows via `migrate_data`.

SELECT create_hypertable(
    'fact_market_metrics',
    'created_at',
    chunk_time_interval => INTERVAL '7 days',
    if_not_exists       => TRUE,
    migrate_data        => TRUE
);

-- ------------------------------------------------------------
-- 2. Compression policy — compress chunks > 7 days old
-- ------------------------------------------------------------
ALTER TABLE fact_market_metrics
    SET (
        timescaledb.compress,
        timescaledb.compress_segmentby = 'asset_id',
        timescaledb.compress_orderby   = 'created_at DESC'
    );

SELECT add_compression_policy(
    'fact_market_metrics',
    INTERVAL '7 days',
    if_not_exists => TRUE
);

-- ------------------------------------------------------------
-- 3. Retention policy — drop chunks > 180 days
-- ------------------------------------------------------------
-- In production you'd export to cold storage (S3 / Glacier)
-- before drop.  Here we simply drop to keep the demo DB small.

SELECT add_retention_policy(
    'fact_market_metrics',
    INTERVAL '180 days',
    if_not_exists => TRUE
);

-- ------------------------------------------------------------
-- 4. Continuous aggregate — 1-minute crisis rollups
-- ------------------------------------------------------------
-- The dashboard's heat-map and trend sparklines don't need
-- tick-level resolution — a 1-minute roll-up of CISS and the
-- combined anomaly score is enough.  Continuous aggregates
-- refresh incrementally, so we don't re-scan the hypertable.

CREATE MATERIALIZED VIEW IF NOT EXISTS mv_market_metrics_1min
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 minute', created_at) AS bucket,
    asset_id,
    AVG(ciss_score)                AS avg_ciss,
    MAX(ciss_score)                AS max_ciss,
    AVG(anomaly_score_combined)    AS avg_combined,
    MAX(anomaly_score_combined)    AS max_combined,
    AVG(prob_default)              AS avg_pd,
    COUNT(*)                       AS n_ticks,
    BOOL_OR(is_degraded)           AS any_degraded
FROM fact_market_metrics
GROUP BY bucket, asset_id
WITH NO DATA;

-- Refresh policy: build the last 6h of buckets every 30s.
-- `start_offset` = -6h ensures recent buckets are kept fresh.
-- `end_offset`   = -30s skips the currently-filling bucket.
SELECT add_continuous_aggregate_policy(
    'mv_market_metrics_1min',
    start_offset     => INTERVAL '6 hours',
    end_offset       => INTERVAL '30 seconds',
    schedule_interval => INTERVAL '30 seconds',
    if_not_exists    => TRUE
);

-- ------------------------------------------------------------
-- 5. Continuous aggregate — 1-hour system-wide CISS
-- ------------------------------------------------------------
-- Used by the long-term "regime history" chart on the dashboard.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_system_ciss_1h
WITH (timescaledb.continuous) AS
SELECT
    time_bucket(INTERVAL '1 hour', created_at) AS bucket,
    AVG(ciss_score)  AS avg_ciss,
    MAX(ciss_score)  AS max_ciss,
    AVG(anomaly_score_combined) AS avg_combined,
    COUNT(*)         AS n_ticks
FROM fact_market_metrics
GROUP BY bucket
WITH NO DATA;

SELECT add_continuous_aggregate_policy(
    'mv_system_ciss_1h',
    start_offset     => INTERVAL '30 days',
    end_offset       => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '5 minutes',
    if_not_exists    => TRUE
);

-- ------------------------------------------------------------
-- 6. Helper index on the hypertable
-- ------------------------------------------------------------
-- Hypertables automatically index on the partitioning column.
-- Add the secondary index the live dashboard queries most
-- often: per-asset recent-window lookup.
CREATE INDEX IF NOT EXISTS idx_fact_asset_created
    ON fact_market_metrics (asset_id, created_at DESC);
