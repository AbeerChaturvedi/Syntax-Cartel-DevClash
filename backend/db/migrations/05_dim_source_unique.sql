-- Migration 05: Add UNIQUE constraint on dim_source.provider_name
-- (needed for ON CONFLICT clauses in persistence.py)

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'dim_source_provider_name_key'
    ) THEN
        -- First dedupe any existing rows that share a provider_name
        DELETE FROM dim_source a USING dim_source b
        WHERE a.provider_name = b.provider_name
          AND a.source_id > b.source_id;

        ALTER TABLE dim_source
            ADD CONSTRAINT dim_source_provider_name_key UNIQUE (provider_name);
    END IF;
END
$$;