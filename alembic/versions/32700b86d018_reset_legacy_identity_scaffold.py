"""reset the superseded legacy identity scaffold

This deliberately destructive Plan 0002 Step 3 migration permanently
discards every application row in the legacy ``canonical`` Brand/Venue
scaffold. It does not backfill, preserve, or restore those rows. Bronze and
Identity are the authoritative post-reset schemas and are left untouched.

Downgrade recreates only the superseded schema structure for migration
testing; it cannot recover application rows discarded by upgrade.

Revision ID: 32700b86d018
Revises: 3f8b2c1d9a74
Create Date: 2026-09-13 01:21:36.472826

"""

from collections.abc import Sequence
import logging
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "32700b86d018"
down_revision: str | Sequence[str] | None = "3f8b2c1d9a74"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CANONICAL = "canonical"
logger = logging.getLogger("alembic.runtime.migration")
LEGACY_TABLES = (
    "venue_site",
    "site_identity",
    "venue_source",
    "venue_alias",
    "venue",
    "brand",
)


def _timestamps() -> list[sa.Column[Any]]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def _report_discarded_row_counts() -> None:
    migration_context = op.get_context()
    if migration_context.as_sql:
        logger.warning(
            "Plan 0002 Step 3 legacy row counts require an online preflight before execution."
        )
        return

    bind = op.get_bind()
    counts = [
        f"{CANONICAL}.{table}="
        f"{bind.execute(sa.text(f'SELECT count(*) FROM {CANONICAL}.{table}')).scalar_one()}"
        for table in LEGACY_TABLES
    ]
    logger.warning(
        "Plan 0002 Step 3 will intentionally discard legacy application rows: %s",
        ", ".join(counts),
    )


def upgrade() -> None:
    """Discard all legacy application rows, tables, and obsolete schemas."""
    _report_discarded_row_counts()

    for table in LEGACY_TABLES:
        op.drop_table(table, schema=CANONICAL)

    # Deliberately omit CASCADE. Unexpected objects must stop the migration
    # instead of being silently discarded under this narrow authorization.
    op.execute("DROP SCHEMA raw")
    op.execute("DROP SCHEMA canonical")
    op.execute("DROP SCHEMA mart")


def downgrade() -> None:
    """Recreate the legacy shape without claiming to restore discarded rows."""
    op.execute("CREATE SCHEMA raw")
    op.execute("CREATE SCHEMA canonical")
    op.execute("CREATE SCHEMA mart")

    op.create_table(
        "brand",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_fingerprint", name="uq_brand_name_fingerprint"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_brand_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(name_fingerprint)) > 0",
            name="ck_brand_fingerprint_not_blank",
        ),
        schema=CANONICAL,
    )

    op.create_table(
        "venue",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address_raw", sa.Text(), nullable=True),
        *_timestamps(),
        sa.Column("name_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("brand_id", sa.Integer(), nullable=True),
        sa.Column("street", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("postal_code", sa.String(length=16), nullable=True),
        sa.Column("country", sa.String(length=2), nullable=True),
        sa.Column("lat", sa.Double(), nullable=True),
        sa.Column("lng", sa.Double(), nullable=True),
        sa.Column("h3_r6", sa.String(length=16), nullable=True),
        sa.Column("h3_r8", sa.String(length=16), nullable=True),
        sa.Column("h3_r9", sa.String(length=16), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["brand_id"],
            [f"{CANONICAL}.brand.id"],
            name="fk_venue_brand_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "status IN ('open', 'closed', 'unknown')",
            name="ck_venue_status",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_venue_name_not_blank",
        ),
        sa.CheckConstraint(
            "lat IS NULL OR (lat BETWEEN -90 AND 90)",
            name="ck_venue_lat_range",
        ),
        sa.CheckConstraint(
            "lng IS NULL OR (lng BETWEEN -180 AND 180)",
            name="ck_venue_lng_range",
        ),
        sa.CheckConstraint(
            "(lat IS NULL) = (lng IS NULL)",
            name="ck_venue_coords_both_or_neither",
        ),
        schema=CANONICAL,
    )
    op.create_index(
        "ix_venue_name_fingerprint",
        "venue",
        ["name_fingerprint"],
        schema=CANONICAL,
    )
    op.create_index("ix_venue_h3_r8", "venue", ["h3_r8"], schema=CANONICAL)
    op.create_index("ix_venue_brand_id", "venue", ["brand_id"], schema=CANONICAL)

    op.create_table(
        "venue_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("alias_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            [f"{CANONICAL}.venue.id"],
            name="fk_venue_alias_venue_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue_id",
            "alias_fingerprint",
            name="uq_venue_alias_venue_fingerprint",
        ),
        sa.CheckConstraint(
            "length(btrim(alias)) > 0",
            name="ck_venue_alias_not_blank",
        ),
        sa.CheckConstraint(
            "source IN ('overture', 'osm', 'manual')",
            name="ck_venue_alias_source_kind",
        ),
        schema=CANONICAL,
    )

    op.create_table(
        "venue_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column(
            "raw_identity",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            [f"{CANONICAL}.venue.id"],
            name="fk_venue_source_venue_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source",
            "external_id",
            name="uq_venue_source_source_external_id",
        ),
        sa.CheckConstraint(
            "source IN ('overture', 'osm', 'manual')",
            name="ck_venue_source_kind",
        ),
        sa.CheckConstraint(
            "length(btrim(external_id)) > 0",
            name="ck_venue_source_external_id",
        ),
        schema=CANONICAL,
    )
    op.create_index(
        "ix_venue_source_venue_id",
        "venue_source",
        ["venue_id"],
        schema=CANONICAL,
    )

    op.create_table(
        "site_identity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_canonical", sa.Text(), nullable=False),
        sa.Column("url_original", sa.Text(), nullable=True),
        sa.Column(
            "liveness_status",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "url_canonical",
            name="uq_site_identity_url_canonical",
        ),
        sa.CheckConstraint(
            "liveness_status IN ('unknown', 'live', 'dead', 'redirected')",
            name="ck_site_identity_liveness_status",
        ),
        sa.CheckConstraint(
            "length(btrim(url_canonical)) > 0",
            name="ck_site_identity_url_not_blank",
        ),
        schema=CANONICAL,
    )

    op.create_table(
        "venue_site",
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("site_identity_id", sa.Integer(), nullable=False),
        sa.Column("resolution_method", sa.String(length=32), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            [f"{CANONICAL}.venue.id"],
            name="fk_venue_site_venue_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_identity_id"],
            [f"{CANONICAL}.site_identity.id"],
            name="fk_venue_site_site_identity_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("venue_id", "site_identity_id"),
        sa.CheckConstraint(
            "resolution_method IN ('overture_website', 'osm_tag', 'manual')",
            name="ck_venue_site_resolution_method",
        ),
        schema=CANONICAL,
    )
    op.create_index(
        "ix_venue_site_site_identity_id",
        "venue_site",
        ["site_identity_id"],
        schema=CANONICAL,
    )
