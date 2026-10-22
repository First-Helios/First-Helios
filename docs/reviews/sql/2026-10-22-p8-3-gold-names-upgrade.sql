BEGIN;

-- Running upgrade 68146a4c5fc5 -> c95d883737db

ALTER TABLE gold.current_menu
    ADD COLUMN section_name VARCHAR(512),
    ADD COLUMN item_name VARCHAR(512);

UPDATE public.alembic_version SET version_num='c95d883737db' WHERE public.alembic_version.version_num = '68146a4c5fc5';

COMMIT;
