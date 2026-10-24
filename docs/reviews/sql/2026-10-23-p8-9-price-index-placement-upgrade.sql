BEGIN;

-- Running upgrade d978bedc2523 -> 13081a087231

CREATE TABLE gold.price_index_placement (
    id BIGSERIAL NOT NULL,
    subject_id BIGINT NOT NULL,
    subject_kind VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    venue_id BIGINT NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    via_organization BOOLEAN NOT NULL,
    effective_instant TIMESTAMP WITH TIME ZONE NOT NULL,
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_gold_price_index_placement UNIQUE (subject_id, subject_kind, source_record_id),
    CONSTRAINT ck_gold_price_index_placement_scope CHECK (subject_kind IN ('organization', 'establishment')),
    CONSTRAINT ck_gold_price_index_placement_venue CHECK (via_organization = (subject_kind = 'organization') AND (via_organization OR venue_id = subject_id)),
    CONSTRAINT ck_gold_price_index_placement_point CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_gold_price_index_placement_times CHECK (isfinite(effective_instant) AND isfinite(refreshed_at))
);

CREATE INDEX ix_gold_price_index_placement_point ON gold.price_index_placement (latitude, longitude);

UPDATE public.alembic_version SET version_num='13081a087231' WHERE public.alembic_version.version_num = 'd978bedc2523';

COMMIT;
