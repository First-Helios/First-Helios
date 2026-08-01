"""venue identity schema and three-layer split

Creates the `raw` / `canonical` / `mart` schemas (ADR-0003), relocates the
existing `venue` scaffold out of `public`, grows it into a real identity
record, and adds the rest of the venue-identity graph (RFC-0001 D2).

Hand-written rather than taken from autogenerate, because autogenerate cannot
express the two things that matter most here:

- `venue` is **moved** with `ALTER TABLE ... SET SCHEMA` and its address column
  **renamed**, so any existing row survives. Autogenerate would have emitted a
  drop-and-create pair, silently discarding data.
- `raw` and `mart` are created now, empty. They are the layers ADR-0003
  authorizes, and creating a schema is free; their tables land in later PRs.

Revision ID: a466cf4bc4e0
Revises: c16e32ee8cd2
Create Date: 2026-08-01

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a466cf4bc4e0"
down_revision: str | Sequence[str] | None = "c16e32ee8cd2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CANONICAL = "canonical"


def upgrade() -> None:
    # --- Layers (ADR-0003) -------------------------------------------------
    op.execute("CREATE SCHEMA IF NOT EXISTS raw")
    op.execute("CREATE SCHEMA IF NOT EXISTS canonical")
    op.execute("CREATE SCHEMA IF NOT EXISTS mart")

    # --- brand: created before venue, which points at it -------------------
    op.create_table(
        "brand",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name_fingerprint", name="uq_brand_name_fingerprint"),
        sa.CheckConstraint("length(btrim(name)) > 0", name="ck_brand_name_not_blank"),
        sa.CheckConstraint(
            "length(btrim(name_fingerprint)) > 0", name="ck_brand_fingerprint_not_blank"
        ),
        schema=CANONICAL,
    )

    # --- venue: relocated, then grown in place -----------------------------
    # SET SCHEMA moves the table with its data, indexes and constraints intact.
    op.execute(f"ALTER TABLE public.venue SET SCHEMA {CANONICAL}")

    # The old free-text `address` becomes the provenance copy; normalized
    # components are added alongside it rather than replacing it.
    op.alter_column(
        "venue",
        "address",
        new_column_name="address_raw",
        type_=sa.Text(),
        existing_type=sa.String(length=500),
        existing_nullable=True,
        schema=CANONICAL,
    )

    op.add_column(
        "venue", sa.Column("name_fingerprint", sa.String(length=255), nullable=True), schema=CANONICAL
    )
    op.add_column("venue", sa.Column("brand_id", sa.Integer(), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("street", sa.String(length=255), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("city", sa.String(length=128), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("region", sa.String(length=64), nullable=True), schema=CANONICAL)
    op.add_column(
        "venue", sa.Column("postal_code", sa.String(length=16), nullable=True), schema=CANONICAL
    )
    op.add_column("venue", sa.Column("country", sa.String(length=2), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("lat", sa.Double(), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("lng", sa.Double(), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("h3_r6", sa.String(length=16), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("h3_r8", sa.String(length=16), nullable=True), schema=CANONICAL)
    op.add_column("venue", sa.Column("h3_r9", sa.String(length=16), nullable=True), schema=CANONICAL)
    op.add_column(
        "venue",
        sa.Column("status", sa.String(length=16), server_default="unknown", nullable=False),
        schema=CANONICAL,
    )
    op.add_column(
        "venue",
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        schema=CANONICAL,
    )
    op.add_column(
        "venue",
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        schema=CANONICAL,
    )

    op.create_foreign_key(
        "fk_venue_brand_id",
        "venue",
        "brand",
        ["brand_id"],
        ["id"],
        source_schema=CANONICAL,
        referent_schema=CANONICAL,
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_venue_status", "venue", "status IN ('open', 'closed', 'unknown')", schema=CANONICAL
    )
    op.create_check_constraint(
        "ck_venue_name_not_blank", "venue", "length(btrim(name)) > 0", schema=CANONICAL
    )
    op.create_check_constraint(
        "ck_venue_lat_range", "venue", "lat IS NULL OR (lat BETWEEN -90 AND 90)", schema=CANONICAL
    )
    op.create_check_constraint(
        "ck_venue_lng_range", "venue", "lng IS NULL OR (lng BETWEEN -180 AND 180)", schema=CANONICAL
    )
    op.create_check_constraint(
        "ck_venue_coords_both_or_neither",
        "venue",
        "(lat IS NULL) = (lng IS NULL)",
        schema=CANONICAL,
    )
    op.create_index("ix_venue_name_fingerprint", "venue", ["name_fingerprint"], schema=CANONICAL)
    op.create_index("ix_venue_h3_r8", "venue", ["h3_r8"], schema=CANONICAL)
    op.create_index("ix_venue_brand_id", "venue", ["brand_id"], schema=CANONICAL)

    # --- venue_alias -------------------------------------------------------
    op.create_table(
        "venue_alias",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("alias_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            [f"{CANONICAL}.venue.id"],
            name="fk_venue_alias_venue_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "venue_id", "alias_fingerprint", name="uq_venue_alias_venue_fingerprint"
        ),
        sa.CheckConstraint("length(btrim(alias)) > 0", name="ck_venue_alias_not_blank"),
        sa.CheckConstraint(
            "source IN ('overture', 'osm', 'manual')", name="ck_venue_alias_source_kind"
        ),
        schema=CANONICAL,
    )

    # --- venue_source ------------------------------------------------------
    op.create_table(
        "venue_source",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("raw_identity", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "first_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["venue_id"],
            [f"{CANONICAL}.venue.id"],
            name="fk_venue_source_venue_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "external_id", name="uq_venue_source_source_external_id"),
        sa.CheckConstraint("source IN ('overture', 'osm', 'manual')", name="ck_venue_source_kind"),
        sa.CheckConstraint("length(btrim(external_id)) > 0", name="ck_venue_source_external_id"),
        schema=CANONICAL,
    )
    op.create_index("ix_venue_source_venue_id", "venue_source", ["venue_id"], schema=CANONICAL)

    # --- site_identity -----------------------------------------------------
    op.create_table(
        "site_identity",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_canonical", sa.Text(), nullable=False),
        sa.Column("url_original", sa.Text(), nullable=True),
        sa.Column(
            "liveness_status", sa.String(length=16), server_default="unknown", nullable=False
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url_canonical", name="uq_site_identity_url_canonical"),
        sa.CheckConstraint(
            "liveness_status IN ('unknown', 'live', 'dead', 'redirected')",
            name="ck_site_identity_liveness_status",
        ),
        sa.CheckConstraint(
            "length(btrim(url_canonical)) > 0", name="ck_site_identity_url_not_blank"
        ),
        schema=CANONICAL,
    )

    # --- venue_site: the many-to-many RFC-0001 D2 describes but doesn't name -
    op.create_table(
        "venue_site",
        sa.Column("venue_id", sa.Integer(), nullable=False),
        sa.Column("site_identity_id", sa.Integer(), nullable=False),
        sa.Column("resolution_method", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
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
        "ix_venue_site_site_identity_id", "venue_site", ["site_identity_id"], schema=CANONICAL
    )


def downgrade() -> None:
    # Reverse order: dependents first, then venue back to public, then schemas.
    op.drop_index("ix_venue_site_site_identity_id", table_name="venue_site", schema=CANONICAL)
    op.drop_table("venue_site", schema=CANONICAL)
    op.drop_table("site_identity", schema=CANONICAL)
    op.drop_index("ix_venue_source_venue_id", table_name="venue_source", schema=CANONICAL)
    op.drop_table("venue_source", schema=CANONICAL)
    op.drop_table("venue_alias", schema=CANONICAL)

    op.drop_index("ix_venue_brand_id", table_name="venue", schema=CANONICAL)
    op.drop_index("ix_venue_h3_r8", table_name="venue", schema=CANONICAL)
    op.drop_index("ix_venue_name_fingerprint", table_name="venue", schema=CANONICAL)
    op.drop_constraint("ck_venue_coords_both_or_neither", "venue", type_="check", schema=CANONICAL)
    op.drop_constraint("ck_venue_lng_range", "venue", type_="check", schema=CANONICAL)
    op.drop_constraint("ck_venue_lat_range", "venue", type_="check", schema=CANONICAL)
    op.drop_constraint("ck_venue_name_not_blank", "venue", type_="check", schema=CANONICAL)
    op.drop_constraint("ck_venue_status", "venue", type_="check", schema=CANONICAL)
    op.drop_constraint("fk_venue_brand_id", "venue", type_="foreignkey", schema=CANONICAL)

    for column in (
        "last_seen_at",
        "first_seen_at",
        "status",
        "h3_r9",
        "h3_r8",
        "h3_r6",
        "lng",
        "lat",
        "country",
        "postal_code",
        "region",
        "city",
        "street",
        "brand_id",
        "name_fingerprint",
    ):
        op.drop_column("venue", column, schema=CANONICAL)

    op.alter_column(
        "venue",
        "address_raw",
        new_column_name="address",
        type_=sa.String(length=500),
        existing_type=sa.Text(),
        existing_nullable=True,
        schema=CANONICAL,
    )
    op.execute(f"ALTER TABLE {CANONICAL}.venue SET SCHEMA public")

    op.drop_table("brand", schema=CANONICAL)

    op.execute("DROP SCHEMA IF EXISTS mart")
    op.execute("DROP SCHEMA IF EXISTS canonical")
    op.execute("DROP SCHEMA IF EXISTS raw")
