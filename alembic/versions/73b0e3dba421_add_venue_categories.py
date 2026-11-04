"""Add the rebuildable venue-category read projection (ADR-0028).

Revision ID: 73b0e3dba421
Revises: 13081a087231
"""

from collections.abc import Sequence

from alembic import op

revision: str = "73b0e3dba421"
down_revision: str | Sequence[str] | None = "13081a087231"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE gold.venue_category (
            venue_id bigint NOT NULL,
            category_group varchar(32) NOT NULL,
            category_key varchar(128) NOT NULL,
            source_record_version_id bigint NOT NULL,
            source_categories text[] NOT NULL,
            mapping_version varchar(64) NOT NULL,
            observed_at timestamptz NOT NULL,
            refreshed_at timestamptz NOT NULL,
            PRIMARY KEY (venue_id, category_group, category_key),
            CONSTRAINT fk_gold_venue_category_venue FOREIGN KEY (venue_id)
                REFERENCES identity.establishment(subject_id) ON DELETE RESTRICT,
            CONSTRAINT fk_gold_venue_category_version FOREIGN KEY (source_record_version_id)
                REFERENCES bronze.source_record_version(id) ON DELETE RESTRICT,
            CONSTRAINT ck_gold_venue_category_group CHECK
                (category_group IN ('cuisine', 'specialty', 'place_type')),
            CONSTRAINT ck_gold_venue_category_key CHECK (category_key ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT ck_gold_venue_category_sources CHECK
                (cardinality(source_categories) > 0 AND array_ndims(source_categories) = 1
                 AND array_position(source_categories, NULL) IS NULL),
            CONSTRAINT ck_gold_venue_category_mapping CHECK (length(btrim(mapping_version)) > 0),
            CONSTRAINT ck_gold_venue_category_times CHECK
                (isfinite(observed_at) AND isfinite(refreshed_at))
        )
    """)
    op.execute(
        "CREATE INDEX ix_gold_venue_category_filter ON gold.venue_category "
        "(category_group, category_key, venue_id)"
    )
    op.execute(
        "CREATE INDEX ix_gold_venue_category_version ON gold.venue_category "
        "(source_record_version_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE gold.venue_category")
