BEGIN;

-- Running downgrade d83f0a21c592 -> b72e6a90c431

DROP TRIGGER trg_menu_currency_insert ON menu.currency;

DROP TRIGGER trg_menu_immutable ON menu.currency;

DROP TRIGGER trg_menu_no_truncate ON menu.currency;

DROP TRIGGER trg_menu_immutable ON menu.menu_page;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_page;

DROP TRIGGER trg_menu_admit ON menu.menu_page;

DROP TRIGGER ct_menu_integrity ON menu.menu_page;

DROP TRIGGER trg_menu_immutable ON menu.menu_applicability;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_applicability;

DROP TRIGGER trg_menu_admit ON menu.menu_applicability;

DROP TRIGGER ct_menu_integrity ON menu.menu_applicability;

DROP TRIGGER trg_menu_immutable ON menu.menu_section;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_section;

DROP TRIGGER trg_menu_admit ON menu.menu_section;

DROP TRIGGER ct_menu_integrity ON menu.menu_section;

DROP TRIGGER trg_menu_immutable ON menu.menu_item;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_item;

DROP TRIGGER trg_menu_admit ON menu.menu_item;

DROP TRIGGER ct_menu_integrity ON menu.menu_item;

DROP TRIGGER trg_menu_immutable ON menu.menu_variant;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_variant;

DROP TRIGGER trg_menu_admit ON menu.menu_variant;

DROP TRIGGER ct_menu_integrity ON menu.menu_variant;

DROP TRIGGER trg_menu_immutable ON menu.menu_modifier;

DROP TRIGGER trg_menu_no_truncate ON menu.menu_modifier;

DROP TRIGGER trg_menu_admit ON menu.menu_modifier;

DROP TRIGGER ct_menu_integrity ON menu.menu_modifier;

DROP TRIGGER trg_menu_immutable ON menu.price_observation;

DROP TRIGGER trg_menu_no_truncate ON menu.price_observation;

DROP TRIGGER trg_menu_admit ON menu.price_observation;

DROP TRIGGER ct_menu_integrity ON menu.price_observation;

DROP TRIGGER trg_menu_immutable ON menu.evidence_link;

DROP TRIGGER trg_menu_no_truncate ON menu.evidence_link;

DROP TRIGGER trg_menu_admit ON menu.evidence_link;

DROP TRIGGER ct_menu_integrity ON menu.evidence_link;

DROP FUNCTION menu.check_integrity();

DROP FUNCTION menu.check_aggregate(bigint);

DROP FUNCTION menu.check_context(bigint[]);

DROP FUNCTION menu.node_path(text, bigint);

DROP FUNCTION menu.nodes(bigint);

DROP FUNCTION menu.admit_member();

DROP FUNCTION menu.admit_page();

DROP FUNCTION menu.admit_scope(menu.menu_page);

DROP FUNCTION menu.lock_admission();

DROP FUNCTION menu.reject_mutation();

DROP FUNCTION menu.input_committed(xid);

DROP TABLE menu.evidence_link;

DROP TABLE menu.price_observation;

DROP TABLE menu.menu_modifier;

DROP TABLE menu.menu_variant;

DROP TABLE menu.menu_item;

DROP TABLE menu.menu_section;

DROP TABLE menu.menu_applicability;

DROP TABLE menu.menu_page;

DROP TABLE menu.currency;

DROP SEQUENCE menu.admission_fence;

DROP FUNCTION menu.valid_tags(text[]);

DROP FUNCTION menu.whitespace();

DROP SCHEMA menu;

UPDATE public.alembic_version SET version_num='b72e6a90c431' WHERE public.alembic_version.version_num = 'd83f0a21c592';

COMMIT;
