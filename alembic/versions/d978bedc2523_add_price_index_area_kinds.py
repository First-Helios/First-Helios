"""Add the 0.05° grid and citywide ``all`` area kinds to the Gold price index.

ADR-0007 Amendment 3 (ADR-0019 step 3), SQL approved as written (OQ5).
``gold.price_index`` only: ``area_kind`` widens to ``latlon_grid_0p05`` and
``all``; ``cell_lat``/``cell_lon`` become nullable, and ``ck_gold_price_index_area``
requires NULL coordinates and the ``all`` key for ``all`` and both coordinates
for a grid kind. No row is rewritten; the existing 0.01° rows are checked
against the new CHECKs under one ``ACCESS EXCLUSIVE`` lock. Gold is rebuildable
(ADR-0004 §1), so the downgrade deletes the 0.05° and ``all`` rows, which the
old code can neither store nor read (OQ4), then restores NOT NULL and the old
CHECK. The 0.01° rows stay. Nothing references ``gold.price_index``.

Revision ID: d978bedc2523
Revises: c95d883737db
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d978bedc2523"
down_revision: str | Sequence[str] | None = "c95d883737db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat DROP NOT NULL,
    ALTER COLUMN cell_lon DROP NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind
        CHECK (area_kind IN ('latlon_grid_0p01', 'latlon_grid_0p05', 'all')),
    ADD CONSTRAINT ck_gold_price_index_area CHECK (
        (area_kind = 'all' AND area_key = 'all' AND cell_lat IS NULL AND cell_lon IS NULL)
        OR (area_kind <> 'all' AND cell_lat IS NOT NULL AND cell_lon IS NOT NULL)
    )
""")


def downgrade() -> None:
    op.execute("""
DELETE FROM gold.price_index WHERE area_kind <> 'latlon_grid_0p01'
""")
    op.execute("""
ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area,
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat SET NOT NULL,
    ALTER COLUMN cell_lon SET NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind CHECK (area_kind IN ('latlon_grid_0p01'))
""")
