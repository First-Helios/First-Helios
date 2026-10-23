BEGIN;

-- Running upgrade c95d883737db -> d978bedc2523

ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat DROP NOT NULL,
    ALTER COLUMN cell_lon DROP NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind
        CHECK (area_kind IN ('latlon_grid_0p01', 'latlon_grid_0p05', 'all')),
    ADD CONSTRAINT ck_gold_price_index_area CHECK (
        (area_kind = 'all' AND area_key = 'all' AND cell_lat IS NULL AND cell_lon IS NULL)
        OR (area_kind <> 'all' AND cell_lat IS NOT NULL AND cell_lon IS NOT NULL)
    );

UPDATE public.alembic_version SET version_num='d978bedc2523' WHERE public.alembic_version.version_num = 'c95d883737db';

COMMIT;
