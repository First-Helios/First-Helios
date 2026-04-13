"""add_restaurant_urls_table

Revision ID: c8edac5d7232
Revises: c412787993e6
Create Date: 2026-04-13 17:08:39.214831

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c8edac5d7232'
down_revision: Union[str, Sequence[str], None] = 'c412787993e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('restaurant_urls',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('local_employer_id', sa.Integer(), nullable=False),
    sa.Column('brand_group_id', sa.Integer(), nullable=True),
    sa.Column('url', sa.String(), nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('confidence', sa.Float(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=True),
    sa.Column('last_checked', sa.DateTime(), nullable=True),
    sa.Column('last_http_status', sa.Integer(), nullable=True),
    sa.Column('has_deals_page', sa.Boolean(), nullable=True),
    sa.Column('deals_page_url', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=True),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['brand_group_id'], ['brand_groups.id'], ),
    sa.ForeignKeyConstraint(['local_employer_id'], ['local_employers.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('local_employer_id', 'source', name='uq_restaurant_url_employer_source')
    )
    op.create_index(op.f('ix_restaurant_urls_brand_group_id'), 'restaurant_urls', ['brand_group_id'], unique=False)
    op.create_index(op.f('ix_restaurant_urls_local_employer_id'), 'restaurant_urls', ['local_employer_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_restaurant_urls_local_employer_id'), table_name='restaurant_urls')
    op.drop_index(op.f('ix_restaurant_urls_brand_group_id'), table_name='restaurant_urls')
    op.drop_table('restaurant_urls')
