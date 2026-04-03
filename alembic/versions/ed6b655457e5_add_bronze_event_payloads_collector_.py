"""add bronze_event_payloads collector_health_baselines and events_collector_run_id

Revision ID: ed6b655457e5
Revises: 28fbdf2816df
Create Date: 2026-04-03 15:52:13.278101

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ed6b655457e5'
down_revision: Union[str, Sequence[str], None] = '28fbdf2816df'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # bronze_event_payloads — raw API payloads for re-processing
    op.create_table('bronze_event_payloads',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('external_id', sa.String(), nullable=False),
    sa.Column('collector_run_id', sa.Integer(), nullable=True),
    sa.Column('raw_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('scraped_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_bronze_event_payloads_collector_run_id'), 'bronze_event_payloads', ['collector_run_id'], unique=False)
    op.create_index(op.f('ix_bronze_event_payloads_scraped_at'), 'bronze_event_payloads', ['scraped_at'], unique=False)
    op.create_index(op.f('ix_bronze_event_payloads_source'), 'bronze_event_payloads', ['source'], unique=False)
    op.create_index('ix_bronze_source_external', 'bronze_event_payloads', ['source', 'external_id'], unique=False)

    # collector_health_baselines — expected ranges per collector
    op.create_table('collector_health_baselines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('min_expected', sa.Integer(), nullable=False),
    sa.Column('max_expected', sa.Integer(), nullable=False),
    sa.Column('alert_on_zero', sa.Boolean(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source')
    )

    # events.collector_run_id — data lineage
    op.add_column('events', sa.Column('collector_run_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_events_collector_run_id'), 'events', ['collector_run_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_events_collector_run_id'), table_name='events')
    op.drop_column('events', 'collector_run_id')
    op.drop_table('collector_health_baselines')
    op.drop_index('ix_bronze_source_external', table_name='bronze_event_payloads')
    op.drop_index(op.f('ix_bronze_event_payloads_source'), table_name='bronze_event_payloads')
    op.drop_index(op.f('ix_bronze_event_payloads_scraped_at'), table_name='bronze_event_payloads')
    op.drop_index(op.f('ix_bronze_event_payloads_collector_run_id'), table_name='bronze_event_payloads')
    op.drop_table('bronze_event_payloads')
