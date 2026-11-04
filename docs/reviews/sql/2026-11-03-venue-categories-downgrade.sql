BEGIN;

-- Running downgrade 73b0e3dba421 -> 13081a087231

DROP TABLE gold.venue_category;

UPDATE public.alembic_version SET version_num='13081a087231' WHERE public.alembic_version.version_num = '73b0e3dba421';

COMMIT;
