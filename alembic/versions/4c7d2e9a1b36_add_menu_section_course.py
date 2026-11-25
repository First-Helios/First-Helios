"""Add the Silver course-label table menu.section_course (ADR-0016 §3, Amendment 3 item 4).

One insert-only row per (section, labeller version): the course a pinned
labeller gave a Gold-reaching section, or NULL when it abstained. A new table:
no existing table or column changes. The structural ``Unsectioned`` grouping
never gets a row (it never reaches Gold).

Revision ID: 4c7d2e9a1b36
Revises: 73b0e3dba421
"""

from collections.abc import Sequence

from alembic import op

revision: str = "4c7d2e9a1b36"
down_revision: str | Sequence[str] | None = "73b0e3dba421"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COURSES = (
    "'appetizer', 'entree', 'side', 'dessert', 'drink', 'alcohol', 'breakfast', 'kids', 'other'"
)


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE menu.section_course (
            id BIGSERIAL NOT NULL,
            section_id BIGINT NOT NULL,
            labeller_version VARCHAR(128) NOT NULL,
            course VARCHAR(16),
            confidence NUMERIC(5, 4),
            labelled_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id),
            CONSTRAINT uq_section_course UNIQUE (section_id, labeller_version),
            CONSTRAINT fk_section_course_section FOREIGN KEY (section_id)
                REFERENCES menu.menu_section (id) ON DELETE RESTRICT ON UPDATE NO ACTION,
            CONSTRAINT ck_section_course_labeller CHECK (
                length(labeller_version) BETWEEN 1 AND 128
                AND labeller_version = btrim(labeller_version, menu.whitespace())),
            CONSTRAINT ck_section_course_course CHECK (course IS NULL OR course IN ({_COURSES})),
            CONSTRAINT ck_section_course_confidence CHECK
                (confidence IS NULL OR confidence BETWEEN 0 AND 1),
            CONSTRAINT ck_section_course_time CHECK (isfinite(labelled_at))
        )
    """)
    op.execute(
        "CREATE INDEX ix_section_course_version ON menu.section_course "
        "(labeller_version, section_id)"
    )
    op.execute("""
CREATE FUNCTION menu.check_section_course()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM menu.menu_section s
               WHERE s.id = NEW.section_id AND s.support_kind = 'structural') THEN
        RAISE EXCEPTION 'the structural Unsectioned grouping takes no course label'
            USING ERRCODE = '23514', CONSTRAINT = 'ck_section_course_section';
    END IF;
    RETURN NEW;
END
$$
    """)
    op.execute(
        "CREATE TRIGGER trg_section_course_section BEFORE INSERT ON menu.section_course "
        "FOR EACH ROW EXECUTE FUNCTION menu.check_section_course()"
    )
    op.execute(
        "CREATE TRIGGER trg_menu_immutable BEFORE UPDATE OR DELETE ON menu.section_course "
        "FOR EACH ROW EXECUTE FUNCTION menu.reject_mutation()"
    )
    op.execute(
        "CREATE TRIGGER trg_menu_no_truncate BEFORE TRUNCATE ON menu.section_course "
        "FOR EACH STATEMENT EXECUTE FUNCTION menu.reject_mutation()"
    )


def downgrade() -> None:
    op.execute("DROP TABLE menu.section_course")
    op.execute("DROP FUNCTION menu.check_section_course()")
