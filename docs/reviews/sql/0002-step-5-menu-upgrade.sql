BEGIN;

-- Running upgrade b72e6a90c431 -> d83f0a21c592

CREATE SCHEMA menu;

CREATE FUNCTION menu.whitespace()
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT U&'\0009\000A\000B\000C\000D\001C\001D\001E\001F\0020\0085\00A0\1680\2000\2001\2002\2003\2004\2005\2006\2007\2008\2009\200A\2028\2029\202F\205F\3000'
$$;

CREATE FUNCTION menu.valid_tags(tags text[])
RETURNS boolean LANGUAGE sql IMMUTABLE AS $$
    SELECT coalesce(array_ndims(tags), 1) = 1
      AND (cardinality(tags) = 0 OR array_lower(tags, 1) = 1)
      AND NOT EXISTS (SELECT 1 FROM unnest(tags) t
                      WHERE t IS NULL OR t = '' OR t <> lower(btrim(t, menu.whitespace())) OR length(t) > 128
                         OR t ~ '^[[:space:]]*$')
      AND cardinality(tags) = (SELECT count(DISTINCT t) FROM unnest(tags) t)
$$;

CREATE TABLE menu.currency (
    code VARCHAR(3) NOT NULL,
    minor_unit SMALLINT NOT NULL,
    PRIMARY KEY (code),
    CONSTRAINT ck_menu_currency CHECK (code ~ '^[A-Z]{3}$' AND minor_unit BETWEEN 0 AND 4)
);

CREATE TABLE menu.menu_page (
    id BIGSERIAL NOT NULL,
    subject_id BIGINT NOT NULL,
    subject_kind VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    source_record_version_id BIGINT NOT NULL,
    resolution_event_id BIGINT NOT NULL,
    root_key VARCHAR(512) NOT NULL,
    source_kind VARCHAR(16) NOT NULL,
    method VARCHAR(128) NOT NULL,
    method_version VARCHAR(128) NOT NULL,
    stream_revision BIGINT NOT NULL,
    interpretation_revision BIGINT NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    accepted_at TIMESTAMP WITH TIME ZONE NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    operation VARCHAR(16) NOT NULL,
    state VARCHAR(16) NOT NULL,
    base_organization_page_id BIGINT,
    supersedes_page_id BIGINT,
    created_transaction_id BIGINT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_stream_revision UNIQUE (source_record_id, root_key, source_kind, stream_revision),
    CONSTRAINT uq_menu_version_revision UNIQUE (source_record_version_id, root_key, source_kind, interpretation_revision),
    CONSTRAINT fk_menu_page_subject FOREIGN KEY(subject_id, subject_kind) REFERENCES identity.subject (id, kind) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_page_record FOREIGN KEY(source_record_id) REFERENCES bronze.source_record (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_page_version FOREIGN KEY(source_record_version_id) REFERENCES bronze.source_record_version (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_page_event FOREIGN KEY(resolution_event_id) REFERENCES identity.resolution_event (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_page_predecessor FOREIGN KEY(supersedes_page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_page_base FOREIGN KEY(base_organization_page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_page_scope CHECK (subject_kind IN ('organization', 'establishment')),
    CONSTRAINT ck_menu_page_kind CHECK (source_kind IN ('jsonld', 'dom', 'pdf', 'llm')),
    CONSTRAINT ck_menu_page_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_menu_page_revisions CHECK (stream_revision > 0 AND interpretation_revision > 0),
    CONSTRAINT ck_menu_page_times CHECK (isfinite(observed_at) AND isfinite(accepted_at)),
    CONSTRAINT ck_menu_page_operation CHECK ((operation = 'withdrawal' AND state = 'withdrawn' AND base_organization_page_id IS NULL) OR (operation IN ('initial','observation','correction','restoration') AND state = 'published')),
    CONSTRAINT ck_menu_page_base_scope CHECK (subject_kind = 'establishment' OR base_organization_page_id IS NULL),
    CONSTRAINT ck_menu_page_keys CHECK ((root_key IS NULL OR (length(root_key) BETWEEN 1 AND 512 AND root_key = btrim(root_key, menu.whitespace()) AND root_key !~ '^[[:space:]]*$')) AND (method IS NULL OR (length(method) BETWEEN 1 AND 128 AND method = btrim(method, menu.whitespace()) AND method !~ '^[[:space:]]*$')) AND (method_version IS NULL OR (length(method_version) BETWEEN 1 AND 128 AND method_version = btrim(method_version, menu.whitespace()) AND method_version !~ '^[[:space:]]*$')))
);

CREATE INDEX ix_menu_page_base ON menu.menu_page (base_organization_page_id);

CREATE INDEX ix_menu_page_event ON menu.menu_page (resolution_event_id);

CREATE INDEX ix_menu_page_operation ON menu.menu_page (source_record_id, root_key, source_kind, operation, stream_revision);

CREATE INDEX ix_menu_page_subject ON menu.menu_page (subject_id, subject_kind, root_key, observed_at);

CREATE UNIQUE INDEX uq_menu_successor ON menu.menu_page (supersedes_page_id) WHERE supersedes_page_id IS NOT NULL;

CREATE TABLE menu.menu_applicability (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    applicability_key VARCHAR(512) NOT NULL,
    channel VARCHAR(16) NOT NULL,
    service_period VARCHAR(128),
    valid_from TIMESTAMP WITH TIME ZONE,
    valid_to TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_applicability_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_menu_applicability_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT uq_menu_applicability_key UNIQUE (page_id, applicability_key),
    CONSTRAINT uq_menu_context UNIQUE NULLS NOT DISTINCT (page_id, channel, service_period, valid_from, valid_to),
    CONSTRAINT ck_menu_context_channel CHECK (channel IN ('unspecified', 'dine_in', 'takeaway')),
    CONSTRAINT ck_menu_context_window CHECK ((valid_from IS NULL OR isfinite(valid_from)) AND (valid_to IS NULL OR isfinite(valid_to)) AND (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to)),
    CONSTRAINT ck_menu_context_keys CHECK ((applicability_key IS NULL OR (length(applicability_key) BETWEEN 1 AND 512 AND applicability_key = btrim(applicability_key, menu.whitespace()) AND applicability_key !~ '^[[:space:]]*$')) AND (service_period IS NULL OR (length(service_period) BETWEEN 1 AND 128 AND service_period = btrim(service_period, menu.whitespace()) AND service_period !~ '^[[:space:]]*$')))
);

CREATE TABLE menu.menu_section (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    section_key VARCHAR(512) NOT NULL,
    source_native_key VARCHAR(512),
    parent_section_id BIGINT,
    name VARCHAR(512),
    course VARCHAR(128),
    position BIGINT,
    applicability_id BIGINT,
    base_section_id BIGINT,
    effect VARCHAR(16) NOT NULL,
    support_kind VARCHAR(16) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_section_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_menu_section_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_section_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_section_base FOREIGN KEY(base_section_id) REFERENCES menu.menu_section (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_section_shape CHECK ((effect = 'replace' AND support_kind = 'direct' AND name IS NOT NULL AND position IS NOT NULL) OR (effect = 'inherit' AND support_kind = 'inherited' AND base_section_id IS NOT NULL AND name IS NULL AND course IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL) OR (effect = 'suppress' AND support_kind = 'direct' AND base_section_id IS NOT NULL AND name IS NULL AND course IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL) OR (effect = 'replace' AND support_kind = 'structural' AND section_key = 'Unsectioned' AND name = 'Unsectioned' AND position = 0 AND base_section_id IS NULL AND parent_section_id IS NULL AND course IS NULL AND source_native_key IS NULL AND applicability_id IS NULL)),
    CONSTRAINT ck_menu_section_position CHECK (position >= 0),
    CONSTRAINT ck_menu_section_keys CHECK ((section_key IS NULL OR (length(section_key) BETWEEN 1 AND 512 AND section_key = btrim(section_key, menu.whitespace()) AND section_key !~ '^[[:space:]]*$')) AND (source_native_key IS NULL OR (length(source_native_key) BETWEEN 1 AND 512 AND source_native_key = btrim(source_native_key, menu.whitespace()) AND source_native_key !~ '^[[:space:]]*$'))),
    CONSTRAINT uq_menu_section_key UNIQUE (page_id, section_key),
    CONSTRAINT fk_menu_section_parent_section_id FOREIGN KEY(parent_section_id, page_id) REFERENCES menu.menu_section (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_menu_section_text CHECK ((name IS NULL OR (length(name) BETWEEN 1 AND 512 AND name = btrim(name, menu.whitespace()) AND name !~ '^[[:space:]]*$')) AND (course IS NULL OR (length(course) BETWEEN 1 AND 512 AND course = btrim(course, menu.whitespace()) AND course !~ '^[[:space:]]*$')))
);

CREATE INDEX ix_menu_section_applicability_id ON menu.menu_section (applicability_id, page_id);

CREATE INDEX ix_menu_section_base ON menu.menu_section (base_section_id);

CREATE INDEX ix_menu_section_parent_section_id ON menu.menu_section (parent_section_id, page_id);

CREATE UNIQUE INDEX uq_menu_section_base ON menu.menu_section (page_id, base_section_id) WHERE base_section_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_section_native ON menu.menu_section (page_id, parent_section_id, source_native_key) NULLS NOT DISTINCT WHERE source_native_key IS NOT NULL;

CREATE TABLE menu.menu_item (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    item_key VARCHAR(512) NOT NULL,
    source_native_key VARCHAR(512),
    section_id BIGINT NOT NULL,
    name VARCHAR(512),
    description TEXT,
    calories BIGINT,
    dietary_tags TEXT[],
    position BIGINT,
    applicability_id BIGINT,
    base_item_id BIGINT,
    effect VARCHAR(16) NOT NULL,
    support_kind VARCHAR(16) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_item_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_menu_item_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_item_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_item_base FOREIGN KEY(base_item_id) REFERENCES menu.menu_item (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_item_shape CHECK ((effect = 'replace' AND support_kind = 'direct' AND name IS NOT NULL AND dietary_tags IS NOT NULL AND position IS NOT NULL) OR (effect = 'inherit' AND support_kind = 'inherited' AND base_item_id IS NOT NULL AND name IS NULL AND description IS NULL AND calories IS NULL AND dietary_tags IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL) OR (effect = 'suppress' AND support_kind = 'direct' AND base_item_id IS NOT NULL AND name IS NULL AND description IS NULL AND calories IS NULL AND dietary_tags IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL)),
    CONSTRAINT ck_menu_item_position CHECK (position >= 0),
    CONSTRAINT ck_menu_item_keys CHECK ((item_key IS NULL OR (length(item_key) BETWEEN 1 AND 512 AND item_key = btrim(item_key, menu.whitespace()) AND item_key !~ '^[[:space:]]*$')) AND (source_native_key IS NULL OR (length(source_native_key) BETWEEN 1 AND 512 AND source_native_key = btrim(source_native_key, menu.whitespace()) AND source_native_key !~ '^[[:space:]]*$'))),
    CONSTRAINT uq_menu_item_key UNIQUE (page_id, item_key),
    CONSTRAINT fk_menu_item_section_id FOREIGN KEY(section_id, page_id) REFERENCES menu.menu_section (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_menu_item_text CHECK ((name IS NULL OR (length(name) BETWEEN 1 AND 512 AND name = btrim(name, menu.whitespace()) AND name !~ '^[[:space:]]*$')) AND (description IS NULL OR (length(description) BETWEEN 1 AND 8192 AND description = btrim(description, menu.whitespace()) AND description !~ '^[[:space:]]*$'))),
    CONSTRAINT ck_menu_item_values CHECK (calories >= 0 AND (dietary_tags IS NULL OR menu.valid_tags(dietary_tags)))
);

CREATE INDEX ix_menu_item_applicability_id ON menu.menu_item (applicability_id, page_id);

CREATE INDEX ix_menu_item_base ON menu.menu_item (base_item_id);

CREATE INDEX ix_menu_item_section_id ON menu.menu_item (section_id, page_id);

CREATE UNIQUE INDEX uq_menu_item_base ON menu.menu_item (page_id, base_item_id) WHERE base_item_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_item_native ON menu.menu_item (page_id, section_id, source_native_key) NULLS NOT DISTINCT WHERE source_native_key IS NOT NULL;

CREATE TABLE menu.menu_variant (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    variant_key VARCHAR(512) NOT NULL,
    source_native_key VARCHAR(512),
    item_id BIGINT NOT NULL,
    label VARCHAR(512),
    position BIGINT,
    applicability_id BIGINT,
    base_variant_id BIGINT,
    effect VARCHAR(16) NOT NULL,
    support_kind VARCHAR(16) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_variant_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_menu_variant_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_variant_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_variant_base FOREIGN KEY(base_variant_id) REFERENCES menu.menu_variant (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_variant_shape CHECK ((effect = 'replace' AND support_kind = 'direct' AND label IS NOT NULL AND position IS NOT NULL) OR (effect = 'inherit' AND support_kind = 'inherited' AND base_variant_id IS NOT NULL AND label IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL) OR (effect = 'suppress' AND support_kind = 'direct' AND base_variant_id IS NOT NULL AND label IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL)),
    CONSTRAINT ck_menu_variant_position CHECK (position >= 0),
    CONSTRAINT ck_menu_variant_keys CHECK ((variant_key IS NULL OR (length(variant_key) BETWEEN 1 AND 512 AND variant_key = btrim(variant_key, menu.whitespace()) AND variant_key !~ '^[[:space:]]*$')) AND (source_native_key IS NULL OR (length(source_native_key) BETWEEN 1 AND 512 AND source_native_key = btrim(source_native_key, menu.whitespace()) AND source_native_key !~ '^[[:space:]]*$'))),
    CONSTRAINT uq_menu_variant_key UNIQUE (page_id, item_id, variant_key),
    CONSTRAINT fk_menu_variant_item_id FOREIGN KEY(item_id, page_id) REFERENCES menu.menu_item (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_menu_variant_text CHECK ((label IS NULL OR (length(label) BETWEEN 1 AND 512 AND label = btrim(label, menu.whitespace()) AND label !~ '^[[:space:]]*$')))
);

CREATE INDEX ix_menu_variant_applicability_id ON menu.menu_variant (applicability_id, page_id);

CREATE INDEX ix_menu_variant_base ON menu.menu_variant (base_variant_id);

CREATE INDEX ix_menu_variant_item_id ON menu.menu_variant (item_id, page_id);

CREATE UNIQUE INDEX uq_menu_variant_base ON menu.menu_variant (page_id, base_variant_id) WHERE base_variant_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_variant_native ON menu.menu_variant (page_id, item_id, source_native_key) NULLS NOT DISTINCT WHERE source_native_key IS NOT NULL;

CREATE TABLE menu.menu_modifier (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    modifier_key VARCHAR(512) NOT NULL,
    source_native_key VARCHAR(512),
    item_id BIGINT,
    section_id BIGINT,
    label VARCHAR(512),
    required BOOLEAN,
    position BIGINT,
    applicability_id BIGINT,
    base_modifier_id BIGINT,
    effect VARCHAR(16) NOT NULL,
    support_kind VARCHAR(16) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_menu_modifier_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_menu_modifier_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_modifier_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_modifier_base FOREIGN KEY(base_modifier_id) REFERENCES menu.menu_modifier (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_modifier_shape CHECK ((effect = 'replace' AND support_kind = 'direct' AND label IS NOT NULL AND required IS NOT NULL AND position IS NOT NULL) OR (effect = 'inherit' AND support_kind = 'inherited' AND base_modifier_id IS NOT NULL AND label IS NULL AND required IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL) OR (effect = 'suppress' AND support_kind = 'direct' AND base_modifier_id IS NOT NULL AND label IS NULL AND required IS NULL AND position IS NULL AND source_native_key IS NULL AND applicability_id IS NULL)),
    CONSTRAINT ck_menu_modifier_position CHECK (position >= 0),
    CONSTRAINT ck_menu_modifier_keys CHECK ((modifier_key IS NULL OR (length(modifier_key) BETWEEN 1 AND 512 AND modifier_key = btrim(modifier_key, menu.whitespace()) AND modifier_key !~ '^[[:space:]]*$')) AND (source_native_key IS NULL OR (length(source_native_key) BETWEEN 1 AND 512 AND source_native_key = btrim(source_native_key, menu.whitespace()) AND source_native_key !~ '^[[:space:]]*$'))),
    CONSTRAINT uq_menu_modifier_key UNIQUE (page_id, modifier_key),
    CONSTRAINT fk_menu_modifier_item_id FOREIGN KEY(item_id, page_id) REFERENCES menu.menu_item (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_modifier_section_id FOREIGN KEY(section_id, page_id) REFERENCES menu.menu_section (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT ck_menu_modifier_text CHECK ((label IS NULL OR (length(label) BETWEEN 1 AND 512 AND label = btrim(label, menu.whitespace()) AND label !~ '^[[:space:]]*$'))),
    CONSTRAINT ck_menu_modifier_parent CHECK (num_nonnulls(item_id, section_id) = 1)
);

CREATE INDEX ix_menu_modifier_applicability_id ON menu.menu_modifier (applicability_id, page_id);

CREATE INDEX ix_menu_modifier_base ON menu.menu_modifier (base_modifier_id);

CREATE INDEX ix_menu_modifier_item_id ON menu.menu_modifier (item_id, page_id);

CREATE INDEX ix_menu_modifier_section_id ON menu.menu_modifier (section_id, page_id);

CREATE UNIQUE INDEX uq_menu_modifier_base ON menu.menu_modifier (page_id, base_modifier_id) WHERE base_modifier_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_modifier_native ON menu.menu_modifier (page_id, item_id, section_id, source_native_key) NULLS NOT DISTINCT WHERE source_native_key IS NOT NULL;

CREATE TABLE menu.price_observation (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    observation_key VARCHAR(512) NOT NULL,
    section_id BIGINT,
    item_id BIGINT,
    variant_id BIGINT,
    modifier_id BIGINT,
    applicability_id BIGINT NOT NULL,
    price_kind VARCHAR(16) NOT NULL,
    price_state VARCHAR(16) NOT NULL,
    amount_minor BIGINT,
    currency_code VARCHAR(3) NOT NULL,
    confidence NUMERIC(5, 4) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_price_observation_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_price_observation_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT uq_menu_price_key UNIQUE (page_id, observation_key),
    CONSTRAINT fk_price_observation_section_id FOREIGN KEY(section_id, page_id) REFERENCES menu.menu_section (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_price_observation_item_id FOREIGN KEY(item_id, page_id) REFERENCES menu.menu_item (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_price_observation_variant_id FOREIGN KEY(variant_id, page_id) REFERENCES menu.menu_variant (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_price_observation_modifier_id FOREIGN KEY(modifier_id, page_id) REFERENCES menu.menu_modifier (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_price_observation_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_menu_price_currency FOREIGN KEY(currency_code) REFERENCES menu.currency (code) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_price_target CHECK (num_nonnulls(section_id, item_id, variant_id, modifier_id) = 1),
    CONSTRAINT ck_menu_price_state CHECK ((price_state = 'priced' AND amount_minor IS NOT NULL) OR (price_state IN ('unknown','unavailable') AND amount_minor IS NULL)),
    CONSTRAINT ck_menu_price_shape CHECK ((modifier_id IS NOT NULL AND price_kind = 'delta') OR (modifier_id IS NULL AND price_kind = 'absolute' AND (amount_minor IS NULL OR amount_minor >= 0))),
    CONSTRAINT ck_menu_price_confidence CHECK (confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_menu_price_key CHECK ((observation_key IS NULL OR (length(observation_key) BETWEEN 1 AND 512 AND observation_key = btrim(observation_key, menu.whitespace()) AND observation_key !~ '^[[:space:]]*$')))
);

CREATE INDEX ix_menu_price_currency ON menu.price_observation (currency_code);

CREATE INDEX ix_price_observation_applicability_id ON menu.price_observation (applicability_id, page_id);

CREATE INDEX ix_price_observation_item_id ON menu.price_observation (item_id, page_id);

CREATE INDEX ix_price_observation_modifier_id ON menu.price_observation (modifier_id, page_id);

CREATE INDEX ix_price_observation_section_id ON menu.price_observation (section_id, page_id);

CREATE INDEX ix_price_observation_variant_id ON menu.price_observation (variant_id, page_id);

CREATE TABLE menu.evidence_link (
    id BIGSERIAL NOT NULL,
    page_id BIGINT NOT NULL,
    evidence_id BIGINT NOT NULL,
    page_target BOOLEAN NOT NULL,
    section_id BIGINT,
    item_id BIGINT,
    variant_id BIGINT,
    modifier_id BIGINT,
    applicability_id BIGINT,
    price_id BIGINT,
    PRIMARY KEY (id),
    CONSTRAINT uq_evidence_link_id_page UNIQUE (id, page_id),
    CONSTRAINT fk_evidence_link_page FOREIGN KEY(page_id) REFERENCES menu.menu_page (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT fk_menu_evidence FOREIGN KEY(evidence_id) REFERENCES bronze.evidence (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
    CONSTRAINT ck_menu_evidence_target CHECK (page_target::int + num_nonnulls(section_id, item_id, variant_id, modifier_id, applicability_id, price_id) = 1),
    CONSTRAINT fk_evidence_link_section_id FOREIGN KEY(section_id, page_id) REFERENCES menu.menu_section (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_evidence_link_item_id FOREIGN KEY(item_id, page_id) REFERENCES menu.menu_item (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_evidence_link_variant_id FOREIGN KEY(variant_id, page_id) REFERENCES menu.menu_variant (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_evidence_link_modifier_id FOREIGN KEY(modifier_id, page_id) REFERENCES menu.menu_modifier (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_evidence_link_applicability_id FOREIGN KEY(applicability_id, page_id) REFERENCES menu.menu_applicability (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED,
    CONSTRAINT fk_evidence_link_price_id FOREIGN KEY(price_id, page_id) REFERENCES menu.price_observation (id, page_id) ON DELETE RESTRICT ON UPDATE NO ACTION DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX ix_evidence_link_applicability_id ON menu.evidence_link (applicability_id, page_id);

CREATE INDEX ix_evidence_link_item_id ON menu.evidence_link (item_id, page_id);

CREATE INDEX ix_evidence_link_modifier_id ON menu.evidence_link (modifier_id, page_id);

CREATE INDEX ix_evidence_link_price_id ON menu.evidence_link (price_id, page_id);

CREATE INDEX ix_evidence_link_section_id ON menu.evidence_link (section_id, page_id);

CREATE INDEX ix_evidence_link_variant_id ON menu.evidence_link (variant_id, page_id);

CREATE INDEX ix_menu_evidence ON menu.evidence_link (evidence_id);

CREATE INDEX ix_menu_evidence_page ON menu.evidence_link (page_id);

CREATE UNIQUE INDEX uq_menu_evidence_applicability ON menu.evidence_link (applicability_id, evidence_id) WHERE applicability_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_evidence_item ON menu.evidence_link (item_id, evidence_id) WHERE item_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_evidence_modifier ON menu.evidence_link (modifier_id, evidence_id) WHERE modifier_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_evidence_page ON menu.evidence_link (page_id, evidence_id) WHERE page_target;

CREATE UNIQUE INDEX uq_menu_evidence_price ON menu.evidence_link (price_id, evidence_id) WHERE price_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_evidence_section ON menu.evidence_link (section_id, evidence_id) WHERE section_id IS NOT NULL;

CREATE UNIQUE INDEX uq_menu_evidence_variant ON menu.evidence_link (variant_id, evidence_id) WHERE variant_id IS NOT NULL;

INSERT INTO menu.currency(code, minor_unit) VALUES ('USD', 2);

CREATE SEQUENCE menu.admission_fence AS bigint START 1;

CREATE FUNCTION menu.input_committed(p_xmin xid)
RETURNS boolean LANGUAGE plpgsql VOLATILE AS $$
DECLARE full_xid bigint; current_xid bigint := txid_current();
BEGIN
    -- Expand the tuple's 32-bit xmin into the current/previous xid epoch.
    -- Visible frozen/old tuples are committed; our top/subtransactions are not.
    IF p_xmin::text::bigint < 3 THEN RETURN true; END IF;
    full_xid := current_xid - mod(current_xid, 4294967296) + p_xmin::text::bigint;
    IF full_xid > current_xid + 2147483648 THEN full_xid := full_xid - 4294967296;
    ELSIF full_xid < current_xid - 2147483648 THEN full_xid := full_xid + 4294967296;
    END IF;
    RETURN coalesce(pg_xact_status(full_xid::text::xid8) = 'committed', true);
END
$$;

CREATE FUNCTION menu.reject_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Menu aggregates and currency are immutable'
        USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_immutable';
END
$$;

CREATE FUNCTION menu.lock_admission()
RETURNS void LANGUAGE plpgsql VOLATILE AS $$
DECLARE previous_xid bigint; this_xid bigint := txid_current();
BEGIN
    -- Provider batch MUST precede this Menu-owned fence. The sequence is a
    -- non-MVCC transaction watermark, not history, a business key, or a counter.
    -- Conservative serialization also detects append-only withdrawals hidden
    -- by REPEATABLE READ. A rolled-back watermark may cause one safe retry.
    PERFORM pg_advisory_xact_lock(48454, 5);
    SELECT last_value INTO previous_xid FROM menu.admission_fence;
    IF previous_xid <> this_xid AND NOT pg_visible_in_snapshot(
            previous_xid::text::xid8, pg_current_snapshot()) THEN
        RAISE EXCEPTION 'Menu admission snapshot is stale; retry the whole transaction'
            USING ERRCODE = '40001';
    END IF;
    PERFORM setval('menu.admission_fence', this_xid, true);
END
$$;

CREATE FUNCTION menu.admit_scope(p menu.menu_page)
RETURNS void LANGUAGE plpgsql VOLATILE AS $$
DECLARE b menu.menu_page; scope record;
BEGIN
    IF p.base_organization_page_id IS NULL THEN
        SELECT * INTO scope FROM identity.require_resolved_scopes(
            ARRAY[p.subject_id], ARRAY[p.source_record_id], ARRAY[p.resolution_event_id]);
    ELSE
        SELECT * INTO b FROM menu.menu_page WHERE id = p.base_organization_page_id;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'base page is missing' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_base';
        END IF;
        -- One complete local/base batch, never two independently ordered guards.
        SELECT * INTO scope FROM identity.require_resolved_scopes(
            ARRAY[p.subject_id, b.subject_id], ARRAY[p.source_record_id, b.source_record_id],
            ARRAY[p.resolution_event_id, b.resolution_event_id]) LIMIT 1;
    END IF;
    IF scope.kind IS DISTINCT FROM p.subject_kind THEN
        RAISE EXCEPTION 'incorrect Menu subject kind' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_scope';
    END IF;
    PERFORM menu.lock_admission();
    IF p.base_organization_page_id IS NOT NULL THEN
        IF p.subject_kind <> 'establishment' OR b.subject_kind <> 'organization'
           OR b.subject_id IS DISTINCT FROM scope.organization_subject_id
           OR b.state <> 'published' OR b.created_transaction_id = txid_current()
           OR EXISTS (SELECT 1 FROM menu.menu_page w
                      WHERE (w.source_record_id, w.root_key, w.source_kind) =
                            (b.source_record_id, b.root_key, b.source_kind)
                        AND w.operation = 'withdrawal' AND w.stream_revision > b.stream_revision) THEN
            RAISE EXCEPTION 'base is not a committed valid operator pin'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_base';
        END IF;
    END IF;
END
$$;

CREATE FUNCTION menu.admit_page()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE v record; predecessor menu.menu_page; next_revision bigint;
BEGIN
    IF NEW.created_transaction_id IS NOT NULL OR NEW.accepted_at IS NOT NULL THEN
        RAISE EXCEPTION 'Menu admission stamps cannot be supplied'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_stamp';
    END IF;
    PERFORM menu.admit_scope(NEW);
    SELECT * INTO v FROM bronze.record_version_info(NEW.source_record_version_id);
    IF NOT FOUND OR v.source_record_id IS DISTINCT FROM NEW.source_record_id
       OR v.observed_at IS DISTINCT FROM NEW.observed_at
       OR NOT (SELECT menu.input_committed(xmin) FROM bronze.source_record_version
               WHERE id = NEW.source_record_version_id)
       OR (v.capture_id IS NOT NULL AND NOT
           (SELECT menu.input_committed(xmin) FROM bronze.capture WHERE id = v.capture_id)) THEN
        RAISE EXCEPTION 'Menu requires exact committed Bronze input and observation time'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_version';
    END IF;
    SELECT * INTO predecessor FROM menu.menu_page
        WHERE (source_record_id, root_key, source_kind) =
              (NEW.source_record_id, NEW.root_key, NEW.source_kind)
        ORDER BY stream_revision DESC LIMIT 1;
    IF predecessor.id IS NULL THEN
        IF NEW.operation <> 'initial' OR NEW.supersedes_page_id IS NOT NULL
           OR NEW.stream_revision <> 1 OR NEW.interpretation_revision <> 1 THEN
            RAISE EXCEPTION 'stream must start with initial revision 1'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_lifecycle';
        END IF;
    ELSE
        IF predecessor.created_transaction_id = txid_current()
           OR NEW.supersedes_page_id IS DISTINCT FROM predecessor.id
           OR NEW.stream_revision <> predecessor.stream_revision + 1
           OR NEW.operation = 'initial'
           OR (predecessor.state = 'withdrawn') <> (NEW.operation = 'restoration') THEN
            RAISE EXCEPTION 'successor requires the committed head and explicit lifecycle'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_lifecycle';
        END IF;
        IF NEW.operation = 'observation' AND
            (NEW.observed_at <= predecessor.observed_at OR EXISTS (
                SELECT 1 FROM menu.menu_page WHERE source_record_version_id = NEW.source_record_version_id
                AND root_key = NEW.root_key AND source_kind = NEW.source_kind)) THEN
            RAISE EXCEPTION 'observation requires unused later Bronze input'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_lifecycle';
        END IF;
    END IF;
    SELECT coalesce(max(interpretation_revision), 0) + 1 INTO next_revision
        FROM menu.menu_page WHERE source_record_version_id = NEW.source_record_version_id
        AND root_key = NEW.root_key AND source_kind = NEW.source_kind;
    IF NEW.interpretation_revision <> next_revision THEN
        RAISE EXCEPTION 'incorrect version interpretation revision'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_lifecycle';
    END IF;
    NEW.created_transaction_id := txid_current();
    NEW.accepted_at := greatest(clock_timestamp(), predecessor.accepted_at + interval '1 microsecond');
    RETURN NEW;
END
$$;

CREATE FUNCTION menu.admit_member()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE p menu.menu_page;
BEGIN
    SELECT * INTO p FROM menu.menu_page WHERE id = NEW.page_id;
    IF NOT FOUND OR p.created_transaction_id <> txid_current() THEN
        RAISE EXCEPTION 'late aggregate membership is forbidden'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_member_transaction';
    END IF;
    PERFORM menu.admit_scope(p);
    IF p.state = 'withdrawn' AND (TG_TABLE_NAME <> 'evidence_link') THEN
        RAISE EXCEPTION 'withdrawal has no graph' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_tombstone';
    END IF;
    IF TG_TABLE_NAME = 'evidence_link' THEN
        IF (p.state = 'withdrawn' AND NOT NEW.page_target)
           OR NOT bronze.evidence_supports_version(NEW.evidence_id, p.source_record_version_id)
           OR NOT (SELECT menu.input_committed(xmin) FROM bronze.evidence WHERE id = NEW.evidence_id) THEN
            RAISE EXCEPTION 'direct support requires committed Evidence for this exact version/capture'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_evidence';
        END IF;
    END IF;
    RETURN NEW;
END
$$;

CREATE FUNCTION menu.nodes(p_page bigint)
RETURNS TABLE(kind text, id bigint, page_id bigint, parent_kind text, parent_id bigint,
              base_id bigint, applicability_id bigint, native_key text, effect text, support_kind text)
LANGUAGE sql STABLE AS $$
    SELECT 'section', id, page_id, 'section', parent_section_id, base_section_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_section WHERE p_page IS NULL OR page_id = p_page
    UNION ALL
    SELECT 'item', id, page_id, 'section', section_id, base_item_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_item WHERE p_page IS NULL OR page_id = p_page
    UNION ALL
    SELECT 'variant', id, page_id, 'item', item_id, base_variant_id,
           applicability_id, source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_variant WHERE p_page IS NULL OR page_id = p_page
    UNION ALL
    SELECT 'modifier', id, page_id, CASE WHEN item_id IS NOT NULL THEN 'item' ELSE 'section' END,
           coalesce(item_id, section_id), base_modifier_id, applicability_id,
           source_native_key::text, effect::text, support_kind::text
        FROM menu.menu_modifier WHERE p_page IS NULL OR page_id = p_page
$$;

CREATE FUNCTION menu.node_path(p_kind text, p_id bigint)
RETURNS TABLE(kind text, id bigint, page_id bigint, applicability_id bigint,
              native_key text, base_id bigint, effect text, depth integer, cycle boolean)
LANGUAGE sql STABLE AS $$
    WITH RECURSIVE path AS (
        SELECT n.*, 0 AS depth, ARRAY[n.kind || ':' || n.id] AS visited, false AS cycle
        FROM menu.nodes(NULL) n WHERE n.kind = p_kind AND n.id = p_id
        UNION ALL
        SELECT n.*, p.depth + 1, p.visited || (n.kind || ':' || n.id),
               (n.kind || ':' || n.id) = ANY(p.visited)
        FROM path p
        JOIN menu.nodes(NULL) n ON
            (n.kind = p.parent_kind AND n.id = p.parent_id)
            OR (n.kind = p.kind AND n.id = p.base_id)
        WHERE NOT p.cycle
    ) SELECT kind, id, page_id, applicability_id, native_key, base_id, effect, depth, cycle FROM path
$$;

CREATE FUNCTION menu.check_context(p_ids bigint[])
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE channels integer; periods integer; lower_bound timestamptz; upper_bound timestamptz;
BEGIN
    SELECT count(DISTINCT channel), count(DISTINCT service_period), max(valid_from), min(valid_to)
        INTO channels, periods, lower_bound, upper_bound
        FROM menu.menu_applicability WHERE id = ANY(p_ids);
    IF channels > 1 OR periods > 1 OR lower_bound >= upper_bound THEN
        RAISE EXCEPTION 'incompatible applicability after ancestor/base intersection'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_context_intersection';
    END IF;
END
$$;

CREATE FUNCTION menu.check_aggregate(p_page bigint)
RETURNS void LANGUAGE plpgsql STABLE AS $$
DECLARE p menu.menu_page; n record; b record; parent record; price record; contexts bigint[];
BEGIN
    SELECT * INTO p FROM menu.menu_page WHERE id = p_page;
    IF NOT EXISTS (SELECT 1 FROM menu.evidence_link WHERE page_id = p_page AND page_target) THEN
        RAISE EXCEPTION 'page needs direct Evidence' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_support';
    END IF;
    -- Only immutable correspondence here: live Identity/base validity was
    -- certified separately at EVERY insertion, never rechecked at commit.
    IF NOT EXISTS (SELECT 1 FROM identity.resolution_event e
                   WHERE e.id = p.resolution_event_id AND e.source_record_id = p.source_record_id
                   AND e.to_subject_id = p.subject_id) THEN
        RAISE EXCEPTION 'immutable resolution correspondence mismatch'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_event';
    END IF;
    FOR n IN SELECT * FROM menu.nodes(p_page) LOOP
        IF n.support_kind = 'direct' AND NOT EXISTS (
            SELECT 1 FROM menu.evidence_link e WHERE e.page_id = p_page AND
            CASE n.kind WHEN 'section' THEN e.section_id WHEN 'item' THEN e.item_id
                WHEN 'variant' THEN e.variant_id ELSE e.modifier_id END = n.id) THEN
            RAISE EXCEPTION 'direct node needs Evidence' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_support';
        END IF;
        IF n.support_kind = 'structural' AND (EXISTS (
                SELECT 1 FROM menu.evidence_link WHERE section_id = n.id) OR NOT EXISTS (
                SELECT 1 FROM menu.menu_item WHERE section_id = n.id AND support_kind = 'direct'
                    AND effect = 'replace' AND base_item_id IS NULL)) THEN
            RAISE EXCEPTION 'structural grouping derives support from local direct items only'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_support';
        END IF;
        IF n.base_id IS NOT NULL THEN
            SELECT * INTO b FROM menu.nodes(p.base_organization_page_id) x
                WHERE x.kind = n.kind AND x.id = n.base_id;
            IF p.base_organization_page_id IS NULL OR b.id IS NULL
               OR b.page_id <> p.base_organization_page_id THEN
                RAISE EXCEPTION 'typed base target must belong to the pinned page'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_base_parent';
            END IF;
            SELECT * INTO parent FROM menu.nodes(p_page) x
                WHERE x.kind = n.parent_kind AND x.id = n.parent_id;
            IF (n.parent_id IS NULL) <> (b.parent_id IS NULL)
               OR (b.parent_id IS NOT NULL AND
                   (parent.base_id IS DISTINCT FROM b.parent_id OR n.parent_kind <> b.parent_kind)) THEN
                RAISE EXCEPTION 'mapped child must retain its typed base parent'
                    USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_base_parent';
            END IF;
        END IF;
        IF EXISTS (SELECT 1 FROM menu.node_path(n.kind, n.id) x
                   WHERE x.cycle OR (x.depth > 0 AND x.effect = 'suppress')) THEN
            RAISE EXCEPTION 'cycle or child in a suppressed branch'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_graph';
        END IF;
        IF n.native_key IS NOT NULL AND EXISTS (
            SELECT 1 FROM menu.node_path(n.kind, n.id) x
            WHERE x.depth > 0 AND x.page_id = p_page AND x.native_key IS NULL AND x.base_id IS NULL) THEN
            RAISE EXCEPTION 'native correspondence requires a stable ancestor path'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_native_path';
        END IF;
        SELECT array_agg(x.applicability_id) INTO contexts FROM menu.node_path(n.kind, n.id) x;
        PERFORM menu.check_context(contexts);
    END LOOP;
    -- Omitted base descendants still inherit the local restrictions on mapped
    -- ancestors. Validate that implicit graph too, skipping suppressed branches.
    IF p.base_organization_page_id IS NOT NULL THEN
        FOR b IN SELECT * FROM menu.nodes(p.base_organization_page_id) LOOP
            IF NOT EXISTS (
                SELECT 1 FROM menu.node_path(b.kind, b.id) path
                JOIN menu.nodes(p_page) mapped ON mapped.kind = path.kind AND mapped.base_id = path.id
                WHERE mapped.effect = 'suppress'
            ) THEN
                SELECT ARRAY(
                    SELECT path.applicability_id FROM menu.node_path(b.kind, b.id) path
                    UNION
                    SELECT local_path.applicability_id
                    FROM menu.node_path(b.kind, b.id) path
                    JOIN menu.nodes(p_page) mapped ON mapped.kind = path.kind AND mapped.base_id = path.id
                    CROSS JOIN LATERAL menu.node_path(mapped.kind, mapped.id) local_path
                ) INTO contexts;
                PERFORM menu.check_context(contexts);
            END IF;
        END LOOP;
    END IF;
    IF EXISTS (SELECT 1 FROM menu.menu_applicability a WHERE a.page_id = p_page
               AND NOT EXISTS (SELECT 1 FROM menu.evidence_link e WHERE e.applicability_id = a.id)) THEN
        RAISE EXCEPTION 'applicability needs Evidence' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_support';
    END IF;
    FOR price IN SELECT * FROM menu.price_observation WHERE page_id = p_page LOOP
        IF NOT EXISTS (SELECT 1 FROM menu.evidence_link WHERE price_id = price.id) THEN
            RAISE EXCEPTION 'price needs Evidence' USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_support';
        END IF;
        SELECT * INTO n FROM menu.nodes(p_page) x WHERE
            (x.kind = 'section' AND x.id = price.section_id) OR
            (x.kind = 'item' AND x.id = price.item_id) OR
            (x.kind = 'variant' AND x.id = price.variant_id) OR
            (x.kind = 'modifier' AND x.id = price.modifier_id);
        IF EXISTS (SELECT 1 FROM menu.node_path(n.kind, n.id) WHERE effect = 'suppress') THEN
            RAISE EXCEPTION 'price targets a suppressed branch'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_menu_graph';
        END IF;
        SELECT array_agg(x.applicability_id) INTO contexts FROM menu.node_path(n.kind, n.id) x;
        PERFORM menu.check_context(array_append(contexts, price.applicability_id));
    END LOOP;
END
$$;

CREATE FUNCTION menu.check_integrity()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'menu_page' THEN PERFORM menu.check_aggregate(NEW.id);
    ELSE PERFORM menu.check_aggregate(NEW.page_id); END IF;
    RETURN NULL;
END
$$;

CREATE TRIGGER trg_menu_currency_insert BEFORE INSERT ON menu.currency FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.currency FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.currency FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_page FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_page FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_page FOR EACH ROW EXECUTE FUNCTION menu.admit_page();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_page DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_applicability FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_applicability FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_applicability FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_applicability DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_section FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_section FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_section FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_section DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_item FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_item FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_item FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_item DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_variant FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_variant FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_variant FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_variant DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.menu_modifier FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.menu_modifier FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.menu_modifier FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.menu_modifier DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.price_observation FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.price_observation FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.price_observation FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.price_observation DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.evidence_link FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.evidence_link FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation();

CREATE TRIGGER trg_menu_admit BEFORE INSERT ON menu.evidence_link FOR EACH ROW EXECUTE FUNCTION menu.admit_member();

CREATE CONSTRAINT TRIGGER ct_menu_integrity AFTER INSERT ON menu.evidence_link DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION menu.check_integrity();

UPDATE public.alembic_version SET version_num='d83f0a21c592' WHERE public.alembic_version.version_num = 'b72e6a90c431';

COMMIT;
