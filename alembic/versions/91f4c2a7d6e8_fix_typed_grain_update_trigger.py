"""fix typed-grain update trigger dispatch

The original shared trigger referenced Establishment-only fields while
processing Place and Organization rows. PostgreSQL resolves those record
fields before the combined boolean condition can short-circuit, so otherwise
valid typed-feature updates failed with ``undefined_column``.

Revision ID: 91f4c2a7d6e8
Revises: 32700b86d018
Create Date: 2026-09-16

"""

from collections.abc import Sequence

from alembic import op

revision: str = "91f4c2a7d6e8"
down_revision: str | Sequence[str] | None = "32700b86d018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

IDENTITY = "identity"


def _install_safe_function() -> None:
    establishment_guard = """
            IF TG_TABLE_NAME = 'establishment' THEN
                IF NEW.organization_subject_id IS DISTINCT FROM
                       OLD.organization_subject_id
                   OR NEW.organization_subject_kind IS DISTINCT FROM
                       OLD.organization_subject_kind
                   OR NEW.place_subject_id IS DISTINCT FROM OLD.place_subject_id
                   OR NEW.place_subject_kind IS DISTINCT FROM OLD.place_subject_kind
                THEN
                    RAISE EXCEPTION
                        'an Establishment organization and Place are immutable'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
        """
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IDENTITY}.protect_typed_grain_key()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'Subject typed grains cannot be truncated'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'a Subject typed grain cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.subject_id IS DISTINCT FROM OLD.subject_id
               OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind THEN
                RAISE EXCEPTION 'typed-grain Subject identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            {establishment_guard}
            RETURN NEW;
        END;
        $$
        """
    )


def upgrade() -> None:
    """Dispatch Establishment-only field checks inside a table-specific branch."""
    _install_safe_function()


def downgrade() -> None:
    """Restore the original trigger function exactly."""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {IDENTITY}.protect_typed_grain_key()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF TG_OP = 'TRUNCATE' THEN
                RAISE EXCEPTION 'Subject typed grains cannot be truncated'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'a Subject typed grain cannot be deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.subject_id IS DISTINCT FROM OLD.subject_id
               OR NEW.subject_kind IS DISTINCT FROM OLD.subject_kind THEN
                RAISE EXCEPTION 'typed-grain Subject identity is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF TG_TABLE_NAME = 'establishment'
               AND (
                    NEW.organization_subject_id IS DISTINCT FROM
                        OLD.organization_subject_id
                    OR NEW.organization_subject_kind IS DISTINCT FROM
                        OLD.organization_subject_kind
                    OR NEW.place_subject_id IS DISTINCT FROM OLD.place_subject_id
                    OR NEW.place_subject_kind IS DISTINCT FROM OLD.place_subject_kind
               ) THEN
                RAISE EXCEPTION
                    'an Establishment organization and Place are immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
