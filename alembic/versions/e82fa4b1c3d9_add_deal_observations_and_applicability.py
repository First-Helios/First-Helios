"""add deal observations and applicability

Revision ID: e82fa4b1c3d9
Revises: d4c7e2a91f31
Create Date: 2026-04-16 23:05:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e82fa4b1c3d9"
down_revision: Union[str, Sequence[str], None] = "d4c7e2a91f31"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deal_observations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), nullable=True),
        sa.Column("site_identity_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("source_observation_key", sa.String(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
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
        sa.Column("raw_scraped_text", sa.Text(), nullable=True),
        sa.Column("extraction_payload", sa.JSON(), nullable=True),
        sa.Column("signal_quality", sa.Float(), nullable=True),
        sa.Column("deal_value_score", sa.Float(), nullable=True),
        sa.Column("review_state", sa.String(), nullable=False, server_default="accepted"),
        sa.Column("superseded_by_observation_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["site_identity_id"], ["site_identities.id"]),
        sa.ForeignKeyConstraint(["superseded_by_observation_id"], ["deal_observations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "source_observation_key", name="uq_deal_observation_source_key"),
    )
    op.create_index("ix_deal_observations_source", "deal_observations", ["source"])
    op.create_index("ix_deal_observations_collector_run_id", "deal_observations", ["collector_run_id"])
    op.create_index("ix_deal_observations_site_identity_id", "deal_observations", ["site_identity_id"])
    op.create_index("ix_deal_observations_observed_at", "deal_observations", ["observed_at"])
    op.create_index("ix_deal_observations_deal_type", "deal_observations", ["deal_type"])
    op.create_index("ix_deal_observations_review_state", "deal_observations", ["review_state"])
    op.create_index("ix_deal_observations_run_source", "deal_observations", ["collector_run_id", "source"])

    op.create_table(
        "deal_applicability",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("observation_id", sa.Integer(), nullable=False),
        sa.Column("applicability_scope", sa.String(), nullable=False),
        sa.Column("canonical_venue_id", sa.Integer(), nullable=True),
        sa.Column("brand_group_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("resolver_method", sa.String(), nullable=False),
        sa.Column("resolver_notes", sa.Text(), nullable=True),
        sa.Column("valid_from", sa.DateTime(), nullable=True),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["observation_id"], ["deal_observations.id"]),
        sa.ForeignKeyConstraint(["canonical_venue_id"], ["canonical_venues.id"]),
        sa.ForeignKeyConstraint(["brand_group_id"], ["brand_groups.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deal_applicability_observation_id", "deal_applicability", ["observation_id"])
    op.create_index("ix_deal_applicability_scope", "deal_applicability", ["applicability_scope"])
    op.create_index("ix_deal_applicability_canonical_venue_id", "deal_applicability", ["canonical_venue_id"])
    op.create_index("ix_deal_applicability_brand_group_id", "deal_applicability", ["brand_group_id"])
    op.create_index("ix_deal_applicability_is_active", "deal_applicability", ["is_active"])
    op.create_index("ix_deal_applicability_observation_active", "deal_applicability", ["observation_id", "is_active"])


def downgrade() -> None:
    op.drop_index("ix_deal_applicability_observation_active", table_name="deal_applicability")
    op.drop_index("ix_deal_applicability_is_active", table_name="deal_applicability")
    op.drop_index("ix_deal_applicability_brand_group_id", table_name="deal_applicability")
    op.drop_index("ix_deal_applicability_canonical_venue_id", table_name="deal_applicability")
    op.drop_index("ix_deal_applicability_scope", table_name="deal_applicability")
    op.drop_index("ix_deal_applicability_observation_id", table_name="deal_applicability")
    op.drop_table("deal_applicability")

    op.drop_index("ix_deal_observations_run_source", table_name="deal_observations")
    op.drop_index("ix_deal_observations_review_state", table_name="deal_observations")
    op.drop_index("ix_deal_observations_deal_type", table_name="deal_observations")
    op.drop_index("ix_deal_observations_observed_at", table_name="deal_observations")
    op.drop_index("ix_deal_observations_site_identity_id", table_name="deal_observations")
    op.drop_index("ix_deal_observations_collector_run_id", table_name="deal_observations")
    op.drop_index("ix_deal_observations_source", table_name="deal_observations")
    op.drop_table("deal_observations")