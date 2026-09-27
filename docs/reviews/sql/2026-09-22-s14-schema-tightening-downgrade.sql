BEGIN;

-- Running downgrade 12a76ebed458 -> 5f3a9c1e7b24

ALTER TABLE gold.current_menu DROP CONSTRAINT ck_gold_staleness;

ALTER TABLE bronze.source_record_version DROP CONSTRAINT ck_source_record_version_observed_at_finite;

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_fetched_at_finite;

ALTER TABLE bronze.source_record DROP CONSTRAINT ck_source_record_first_seen_finite;

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_outcome_canonical;

ALTER TABLE bronze.source_endpoint DROP CONSTRAINT ck_source_endpoint_kind_canonical;

ALTER TABLE bronze.source DROP CONSTRAINT ck_source_kind_canonical;

ALTER TABLE identity.subject_change DROP CONSTRAINT ck_subject_change_method_version_not_blank;

ALTER TABLE identity.subject_change ADD CONSTRAINT ck_subject_change_method_version_not_blank CHECK (method_version = btrim(method_version) AND length(method_version) > 0);

ALTER TABLE identity.subject_change DROP CONSTRAINT ck_subject_change_method_not_blank;

ALTER TABLE identity.subject_change ADD CONSTRAINT ck_subject_change_method_not_blank CHECK (method = btrim(method) AND length(method) > 0);

ALTER TABLE identity.resolution_event DROP CONSTRAINT ck_resolution_event_method_version_not_blank;

ALTER TABLE identity.resolution_event ADD CONSTRAINT ck_resolution_event_method_version_not_blank CHECK (method_version = btrim(method_version) AND length(method_version) > 0);

ALTER TABLE identity.resolution_event DROP CONSTRAINT ck_resolution_event_method_not_blank;

ALTER TABLE identity.resolution_event ADD CONSTRAINT ck_resolution_event_method_not_blank CHECK (method = btrim(method) AND length(method) > 0);

ALTER TABLE identity.adjudication DROP CONSTRAINT ck_adjudication_rationale_bounds;

ALTER TABLE identity.adjudication ADD CONSTRAINT ck_adjudication_rationale_bounds CHECK (rationale = btrim(rationale) AND length(rationale) > 0 AND length(rationale) <= 4000);

ALTER TABLE identity.adjudication DROP CONSTRAINT ck_adjudication_actor_not_blank;

ALTER TABLE identity.adjudication ADD CONSTRAINT ck_adjudication_actor_not_blank CHECK (actor = btrim(actor) AND length(actor) > 0);

ALTER TABLE identity.subject_name DROP CONSTRAINT ck_subject_name_fingerprint_not_blank;

ALTER TABLE identity.subject_name ADD CONSTRAINT ck_subject_name_fingerprint_not_blank CHECK (name_fingerprint = btrim(name_fingerprint) AND length(name_fingerprint) > 0);

ALTER TABLE identity.subject_name DROP CONSTRAINT ck_subject_name_not_blank;

ALTER TABLE identity.subject_name ADD CONSTRAINT ck_subject_name_not_blank CHECK (name = btrim(name) AND length(name) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_kind_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_kind_not_blank CHECK (organization_kind = btrim(organization_kind) AND length(organization_kind) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_fingerprint_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_fingerprint_not_blank CHECK (name_fingerprint IS NULL OR length(btrim(name_fingerprint)) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_name_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_name_not_blank CHECK (canonical_name IS NULL OR length(btrim(canonical_name)) > 0);

ALTER TABLE bronze.evidence DROP CONSTRAINT ck_evidence_excerpt_hash_not_blank;

ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_excerpt_hash_not_blank CHECK (length(btrim(excerpt_hash)) > 0);

ALTER TABLE bronze.evidence DROP CONSTRAINT ck_evidence_locator_not_blank;

ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_locator_not_blank CHECK (length(btrim(locator)) > 0);

ALTER TABLE bronze.source_record_version DROP CONSTRAINT ck_source_record_version_content_hash_not_blank;

ALTER TABLE bronze.source_record_version ADD CONSTRAINT ck_source_record_version_content_hash_not_blank CHECK (length(btrim(content_hash)) > 0);

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_bundle_path_not_blank;

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_bundle_path_not_blank CHECK (bundle_path IS NULL OR length(btrim(bundle_path)) > 0);

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_content_hash_not_blank;

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_content_hash_not_blank CHECK (content_hash IS NULL OR length(btrim(content_hash)) > 0);

ALTER TABLE bronze.source_record DROP CONSTRAINT ck_source_record_external_key_canonical;

ALTER TABLE bronze.source_record ADD CONSTRAINT ck_source_record_external_key_canonical CHECK (external_key = btrim(external_key) AND length(external_key) > 0);

ALTER TABLE bronze.source_endpoint DROP CONSTRAINT ck_source_endpoint_uri_canonical;

ALTER TABLE bronze.source_endpoint ADD CONSTRAINT ck_source_endpoint_uri_canonical CHECK (canonical_uri = btrim(canonical_uri) AND length(canonical_uri) > 0);

ALTER TABLE bronze.source DROP CONSTRAINT ck_source_namespace_canonical;

ALTER TABLE bronze.source ADD CONSTRAINT ck_source_namespace_canonical CHECK (namespace = btrim(namespace) AND length(namespace) > 0);

DROP TRIGGER trg_evidence_provenance_no_truncate ON bronze.evidence;

DROP TRIGGER trg_source_record_version_provenance_no_truncate ON bronze.source_record_version;

DROP TRIGGER trg_capture_provenance_no_truncate ON bronze.capture;

DROP TRIGGER trg_source_record_provenance_no_truncate ON bronze.source_record;

DROP TRIGGER trg_source_endpoint_provenance_no_truncate ON bronze.source_endpoint;

DROP TRIGGER trg_source_provenance_no_truncate ON bronze.source;

DROP TRIGGER trg_source_provenance_immutable ON bronze.source;

CREATE TRIGGER trg_source_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation('namespace');

DROP TRIGGER trg_source_endpoint_provenance_immutable ON bronze.source_endpoint;

CREATE TRIGGER trg_source_endpoint_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source_endpoint
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation('source_id', 'canonical_uri');

DROP TRIGGER trg_source_record_provenance_immutable ON bronze.source_record;

CREATE TRIGGER trg_source_record_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source_record
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation('source_id', 'external_key');

CREATE OR REPLACE FUNCTION bronze.reject_provenance_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    immutable_column text;
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION '%.% is immutable and cannot be deleted',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;

    IF TG_NARGS = 0 THEN
        RAISE EXCEPTION '%.% is immutable and cannot be updated',
            TG_TABLE_SCHEMA, TG_TABLE_NAME
            USING ERRCODE = '55000';
    END IF;

    FOREACH immutable_column IN ARRAY TG_ARGV LOOP
        IF to_jsonb(NEW) -> immutable_column
            IS DISTINCT FROM to_jsonb(OLD) -> immutable_column THEN
            RAISE EXCEPTION '%.%.% is immutable',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, immutable_column
                USING ERRCODE = '55000';
        END IF;
    END LOOP;

    RETURN NEW;
END;
$$;

DROP FUNCTION bronze.whitespace();

UPDATE public.alembic_version SET version_num='5f3a9c1e7b24' WHERE public.alembic_version.version_num = '12a76ebed458';

COMMIT;
