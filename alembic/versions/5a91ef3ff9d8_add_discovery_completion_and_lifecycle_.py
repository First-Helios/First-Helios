"""add discovery completion and lifecycle checkpoints

Revision ID: 5a91ef3ff9d8
Revises: c91a6f02de73
Create Date: 2026-09-28 17:28:58.228407

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '5a91ef3ff9d8'
down_revision: Union[str, Sequence[str], None] = 'c91a6f02de73'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('discovery_release_completion',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('release_endpoint', sa.Text(), nullable=False),
    sa.Column('release_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('coverage_key', sa.Text(), nullable=False),
    sa.Column('coverage', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('poi_count', sa.BigInteger(), nullable=False),
    sa.Column('predecessor', sa.Text(), nullable=True),
    sa.Column('completed_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.CheckConstraint('isfinite(release_at)', name='ck_discovery_completion_time'),
    sa.CheckConstraint('poi_count >= 0', name='ck_discovery_completion_count'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('release_endpoint', 'coverage_key', 'release_at', 'poi_count', 'predecessor', name='uq_discovery_completion_retry', postgresql_nulls_not_distinct=True),
    schema='bronze'
    )
    op.create_index('ix_discovery_completion_coverage_release', 'discovery_release_completion', ['coverage_key', 'release_at'], unique=False, schema='bronze')
    op.create_table('discovery_lifecycle_state',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('source_record_id', sa.BigInteger(), nullable=True),
    sa.Column('version_id', sa.BigInteger(), nullable=True),
    sa.Column('subject_id', sa.BigInteger(), nullable=False),
    sa.Column('release_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('action', sa.Text(), nullable=False),
    sa.Column('first_missing_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('recorded_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.CheckConstraint("(action = 'closed') = (first_missing_at IS NOT NULL)", name='ck_discovery_lifecycle_closure'),
    sa.CheckConstraint("action IN ('projected', 'closed', 'reopened')", name='ck_discovery_lifecycle_action'),
    sa.CheckConstraint('isfinite(release_at)', name='ck_discovery_lifecycle_time'),
    sa.ForeignKeyConstraint(['source_record_id'], ['bronze.source_record.id'], ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['version_id'], ['bronze.source_record_version.id'], ondelete='RESTRICT'),
    sa.PrimaryKeyConstraint('id'),
    schema='bronze'
    )
    op.create_index('ix_discovery_lifecycle_record', 'discovery_lifecycle_state', ['source_record_id', 'release_at'], unique=False, schema='bronze')
    op.create_index('ix_discovery_lifecycle_subject', 'discovery_lifecycle_state', ['subject_id', 'id'], unique=False, schema='bronze')

    # Reuse Bronze's immutable-row guard; also forbid TRUNCATE, which bypasses it.
    op.execute("""
        CREATE FUNCTION bronze.reject_discovery_truncate() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
          RAISE EXCEPTION 'discovery evidence cannot be truncated' USING ERRCODE = '55000';
        END $$
    """)
    for table in ("discovery_release_completion", "discovery_lifecycle_state"):
        op.execute(f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE OR DELETE ON bronze.{table} FOR EACH ROW EXECUTE FUNCTION bronze.reject_provenance_mutation()")
        op.execute(f"CREATE TRIGGER trg_{table}_truncate BEFORE TRUNCATE ON bronze.{table} FOR EACH STATEMENT EXECUTE FUNCTION bronze.reject_discovery_truncate()")


def downgrade() -> None:
    """Only empty discovery state can be downgraded without losing history."""
    op.execute("""DO $$ BEGIN
      IF EXISTS (SELECT 1 FROM bronze.discovery_release_completion)
         OR EXISTS (SELECT 1 FROM bronze.discovery_lifecycle_state) THEN
        RAISE EXCEPTION 'ADR-0012: populated lifecycle history cannot be downgraded';
      END IF;
    END $$""")
    op.drop_index('ix_discovery_lifecycle_subject', table_name='discovery_lifecycle_state', schema='bronze')
    op.drop_index('ix_discovery_lifecycle_record', table_name='discovery_lifecycle_state', schema='bronze')
    op.drop_table('discovery_lifecycle_state', schema='bronze')
    op.drop_index('ix_discovery_completion_coverage_release', table_name='discovery_release_completion', schema='bronze')
    op.drop_table('discovery_release_completion', schema='bronze')
    op.execute("DROP FUNCTION bronze.reject_discovery_truncate()")
