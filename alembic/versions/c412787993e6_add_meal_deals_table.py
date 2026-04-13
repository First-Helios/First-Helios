"""add_meal_deals_table

Revision ID: c412787993e6
Revises: c1a4f7e39b02
Create Date: 2026-04-13 16:48:43.740566

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c412787993e6'
down_revision: Union[str, Sequence[str], None] = 'c1a4f7e39b02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('meal_deals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('local_employer_id', sa.Integer(), nullable=False),
    sa.Column('brand_group_id', sa.Integer(), nullable=True),
    sa.Column('deal_name', sa.String(), nullable=False),
    sa.Column('deal_description', sa.Text(), nullable=True),
    sa.Column('deal_type', sa.String(), nullable=False),
    sa.Column('price', sa.Float(), nullable=True),
    sa.Column('original_price', sa.Float(), nullable=True),
    sa.Column('valid_days', sa.String(), nullable=True),
    sa.Column('valid_start_time', sa.String(), nullable=True),
    sa.Column('valid_end_time', sa.String(), nullable=True),
    sa.Column('is_recurring', sa.Boolean(), nullable=True),
    sa.Column('start_date', sa.DateTime(), nullable=True),
    sa.Column('end_date', sa.DateTime(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('source_url', sa.String(), nullable=True),
    sa.Column('verified_at', sa.DateTime(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.Column('lat', sa.Float(), nullable=True),
    sa.Column('lng', sa.Float(), nullable=True),
    sa.Column('region', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['brand_group_id'], ['brand_groups.id'], ),
    sa.ForeignKeyConstraint(['local_employer_id'], ['local_employers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('local_employer_id', 'deal_name', 'source', name='uq_meal_deal_employer_name_source')
    )
    op.create_index('ix_meal_deals_brand_active', 'meal_deals', ['brand_group_id', 'is_active'], unique=False)
    op.create_index(op.f('ix_meal_deals_brand_group_id'), 'meal_deals', ['brand_group_id'], unique=False)
    op.create_index(op.f('ix_meal_deals_deal_type'), 'meal_deals', ['deal_type'], unique=False)
    op.create_index('ix_meal_deals_employer_active', 'meal_deals', ['local_employer_id', 'is_active'], unique=False)
    op.create_index(op.f('ix_meal_deals_is_active'), 'meal_deals', ['is_active'], unique=False)
    op.create_index(op.f('ix_meal_deals_local_employer_id'), 'meal_deals', ['local_employer_id'], unique=False)
    op.create_index(op.f('ix_meal_deals_region'), 'meal_deals', ['region'], unique=False)
    op.create_index('ix_meal_deals_region_active', 'meal_deals', ['region', 'is_active'], unique=False)
    op.create_index('ix_meal_deals_type_region', 'meal_deals', ['deal_type', 'region'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_meal_deals_type_region', table_name='meal_deals')
    op.drop_index('ix_meal_deals_region_active', table_name='meal_deals')
    op.drop_index(op.f('ix_meal_deals_region'), table_name='meal_deals')
    op.drop_index(op.f('ix_meal_deals_local_employer_id'), table_name='meal_deals')
    op.drop_index(op.f('ix_meal_deals_is_active'), table_name='meal_deals')
    op.drop_index('ix_meal_deals_employer_active', table_name='meal_deals')
    op.drop_index(op.f('ix_meal_deals_deal_type'), table_name='meal_deals')
    op.drop_index(op.f('ix_meal_deals_brand_group_id'), table_name='meal_deals')
    op.drop_index('ix_meal_deals_brand_active', table_name='meal_deals')
    op.drop_table('meal_deals')
