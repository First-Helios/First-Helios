"""Add course labels to gold.current_menu and the course category (ADR-0016 §6, Amendment 3 item 5).

Two additive nullable columns on ``gold.current_menu``:

* ``course_labeller``: the pinned labeller version, on every row whose section
  has a ``menu.section_course`` row at that version (abstentions included);
* ``course``: that row's label, NULL when the labeller abstained.

``category_kind`` of ``gold.price_index`` widens from ``('all')`` to
``('all', 'course')``. Gold is rebuilt by its refresh: existing rows simply get
NULL until the next refresh, and nothing with data is altered in place.

Revision ID: 9b1e5d3c7a20
Revises: 4c7d2e9a1b36
"""

from collections.abc import Sequence

from alembic import op

revision: str = "9b1e5d3c7a20"
down_revision: str | Sequence[str] | None = "4c7d2e9a1b36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COURSES = (
    "'appetizer', 'entree', 'side', 'dessert', 'drink', 'alcohol', 'breakfast', 'kids', 'other'"
)


def upgrade() -> None:
    op.execute(f"""
        ALTER TABLE gold.current_menu
            ADD COLUMN course VARCHAR(16),
            ADD COLUMN course_labeller VARCHAR(128),
            ADD CONSTRAINT ck_gold_course CHECK (course IS NULL OR course IN ({_COURSES})),
            ADD CONSTRAINT ck_gold_course_labeller CHECK (
                (course IS NULL OR course_labeller IS NOT NULL)
                AND (course_labeller IS NULL OR length(btrim(course_labeller)) > 0))
    """)
    op.execute("""
        ALTER TABLE gold.price_index
            DROP CONSTRAINT ck_gold_price_index_category_kind,
            ADD CONSTRAINT ck_gold_price_index_category_kind
                CHECK (category_kind IN ('all', 'course'))
    """)


def downgrade() -> None:
    op.execute("DELETE FROM gold.price_index WHERE category_kind = 'course'")
    op.execute("""
        ALTER TABLE gold.price_index
            DROP CONSTRAINT ck_gold_price_index_category_kind,
            ADD CONSTRAINT ck_gold_price_index_category_kind CHECK (category_kind IN ('all'))
    """)
    op.execute("""
        ALTER TABLE gold.current_menu
            DROP CONSTRAINT ck_gold_course_labeller,
            DROP CONSTRAINT ck_gold_course,
            DROP COLUMN course_labeller,
            DROP COLUMN course
    """)
