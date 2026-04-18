-- ============================================
-- Project Velure — Star Schema
-- Real-Time Financial Crisis Early Warning System
-- ============================================

-- Dimension: Time
CREATE TABLE IF NOT EXISTS dim_time (
    time_id         SERIAL PRIMARY KEY,
    epoch_ms        BIGINT NOT NULL,
    timestamp_utc   TIMESTAMP NOT NULL,
    trading_hour    SMALLINT,
    day_of_week     SMALLINT,
    calendar_month  SMALLINT,
    market_session  VARCHAR(20) DEFAULT 'UNKNOWN',
    is_trading_day  BOOLEAN DEFAULT TRUE,
    UNIQUE(epoch_ms)
);

-- Dimension: Asset
CREATE TABLE IF NOT EXISTS dim_asset (
    asset_id        SERIAL PRIMARY KEY,
    ticker          VARCHAR(20) NOT NULL UNIQUE,
    asset_class     VARCHAR(30) NOT NULL,
    asset_name      VARCHAR(100),
    currency        VARCHAR(3) DEFAULT 'USD',
    jurisdiction    VARCHAR(50) DEFAULT 'US',
    sector          VARCHAR(50),
    is_active       BOOLEAN DEFAULT TRUE
);

-- Dimension: Source
CREATE TABLE IF NOT EXISTS dim_source (
    source_id       SERIAL PRIMARY KEY,
    provider_name   VARCHAR(50) NOT NULL,
    api_endpoint    VARCHAR(200),
    data_frequency  VARCHAR(20) DEFAULT 'TICK',
    latency_tier    VARCHAR(10) DEFAULT 'LOW'
);

-- Dimension: Alert
CREATE TABLE IF NOT EXISTS dim_alert (
    alert_id        SERIAL PRIMARY KEY,
    alert_type      VARCHAR(50) NOT NULL,
    severity        VARCHAR(10) NOT NULL DEFAULT 'LOW',
    model_source    VARCHAR(30) NOT NULL,
    description     TEXT,
    triggered_at    TIMESTAMP DEFAULT NOW(),
    asset_id        INTEGER REFERENCES dim_asset(asset_id),
    score_value     DECIMAL(8,6),
    acknowledged    BOOLEAN DEFAULT FALSE
);

-- Fact Table: Market Metrics
CREATE TABLE IF NOT EXISTS fact_market_metrics (
    metric_id       BIGSERIAL PRIMARY KEY,
    time_id         INTEGER REFERENCES dim_time(time_id),
    asset_id        INTEGER REFERENCES dim_asset(asset_id),
    source_id       INTEGER REFERENCES dim_source(source_id),
    price           DECIMAL(18,6),
    price_change    DECIMAL(18,6),
    spread_bps      DECIMAL(10,4),
    implied_vol     DECIMAL(10,6),
    volume          BIGINT,
    bid_ask_spread  DECIMAL(10,6),
    anomaly_score_if    DECIMAL(8,6),
    anomaly_score_lstm  DECIMAL(8,6),
    anomaly_score_combined DECIMAL(8,6),
    ciss_score      DECIMAL(8,6),
    distance_default DECIMAL(12,6),
    prob_default    DECIMAL(8,6),
    is_degraded     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_fact_time ON fact_market_metrics(time_id);
CREATE INDEX IF NOT EXISTS idx_fact_asset ON fact_market_metrics(asset_id);
CREATE INDEX IF NOT EXISTS idx_fact_created ON fact_market_metrics(created_at);
CREATE INDEX IF NOT EXISTS idx_fact_ciss ON fact_market_metrics(ciss_score);
CREATE INDEX IF NOT EXISTS idx_alert_severity ON dim_alert(severity);
CREATE INDEX IF NOT EXISTS idx_alert_triggered ON dim_alert(triggered_at);
