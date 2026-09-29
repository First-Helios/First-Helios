BEGIN;

-- Running upgrade c91a6f02de73 -> 5a91ef3ff9d8

CREATE TABLE bronze.discovery_release_completion (
    id BIGSERIAL NOT NULL,
    release_endpoint TEXT NOT NULL,
    release_at TIMESTAMP WITH TIME ZONE NOT NULL,
    coverage_key TEXT NOT NULL,
    coverage JSONB NOT NULL,
    poi_count BIGINT NOT NULL,
    predecessor TEXT,
    completed_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_discovery_completion_time CHECK (isfinite(release_at)),
    CONSTRAINT ck_discovery_completion_count CHECK (poi_count >= 0),
    CONSTRAINT uq_discovery_completion_retry UNIQUE NULLS NOT DISTINCT (release_endpoint, coverage_key, release_at, poi_count, predecessor)
);

CREATE INDEX ix_discovery_completion_coverage_release ON bronze.discovery_release_completion (coverage_key, release_at);

CREATE TABLE bronze.discovery_lifecycle_state (
    id BIGSERIAL NOT NULL,
    source_record_id BIGINT,
    version_id BIGINT,
    subject_id BIGINT NOT NULL,
    release_at TIMESTAMP WITH TIME ZONE NOT NULL,
    action TEXT NOT NULL,
    first_missing_at TIMESTAMP WITH TIME ZONE,
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT clock_timestamp() NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_discovery_lifecycle_closure CHECK ((action = 'closed') = (first_missing_at IS NOT NULL)),
    CONSTRAINT ck_discovery_lifecycle_action CHECK (action IN ('projected', 'closed', 'reopened')),
    CONSTRAINT ck_discovery_lifecycle_time CHECK (isfinite(release_at)),
    FOREIGN KEY(source_record_id) REFERENCES bronze.source_record (id) ON DELETE RESTRICT,
    FOREIGN KEY(version_id) REFERENCES bronze.source_record_version (id) ON DELETE RESTRICT
);

CREATE INDEX ix_discovery_lifecycle_record ON bronze.discovery_lifecycle_state (source_record_id, release_at);

CREATE INDEX ix_discovery_lifecycle_subject ON bronze.discovery_lifecycle_state (subject_id, id);

CREATE FUNCTION bronze.reject_discovery_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'discovery evidence cannot be truncated' USING ERRCODE = '55000';
        END $$;

CREATE TRIGGER trg_discovery_release_completion_immutable BEFORE UPDATE OR DELETE ON bronze.discovery_release_completion FOR EACH ROW EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_discovery_release_completion_truncate BEFORE TRUNCATE ON bronze.discovery_release_completion FOR EACH STATEMENT EXECUTE FUNCTION bronze.reject_discovery_truncate();

CREATE TRIGGER trg_discovery_lifecycle_state_immutable BEFORE UPDATE OR DELETE ON bronze.discovery_lifecycle_state FOR EACH ROW EXECUTE FUNCTION bronze.reject_provenance_mutation();

CREATE TRIGGER trg_discovery_lifecycle_state_truncate BEFORE TRUNCATE ON bronze.discovery_lifecycle_state FOR EACH STATEMENT EXECUTE FUNCTION bronze.reject_discovery_truncate();

UPDATE public.alembic_version SET version_num='5a91ef3ff9d8' WHERE public.alembic_version.version_num = 'c91a6f02de73';

COMMIT;
