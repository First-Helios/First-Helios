"""meal_deal: add deal_value_score column

Revision ID: b3d2e1f0a9c8
Revises: a8c3e9d1f720
Create Date: 2026-04-16

Adds deal_value_score FLOAT (0.0–1.0) representing offer strength,
separate from signal_quality (which measures data completeness).

  signal_quality  — how complete/clean the data record is
  deal_value_score — how good the actual discount/offer is for the consumer

Indexed to support ORDER BY deal_value_score DESC in feed queries.
"""

from alembic import op
import sqlalchemy as sa

revision = "b3d2e1f0a9c8"
down_revision = "a8c3e9d1f720"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "meal_deals",
        sa.Column("deal_value_score", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_meal_deals_value_score",
        "meal_deals",
        ["deal_value_score"],
    )


def downgrade() -> None:
    op.drop_index("ix_meal_deals_value_score", table_name="meal_deals")
    op.drop_column("meal_deals", "deal_value_score")
