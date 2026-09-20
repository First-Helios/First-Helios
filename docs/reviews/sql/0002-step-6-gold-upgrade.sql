BEGIN;

-- Running upgrade d83f0a21c592 -> 5f3a9c1e7b24

CREATE SCHEMA gold;

CREATE TABLE gold.current_menu (
    id BIGSERIAL NOT NULL,
    subject_id BIGINT NOT NULL,
    subject_kind VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    root_key VARCHAR(512) NOT NULL,
    target_kind VARCHAR(16) NOT NULL,
    target_path TEXT NOT NULL,
    channel VARCHAR(16) NOT NULL,
    service_period VARCHAR(128),
    valid_from TIMESTAMP WITH TIME ZONE,
    valid_to TIMESTAMP WITH TIME ZONE,
    currency_code VARCHAR(3) NOT NULL,
    effective_instant TIMESTAMP WITH TIME ZONE NOT NULL,
    price_state VARCHAR(16) NOT NULL,
    amount_minor BIGINT,
    price_scope_subject_id BIGINT,
    price_source_kind VARCHAR(16),
    price_observed_at TIMESTAMP WITH TIME ZONE,
    price_confidence NUMERIC(5, 4),
    price_page_id BIGINT,
    price_evidence_ids BIGINT[] NOT NULL,
    staleness_seconds BIGINT,
    content_scope VARCHAR(16),
    content_name VARCHAR(512),
    content_description TEXT,
    content_source_kind VARCHAR(16),
    content_observed_at TIMESTAMP WITH TIME ZONE,
    content_scope_subject_id BIGINT,
    content_page_id BIGINT,
    content_evidence_ids BIGINT[] NOT NULL,
    organization_claim_count INTEGER NOT NULL,
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_gold_current_menu UNIQUE NULLS NOT DISTINCT (subject_id, subject_kind, source_record_id, root_key, target_kind, target_path, channel, service_period, valid_from, valid_to, currency_code),
    CONSTRAINT fk_gold_current_menu_subject FOREIGN KEY(subject_id, subject_kind) REFERENCES identity.subject (id, kind) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_gold_current_menu_record FOREIGN KEY(source_record_id) REFERENCES bronze.source_record (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_gold_current_menu_currency FOREIGN KEY(currency_code) REFERENCES menu.currency (code) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_gold_current_menu_price_page FOREIGN KEY(price_page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_gold_current_menu_content_page FOREIGN KEY(content_page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_gold_scope_kind CHECK (subject_kind IN ('organization', 'establishment')),
    CONSTRAINT ck_gold_target_kind CHECK (target_kind IN ('section', 'item', 'variant', 'modifier')),
    CONSTRAINT ck_gold_channel CHECK (channel IN ('unspecified', 'dine_in', 'takeaway')),
    CONSTRAINT ck_gold_price_state CHECK (price_state IN ('priced', 'unknown', 'unavailable', 'absent', 'withdrawn', 'unresolved_base', 'unresolved_scope', 'not_operating')),
    CONSTRAINT ck_gold_amount CHECK ((price_state = 'priced') = (amount_minor IS NOT NULL)),
    CONSTRAINT ck_gold_currency CHECK (currency_code ~ '^[A-Z]{3}$'),
    CONSTRAINT ck_gold_content_scope CHECK (content_scope IS NULL OR content_scope IN ('local', 'organization')),
    CONSTRAINT ck_gold_price_confidence CHECK (price_confidence IS NULL OR price_confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_gold_times CHECK (isfinite(effective_instant) AND isfinite(refreshed_at) AND (price_observed_at IS NULL OR isfinite(price_observed_at)) AND (content_observed_at IS NULL OR isfinite(content_observed_at))),
    CONSTRAINT ck_gold_org_claims CHECK (organization_claim_count >= 0)
);

CREATE INDEX ix_gold_current_menu_scope ON gold.current_menu (subject_id, subject_kind);

CREATE INDEX ix_gold_current_menu_record ON gold.current_menu (source_record_id);

CREATE INDEX ix_gold_current_menu_currency ON gold.current_menu (currency_code);

CREATE INDEX ix_gold_current_menu_price_page ON gold.current_menu (price_page_id);

CREATE INDEX ix_gold_current_menu_content_page ON gold.current_menu (content_page_id);

UPDATE public.alembic_version SET version_num='5f3a9c1e7b24' WHERE public.alembic_version.version_num = 'd83f0a21c592';

COMMIT;
