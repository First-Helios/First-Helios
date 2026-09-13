"""add Bronze provenance foundation

Creates ADR-0004's durable shared-provenance schema without changing the
legacy raw/canonical/mart scaffold. Source-local records need no Identity row,
and database triggers reject destructive provenance rewrites.

Revision ID: 6344725640bd
Revises: a466cf4bc4e0
Create Date: 2026-09-12 19:55:50.297787

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6344725640bd"
down_revision: str | Sequence[str] | None = "a466cf4bc4e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BRONZE = "bronze"


def _install_immutability_trigger(table: str, *identity_columns: str) -> None:
    arguments = ", ".join(f"'{column}'" for column in identity_columns)
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_provenance_immutable
        BEFORE UPDATE OR DELETE ON {BRONZE}.{table}
        FOR EACH ROW
        EXECUTE FUNCTION {BRONZE}.reject_provenance_mutation({arguments})
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {BRONZE}")

    op.create_table(
        "source",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("namespace", sa.String(length=128), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("namespace", name="uq_source_namespace"),
        sa.CheckConstraint(
            "namespace = btrim(namespace) AND length(namespace) > 0",
            name="ck_source_namespace_canonical",
        ),
        schema=BRONZE,
    )

    op.create_table(
        "source_endpoint",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_uri", sa.Text(), nullable=False),
        sa.Column("endpoint_kind", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{BRONZE}.source.id"],
            name="fk_source_endpoint_source_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("canonical_uri", name="uq_source_endpoint_canonical_uri"),
        sa.UniqueConstraint("id", "source_id", name="uq_source_endpoint_id_source"),
        sa.CheckConstraint(
            "canonical_uri = btrim(canonical_uri) AND length(canonical_uri) > 0",
            name="ck_source_endpoint_uri_canonical",
        ),
        schema=BRONZE,
    )
    op.create_index(
        "ix_source_endpoint_source_id",
        "source_endpoint",
        ["source_id"],
        schema=BRONZE,
    )

    op.create_table(
        "source_record",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("external_key", sa.String(length=512), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{BRONZE}.source.id"],
            name="fk_source_record_source_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "external_key",
            name="uq_source_record_source_external_key",
        ),
        sa.UniqueConstraint("id", "source_id", name="uq_source_record_id_source"),
        sa.CheckConstraint(
            "external_key = btrim(external_key) AND length(external_key) > 0",
            name="ck_source_record_external_key_canonical",
        ),
        schema=BRONZE,
    )

    op.create_table(
        "capture",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("source_endpoint_id", sa.BigInteger(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("bundle_path", sa.Text(), nullable=True),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            [f"{BRONZE}.source.id"],
            name="fk_capture_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_endpoint_id", "source_id"],
            [
                f"{BRONZE}.source_endpoint.id",
                f"{BRONZE}.source_endpoint.source_id",
            ],
            name="fk_capture_endpoint_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "content_hash IS NULL OR length(btrim(content_hash)) > 0",
            name="ck_capture_content_hash_not_blank",
        ),
        sa.CheckConstraint(
            "bundle_path IS NULL OR length(btrim(bundle_path)) > 0",
            name="ck_capture_bundle_path_not_blank",
        ),
        sa.UniqueConstraint("id", "source_id", name="uq_capture_id_source"),
        schema=BRONZE,
    )
    op.create_index("ix_capture_source_id", "capture", ["source_id"], schema=BRONZE)
    op.create_index(
        "ix_capture_source_endpoint_id",
        "capture",
        ["source_endpoint_id"],
        schema=BRONZE,
    )

    op.create_table(
        "source_record_version",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("capture_id", sa.BigInteger(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column(
            "source_payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id", "source_id"],
            [
                f"{BRONZE}.source_record.id",
                f"{BRONZE}.source_record.source_id",
            ],
            name="fk_source_record_version_record_source",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["capture_id", "source_id"],
            [f"{BRONZE}.capture.id", f"{BRONZE}.capture.source_id"],
            name="fk_source_record_version_capture_source",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "length(btrim(content_hash)) > 0",
            name="ck_source_record_version_content_hash_not_blank",
        ),
        schema=BRONZE,
    )
    op.create_index(
        "ix_source_record_version_source_record_id",
        "source_record_version",
        ["source_record_id"],
        schema=BRONZE,
    )
    op.create_index(
        "ix_source_record_version_capture_id",
        "source_record_version",
        ["capture_id"],
        schema=BRONZE,
    )

    op.create_table(
        "evidence",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_version_id", sa.BigInteger(), nullable=True),
        sa.Column("capture_id", sa.BigInteger(), nullable=True),
        sa.Column("locator", sa.Text(), nullable=False),
        sa.Column("excerpt_hash", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_version_id"],
            [f"{BRONZE}.source_record_version.id"],
            name="fk_evidence_source_record_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["capture_id"],
            [f"{BRONZE}.capture.id"],
            name="fk_evidence_capture_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(source_record_version_id IS NOT NULL) <> (capture_id IS NOT NULL)",
            name="ck_evidence_exactly_one_target",
        ),
        sa.CheckConstraint(
            "length(btrim(locator)) > 0",
            name="ck_evidence_locator_not_blank",
        ),
        sa.CheckConstraint(
            "length(btrim(excerpt_hash)) > 0",
            name="ck_evidence_excerpt_hash_not_blank",
        ),
        schema=BRONZE,
    )
    op.create_index(
        "ix_evidence_source_record_version_id",
        "evidence",
        ["source_record_version_id"],
        schema=BRONZE,
    )
    op.create_index(
        "ix_evidence_capture_id",
        "evidence",
        ["capture_id"],
        schema=BRONZE,
    )

    op.execute(
        f"""
        CREATE FUNCTION {BRONZE}.reject_provenance_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            immutable_column text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION '%.% is immutable and cannot be deleted',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;

            IF TG_NARGS = 0 THEN
                RAISE EXCEPTION '%.% is immutable and cannot be updated',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;

            FOREACH immutable_column IN ARRAY TG_ARGV LOOP
                IF to_jsonb(NEW) -> immutable_column
                    IS DISTINCT FROM to_jsonb(OLD) -> immutable_column THEN
                    RAISE EXCEPTION '%.%.% is immutable',
                        TG_TABLE_SCHEMA, TG_TABLE_NAME, immutable_column
                        USING ERRCODE = '55000';
                END IF;
            END LOOP;

            RETURN NEW;
        END;
        $$
        """
    )

    _install_immutability_trigger("source", "namespace")
    _install_immutability_trigger("source_endpoint", "source_id", "canonical_uri")
    _install_immutability_trigger("source_record", "source_id", "external_key")
    _install_immutability_trigger("capture")
    _install_immutability_trigger("source_record_version")
    _install_immutability_trigger("evidence")


def downgrade() -> None:
    op.drop_index("ix_evidence_capture_id", table_name="evidence", schema=BRONZE)
    op.drop_index(
        "ix_evidence_source_record_version_id",
        table_name="evidence",
        schema=BRONZE,
    )
    op.drop_table("evidence", schema=BRONZE)

    op.drop_index(
        "ix_source_record_version_capture_id",
        table_name="source_record_version",
        schema=BRONZE,
    )
    op.drop_index(
        "ix_source_record_version_source_record_id",
        table_name="source_record_version",
        schema=BRONZE,
    )
    op.drop_table("source_record_version", schema=BRONZE)

    op.drop_index(
        "ix_capture_source_endpoint_id",
        table_name="capture",
        schema=BRONZE,
    )
    op.drop_index("ix_capture_source_id", table_name="capture", schema=BRONZE)
    op.drop_table("capture", schema=BRONZE)

    op.drop_table("source_record", schema=BRONZE)
    op.drop_index(
        "ix_source_endpoint_source_id",
        table_name="source_endpoint",
        schema=BRONZE,
    )
    op.drop_table("source_endpoint", schema=BRONZE)
    op.drop_table("source", schema=BRONZE)

    op.execute(f"DROP FUNCTION {BRONZE}.reject_provenance_mutation()")
    op.execute(f"DROP SCHEMA {BRONZE}")
