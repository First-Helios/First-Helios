"""add_google_places_failures_table

Revision ID: e3f1a9b2c0d5
Revises: 4a0aa473b6eb
Create Date: 2026-04-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e3f1a9b2c0d5'
down_revision: Union[str, Sequence[str], None] = '4a0aa473b6eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create google_places_failures table to track unresolvable brands/employers."""
    op.create_table(
        'google_places_failures',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('entity_type', sa.String(length=20), nullable=False),
        sa.Column('entity_id', sa.Integer(), nullable=False),
        sa.Column('canonical_name', sa.String(length=255), nullable=True),
        sa.Column('failure_reason', sa.String(length=20), nullable=True),
        sa.Column('failed_at', sa.DateTime(), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('entity_type', 'entity_id', name='uq_gp_failure_entity'),
    )
    op.create_index('ix_gp_failures_entity_type', 'google_places_failures', ['entity_type'])


def downgrade() -> None:
    op.drop_index('ix_gp_failures_entity_type', table_name='google_places_failures')
    op.drop_table('google_places_failures')
