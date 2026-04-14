"""add_nutrition_pricing_and_permanent_url_fields

Revision ID: 4a0aa473b6eb
Revises: c8edac5d7232
Create Date: 2026-04-13 22:49:53.748394

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '4a0aa473b6eb'
down_revision: Union[str, Sequence[str], None] = 'c8edac5d7232'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add nutrition/pricing columns to meal_deals and is_permanent to restaurant_urls."""
    op.add_column('meal_deals', sa.Column('menu_avg_price', sa.Float(), nullable=True))
    op.add_column('meal_deals', sa.Column('calories', sa.Integer(), nullable=True))
    op.add_column('meal_deals', sa.Column('calorie_price_ratio', sa.Float(), nullable=True))
    op.add_column('restaurant_urls', sa.Column('is_permanent', sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Remove nutrition/pricing columns and is_permanent."""
    op.drop_column('restaurant_urls', 'is_permanent')
    op.drop_column('meal_deals', 'calorie_price_ratio')
    op.drop_column('meal_deals', 'calories')
    op.drop_column('meal_deals', 'menu_avg_price')
