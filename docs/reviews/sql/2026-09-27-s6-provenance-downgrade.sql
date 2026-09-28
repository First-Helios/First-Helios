BEGIN;

-- Running downgrade c91a6f02de73 -> 12a76ebed458

DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM bronze.source) THEN
 RAISE EXCEPTION 'ADR-0011: downgrade requires an empty Bronze database; rebuild it';
 END IF;
END $$;;

CREATE OR REPLACE FUNCTION bronze.record_version_info(p_id bigint)
        RETURNS TABLE (
            id bigint, source_record_id bigint, capture_id bigint,
            observed_at timestamptz, content_hash text,
            source_namespace text, external_key text, canonical_key jsonb
        ) LANGUAGE sql STABLE AS $$
            SELECT v.id, v.source_record_id, v.capture_id, v.observed_at,
                   v.content_hash::text, s.namespace::text, r.external_key::text,
                   jsonb_build_array(
                       'version-v1', s.namespace, r.external_key,
                       to_char(v.observed_at AT TIME ZONE 'UTC',
                               'YYYY-MM-DD"T"HH24:MI:SS.US'),
                       v.content_hash,
                       coalesce(bronze.capture_business_key(v.capture_id), '[]'::jsonb)
                   )
            FROM bronze.source_record_version v
            JOIN bronze.source_record r ON r.id = v.source_record_id
            JOIN bronze.source s ON s.id = r.source_id
            WHERE v.id = p_id
        $$;

CREATE OR REPLACE FUNCTION bronze.capture_business_key(p_id bigint)
        RETURNS jsonb LANGUAGE sql STABLE AS $$
            SELECT jsonb_build_array(
                'capture-v1', s.namespace, coalesce(e.canonical_uri, ''),
                to_char(c.fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
                coalesce(c.content_hash, ''), c.outcome, coalesce(c.bundle_path, '')
            )
            FROM bronze.capture c
            JOIN bronze.source s ON s.id = c.source_id
            LEFT JOIN bronze.source_endpoint e ON e.id = c.source_endpoint_id
            WHERE c.id = p_id
        $$;

ALTER TABLE bronze.evidence DROP COLUMN ingested_at;

ALTER TABLE bronze.source_record_version DROP COLUMN ingested_at;

ALTER TABLE bronze.capture DROP COLUMN ingested_at;

ALTER TABLE bronze.evidence DROP CONSTRAINT ck_evidence_version_locator_jsonpath;
DROP INDEX bronze.ix_source_record_version_identity_match_endpoint_id;
ALTER TABLE bronze.source_record_version DROP CONSTRAINT fk_source_record_version_match_endpoint_source;
ALTER TABLE bronze.source_record_version DROP COLUMN identity_match_endpoint_id;
ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_reason_code_format;
ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_reason_matches_outcome;
ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_outcome;
ALTER TABLE bronze.capture DROP COLUMN reason_code;
ALTER TABLE bronze.capture ALTER COLUMN source_endpoint_id DROP NOT NULL;
ALTER TABLE bronze.source_endpoint DROP CONSTRAINT ck_source_endpoint_kind;
ALTER TABLE bronze.source_endpoint DROP CONSTRAINT uq_source_endpoint_source_canonical_uri;
ALTER TABLE bronze.source_endpoint ADD CONSTRAINT uq_source_endpoint_canonical_uri UNIQUE (canonical_uri);;

UPDATE public.alembic_version SET version_num='12a76ebed458' WHERE public.alembic_version.version_num = 'c91a6f02de73';

COMMIT;
