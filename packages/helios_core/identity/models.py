"""Typed SQLAlchemy models for shared Identity state and decision history.

Identity is durable Silver data.  Source interpretation and Subject lineage
are append-only histories; the ``current_*`` and lineage tables are internal,
rebuildable projections maintained by database triggers.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.helios_core.db.base import SCHEMA_BRONZE, SCHEMA_IDENTITY, Base

# Python's ``str.strip()`` whitespace, and the zero-width characters a name
# cannot consist of; see migration 12a76ebed458.
WHITESPACE = f"{SCHEMA_BRONZE}.whitespace()"
INVISIBLE = "U&'\\200B\\200C\\200D\\2060\\FEFF'"

SUBJECT_KINDS = ("place", "organization", "establishment")
SUBJECT_READINESS_STATES = ("provisional", "eligible")
SUBJECT_NAME_KINDS = ("canonical", "alias")
ESTABLISHMENT_STATUSES = ("unknown", "open", "closed")
RESOLUTION_OPERATIONS = ("open", "assign", "remap", "unassign")
RESOLUTION_STATES = ("unresolved", "resolved", "needs_review")
SUBJECT_CHANGE_OPERATIONS = ("merge", "split", "retire")
SUBJECT_CHANGE_ROLES = ("input", "output")
DECISION_ACTOR_CLASSES = ("rule", "model", "migration", "human")


def _in_check(column: str, allowed: tuple[str, ...], name: str) -> CheckConstraint:
    values = ", ".join(f"'{value}'" for value in allowed)
    return CheckConstraint(f"{column} IN ({values})", name=name)


def _decision_checks(prefix: str) -> tuple[CheckConstraint, ...]:
    return (
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=f"ck_{prefix}_confidence",
        ),
        CheckConstraint(
            f"method = btrim(method, {WHITESPACE}) AND length(method) > 0",
            name=f"ck_{prefix}_method_not_blank",
        ),
        CheckConstraint(
            f"method_version = btrim(method_version, {WHITESPACE}) AND length(method_version) > 0",
            name=f"ck_{prefix}_method_version_not_blank",
        ),
        _in_check(
            "actor_class",
            DECISION_ACTOR_CLASSES,
            f"ck_{prefix}_actor_class",
        ),
    )


class Subject(Base):
    """Stable typed handle shared by resolution and vertical contracts."""

    __tablename__ = "subject"
    __table_args__: Any = (
        _in_check("kind", SUBJECT_KINDS, "ck_subject_kind"),
        _in_check(
            "readiness",
            SUBJECT_READINESS_STATES,
            "ck_subject_readiness",
        ),
        UniqueConstraint("id", "kind", name="uq_subject_id_kind"),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    readiness: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="provisional",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    created_transaction_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("txid_current()"),
    )


class Place(Base):
    """A physical location independent of its current operator."""

    __tablename__ = "place"
    __table_args__: Any = (
        CheckConstraint("subject_kind = 'place'", name="ck_place_subject_kind"),
        CheckConstraint(
            "(latitude IS NULL) = (longitude IS NULL)",
            name="ck_place_coordinates_both_or_neither",
        ),
        CheckConstraint(
            "latitude IS NULL OR latitude BETWEEN -90 AND 90",
            name="ck_place_latitude",
        ),
        CheckConstraint(
            "longitude IS NULL OR longitude BETWEEN -180 AND 180",
            name="ck_place_longitude",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_place_subject",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("subject_id", "subject_kind", name="uq_place_subject_kind"),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="place",
    )
    address: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))


class Organization(Base):
    """An operating or brand identity independent of any one Place."""

    __tablename__ = "organization"
    __table_args__: Any = (
        CheckConstraint(
            "subject_kind = 'organization'",
            name="ck_organization_subject_kind",
        ),
        CheckConstraint(
            "(canonical_name IS NULL) = (name_fingerprint IS NULL)",
            name="ck_organization_name_pair",
        ),
        CheckConstraint(
            f"canonical_name IS NULL OR length(btrim(canonical_name, {WHITESPACE} || {INVISIBLE})) > 0",
            name="ck_organization_name_not_blank",
        ),
        CheckConstraint(
            f"name_fingerprint IS NULL OR length(btrim(name_fingerprint, {WHITESPACE})) > 0",
            name="ck_organization_fingerprint_not_blank",
        ),
        CheckConstraint(
            f"organization_kind = btrim(organization_kind, {WHITESPACE})"
            " AND length(organization_kind) > 0",
            name="ck_organization_kind_not_blank",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_organization_subject",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "subject_id",
            "subject_kind",
            name="uq_organization_subject_kind",
        ),
        Index("ix_organization_name_fingerprint", "name_fingerprint"),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="organization",
    )
    canonical_name: Mapped[str | None] = mapped_column(String(255))
    name_fingerprint: Mapped[str | None] = mapped_column(String(255))
    organization_kind: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        server_default="operating_identity",
    )


class Establishment(Base):
    """One Organization operating at one Place for an effective interval."""

    __tablename__ = "establishment"
    __table_args__: Any = (
        CheckConstraint(
            "subject_kind = 'establishment'",
            name="ck_establishment_subject_kind",
        ),
        CheckConstraint(
            "organization_subject_kind = 'organization'",
            name="ck_establishment_organization_kind",
        ),
        CheckConstraint(
            "place_subject_kind = 'place'",
            name="ck_establishment_place_kind",
        ),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from",
            name="ck_establishment_effective_interval",
        ),
        _in_check(
            "operating_status",
            ESTABLISHMENT_STATUSES,
            "ck_establishment_operating_status",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_establishment_subject",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["organization_subject_id", "organization_subject_kind"],
            [
                f"{SCHEMA_IDENTITY}.organization.subject_id",
                f"{SCHEMA_IDENTITY}.organization.subject_kind",
            ],
            name="fk_establishment_organization",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["place_subject_id", "place_subject_kind"],
            [
                f"{SCHEMA_IDENTITY}.place.subject_id",
                f"{SCHEMA_IDENTITY}.place.subject_kind",
            ],
            name="fk_establishment_place",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "subject_id",
            "subject_kind",
            name="uq_establishment_subject_kind",
        ),
        Index(
            "ix_establishment_organization_subject_id",
            "organization_subject_id",
        ),
        Index("ix_establishment_place_subject_id", "place_subject_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="establishment",
    )
    organization_subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    organization_subject_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="organization",
    )
    place_subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    place_subject_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        server_default="place",
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    operating_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        server_default="unknown",
    )


class SubjectName(Base):
    """A typed canonical name or alias, optionally grounded in Evidence."""

    __tablename__ = "subject_name"
    __table_args__: Any = (
        _in_check("subject_kind", SUBJECT_KINDS, "ck_subject_name_subject_kind"),
        _in_check("name_kind", SUBJECT_NAME_KINDS, "ck_subject_name_kind"),
        CheckConstraint(
            f"name = btrim(name, {WHITESPACE}) AND length(name) > 0",
            name="ck_subject_name_not_blank",
        ),
        CheckConstraint(
            f"name_fingerprint = btrim(name_fingerprint, {WHITESPACE}) AND length(name_fingerprint) > 0",
            name="ck_subject_name_fingerprint_not_blank",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_subject_name_subject",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "subject_id",
            "name_kind",
            "name_fingerprint",
            name="uq_subject_name_kind_fingerprint",
        ),
        Index("ix_subject_name_fingerprint", "name_fingerprint"),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    name_fingerprint: Mapped[str] = mapped_column(String(255), nullable=False)
    name_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    evidence_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.evidence.id",
            name="fk_subject_name_evidence_id",
            ondelete="RESTRICT",
        ),
    )


class Adjudication(Base):
    """Immutable human rationale that may justify an Identity decision."""

    __tablename__ = "adjudication"
    __table_args__: Any = (
        CheckConstraint(
            f"actor = btrim(actor, {WHITESPACE}) AND length(actor) > 0",
            name="ck_adjudication_actor_not_blank",
        ),
        CheckConstraint(
            f"rationale = btrim(rationale, {WHITESPACE}) AND length(rationale) > 0"
            " AND length(rationale) <= 4000",
            name="ck_adjudication_rationale_bounds",
        ),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor: Mapped[str] = mapped_column(String(255), nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ResolutionEvent(Base):
    """Append-only interpretation event for one Bronze Source Record."""

    __tablename__ = "resolution_event"
    __table_args__: Any = (
        _in_check(
            "operation",
            RESOLUTION_OPERATIONS,
            "ck_resolution_event_operation",
        ),
        CheckConstraint(
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
        *_decision_checks("resolution_event"),
        UniqueConstraint(
            "id",
            "source_record_id",
            name="uq_resolution_event_id_source_record",
        ),
        UniqueConstraint(
            "source_record_id",
            "sequence_no",
            name="uq_resolution_event_source_sequence",
        ),
        Index(
            "uq_resolution_event_one_open",
            "source_record_id",
            unique=True,
            postgresql_where=text("operation = 'open'"),
        ),
        Index("ix_resolution_event_source_record_id", "source_record_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source_record.id",
            name="fk_resolution_event_source_record_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("0"),
    )
    created_transaction_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("txid_current()"),
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    from_subject_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject.id",
            name="fk_resolution_event_from_subject_id",
            ondelete="RESTRICT",
        ),
    )
    to_subject_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject.id",
            name="fk_resolution_event_to_subject_id",
            ondelete="RESTRICT",
        ),
    )
    adjudication_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.adjudication.id",
            name="fk_resolution_event_adjudication_id",
            ondelete="RESTRICT",
        ),
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    method: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_class: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class ResolutionEvidence(Base):
    """Immutable Evidence membership in a resolution decision aggregate."""

    __tablename__ = "resolution_evidence"
    __table_args__: Any = ({"schema": SCHEMA_IDENTITY},)

    resolution_event_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.resolution_event.id",
            name="fk_resolution_evidence_event_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.evidence.id",
            name="fk_resolution_evidence_evidence_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )


class CurrentResolution(Base):
    """Rebuildable projection of the latest event for a Source Record."""

    __tablename__ = "current_resolution"
    __table_args__: Any = (
        _in_check(
            "state",
            RESOLUTION_STATES,
            "ck_current_resolution_state",
        ),
        CheckConstraint(
            "(state = 'resolved' AND subject_id IS NOT NULL) "
            "OR (state IN ('unresolved', 'needs_review') AND subject_id IS NULL)",
            name="ck_current_resolution_state_subject",
        ),
        ForeignKeyConstraint(
            ["last_event_id", "source_record_id"],
            [
                f"{SCHEMA_IDENTITY}.resolution_event.id",
                f"{SCHEMA_IDENTITY}.resolution_event.source_record_id",
            ],
            name="fk_current_resolution_last_event",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_current_resolution_unresolved",
            "source_record_id",
            postgresql_where=text("state = 'unresolved'"),
        ),
        Index(
            "ix_current_resolution_needs_review",
            "source_record_id",
            postgresql_where=text("state = 'needs_review'"),
        ),
        Index("ix_current_resolution_subject_id", "subject_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    source_record_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source_record.id",
            name="fk_current_resolution_source_record_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    subject_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject.id",
            name="fk_current_resolution_subject_id",
            ondelete="RESTRICT",
        ),
    )
    last_event_id: Mapped[int] = mapped_column(BigInteger, nullable=False, unique=True)
    state: Mapped[str] = mapped_column(String(16), nullable=False)


class SubjectChange(Base):
    """Append-only merge, split, or retirement decision."""

    __tablename__ = "subject_change"
    __table_args__: Any = (
        _in_check(
            "operation",
            SUBJECT_CHANGE_OPERATIONS,
            "ck_subject_change_operation",
        ),
        *_decision_checks("subject_change"),
        {"schema": SCHEMA_IDENTITY},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    created_transaction_id: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        server_default=text("txid_current()"),
    )
    operation: Mapped[str] = mapped_column(String(16), nullable=False)
    adjudication_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.adjudication.id",
            name="fk_subject_change_adjudication_id",
            ondelete="RESTRICT",
        ),
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(6, 5), nullable=False)
    method: Mapped[str] = mapped_column(String(128), nullable=False)
    method_version: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_class: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )


class SubjectChangeMember(Base):
    """Typed input or output membership in one Subject change."""

    __tablename__ = "subject_change_member"
    __table_args__: Any = (
        _in_check(
            "subject_kind",
            SUBJECT_KINDS,
            "ck_subject_change_member_subject_kind",
        ),
        _in_check(
            "role",
            SUBJECT_CHANGE_ROLES,
            "ck_subject_change_member_role",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_subject_change_member_subject",
            ondelete="RESTRICT",
        ),
        Index("ix_subject_change_member_subject_id", "subject_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_change_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject_change.id",
            name="fk_subject_change_member_change_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    role: Mapped[str] = mapped_column(String(16), primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)


class SubjectChangeEvidence(Base):
    """Immutable Evidence membership in a Subject-change aggregate."""

    __tablename__ = "subject_change_evidence"
    __table_args__: Any = ({"schema": SCHEMA_IDENTITY},)

    subject_change_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject_change.id",
            name="fk_subject_change_evidence_change_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    evidence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.evidence.id",
            name="fk_subject_change_evidence_evidence_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )


class SubjectCurrentness(Base):
    """Rebuildable current/retired state for every Subject."""

    __tablename__ = "subject_currentness"
    __table_args__: Any = (
        _in_check(
            "subject_kind",
            SUBJECT_KINDS,
            "ck_subject_currentness_subject_kind",
        ),
        CheckConstraint(
            "(is_current AND retired_by_change_id IS NULL AND retirement_reason IS NULL) "
            "OR "
            "(NOT is_current AND retired_by_change_id IS NOT NULL "
            "AND retirement_reason IS NOT NULL)",
            name="ck_subject_currentness_retirement",
        ),
        CheckConstraint(
            "retirement_reason IS NULL OR retirement_reason IN ('merge', 'split', 'retire')",
            name="ck_subject_currentness_retirement_reason",
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_subject_currentness_subject",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_subject_currentness_current",
            "subject_id",
            postgresql_where=text("is_current"),
        ),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    is_current: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        server_default=text("true"),
    )
    retired_by_change_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject_change.id",
            name="fk_subject_currentness_retired_by_change_id",
            ondelete="RESTRICT",
        ),
    )
    retirement_reason: Mapped[str | None] = mapped_column(String(16))


class SubjectLineage(Base):
    """Rebuildable directed edge from a retired Subject to its successor."""

    __tablename__ = "subject_lineage"
    __table_args__: Any = (
        CheckConstraint(
            "predecessor_subject_id <> successor_subject_id",
            name="ck_subject_lineage_no_self_edge",
        ),
        ForeignKeyConstraint(
            ["predecessor_subject_id", "predecessor_subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_subject_lineage_predecessor",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["successor_subject_id", "successor_subject_kind"],
            [f"{SCHEMA_IDENTITY}.subject.id", f"{SCHEMA_IDENTITY}.subject.kind"],
            name="fk_subject_lineage_successor",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_subject_lineage_predecessor",
            "predecessor_subject_id",
        ),
        Index("ix_subject_lineage_successor", "successor_subject_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    subject_change_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject_change.id",
            name="fk_subject_lineage_change_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
    predecessor_subject_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    successor_subject_id: Mapped[int] = mapped_column(
        BigInteger,
        primary_key=True,
    )
    predecessor_subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    successor_subject_kind: Mapped[str] = mapped_column(String(32), nullable=False)


class AppliedSubjectChange(Base):
    """Immutable seal written after a Subject change is validated and applied."""

    __tablename__ = "applied_subject_change"
    __table_args__: Any = ({"schema": SCHEMA_IDENTITY},)

    subject_change_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_IDENTITY}.subject_change.id",
            name="fk_applied_subject_change_id",
            ondelete="RESTRICT",
        ),
        primary_key=True,
    )
