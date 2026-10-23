BEGIN;

-- Running downgrade d978bedc2523 -> c95d883737db

DELETE FROM gold.price_index WHERE area_kind <> 'latlon_grid_0p01';

ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area,
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat SET NOT NULL,
    ALTER COLUMN cell_lon SET NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind CHECK (area_kind IN ('latlon_grid_0p01'));

UPDATE public.alembic_version SET version_num='c95d883737db' WHERE public.alembic_version.version_num = 'd978bedc2523';

COMMIT;
