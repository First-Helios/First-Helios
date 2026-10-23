BEGIN;

-- Running downgrade c95d883737db -> 68146a4c5fc5

ALTER TABLE gold.current_menu
    DROP COLUMN item_name,
    DROP COLUMN section_name;

UPDATE public.alembic_version SET version_num='68146a4c5fc5' WHERE public.alembic_version.version_num = 'c95d883737db';

COMMIT;
