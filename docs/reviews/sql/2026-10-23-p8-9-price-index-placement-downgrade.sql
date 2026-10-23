BEGIN;

-- Running downgrade 13081a087231 -> d978bedc2523

DROP TABLE gold.price_index_placement;

UPDATE public.alembic_version SET version_num='d978bedc2523' WHERE public.alembic_version.version_num = '13081a087231';

COMMIT;
