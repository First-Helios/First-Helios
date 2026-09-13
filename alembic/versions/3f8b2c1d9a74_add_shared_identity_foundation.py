"""add shared Identity foundation

Creates ADR-0004's durable shared-identity schema.  Constraint triggers
enforce exact typed grains, complete append-only decisions, serialized
resolution transitions, and valid acyclic Subject lineage.  Mutable current
state is an internal projection that can be rebuilt from decision history.

This migration deliberately preserves the legacy raw/canonical/mart scaffold;
Plan 0002 Step 3 owns its reviewed removal.

Revision ID: 3f8b2c1d9a74
Revises: 6344725640bd
Create Date: 2026-09-12

"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "3f8b2c1d9a74"
down_revision: str | Sequence[str] | None = "6344725640bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BRONZE = "bronze"
IDENTITY = "identity"


def _decision_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("confidence", sa.Numeric(6, 5), nullable=False),
        sa.Column("method", sa.String(length=128), nullable=False),
        sa.Column("method_version", sa.String(length=64), nullable=False),
        sa.Column("actor_class", sa.String(length=16), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
    ]


def _install_history_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE TRIGGER trg_{table}_append_only
        BEFORE UPDATE OR DELETE ON {IDENTITY}.{table}
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.reject_history_mutation()
        """
    )


def _install_typed_grain_trigger(table: str) -> None:
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER ct_{table}_exact_typed_grain
        AFTER INSERT OR UPDATE OR DELETE ON {IDENTITY}.{table}
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.check_exact_typed_grain()
        """
    )


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {IDENTITY}")

    op.create_table(
        "subject",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "readiness",
            sa.String(length=16),
            server_default="provisional",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_transaction_id",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("id", "kind", name="uq_subject_id_kind"),
        sa.CheckConstraint(
            "kind IN ('place', 'organization', 'establishment')",
            name="ck_subject_kind",
        ),
        sa.CheckConstraint(
            "readiness IN ('provisional', 'eligible')",
            name="ck_subject_readiness",
        ),
        schema=IDENTITY,
    )

    op.create_table(
        "place",
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "subject_kind",
            sa.String(length=32),
            server_default="place",
            nullable=False,
        ),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Numeric(9, 6), nullable=True),
        sa.Column("longitude", sa.Numeric(9, 6), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_place_subject",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_id"),
        sa.UniqueConstraint("subject_id", "subject_kind", name="uq_place_subject_kind"),
        sa.CheckConstraint("subject_kind = 'place'", name="ck_place_subject_kind"),
        sa.CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)",
            name="ck_place_coordinates_both_or_neither",
        ),
        sa.CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_place_latitude",
        ),
        sa.CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_place_longitude",
        ),
        schema=IDENTITY,
    )

    op.create_table(
        "organization",
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "subject_kind",
            sa.String(length=32),
            server_default="organization",
            nullable=False,
        ),
        sa.Column("canonical_name", sa.String(length=255), nullable=True),
        sa.Column("name_fingerprint", sa.String(length=255), nullable=True),
        sa.Column(
            "organization_kind",
            sa.String(length=64),
            server_default="operating_identity",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_organization_subject",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_id"),
        sa.UniqueConstraint(
            "subject_id",
            "subject_kind",
            name="uq_organization_subject_kind",
        ),
        sa.CheckConstraint(
            "subject_kind = 'organization'",
            name="ck_organization_subject_kind",
        ),
        sa.CheckConstraint(
            "(canonical_name IS NULL) = (name_fingerprint IS NULL)",
            name="ck_organization_name_pair",
        ),
        sa.CheckConstraint(
            "canonical_name IS NULL OR length(btrim(canonical_name)) > 0",
            name="ck_organization_name_not_blank",
        ),
        sa.CheckConstraint(
            "name_fingerprint IS NULL OR length(btrim(name_fingerprint)) > 0",
            name="ck_organization_fingerprint_not_blank",
        ),
        sa.CheckConstraint(
            "organization_kind = btrim(organization_kind) AND length(organization_kind) > 0",
            name="ck_organization_kind_not_blank",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_organization_name_fingerprint",
        "organization",
        ["name_fingerprint"],
        schema=IDENTITY,
    )

    op.create_table(
        "establishment",
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "subject_kind",
            sa.String(length=32),
            server_default="establishment",
            nullable=False,
        ),
        sa.Column("organization_subject_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "organization_subject_kind",
            sa.String(length=32),
            server_default="organization",
            nullable=False,
        ),
        sa.Column("place_subject_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "place_subject_kind",
            sa.String(length=32),
            server_default="place",
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "operating_status",
            sa.String(length=16),
            server_default="unknown",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_establishment_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["organization_subject_id", "organization_subject_kind"],
            [
                f"{IDENTITY}.organization.subject_id",
                f"{IDENTITY}.organization.subject_kind",
            ],
            name="fk_establishment_organization",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["place_subject_id", "place_subject_kind"],
            [f"{IDENTITY}.place.subject_id", f"{IDENTITY}.place.subject_kind"],
            name="fk_establishment_place",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_id"),
        sa.UniqueConstraint(
            "subject_id",
            "subject_kind",
            name="uq_establishment_subject_kind",
        ),
        sa.CheckConstraint(
            "subject_kind = 'establishment'",
            name="ck_establishment_subject_kind",
        ),
        sa.CheckConstraint(
            "organization_subject_kind = 'organization'",
            name="ck_establishment_organization_kind",
        ),
        sa.CheckConstraint(
            "place_subject_kind = 'place'",
            name="ck_establishment_place_kind",
        ),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_establishment_effective_interval",
        ),
        sa.CheckConstraint(
            "operating_status IN ('unknown', 'open', 'closed')",
            name="ck_establishment_operating_status",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_establishment_organization_subject_id",
        "establishment",
        ["organization_subject_id"],
        schema=IDENTITY,
    )
    op.create_index(
        "ix_establishment_place_subject_id",
        "establishment",
        ["place_subject_id"],
        schema=IDENTITY,
    )

    op.create_table(
        "subject_name",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("name_fingerprint", sa.String(length=255), nullable=False),
        sa.Column("name_kind", sa.String(length=16), nullable=False),
        sa.Column("evidence_id", sa.BigInteger(), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_subject_name_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            [f"{BRONZE}.evidence.id"],
            name="fk_subject_name_evidence_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "subject_id",
            "name_kind",
            "name_fingerprint",
            name="uq_subject_name_kind_fingerprint",
        ),
        sa.CheckConstraint(
            "subject_kind IN ('place', 'organization', 'establishment')",
            name="ck_subject_name_subject_kind",
        ),
        sa.CheckConstraint(
            "name_kind IN ('canonical', 'alias')",
            name="ck_subject_name_kind",
        ),
        sa.CheckConstraint(
            "name = btrim(name) AND length(name) > 0",
            name="ck_subject_name_not_blank",
        ),
        sa.CheckConstraint(
            "name_fingerprint = btrim(name_fingerprint) AND length(name_fingerprint) > 0",
            name="ck_subject_name_fingerprint_not_blank",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_subject_name_fingerprint",
        "subject_name",
        ["name_fingerprint"],
        schema=IDENTITY,
    )

    op.create_table(
        "adjudication",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "actor = btrim(actor) AND length(actor) > 0",
            name="ck_adjudication_actor_not_blank",
        ),
        sa.CheckConstraint(
            "rationale = btrim(rationale) AND length(rationale) > 0 AND length(rationale) <= 4000",
            name="ck_adjudication_rationale_bounds",
        ),
        schema=IDENTITY,
    )

    op.create_table(
        "resolution_event",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "sequence_no",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "created_transaction_id",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("from_subject_id", sa.BigInteger(), nullable=True),
        sa.Column("to_subject_id", sa.BigInteger(), nullable=True),
        sa.Column("adjudication_id", sa.BigInteger(), nullable=True),
        *_decision_columns(),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            [f"{BRONZE}.source_record.id"],
            name="fk_resolution_event_source_record_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["from_subject_id"],
            [f"{IDENTITY}.subject.id"],
            name="fk_resolution_event_from_subject_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["to_subject_id"],
            [f"{IDENTITY}.subject.id"],
            name="fk_resolution_event_to_subject_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["adjudication_id"],
            [f"{IDENTITY}.adjudication.id"],
            name="fk_resolution_event_adjudication_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "source_record_id",
            name="uq_resolution_event_id_source_record",
        ),
        sa.UniqueConstraint(
            "source_record_id",
            "sequence_no",
            name="uq_resolution_event_source_sequence",
        ),
        sa.CheckConstraint(
            "operation IN ('open', 'assign', 'remap', 'unassign')",
            name="ck_resolution_event_operation",
        ),
        sa.CheckConstraint(
            """
            (operation = 'open' AND from_subject_id IS NULL AND to_subject_id IS NULL)
            OR
            (operation = 'assign' AND from_subject_id IS NULL AND to_subject_id IS NOT NULL)
            OR
            (
                operation = 'remap'
                AND from_subject_id IS NOT NULL
                AND to_subject_id IS NOT NULL
                AND from_subject_id <> to_subject_id
            )
            OR
            (operation = 'unassign' AND from_subject_id IS NOT NULL AND to_subject_id IS NULL)
            """,
            name="ck_resolution_event_operation_shape",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_resolution_event_confidence",
        ),
        sa.CheckConstraint(
            "method = btrim(method) AND length(method) > 0",
            name="ck_resolution_event_method_not_blank",
        ),
        sa.CheckConstraint(
            "method_version = btrim(method_version) AND length(method_version) > 0",
            name="ck_resolution_event_method_version_not_blank",
        ),
        sa.CheckConstraint(
            "actor_class IN ('rule', 'model', 'migration', 'human')",
            name="ck_resolution_event_actor_class",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_resolution_event_source_record_id",
        "resolution_event",
        ["source_record_id"],
        schema=IDENTITY,
    )
    op.create_index(
        "uq_resolution_event_one_open",
        "resolution_event",
        ["source_record_id"],
        unique=True,
        schema=IDENTITY,
        postgresql_where=sa.text("operation = 'open'"),
    )

    op.create_table(
        "resolution_evidence",
        sa.Column("resolution_event_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["resolution_event_id"],
            [f"{IDENTITY}.resolution_event.id"],
            name="fk_resolution_evidence_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            [f"{BRONZE}.evidence.id"],
            name="fk_resolution_evidence_evidence_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("resolution_event_id", "evidence_id"),
        schema=IDENTITY,
    )

    op.create_table(
        "current_resolution",
        sa.Column("source_record_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=True),
        sa.Column("last_event_id", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            [f"{BRONZE}.source_record.id"],
            name="fk_current_resolution_source_record_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            [f"{IDENTITY}.subject.id"],
            name="fk_current_resolution_subject_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_event_id", "source_record_id"],
            [
                f"{IDENTITY}.resolution_event.id",
                f"{IDENTITY}.resolution_event.source_record_id",
            ],
            name="fk_current_resolution_last_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("source_record_id"),
        sa.UniqueConstraint("last_event_id"),
        sa.CheckConstraint(
            "state IN ('unresolved', 'resolved', 'needs_review')",
            name="ck_current_resolution_state",
        ),
        sa.CheckConstraint(
            "(state = 'resolved' AND subject_id IS NOT NULL) "
            "OR (state IN ('unresolved', 'needs_review') AND subject_id IS NULL)",
            name="ck_current_resolution_state_subject",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_current_resolution_unresolved",
        "current_resolution",
        ["source_record_id"],
        schema=IDENTITY,
        postgresql_where=sa.text("state = 'unresolved'"),
    )
    op.create_index(
        "ix_current_resolution_needs_review",
        "current_resolution",
        ["source_record_id"],
        schema=IDENTITY,
        postgresql_where=sa.text("state = 'needs_review'"),
    )
    op.create_index(
        "ix_current_resolution_subject_id",
        "current_resolution",
        ["subject_id"],
        schema=IDENTITY,
    )

    op.create_table(
        "subject_change",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_transaction_id",
            sa.BigInteger(),
            server_default=sa.text("txid_current()"),
            nullable=False,
        ),
        sa.Column("operation", sa.String(length=16), nullable=False),
        sa.Column("adjudication_id", sa.BigInteger(), nullable=True),
        *_decision_columns(),
        sa.ForeignKeyConstraint(
            ["adjudication_id"],
            [f"{IDENTITY}.adjudication.id"],
            name="fk_subject_change_adjudication_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "operation IN ('merge', 'split', 'retire')",
            name="ck_subject_change_operation",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_subject_change_confidence",
        ),
        sa.CheckConstraint(
            "method = btrim(method) AND length(method) > 0",
            name="ck_subject_change_method_not_blank",
        ),
        sa.CheckConstraint(
            "method_version = btrim(method_version) AND length(method_version) > 0",
            name="ck_subject_change_method_version_not_blank",
        ),
        sa.CheckConstraint(
            "actor_class IN ('rule', 'model', 'migration', 'human')",
            name="ck_subject_change_actor_class",
        ),
        schema=IDENTITY,
    )

    op.create_table(
        "subject_change_member",
        sa.Column("subject_change_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_change_id"],
            [f"{IDENTITY}.subject_change.id"],
            name="fk_subject_change_member_change_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_subject_change_member_subject",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_change_id", "subject_id", "role"),
        sa.CheckConstraint(
            "subject_kind IN ('place', 'organization', 'establishment')",
            name="ck_subject_change_member_subject_kind",
        ),
        sa.CheckConstraint(
            "role IN ('input', 'output')",
            name="ck_subject_change_member_role",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_subject_change_member_subject_id",
        "subject_change_member",
        ["subject_id"],
        schema=IDENTITY,
    )

    op.create_table(
        "subject_change_evidence",
        sa.Column("subject_change_id", sa.BigInteger(), nullable=False),
        sa.Column("evidence_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_change_id"],
            [f"{IDENTITY}.subject_change.id"],
            name="fk_subject_change_evidence_change_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            [f"{BRONZE}.evidence.id"],
            name="fk_subject_change_evidence_evidence_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_change_id", "evidence_id"),
        schema=IDENTITY,
    )

    op.create_table(
        "subject_currentness",
        sa.Column("subject_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column(
            "is_current",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("retired_by_change_id", sa.BigInteger(), nullable=True),
        sa.Column("retirement_reason", sa.String(length=16), nullable=True),
        sa.ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_subject_currentness_subject",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["retired_by_change_id"],
            [f"{IDENTITY}.subject_change.id"],
            name="fk_subject_currentness_retired_by_change_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_id"),
        sa.CheckConstraint(
            "subject_kind IN ('place', 'organization', 'establishment')",
            name="ck_subject_currentness_subject_kind",
        ),
        sa.CheckConstraint(
            "(is_current AND retired_by_change_id IS NULL AND retirement_reason IS NULL) "
            "OR "
            "(NOT is_current AND retired_by_change_id IS NOT NULL "
            "AND retirement_reason IS NOT NULL)",
            name="ck_subject_currentness_retirement",
        ),
        sa.CheckConstraint(
            "retirement_reason IS NULL OR retirement_reason IN ('merge', 'split', 'retire')",
            name="ck_subject_currentness_retirement_reason",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_subject_currentness_current",
        "subject_currentness",
        ["subject_id"],
        schema=IDENTITY,
        postgresql_where=sa.text("is_current"),
    )

    op.create_table(
        "subject_lineage",
        sa.Column("subject_change_id", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_subject_id", sa.BigInteger(), nullable=False),
        sa.Column("successor_subject_id", sa.BigInteger(), nullable=False),
        sa.Column("predecessor_subject_kind", sa.String(length=32), nullable=False),
        sa.Column("successor_subject_kind", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_change_id"],
            [f"{IDENTITY}.subject_change.id"],
            name="fk_subject_lineage_change_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_subject_id", "predecessor_subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_subject_lineage_predecessor",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["successor_subject_id", "successor_subject_kind"],
            [f"{IDENTITY}.subject.id", f"{IDENTITY}.subject.kind"],
            name="fk_subject_lineage_successor",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "subject_change_id",
            "predecessor_subject_id",
            "successor_subject_id",
        ),
        sa.CheckConstraint(
            "predecessor_subject_id <> successor_subject_id",
            name="ck_subject_lineage_no_self_edge",
        ),
        schema=IDENTITY,
    )
    op.create_index(
        "ix_subject_lineage_predecessor",
        "subject_lineage",
        ["predecessor_subject_id"],
        schema=IDENTITY,
    )
    op.create_index(
        "ix_subject_lineage_successor",
        "subject_lineage",
        ["successor_subject_id"],
        schema=IDENTITY,
    )

    op.create_table(
        "applied_subject_change",
        sa.Column("subject_change_id", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["subject_change_id"],
            [f"{IDENTITY}.subject_change.id"],
            name="fk_applied_subject_change_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("subject_change_id"),
        schema=IDENTITY,
    )

    # -- Generic history/projection protection -----------------------------
    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.reject_history_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '%.% is append-only and cannot be %',
                TG_TABLE_SCHEMA, TG_TABLE_NAME, lower(TG_OP)
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in (
        "adjudication",
        "resolution_event",
        "resolution_evidence",
        "subject_change",
        "subject_change_member",
        "subject_change_evidence",
        "applied_subject_change",
    ):
        _install_history_trigger(table)
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only_truncate
            BEFORE TRUNCATE ON {IDENTITY}.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {IDENTITY}.reject_history_mutation()
            """
        )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.reject_late_decision_member()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            parent_transaction_id bigint;
            parent_is_applied boolean := false;
        BEGIN
            IF TG_TABLE_NAME = 'resolution_evidence' THEN
                SELECT created_transaction_id
                INTO parent_transaction_id
                FROM {IDENTITY}.resolution_event
                WHERE id = NEW.resolution_event_id;
            ELSE
                SELECT created_transaction_id
                INTO parent_transaction_id
                FROM {IDENTITY}.subject_change
                WHERE id = NEW.subject_change_id;

                IF TG_TABLE_NAME <> 'applied_subject_change' THEN
                    SELECT EXISTS (
                        SELECT 1
                        FROM {IDENTITY}.applied_subject_change
                        WHERE subject_change_id = NEW.subject_change_id
                    )
                    INTO parent_is_applied;
                END IF;
            END IF;

            IF parent_transaction_id IS DISTINCT FROM txid_current()
               OR parent_is_applied THEN
                RAISE EXCEPTION
                    'decision members may only be inserted with their parent decision'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in (
        "resolution_evidence",
        "subject_change_member",
        "subject_change_evidence",
        "applied_subject_change",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_parent_transaction
            BEFORE INSERT ON {IDENTITY}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {IDENTITY}.reject_late_decision_member()
            """
        )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.validate_projection_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            expected_event_id bigint;
            expected_subject_id bigint;
            expected_state text;
            expected_subject_kind text;
            retirement_count integer;
            expected_retirement_change_id bigint;
            expected_retirement_reason text;
        BEGIN
            IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
                RAISE EXCEPTION '%.% is a derived Identity projection',
                    TG_TABLE_SCHEMA, TG_TABLE_NAME
                    USING ERRCODE = '55000';
            END IF;

            IF TG_TABLE_NAME = 'current_resolution' THEN
                IF TG_OP = 'UPDATE'
                   AND NEW.source_record_id IS DISTINCT FROM
                       OLD.source_record_id THEN
                    RAISE EXCEPTION
                        'current-resolution projection key is immutable'
                        USING ERRCODE = '55000';
                END IF;

                SELECT
                    event.id,
                    CASE
                        WHEN event.operation IN ('assign', 'remap')
                        THEN event.to_subject_id
                        ELSE NULL
                    END,
                    CASE event.operation
                        WHEN 'open' THEN 'unresolved'
                        WHEN 'unassign' THEN 'needs_review'
                        ELSE 'resolved'
                    END
                INTO
                    expected_event_id,
                    expected_subject_id,
                    expected_state
                FROM {IDENTITY}.resolution_event AS event
                WHERE event.source_record_id = NEW.source_record_id
                ORDER BY event.sequence_no DESC
                LIMIT 1;

                IF NOT FOUND
                   OR NEW.last_event_id IS DISTINCT FROM expected_event_id
                   OR NEW.subject_id IS DISTINCT FROM expected_subject_id
                   OR NEW.state IS DISTINCT FROM expected_state THEN
                    RAISE EXCEPTION
                        'current-resolution row must match authoritative history'
                        USING ERRCODE = '55000';
                END IF;
            ELSIF TG_TABLE_NAME = 'subject_currentness' THEN
                IF TG_OP = 'UPDATE'
                   AND NEW.subject_id IS DISTINCT FROM OLD.subject_id THEN
                    RAISE EXCEPTION
                        'Subject-currentness projection key is immutable'
                        USING ERRCODE = '55000';
                END IF;

                SELECT kind
                INTO expected_subject_kind
                FROM {IDENTITY}.subject
                WHERE id = NEW.subject_id;

                SELECT
                    count(*),
                    min(change.id),
                    min(change.operation)
                INTO
                    retirement_count,
                    expected_retirement_change_id,
                    expected_retirement_reason
                FROM {IDENTITY}.subject_change_member AS input_member
                JOIN {IDENTITY}.subject_change AS change
                  ON change.id = input_member.subject_change_id
                WHERE input_member.subject_id = NEW.subject_id
                  AND input_member.role = 'input'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {IDENTITY}.subject_change_member AS output_member
                      WHERE output_member.subject_change_id =
                            input_member.subject_change_id
                        AND output_member.subject_id = input_member.subject_id
                        AND output_member.role = 'output'
                  );

                IF expected_subject_kind IS NULL
                   OR retirement_count > 1
                   OR NEW.subject_kind IS DISTINCT FROM expected_subject_kind
                   OR NEW.is_current IS DISTINCT FROM (retirement_count = 0)
                   OR NEW.retired_by_change_id IS DISTINCT FROM
                      expected_retirement_change_id
                   OR NEW.retirement_reason IS DISTINCT FROM
                      expected_retirement_reason THEN
                    RAISE EXCEPTION
                        'Subject-currentness row must match authoritative history'
                        USING ERRCODE = '55000';
                END IF;
            ELSE
                IF TG_OP = 'UPDATE' THEN
                    RAISE EXCEPTION
                        'Subject-lineage projection rows are immutable'
                        USING ERRCODE = '55000';
                END IF;

                IF NOT EXISTS (
                    SELECT 1
                    FROM {IDENTITY}.subject_change_member AS input_member
                    JOIN {IDENTITY}.subject_change_member AS output_member
                      ON output_member.subject_change_id =
                         input_member.subject_change_id
                     AND output_member.role = 'output'
                    WHERE input_member.subject_change_id =
                          NEW.subject_change_id
                      AND input_member.role = 'input'
                      AND input_member.subject_id =
                          NEW.predecessor_subject_id
                      AND input_member.subject_kind =
                          NEW.predecessor_subject_kind
                      AND output_member.subject_id =
                          NEW.successor_subject_id
                      AND output_member.subject_kind =
                          NEW.successor_subject_kind
                      AND input_member.subject_id <>
                          output_member.subject_id
                ) THEN
                    RAISE EXCEPTION
                        'Subject-lineage row must match authoritative history'
                        USING ERRCODE = '55000';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table in (
        "current_resolution",
        "subject_currentness",
        "subject_lineage",
    ):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_identity_owned
            BEFORE INSERT OR UPDATE OR DELETE ON {IDENTITY}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {IDENTITY}.validate_projection_mutation()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_identity_owned_truncate
            BEFORE TRUNCATE ON {IDENTITY}.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {IDENTITY}.validate_projection_mutation()
            """
        )

    # -- Exact typed grain and Subject lifecycle ---------------------------
    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.protect_subject_identity()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(48454, 2);

            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'Identity Subjects are retired, not deleted'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.kind IS DISTINCT FROM OLD.kind THEN
                RAISE EXCEPTION 'Subject kind is immutable'
                    USING ERRCODE = '55000';
            END IF;
            IF NEW.created_transaction_id IS DISTINCT FROM
               OLD.created_transaction_id THEN
                RAISE EXCEPTION 'Subject creation transaction is immutable'
                    USING ERRCODE = '55000';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_subject_identity_stable
        BEFORE UPDATE OR DELETE ON {IDENTITY}.subject
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.protect_subject_identity()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.stamp_subject_creation_transaction()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(48454, 2);
            NEW.created_transaction_id := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_subject_stamp_creation_transaction
        BEFORE INSERT ON {IDENTITY}.subject
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.stamp_subject_creation_transaction()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.initialize_subject_currentness()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            INSERT INTO {IDENTITY}.subject_currentness (
                subject_id, subject_kind, is_current
            )
            VALUES (NEW.id, NEW.kind, true);
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_subject_initialize_currentness
        AFTER INSERT ON {IDENTITY}.subject
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.initialize_subject_currentness()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.protect_typed_grain_key()
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
    for table in ("place", "organization", "establishment"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_subject_key_stable
            BEFORE UPDATE OR DELETE ON {IDENTITY}.{table}
            FOR EACH ROW
            EXECUTE FUNCTION {IDENTITY}.protect_typed_grain_key()
            """
        )
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_subject_key_stable_truncate
            BEFORE TRUNCATE ON {IDENTITY}.{table}
            FOR EACH STATEMENT
            EXECUTE FUNCTION {IDENTITY}.protect_typed_grain_key()
            """
        )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.check_exact_typed_grain()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            checked_subject_id bigint;
            expected_kind text;
            typed_count integer;
            matching_count integer;
        BEGIN
            IF TG_TABLE_NAME = 'subject' THEN
                checked_subject_id := CASE
                    WHEN TG_OP = 'DELETE' THEN OLD.id
                    ELSE NEW.id
                END;
            ELSE
                checked_subject_id := CASE
                    WHEN TG_OP = 'DELETE' THEN OLD.subject_id
                    ELSE NEW.subject_id
                END;
            END IF;

            SELECT kind INTO expected_kind
            FROM {IDENTITY}.subject
            WHERE id = checked_subject_id;

            IF expected_kind IS NULL THEN
                RETURN NULL;
            END IF;

            SELECT
                (SELECT count(*) FROM {IDENTITY}.place
                 WHERE subject_id = checked_subject_id)
                +
                (SELECT count(*) FROM {IDENTITY}.organization
                 WHERE subject_id = checked_subject_id)
                +
                (SELECT count(*) FROM {IDENTITY}.establishment
                 WHERE subject_id = checked_subject_id),
                CASE expected_kind
                    WHEN 'place' THEN
                        (SELECT count(*) FROM {IDENTITY}.place
                         WHERE subject_id = checked_subject_id)
                    WHEN 'organization' THEN
                        (SELECT count(*) FROM {IDENTITY}.organization
                         WHERE subject_id = checked_subject_id)
                    WHEN 'establishment' THEN
                        (SELECT count(*) FROM {IDENTITY}.establishment
                         WHERE subject_id = checked_subject_id)
                    ELSE 0
                END
            INTO typed_count, matching_count;

            IF typed_count <> 1 OR matching_count <> 1 THEN
                RAISE EXCEPTION
                    'Subject % must have exactly one matching typed grain (kind %, count %)',
                    checked_subject_id, expected_kind, typed_count
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_exact_typed_grain';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    for table in ("subject", "place", "organization", "establishment"):
        _install_typed_grain_trigger(table)

    # -- Resolution transition machine and projection ---------------------
    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.validate_resolution_transition()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        DECLARE
            current_row {IDENTITY}.current_resolution%ROWTYPE;
            target_is_current boolean;
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(48454, 2);

            -- Resolution and Subject changes share one stable lock order:
            -- Subject rows, then the owning Source Record, then projections.
            -- FOR SHARE conflicts with Subject changes' FOR NO KEY UPDATE,
            -- while the Source Record's weaker lock remains compatible with
            -- Bronze-version FK checks that already hold FOR KEY SHARE.
            PERFORM id
            FROM {IDENTITY}.subject
            WHERE id IN (NEW.from_subject_id, NEW.to_subject_id)
            ORDER BY id
            FOR SHARE;

            PERFORM id
            FROM {BRONZE}.source_record
            WHERE id = NEW.source_record_id
            FOR NO KEY UPDATE;

            SELECT * INTO current_row
            FROM {IDENTITY}.current_resolution
            WHERE source_record_id = NEW.source_record_id
            FOR UPDATE;

            SELECT coalesce(max(event.sequence_no), 0) + 1
            INTO NEW.sequence_no
            FROM {IDENTITY}.resolution_event AS event
            WHERE event.source_record_id = NEW.source_record_id;
            NEW.created_transaction_id := txid_current();

            IF NEW.to_subject_id IS NOT NULL THEN
                SELECT is_current INTO target_is_current
                FROM {IDENTITY}.subject_currentness
                WHERE subject_id = NEW.to_subject_id
                FOR SHARE;
                IF NOT coalesce(target_is_current, false) THEN
                    RAISE EXCEPTION 'resolution target Subject % is not current',
                        NEW.to_subject_id
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ct_resolution_transition';
                END IF;
            END IF;

            CASE NEW.operation
                WHEN 'open' THEN
                    IF current_row.source_record_id IS NOT NULL THEN
                        RAISE EXCEPTION 'Source Record % is already in resolution',
                            NEW.source_record_id
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ct_resolution_transition';
                    END IF;
                WHEN 'assign' THEN
                    IF current_row.source_record_id IS NULL
                       OR current_row.state NOT IN ('unresolved', 'needs_review')
                       OR current_row.subject_id IS NOT NULL THEN
                        RAISE EXCEPTION
                            'assign requires unresolved or needs_review current state'
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ct_resolution_transition';
                    END IF;
                WHEN 'remap' THEN
                    IF current_row.state <> 'resolved'
                       OR current_row.subject_id IS DISTINCT FROM NEW.from_subject_id THEN
                        RAISE EXCEPTION 'remap must name the current Subject'
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ct_resolution_transition';
                    END IF;
                WHEN 'unassign' THEN
                    IF current_row.state <> 'resolved'
                       OR current_row.subject_id IS DISTINCT FROM NEW.from_subject_id THEN
                        RAISE EXCEPTION 'unassign must name the current Subject'
                            USING ERRCODE = '23514',
                                  CONSTRAINT = 'ct_resolution_transition';
                    END IF;
                ELSE
                    RAISE EXCEPTION 'unknown resolution operation %', NEW.operation
                        USING ERRCODE = '23514',
                              CONSTRAINT = 'ct_resolution_transition';
            END CASE;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_resolution_event_validate
        BEFORE INSERT ON {IDENTITY}.resolution_event
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.validate_resolution_transition()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.project_resolution_event()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.operation = 'open' THEN
                INSERT INTO {IDENTITY}.current_resolution (
                    source_record_id, subject_id, last_event_id, state
                )
                VALUES (NEW.source_record_id, NULL, NEW.id, 'unresolved');
            ELSIF NEW.operation IN ('assign', 'remap') THEN
                UPDATE {IDENTITY}.current_resolution
                SET subject_id = NEW.to_subject_id,
                    last_event_id = NEW.id,
                    state = 'resolved'
                WHERE source_record_id = NEW.source_record_id;
            ELSE
                UPDATE {IDENTITY}.current_resolution
                SET subject_id = NULL,
                    last_event_id = NEW.id,
                    state = 'needs_review'
                WHERE source_record_id = NEW.source_record_id;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_resolution_event_project
        AFTER INSERT ON {IDENTITY}.resolution_event
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.project_resolution_event()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.check_resolution_support()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.adjudication_id IS NULL
               AND NOT EXISTS (
                    SELECT 1
                    FROM {IDENTITY}.resolution_evidence
                    WHERE resolution_event_id = NEW.id
               ) THEN
                RAISE EXCEPTION
                    'resolution event % requires Evidence or Adjudication',
                    NEW.id
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_resolution_event_support';
            END IF;
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER ct_resolution_event_support
        AFTER INSERT ON {IDENTITY}.resolution_event
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.check_resolution_support()
        """
    )

    # -- Subject-change validation, locking, retirement, and lineage -------
    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.stamp_subject_change_transaction()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            NEW.created_transaction_id := txid_current();
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER trg_subject_change_stamp_transaction
        BEFORE INSERT ON {IDENTITY}.subject_change
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.stamp_subject_change_transaction()
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.apply_subject_change(change_id bigint)
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        DECLARE
            change_row {IDENTITY}.subject_change%ROWTYPE;
            input_count integer;
            output_count integer;
            kind_count integer;
            edge record;
        BEGIN
            PERFORM pg_advisory_xact_lock_shared(48454, 2);

            SELECT * INTO STRICT change_row
            FROM {IDENTITY}.subject_change
            WHERE id = change_id
            FOR UPDATE;

            IF change_row.adjudication_id IS NULL
               AND NOT EXISTS (
                    SELECT 1
                    FROM {IDENTITY}.subject_change_evidence
                    WHERE subject_change_id = change_id
               ) THEN
                RAISE EXCEPTION
                    'Subject change % requires Evidence or Adjudication',
                    change_id
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            SELECT
                count(*) FILTER (WHERE role = 'input'),
                count(*) FILTER (WHERE role = 'output'),
                count(DISTINCT subject_kind)
            INTO input_count, output_count, kind_count
            FROM {IDENTITY}.subject_change_member
            WHERE subject_change_id = change_id;

            IF kind_count <> 1 THEN
                RAISE EXCEPTION 'Subject change % must contain one Subject kind',
                    change_id
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            IF (change_row.operation = 'merge'
                    AND NOT (input_count >= 2 AND output_count = 1))
               OR (change_row.operation = 'split'
                    AND NOT (input_count = 1 AND output_count >= 2))
               OR (change_row.operation = 'retire'
                    AND NOT (input_count = 1 AND output_count = 0)) THEN
                RAISE EXCEPTION
                    'invalid % member cardinality: % inputs, % outputs',
                    change_row.operation, input_count, output_count
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            IF change_row.operation = 'split'
               AND EXISTS (
                    SELECT 1
                    FROM {IDENTITY}.subject_change_member AS output_member
                    WHERE output_member.subject_change_id = change_id
                      AND output_member.role = 'output'
                      AND (
                          EXISTS (
                              SELECT 1
                              FROM {IDENTITY}.subject_change_member AS input_member
                              WHERE input_member.subject_change_id = change_id
                                AND input_member.role = 'input'
                                AND input_member.subject_id =
                                    output_member.subject_id
                          )
                          OR EXISTS (
                              SELECT 1
                              FROM {IDENTITY}.subject_change_member AS prior
                              WHERE prior.subject_id = output_member.subject_id
                                AND prior.subject_change_id < change_id
                          )
                          OR NOT EXISTS (
                              SELECT 1
                              FROM {IDENTITY}.subject AS output_subject
                              WHERE output_subject.id = output_member.subject_id
                                AND output_subject.created_transaction_id =
                                    txid_current()
                          )
                      )
               ) THEN
                RAISE EXCEPTION 'split outputs must be new, distinct Subjects'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            IF change_row.operation = 'merge'
               AND EXISTS (
                    SELECT 1
                    FROM {IDENTITY}.subject_change_member AS output_member
                    WHERE output_member.subject_change_id = change_id
                      AND output_member.role = 'output'
                      AND NOT EXISTS (
                          SELECT 1
                          FROM {IDENTITY}.subject_change_member AS input_member
                          WHERE input_member.subject_change_id = change_id
                            AND input_member.role = 'input'
                            AND input_member.subject_id =
                                output_member.subject_id
                      )
                      AND (
                          NOT EXISTS (
                              SELECT 1
                              FROM {IDENTITY}.subject AS output_subject
                              WHERE output_subject.id = output_member.subject_id
                                AND output_subject.created_transaction_id =
                                    txid_current()
                          )
                          OR
                          EXISTS (
                              SELECT 1
                              FROM {IDENTITY}.subject_change_member AS prior
                              WHERE prior.subject_id = output_member.subject_id
                                AND prior.subject_change_id < change_id
                          )
                      )
               ) THEN
                RAISE EXCEPTION
                    'an existing merge survivor must also be an input'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            -- Every participant is locked in stable ID order.  Overlapping
            -- concurrent changes therefore wait rather than deadlock.
            PERFORM subject.id
            FROM {IDENTITY}.subject AS subject
            JOIN {IDENTITY}.subject_change_member AS member
              ON member.subject_id = subject.id
            WHERE member.subject_change_id = change_id
            ORDER BY subject.id
            FOR NO KEY UPDATE OF subject;

            FOR edge IN
                SELECT
                    input_member.subject_id AS predecessor_id,
                    output_member.subject_id AS successor_id,
                    input_member.subject_kind AS predecessor_kind,
                    output_member.subject_kind AS successor_kind
                FROM {IDENTITY}.subject_change_member AS input_member
                JOIN {IDENTITY}.subject_change_member AS output_member
                  ON output_member.subject_change_id =
                     input_member.subject_change_id
                 AND output_member.role = 'output'
                WHERE input_member.subject_change_id = change_id
                  AND input_member.role = 'input'
                  AND input_member.subject_id <> output_member.subject_id
            LOOP
                IF EXISTS (
                    WITH RECURSIVE successors(subject_id) AS (
                        SELECT edge.successor_id
                        UNION
                        SELECT lineage.successor_subject_id
                        FROM {IDENTITY}.subject_lineage AS lineage
                        JOIN successors
                          ON lineage.predecessor_subject_id =
                             successors.subject_id
                    )
                    SELECT 1
                    FROM successors
                    WHERE subject_id = edge.predecessor_id
                ) THEN
                    RAISE EXCEPTION
                        'Subject change % would create a lineage cycle',
                        change_id
                        USING ERRCODE = '23514',
                              CONSTRAINT =
                                  'ct_subject_change_complete_and_apply';
                END IF;
            END LOOP;

            IF EXISTS (
                SELECT 1
                FROM {IDENTITY}.subject_change_member AS member
                JOIN {IDENTITY}.subject_currentness AS currentness
                  ON currentness.subject_id = member.subject_id
                WHERE member.subject_change_id = change_id
                  AND member.role = 'input'
                  AND NOT currentness.is_current
            ) THEN
                RAISE EXCEPTION 'every Subject-change input must be current'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            IF EXISTS (
                SELECT 1
                FROM {IDENTITY}.subject_change_member AS member
                LEFT JOIN {IDENTITY}.subject_currentness AS currentness
                  ON currentness.subject_id = member.subject_id
                WHERE member.subject_change_id = change_id
                  AND (
                      currentness.subject_id IS NULL
                      OR NOT currentness.is_current
                  )
            ) THEN
                RAISE EXCEPTION 'every Subject-change member must be current'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ct_subject_change_complete_and_apply';
            END IF;

            INSERT INTO {IDENTITY}.subject_lineage (
                subject_change_id,
                predecessor_subject_id,
                successor_subject_id,
                predecessor_subject_kind,
                successor_subject_kind
            )
            SELECT
                change_id,
                input_member.subject_id,
                output_member.subject_id,
                input_member.subject_kind,
                output_member.subject_kind
            FROM {IDENTITY}.subject_change_member AS input_member
            JOIN {IDENTITY}.subject_change_member AS output_member
              ON output_member.subject_change_id = input_member.subject_change_id
             AND output_member.role = 'output'
            WHERE input_member.subject_change_id = change_id
              AND input_member.role = 'input'
              AND input_member.subject_id <> output_member.subject_id;

            UPDATE {IDENTITY}.subject_currentness AS currentness
            SET is_current = false,
                retired_by_change_id = change_id,
                retirement_reason = change_row.operation
            FROM {IDENTITY}.subject_change_member AS input_member
            WHERE input_member.subject_change_id = change_id
              AND input_member.role = 'input'
              AND currentness.subject_id = input_member.subject_id
              AND NOT EXISTS (
                  SELECT 1
                  FROM {IDENTITY}.subject_change_member AS output_member
                  WHERE output_member.subject_change_id = change_id
                    AND output_member.role = 'output'
                    AND output_member.subject_id = input_member.subject_id
              );

            INSERT INTO {IDENTITY}.applied_subject_change (
                subject_change_id
            )
            VALUES (change_id);
        END;
        $$
        """
    )

    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.complete_and_apply_subject_change()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            PERFORM {IDENTITY}.apply_subject_change(NEW.id);
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        f"""
        CREATE CONSTRAINT TRIGGER ct_subject_change_complete_and_apply
        AFTER INSERT ON {IDENTITY}.subject_change
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION {IDENTITY}.complete_and_apply_subject_change()
        """
    )

    # -- Projection rebuild -------------------------------------------------
    op.execute(
        f"""
        CREATE FUNCTION {IDENTITY}.rebuild_identity_projections()
        RETURNS void
        LANGUAGE plpgsql
        AS $$
        BEGIN
            -- Identity writers take the same transaction-level lock before
            -- changing authoritative history or Subject readiness.
            IF NOT pg_try_advisory_xact_lock(48454, 2) THEN
                RAISE EXCEPTION
                    'Identity projections can only be rebuilt without concurrent writers'
                    USING ERRCODE = '55000';
            END IF;
            SET CONSTRAINTS ALL IMMEDIATE;
            SET CONSTRAINTS ALL DEFERRED;

            IF EXISTS (
                SELECT 1
                FROM {IDENTITY}.resolution_event AS event
                WHERE event.adjudication_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {IDENTITY}.resolution_evidence AS evidence
                      WHERE evidence.resolution_event_id = event.id
                  )
            ) THEN
                RAISE EXCEPTION
                    'cannot rebuild projections from an incomplete resolution event'
                    USING ERRCODE = '23514';
            END IF;

            INSERT INTO {IDENTITY}.subject_currentness (
                subject_id,
                subject_kind,
                is_current,
                retired_by_change_id,
                retirement_reason
            )
            SELECT
                subject.id,
                subject.kind,
                retirement.subject_change_id IS NULL,
                retirement.subject_change_id,
                retirement.operation
            FROM {IDENTITY}.subject AS subject
            LEFT JOIN LATERAL (
                SELECT
                    input_member.subject_change_id,
                    change.operation
                FROM {IDENTITY}.subject_change_member AS input_member
                JOIN {IDENTITY}.subject_change AS change
                  ON change.id = input_member.subject_change_id
                WHERE input_member.subject_id = subject.id
                  AND input_member.role = 'input'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM {IDENTITY}.subject_change_member AS output_member
                      WHERE output_member.subject_change_id =
                            input_member.subject_change_id
                        AND output_member.role = 'output'
                        AND output_member.subject_id =
                            input_member.subject_id
                  )
                LIMIT 1
            ) AS retirement ON true
            ORDER BY subject.id
            ON CONFLICT (subject_id) DO UPDATE
            SET subject_kind = EXCLUDED.subject_kind,
                is_current = EXCLUDED.is_current,
                retired_by_change_id = EXCLUDED.retired_by_change_id,
                retirement_reason = EXCLUDED.retirement_reason;

            INSERT INTO {IDENTITY}.current_resolution (
                source_record_id, subject_id, last_event_id, state
            )
            SELECT DISTINCT ON (event.source_record_id)
                event.source_record_id,
                CASE
                    WHEN event.operation IN ('assign', 'remap')
                    THEN event.to_subject_id
                    ELSE NULL
                END,
                event.id,
                CASE event.operation
                    WHEN 'open' THEN 'unresolved'
                    WHEN 'unassign' THEN 'needs_review'
                    ELSE 'resolved'
                END
            FROM {IDENTITY}.resolution_event AS event
            ORDER BY event.source_record_id, event.sequence_no DESC
            ON CONFLICT (source_record_id) DO UPDATE
            SET subject_id = EXCLUDED.subject_id,
                last_event_id = EXCLUDED.last_event_id,
                state = EXCLUDED.state;

            INSERT INTO {IDENTITY}.subject_lineage (
                subject_change_id,
                predecessor_subject_id,
                successor_subject_id,
                predecessor_subject_kind,
                successor_subject_kind
            )
            SELECT
                input_member.subject_change_id,
                input_member.subject_id,
                output_member.subject_id,
                input_member.subject_kind,
                output_member.subject_kind
            FROM {IDENTITY}.subject_change_member AS input_member
            JOIN {IDENTITY}.subject_change_member AS output_member
              ON output_member.subject_change_id =
                 input_member.subject_change_id
             AND output_member.role = 'output'
            WHERE input_member.role = 'input'
              AND input_member.subject_id <> output_member.subject_id
            ON CONFLICT (
                subject_change_id,
                predecessor_subject_id,
                successor_subject_id
            ) DO NOTHING;
        END;
        $$
        """
    )


def downgrade() -> None:
    # No lower schema references Identity at this step, so the bounded context
    # can be removed as one unit.  Bronze and every legacy schema remain.
    op.execute(f"DROP SCHEMA {IDENTITY} CASCADE")
