"""Add sub_deals JSONB column and formalize is_chain_template on meal_deals

Phase 4 of the meal deal signal quality overhaul.

- sub_deals (JSONB): structured decomposition of multi-promo deals, e.g.
    [{"item": "appetizers", "discount_type": "percentage_off", "discount_value": 50},
     {"item": "cocktails", "discount_type": "discount_amount", "discount_value": 1.00}]
  Populated by scripts/one_shot/populate_sub_deals.py and by the ingest pipeline when
  a text block contains multiple offers.

- is_chain_template (Boolean): column was introduced during Phase 3 dedupe
  (scripts/one_shot/dedupe_chain_deals.py) but never got its own migration.
  ADD IF NOT EXISTS so this migration is idempotent against DBs where the
  column already exists.

Revision ID: a8c3e9d1f720
Revises: f7a1b2c3d4e5
Create Date: 2026-04-16 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a8c3e9d1f720"
down_revision = "f7a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_chain_template: add only if not present (Phase 3 introduced it manually).
    op.execute(
        "ALTER TABLE meal_deals "
        "ADD COLUMN IF NOT EXISTS is_chain_template BOOLEAN NOT NULL DEFAULT FALSE"
    )

    # sub_deals JSONB — structured multi-promo decomposition.
    op.add_column(
        "meal_deals",
        sa.Column("sub_deals", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Partial unique index for chain-template upserts:
    # (brand_group_id, deal_name, source) WHERE is_chain_template = TRUE.
    # Already in place on current DBs — guard with IF NOT EXISTS.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS "
        "uq_meal_deal_chain_template "
        "ON meal_deals (brand_group_id, deal_name, source) "
        "WHERE is_chain_template = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_meal_deal_chain_template")
    op.drop_column("meal_deals", "sub_deals")
    op.drop_column("meal_deals", "is_chain_template")
