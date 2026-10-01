BEGIN;

-- Running downgrade 7c2e4b9d1f3a -> 5a91ef3ff9d8

DROP TABLE gold.price_index;

UPDATE public.alembic_version SET version_num='5a91ef3ff9d8' WHERE public.alembic_version.version_num = '7c2e4b9d1f3a';

COMMIT;
