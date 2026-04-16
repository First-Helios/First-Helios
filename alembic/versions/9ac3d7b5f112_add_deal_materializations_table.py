"""add deal materializations table

Revision ID: 9ac3d7b5f112
Revises: e82fa4b1c3d9
Create Date: 2026-04-16 23:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9ac3d7b5f112"
down_revision: Union[str, Sequence[str], None] = "e82fa4b1c3d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(table_name: str) -> bool:
    return table_name in sa.inspect(op.get_bind()).get_table_names()


def _index_exists(table_name: str, index_name: str) -> bool:
    if not _table_exists(table_name):
        return False
    return any(index["name"] == index_name for index in sa.inspect(op.get_bind()).get_indexes(table_name))


def upgrade() -> None:
    if not _table_exists("deal_materializations"):
        op.create_table(
            "deal_materializations",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("observation_id", sa.Integer(), nullable=False),
            sa.Column("applicability_id", sa.Integer(), nullable=False),
            sa.Column("canonical_venue_id", sa.Integer(), nullable=False),
            sa.Column("local_employer_id", sa.Integer(), nullable=True),
            sa.Column("brand_group_id", sa.Integer(), nullable=True),
            sa.Column("restaurant_name", sa.String(), nullable=False),
            sa.Column("address", sa.String(), nullable=True),
            sa.Column("lat", sa.Float(), nullable=True),
            sa.Column("lng", sa.Float(), nullable=True),
            sa.Column("region", sa.String(), nullable=False),
            sa.Column("applicability_scope", sa.String(), nullable=False),
            sa.Column("is_chain_template", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("deal_name", sa.String(), nullable=False),
            sa.Column("deal_description", sa.Text(), nullable=True),
            sa.Column("deal_type", sa.String(), nullable=False),
            sa.Column("price", sa.Float(), nullable=True),
            sa.Column("price_type", sa.String(), nullable=True),
            sa.Column("discount_percentage", sa.Float(), nullable=True),
            sa.Column("original_price", sa.Float(), nullable=True),
            sa.Column("menu_avg_price", sa.Float(), nullable=True),
            sa.Column("calories", sa.Integer(), nullable=True),
            sa.Column("calorie_price_ratio", sa.Float(), nullable=True),
            sa.Column("valid_days", sa.String(), nullable=True),
            sa.Column("valid_start_time", sa.String(), nullable=True),
            sa.Column("valid_end_time", sa.String(), nullable=True),
            sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("start_date", sa.DateTime(), nullable=True),
            sa.Column("end_date", sa.DateTime(), nullable=True),
            sa.Column("source", sa.String(), nullable=False),
            sa.Column("source_url", sa.String(), nullable=True),
            sa.Column("source_observation_key", sa.String(), nullable=False),
            sa.Column("verified_at", sa.DateTime(), nullable=True),
            sa.Column("raw_scraped_text", sa.Text(), nullable=True),
            sa.Column("signal_quality", sa.Float(), nullable=True),
            sa.Column("deal_value_score", sa.Float(), nullable=True),
            sa.Column("sub_deals", sa.JSON(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("resolver_method", sa.String(), nullable=False),
            sa.Column("review_state", sa.String(), nullable=False, server_default="accepted"),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["observation_id"], ["deal_observations.id"]),
            sa.ForeignKeyConstraint(["applicability_id"], ["deal_applicability.id"]),
            sa.ForeignKeyConstraint(["canonical_venue_id"], ["canonical_venues.id"]),
            sa.ForeignKeyConstraint(["local_employer_id"], ["local_employers.id"]),
            sa.ForeignKeyConstraint(["brand_group_id"], ["brand_groups.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("observation_id", "canonical_venue_id", name="uq_deal_materialization_observation_venue"),
        )
    if not _index_exists("deal_materializations", "ix_deal_materializations_observation_id"):
        op.create_index("ix_deal_materializations_observation_id", "deal_materializations", ["observation_id"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_applicability_id"):
        op.create_index("ix_deal_materializations_applicability_id", "deal_materializations", ["applicability_id"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_canonical_venue_id"):
        op.create_index("ix_deal_materializations_canonical_venue_id", "deal_materializations", ["canonical_venue_id"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_local_employer_id"):
        op.create_index("ix_deal_materializations_local_employer_id", "deal_materializations", ["local_employer_id"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_brand_group_id"):
        op.create_index("ix_deal_materializations_brand_group_id", "deal_materializations", ["brand_group_id"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_region"):
        op.create_index("ix_deal_materializations_region", "deal_materializations", ["region"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_applicability_scope"):
        op.create_index("ix_deal_materializations_applicability_scope", "deal_materializations", ["applicability_scope"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_deal_type"):
        op.create_index("ix_deal_materializations_deal_type", "deal_materializations", ["deal_type"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_source"):
        op.create_index("ix_deal_materializations_source", "deal_materializations", ["source"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_source_observation_key"):
        op.create_index("ix_deal_materializations_source_observation_key", "deal_materializations", ["source_observation_key"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_verified_at"):
        op.create_index("ix_deal_materializations_verified_at", "deal_materializations", ["verified_at"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_review_state"):
        op.create_index("ix_deal_materializations_review_state", "deal_materializations", ["review_state"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_is_active"):
        op.create_index("ix_deal_materializations_is_active", "deal_materializations", ["is_active"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_region_active"):
        op.create_index("ix_deal_materializations_region_active", "deal_materializations", ["region", "is_active"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_brand_active"):
        op.create_index("ix_deal_materializations_brand_active", "deal_materializations", ["brand_group_id", "is_active"])
    if not _index_exists("deal_materializations", "ix_deal_materializations_type_region"):
        op.create_index("ix_deal_materializations_type_region", "deal_materializations", ["deal_type", "region"])


def downgrade() -> None:
    op.drop_index("ix_deal_materializations_type_region", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_brand_active", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_region_active", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_is_active", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_review_state", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_verified_at", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_source_observation_key", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_source", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_deal_type", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_applicability_scope", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_region", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_brand_group_id", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_local_employer_id", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_canonical_venue_id", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_applicability_id", table_name="deal_materializations")
    op.drop_index("ix_deal_materializations_observation_id", table_name="deal_materializations")
    op.drop_table("deal_materializations")