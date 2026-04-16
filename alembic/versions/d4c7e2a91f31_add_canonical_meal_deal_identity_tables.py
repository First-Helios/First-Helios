"""add canonical meal deal identity tables

Revision ID: d4c7e2a91f31
Revises: a8c3e9d1f720
Create Date: 2026-04-16 22:15:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d4c7e2a91f31"
down_revision: Union[str, Sequence[str], None] = "a8c3e9d1f720"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_venues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("normalized_address", sa.String(), nullable=True),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("region", sa.String(), nullable=False),
        sa.Column("brand_group_id", sa.Integer(), nullable=True),
        sa.Column("site_status", sa.String(), nullable=False, server_default="no_site"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["brand_group_id"], ["brand_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_canonical_venues_normalized_name", "canonical_venues", ["normalized_name"])
    op.create_index("ix_canonical_venues_normalized_address", "canonical_venues", ["normalized_address"])
    op.create_index("ix_canonical_venues_region", "canonical_venues", ["region"])
    op.create_index("ix_canonical_venues_brand_group_id", "canonical_venues", ["brand_group_id"])
    op.create_index("ix_canonical_venues_region_name", "canonical_venues", ["region", "normalized_name"])

    op.create_table(
        "canonical_venue_aliases",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("canonical_venue_id", sa.Integer(), nullable=False),
        sa.Column("local_employer_id", sa.Integer(), nullable=False),
        sa.Column("alias_role", sa.String(), nullable=False, server_default="alias"),
        sa.Column("match_method", sa.String(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["canonical_venue_id"], ["canonical_venues.id"]),
        sa.ForeignKeyConstraint(["local_employer_id"], ["local_employers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("local_employer_id", name="uq_canonical_venue_alias_local_employer"),
    )
    op.create_index("ix_canonical_venue_aliases_canonical_venue_id", "canonical_venue_aliases", ["canonical_venue_id"])
    op.create_index("ix_canonical_venue_aliases_local_employer_id", "canonical_venue_aliases", ["local_employer_id"])

    op.create_table(
        "site_identities",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("normalized_url", sa.String(), nullable=False),
        sa.Column("canonical_url", sa.String(), nullable=False),
        sa.Column("host", sa.String(), nullable=False),
        sa.Column("path", sa.String(), nullable=True),
        sa.Column("ownership_scope", sa.String(), nullable=False, server_default="unknown"),
        sa.Column("conflict_state", sa.String(), nullable=False, server_default="needs_review"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_url"),
    )
    op.create_index("ix_site_identities_normalized_url", "site_identities", ["normalized_url"])
    op.create_index("ix_site_identities_host", "site_identities", ["host"])

    op.create_table(
        "site_assignments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("site_identity_id", sa.Integer(), nullable=False),
        sa.Column("canonical_venue_id", sa.Integer(), nullable=True),
        sa.Column("brand_group_id", sa.Integer(), nullable=True),
        sa.Column("assignment_scope", sa.String(), nullable=False),
        sa.Column("match_method", sa.String(), nullable=False),
        sa.Column("match_confidence", sa.Float(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["site_identity_id"], ["site_identities.id"]),
        sa.ForeignKeyConstraint(["canonical_venue_id"], ["canonical_venues.id"]),
        sa.ForeignKeyConstraint(["brand_group_id"], ["brand_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_site_assignments_site_identity_id", "site_assignments", ["site_identity_id"])
    op.create_index("ix_site_assignments_canonical_venue_id", "site_assignments", ["canonical_venue_id"])
    op.create_index("ix_site_assignments_brand_group_id", "site_assignments", ["brand_group_id"])


def downgrade() -> None:
    op.drop_index("ix_site_assignments_brand_group_id", table_name="site_assignments")
    op.drop_index("ix_site_assignments_canonical_venue_id", table_name="site_assignments")
    op.drop_index("ix_site_assignments_site_identity_id", table_name="site_assignments")
    op.drop_table("site_assignments")

    op.drop_index("ix_site_identities_host", table_name="site_identities")
    op.drop_index("ix_site_identities_normalized_url", table_name="site_identities")
    op.drop_table("site_identities")

    op.drop_index("ix_canonical_venue_aliases_local_employer_id", table_name="canonical_venue_aliases")
    op.drop_index("ix_canonical_venue_aliases_canonical_venue_id", table_name="canonical_venue_aliases")
    op.drop_table("canonical_venue_aliases")

    op.drop_index("ix_canonical_venues_region_name", table_name="canonical_venues")
    op.drop_index("ix_canonical_venues_brand_group_id", table_name="canonical_venues")
    op.drop_index("ix_canonical_venues_region", table_name="canonical_venues")
    op.drop_index("ix_canonical_venues_normalized_address", table_name="canonical_venues")
    op.drop_index("ix_canonical_venues_normalized_name", table_name="canonical_venues")
    op.drop_table("canonical_venues")