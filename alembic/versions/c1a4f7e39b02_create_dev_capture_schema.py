"""create dev_capture schema

Revision ID: c1a4f7e39b02
Revises: ae445d02acad
Create Date: 2026-04-06

Adds the dev_capture PostgreSQL schema and raw_signals table for
dev-mode A/B comparison of raw DOM extraction vs Helios privacy output.
Completely separated from production tables in the public schema.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c1a4f7e39b02'
down_revision: Union[str, Sequence[str], None] = 'ae445d02acad'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create dev_capture schema and raw_signals table."""
    # Create the schema (PostgreSQL only — no-op on SQLite)
    op.execute('CREATE SCHEMA IF NOT EXISTS dev_capture')

    op.create_table('raw_signals',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('domain', sa.String(), nullable=False),
        sa.Column('session_token', sa.Text(), nullable=False),
        sa.Column('captured_at', sa.DateTime(), nullable=False),
        sa.Column('raw_html', sa.Text(), nullable=True),
        sa.Column('extracted_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('sanitized_fields', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('extraction_source', sa.String(), nullable=True),
        sa.Column('pipeline_version', sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        schema='dev_capture',
    )


def downgrade() -> None:
    """Drop dev_capture schema and all its tables."""
    op.drop_table('raw_signals', schema='dev_capture')
    op.execute('DROP SCHEMA IF EXISTS dev_capture')
