-- ═══════════════════════════════════════════════════════════════════
--  Project Velure — Audit + Model Lineage tables
--
--  Why this exists:
--    · Compliance regimes (MiFID II, SOC 2) require demonstrating that
--      alerts produced by the model are tamper-evident.
--    · Post-incident review needs a record of *which model version*
--      emitted a given alert, so we can re-run the exact computation.
--
--  Idempotent: safe to apply to fresh DBs (init dir) or existing ones
--  (manually `psql -f 04_audit.sql`).  Uses IF NOT EXISTS guards.
-- ═══════════════════════════════════════════════════════════════════

-- ── 1. Audit log: append-only, hash-chained ────────────────────────
--
--  Each row's `this_hash` is sha256( prev_hash || canonical_payload ).
--  The application computes the chain — Postgres stores it.  Verify
--  integrity later by walking the table in id order and recomputing.
--
--  Tamper detection: any row mutation breaks the chain at that row
--  and every row after it.  Detect by re-running the chain check.
CREATE TABLE IF NOT EXISTS audit_log (
    audit_id     BIGSERIAL    PRIMARY KEY,
    occurred_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    actor        VARCHAR(64)  NOT NULL,        -- 'system', 'user:<id>', 'alert_dispatcher'
    event_type   VARCHAR(64)  NOT NULL,        -- ALERT_DISPATCH, MODEL_CHECKPOINT, CONFIG_CHANGE, etc.
    severity     VARCHAR(16)  NOT NULL DEFAULT 'INFO',
    model_version VARCHAR(32),                 -- e.g. v3.0+lstm-32-64
    payload      JSONB        NOT NULL,
    prev_hash    CHAR(64),                     -- NULL only for the genesis row
    this_hash    CHAR(64)     NOT NULL,
    UNIQUE (audit_id, this_hash)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_ts        ON audit_log (occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event     ON audit_log (event_type, occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_severity  ON audit_log (severity, occurred_at DESC);

COMMENT ON TABLE  audit_log  IS 'Append-only hash-chained audit trail. Mutations break the chain.';
COMMENT ON COLUMN audit_log.this_hash IS 'sha256( prev_hash || canonical_json(payload + meta) )';


-- ── 2. Model lineage: which checkpoint produced which scores ───────
--
--  Every time the ensemble computes scores, it stamps the current
--  model_version + checkpoint_hash onto the result.  This table is
--  the registry of versions seen — regulators ask "what model produced
--  alert X on Y?", and the answer is a join from audit_log →
--  model_lineage on (model_version).
CREATE TABLE IF NOT EXISTS model_lineage (
    lineage_id        BIGSERIAL    PRIMARY KEY,
    model_version     VARCHAR(32)  NOT NULL,
    checkpoint_hash   CHAR(64)     NOT NULL,
    components        JSONB        NOT NULL,    -- {if: bool, lstm: bool, ciss: bool, ...}
    ensemble_weights  JSONB        NOT NULL,
    activated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    deactivated_at    TIMESTAMPTZ,
    UNIQUE (model_version, checkpoint_hash)
);

CREATE INDEX IF NOT EXISTS idx_model_lineage_active
    ON model_lineage (activated_at DESC)
    WHERE deactivated_at IS NULL;

COMMENT ON TABLE model_lineage IS 'Registry of model versions/checkpoints active at given times. Joined from audit_log on model_version.';


-- ── 3. View: alert audit (convenience) ─────────────────────────────
CREATE OR REPLACE VIEW v_alert_audit AS
    SELECT
        a.audit_id,
        a.occurred_at,
        a.severity,
        a.model_version,
        l.checkpoint_hash,
        a.payload->>'type'    AS alert_type,
        a.payload->>'message' AS message,
        (a.payload->>'score')::FLOAT AS score,
        a.payload->'sinks'    AS sinks_attempted,
        a.this_hash,
        a.prev_hash
    FROM audit_log a
    LEFT JOIN LATERAL (
        SELECT checkpoint_hash
        FROM model_lineage
        WHERE model_version = a.model_version
        ORDER BY activated_at DESC
        LIMIT 1
    ) l ON TRUE
    WHERE a.event_type = 'ALERT_DISPATCH'
    ORDER BY a.occurred_at DESC;
