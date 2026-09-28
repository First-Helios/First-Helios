BEGIN;

-- Running upgrade 12a76ebed458 -> c91a6f02de73

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM bronze.capture WHERE source_endpoint_id IS NULL)
 OR EXISTS (SELECT 1 FROM bronze.evidence WHERE source_record_version_id IS NOT NULL AND left(locator, 1) <> '$') THEN
 RAISE EXCEPTION 'ADR-0011: this database holds pre-ADR-0011 Bronze rows; rebuild it (see ADR-0011 §8)';
 END IF;
END $$;
ALTER TABLE bronze.source_endpoint DROP CONSTRAINT uq_source_endpoint_canonical_uri;
ALTER TABLE bronze.source_endpoint ADD CONSTRAINT uq_source_endpoint_source_canonical_uri UNIQUE (source_id, canonical_uri);
ALTER TABLE bronze.source_endpoint ADD CONSTRAINT ck_source_endpoint_kind CHECK (endpoint_kind IN ('http', 'https', 's3', 'repo'));
ALTER TABLE bronze.capture ALTER COLUMN source_endpoint_id SET NOT NULL;
ALTER TABLE bronze.capture ADD COLUMN reason_code varchar(64);
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_outcome CHECK (outcome IN ('succeeded', 'failed', 'skipped', 'rejected'));
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_reason_matches_outcome CHECK ((outcome = 'succeeded') = (reason_code IS NULL));
ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_reason_code_format CHECK (reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]*$');
ALTER TABLE bronze.source_record_version ADD COLUMN identity_match_endpoint_id bigint;
ALTER TABLE bronze.source_record_version ADD CONSTRAINT fk_source_record_version_match_endpoint_source FOREIGN KEY (identity_match_endpoint_id, source_id) REFERENCES bronze.source_endpoint (id, source_id) ON DELETE RESTRICT;
CREATE INDEX ix_source_record_version_identity_match_endpoint_id ON bronze.source_record_version (identity_match_endpoint_id) WHERE identity_match_endpoint_id IS NOT NULL;
ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_version_locator_jsonpath CHECK (source_record_version_id IS NULL OR left(locator, 1) = '$');;

ALTER TABLE bronze.capture ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE bronze.source_record_version ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE bronze.evidence ADD COLUMN ingested_at timestamptz NOT NULL DEFAULT now();

CREATE OR REPLACE FUNCTION bronze.capture_business_key(p_id bigint)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
            SELECT jsonb_build_array(
                'capture-v2', s.namespace, coalesce(e.canonical_uri, ''),
                to_char(c.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                coalesce(c.content_hash, ''), c.outcome, coalesce(c.bundle_path, ''), coalesce(c.reason_code, '')
            )
            FROM bronze.capture c
            JOIN bronze.source s ON s.id = c.source_id
            LEFT JOIN bronze.source_endpoint e ON e.id = c.source_endpoint_id
            WHERE c.id = p_id
        $$;

CREATE OR REPLACE FUNCTION bronze.record_version_info(p_id bigint)
        RETURNS TABLE (
            id bigint, source_record_id bigint, capture_id bigint,
            observed_at timestamptz, content_hash text,
            source_namespace text, external_key text, canonical_key jsonb
        ) LANGUAGE sql STABLE AS $$
            SELECT v.id, v.source_record_id, v.capture_id, v.observed_at,
                   v.content_hash::text, s.namespace::text, r.external_key::text,
                   jsonb_build_array(
                       'version-v2', s.namespace, r.external_key,
                       to_char(v.observed_at AT TIME ZONE 'UTC',
                               'YYYY-MM-DD"T"HH24:MI:SS.US'),
                       v.content_hash, coalesce(m.canonical_uri, ''),
                       coalesce(bronze.capture_business_key(v.capture_id), '[]'::jsonb)
                   )
            FROM bronze.source_record_version v
            JOIN bronze.source_record r ON r.id = v.source_record_id
            JOIN bronze.source s ON s.id = r.source_id
            LEFT JOIN bronze.source_endpoint m ON m.id = v.identity_match_endpoint_id
            WHERE v.id = p_id
        $$;

UPDATE public.alembic_version SET version_num='c91a6f02de73' WHERE public.alembic_version.version_num = '12a76ebed458';

COMMIT;
