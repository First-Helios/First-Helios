"""Add section and item names to the Gold current-menu projection.

ADR-0006 Amendment 1 (ADR-0019 step 2). Two nullable columns on
``gold.current_menu``: ``section_name`` (the selected content name of the
innermost section on the row's target path) and ``item_name`` (the same for the
path's item). Both are filled by ``python -m apps.gold.refresh``. Adding a
nullable column with no default is catalog-only in PostgreSQL: no table rewrite,
no row touched; existing rows read null until the next refresh. Gold is a
rebuildable projection (ADR-0004 §1), so the downgrade drops both columns and
loses nothing a refresh cannot rebuild. No grain, constraint, index or FK change.

Revision ID: c95d883737db
Revises: 68146a4c5fc5
Create Date: 2026-10-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c95d883737db"
down_revision: str | Sequence[str] | None = "68146a4c5fc5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
ALTER TABLE gold.current_menu
    ADD COLUMN section_name VARCHAR(512),
    ADD COLUMN item_name VARCHAR(512)
""")


def downgrade() -> None:
    op.execute("""
ALTER TABLE gold.current_menu
    DROP COLUMN item_name,
    DROP COLUMN section_name
""")
