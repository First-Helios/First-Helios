"""Add the Gold price-index placements, the families behind each index row.

ADR-0020 §2 (owner decision 3 approved the direction; this SQL is reviewed in
the build PR). Creates ``gold.price_index_placement``: one row per family the
price index counts, with the venue and Place point it counts at, written by the
price-index refresh beside ``gold.price_index``. Additive only: no existing
table, column or row is touched, and nothing references the new table. Its
rows are rebuilt in full by every refresh, so the upgrade leaves it empty until
the next one, and the downgrade drops it with its rows (Gold is rebuildable,
ADR-0004 §1).

Revision ID: 13081a087231
Revises: d978bedc2523
Create Date: 2026-10-23
"""

from collections.abc import Sequence

from alembic import op

revision: str = "13081a087231"
down_revision: str | Sequence[str] | None = "d978bedc2523"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
CREATE TABLE gold.price_index_placement (
    id BIGSERIAL NOT NULL,
    subject_id BIGINT NOT NULL,
    subject_kind VARCHAR(32) NOT NULL,
    source_record_id BIGINT NOT NULL,
    venue_id BIGINT NOT NULL,
    latitude NUMERIC(9, 6) NOT NULL,
    longitude NUMERIC(9, 6) NOT NULL,
    via_organization BOOLEAN NOT NULL,
    effective_instant TIMESTAMP WITH TIME ZONE NOT NULL,
    refreshed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_gold_price_index_placement UNIQUE (subject_id, subject_kind, source_record_id),
    CONSTRAINT ck_gold_price_index_placement_scope CHECK (subject_kind IN ('organization', 'establishment')),
    CONSTRAINT ck_gold_price_index_placement_venue CHECK (via_organization = (subject_kind = 'organization') AND (via_organization OR venue_id = subject_id)),
    CONSTRAINT ck_gold_price_index_placement_point CHECK (latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180),
    CONSTRAINT ck_gold_price_index_placement_times CHECK (isfinite(effective_instant) AND isfinite(refreshed_at))
)
    """)
    op.execute("""
CREATE INDEX ix_gold_price_index_placement_point ON gold.price_index_placement (latitude, longitude)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE gold.price_index_placement")
