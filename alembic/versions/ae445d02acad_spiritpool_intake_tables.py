"""spiritpool_intake_tables

Revision ID: ae445d02acad
Revises: ed6b655457e5
Create Date: 2026-04-05 04:28:29.875444

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ae445d02acad'
down_revision: Union[str, Sequence[str], None] = 'ed6b655457e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema — additive only, no changes to existing tables."""
    # SpiritPool contributor pipeline tables (FH-0)
    op.create_table('contributors',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('uuid', sa.Text(), nullable=False),
    sa.Column('total_signals', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('uuid')
    )
    op.create_table('burn_pool',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('month_key', sa.String(), nullable=False),
    sa.Column('signal_count', sa.Integer(), nullable=False),
    sa.Column('burned_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('quarantine',
    sa.Column('quarantine_id', sa.String(), nullable=False),
    sa.Column('original_payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('redaction_types', sa.Text(), nullable=False),
    sa.Column('rule_version', sa.Integer(), nullable=False),
    sa.Column('quarantined_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('quarantine_id')
    )
    op.create_table('sp_events',
    sa.Column('event_id', sa.String(), nullable=False),
    sa.Column('session_token', sa.Text(), nullable=False),
    sa.Column('epoch_id', sa.Integer(), nullable=False),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('source_type', sa.String(), nullable=False),
    sa.Column('collected_at', sa.DateTime(), nullable=False),
    sa.Column('pipeline_version', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('event_id')
    )
    op.create_index('idx_sp_events_session_epoch', 'sp_events', ['session_token', 'epoch_id'], unique=False)
    op.create_index('idx_sp_events_type_collected', 'sp_events', ['event_type', 'collected_at'], unique=False)
    op.create_table('session_epochs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('session_token', sa.Text(), nullable=False),
    sa.Column('epoch_id', sa.Integer(), nullable=False),
    sa.Column('contributor_id', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('burned_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['contributor_id'], ['contributors.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('session_token')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('session_epochs')
    op.drop_index('idx_sp_events_type_collected', table_name='sp_events')
    op.drop_index('idx_sp_events_session_epoch', table_name='sp_events')
    op.drop_table('sp_events')
    op.drop_table('quarantine')
    op.drop_table('burn_pool')
    op.drop_table('contributors')
