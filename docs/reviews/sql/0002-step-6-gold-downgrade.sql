BEGIN;

-- Running downgrade 5f3a9c1e7b24 -> d83f0a21c592

DROP TABLE gold.current_menu;

DROP SCHEMA gold;

UPDATE public.alembic_version SET version_num='d83f0a21c592' WHERE public.alembic_version.version_num = '5f3a9c1e7b24';

COMMIT;
