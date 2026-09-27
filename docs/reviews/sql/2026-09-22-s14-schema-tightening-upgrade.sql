BEGIN;

-- Running upgrade 5f3a9c1e7b24 -> 12a76ebed458

CREATE FUNCTION bronze.whitespace()
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
$$;

CREATE OR REPLACE FUNCTION bronze.reject_provenance_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '%.% is immutable and cannot be %',
        TG_TABLE_SCHEMA, TG_TABLE_NAME,
        CASE TG_OP WHEN 'UPDATE' THEN 'updated' WHEN 'DELETE' THEN 'deleted' ELSE 'truncated' END
        USING ERRCODE = '55000';
END;
$$;

DROP TRIGGER trg_source_provenance_immutable ON bronze.source;

CREATE TRIGGER trg_source_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation();

DROP TRIGGER trg_source_endpoint_provenance_immutable ON bronze.source_endpoint;

CREATE TRIGGER trg_source_endpoint_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source_endpoint
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation();

DROP TRIGGER trg_source_record_provenance_immutable ON bronze.source_record;

CREATE TRIGGER trg_source_record_provenance_immutable
BEFORE UPDATE OR DELETE ON bronze.source_record
FOR EACH ROW
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_source_provenance_no_truncate
BEFORE TRUNCATE ON bronze.source
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_source_endpoint_provenance_no_truncate
BEFORE TRUNCATE ON bronze.source_endpoint
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_source_record_provenance_no_truncate
BEFORE TRUNCATE ON bronze.source_record
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_capture_provenance_no_truncate
BEFORE TRUNCATE ON bronze.capture
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_source_record_version_provenance_no_truncate
BEFORE TRUNCATE ON bronze.source_record_version
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_evidence_provenance_no_truncate
BEFORE TRUNCATE ON bronze.evidence
FOR EACH STATEMENT
EXECUTE FUNCTION bronze.reject_provenance_mutation();

ALTER TABLE bronze.source DROP CONSTRAINT ck_source_namespace_canonical;

ALTER TABLE bronze.source ADD CONSTRAINT ck_source_namespace_canonical CHECK (namespace = btrim(namespace, bronze.whitespace()) AND length(namespace) > 0);

ALTER TABLE bronze.source_endpoint DROP CONSTRAINT ck_source_endpoint_uri_canonical;

ALTER TABLE bronze.source_endpoint ADD CONSTRAINT ck_source_endpoint_uri_canonical CHECK (canonical_uri = btrim(canonical_uri, bronze.whitespace()) AND length(canonical_uri) > 0);

ALTER TABLE bronze.source_record DROP CONSTRAINT ck_source_record_external_key_canonical;

ALTER TABLE bronze.source_record ADD CONSTRAINT ck_source_record_external_key_canonical CHECK (external_key = btrim(external_key, bronze.whitespace()) AND length(external_key) > 0);

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_content_hash_not_blank;

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_content_hash_not_blank CHECK (content_hash IS NULL OR length(btrim(content_hash, bronze.whitespace())) > 0);

ALTER TABLE bronze.capture DROP CONSTRAINT ck_capture_bundle_path_not_blank;

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_bundle_path_not_blank CHECK (bundle_path IS NULL OR length(btrim(bundle_path, bronze.whitespace())) > 0);

ALTER TABLE bronze.source_record_version DROP CONSTRAINT ck_source_record_version_content_hash_not_blank;

ALTER TABLE bronze.source_record_version ADD CONSTRAINT ck_source_record_version_content_hash_not_blank CHECK (length(btrim(content_hash, bronze.whitespace())) > 0);

ALTER TABLE bronze.evidence DROP CONSTRAINT ck_evidence_locator_not_blank;

ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_locator_not_blank CHECK (length(btrim(locator, bronze.whitespace())) > 0);

ALTER TABLE bronze.evidence DROP CONSTRAINT ck_evidence_excerpt_hash_not_blank;

ALTER TABLE bronze.evidence ADD CONSTRAINT ck_evidence_excerpt_hash_not_blank CHECK (length(btrim(excerpt_hash, bronze.whitespace())) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_name_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_name_not_blank CHECK (canonical_name IS NULL OR length(btrim(canonical_name, bronze.whitespace() || U&'\200B\200C\200D\2060\FEFF')) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_fingerprint_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_fingerprint_not_blank CHECK (name_fingerprint IS NULL OR length(btrim(name_fingerprint, bronze.whitespace())) > 0);

ALTER TABLE identity.organization DROP CONSTRAINT ck_organization_kind_not_blank;

ALTER TABLE identity.organization ADD CONSTRAINT ck_organization_kind_not_blank CHECK (organization_kind = btrim(organization_kind, bronze.whitespace()) AND length(organization_kind) > 0);

ALTER TABLE identity.subject_name DROP CONSTRAINT ck_subject_name_not_blank;

ALTER TABLE identity.subject_name ADD CONSTRAINT ck_subject_name_not_blank CHECK (name = btrim(name, bronze.whitespace()) AND length(name) > 0);

ALTER TABLE identity.subject_name DROP CONSTRAINT ck_subject_name_fingerprint_not_blank;

ALTER TABLE identity.subject_name ADD CONSTRAINT ck_subject_name_fingerprint_not_blank CHECK (name_fingerprint = btrim(name_fingerprint, bronze.whitespace()) AND length(name_fingerprint) > 0);

ALTER TABLE identity.adjudication DROP CONSTRAINT ck_adjudication_actor_not_blank;

ALTER TABLE identity.adjudication ADD CONSTRAINT ck_adjudication_actor_not_blank CHECK (actor = btrim(actor, bronze.whitespace()) AND length(actor) > 0);

ALTER TABLE identity.adjudication DROP CONSTRAINT ck_adjudication_rationale_bounds;

ALTER TABLE identity.adjudication ADD CONSTRAINT ck_adjudication_rationale_bounds CHECK (rationale = btrim(rationale, bronze.whitespace()) AND length(rationale) > 0 AND length(rationale) <= 4000);

ALTER TABLE identity.resolution_event DROP CONSTRAINT ck_resolution_event_method_not_blank;

ALTER TABLE identity.resolution_event ADD CONSTRAINT ck_resolution_event_method_not_blank CHECK (method = btrim(method, bronze.whitespace()) AND length(method) > 0);

ALTER TABLE identity.resolution_event DROP CONSTRAINT ck_resolution_event_method_version_not_blank;

ALTER TABLE identity.resolution_event ADD CONSTRAINT ck_resolution_event_method_version_not_blank CHECK (method_version = btrim(method_version, bronze.whitespace()) AND length(method_version) > 0);

ALTER TABLE identity.subject_change DROP CONSTRAINT ck_subject_change_method_not_blank;

ALTER TABLE identity.subject_change ADD CONSTRAINT ck_subject_change_method_not_blank CHECK (method = btrim(method, bronze.whitespace()) AND length(method) > 0);

ALTER TABLE identity.subject_change DROP CONSTRAINT ck_subject_change_method_version_not_blank;

ALTER TABLE identity.subject_change ADD CONSTRAINT ck_subject_change_method_version_not_blank CHECK (method_version = btrim(method_version, bronze.whitespace()) AND length(method_version) > 0);

ALTER TABLE bronze.source ADD CONSTRAINT ck_source_kind_canonical CHECK (kind = btrim(kind, bronze.whitespace()) AND length(kind) > 0);

ALTER TABLE bronze.source_endpoint ADD CONSTRAINT ck_source_endpoint_kind_canonical CHECK (endpoint_kind = btrim(endpoint_kind, bronze.whitespace()) AND length(endpoint_kind) > 0);

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_outcome_canonical CHECK (outcome = btrim(outcome, bronze.whitespace()) AND length(outcome) > 0);

ALTER TABLE bronze.source_record ADD CONSTRAINT ck_source_record_first_seen_finite CHECK (isfinite(first_seen_at));

ALTER TABLE bronze.capture ADD CONSTRAINT ck_capture_fetched_at_finite CHECK (isfinite(fetched_at));

ALTER TABLE bronze.source_record_version ADD CONSTRAINT ck_source_record_version_observed_at_finite CHECK (isfinite(observed_at));

ALTER TABLE gold.current_menu ADD CONSTRAINT ck_gold_staleness CHECK (staleness_seconds IS NULL OR staleness_seconds >= 0);

UPDATE public.alembic_version SET version_num='12a76ebed458' WHERE public.alembic_version.version_num = '5f3a9c1e7b24';

COMMIT;
