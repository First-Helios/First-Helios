"""Add signal quality columns to meal_deals: price_type, discount_percentage, raw_scraped_text, signal_quality

Revision ID: f7a1b2c3d4e5
Revises: e3f1a9b2c0d5
Create Date: 2026-04-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f7a1b2c3d4e5"
down_revision = "e3f1a9b2c0d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # price_type: distinguishes absolute price vs discount amount vs percentage off
    op.add_column(
        "meal_deals",
        sa.Column(
            "price_type",
            sa.String(),
            nullable=True,
            comment="absolute | discount_amount | percentage_off | unknown",
        ),
    )

    # discount_percentage: numeric representation for "half off" (50.0), "20% off" (20.0)
    op.add_column(
        "meal_deals",
        sa.Column("discount_percentage", sa.Float(), nullable=True),
    )

    # raw_scraped_text: original text block before parsing, for reprocessing
    op.add_column(
        "meal_deals",
        sa.Column("raw_scraped_text", sa.Text(), nullable=True),
    )

    # signal_quality: 0.0–1.0 composite score computed at ingest
    op.add_column(
        "meal_deals",
        sa.Column("signal_quality", sa.Float(), nullable=True),
    )

    # Backfill existing rows: set price_type='unknown' where price exists
    op.execute(
        "UPDATE meal_deals SET price_type = 'unknown' WHERE price IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("meal_deals", "signal_quality")
    op.drop_column("meal_deals", "raw_scraped_text")
    op.drop_column("meal_deals", "discount_percentage")
    op.drop_column("meal_deals", "price_type")
