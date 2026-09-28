"""Typed SQLAlchemy models for durable, source-faithful Bronze provenance."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.helios_core.db.base import SCHEMA_BRONZE, Base

# Python's ``str.strip()`` whitespace; see migration 12a76ebed458.
WHITESPACE = f"{SCHEMA_BRONZE}.whitespace()"


def _canonical(column: str, name: str) -> CheckConstraint:
    """Nonblank and trimmed, as ``_require_trimmed`` checks it in Python."""
    return CheckConstraint(
        f"{column} = btrim({column}, {WHITESPACE}) AND length({column}) > 0", name=name
    )


class Source(Base):
    """A stable namespace for source-local record keys."""

    __tablename__ = "source"
    __table_args__: Any = (
        UniqueConstraint("namespace", name="uq_source_namespace"),
        _canonical("namespace", "ck_source_namespace_canonical"),
        _canonical("kind", "ck_source_kind_canonical"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    namespace: Mapped[str] = mapped_column(String(128), nullable=False)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)


class SourceEndpoint(Base):
    """A canonical retrievable location exposed by a Source."""

    __tablename__ = "source_endpoint"
    __table_args__: Any = (
        UniqueConstraint(
            "source_id", "canonical_uri", name="uq_source_endpoint_source_canonical_uri"
        ),
        CheckConstraint(
            "endpoint_kind IN ('http', 'https', 's3', 'repo')", name="ck_source_endpoint_kind"
        ),
        UniqueConstraint("id", "source_id", name="uq_source_endpoint_id_source"),
        _canonical("canonical_uri", "ck_source_endpoint_uri_canonical"),
        _canonical("endpoint_kind", "ck_source_endpoint_kind_canonical"),
        Index("ix_source_endpoint_source_id", "source_id"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source.id",
            name="fk_source_endpoint_source_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    canonical_uri: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint_kind: Mapped[str] = mapped_column(String(64), nullable=False)


class Capture(Base):
    """An immutable acquisition attempt and its outcome."""

    __tablename__ = "capture"
    __table_args__: Any = (
        ForeignKeyConstraint(
            ["source_endpoint_id", "source_id"],
            [
                f"{SCHEMA_BRONZE}.source_endpoint.id",
                f"{SCHEMA_BRONZE}.source_endpoint.source_id",
            ],
            name="fk_capture_endpoint_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"content_hash IS NULL OR length(btrim(content_hash, {WHITESPACE})) > 0",
            name="ck_capture_content_hash_not_blank",
        ),
        CheckConstraint(
            f"bundle_path IS NULL OR length(btrim(bundle_path, {WHITESPACE})) > 0",
            name="ck_capture_bundle_path_not_blank",
        ),
        _canonical("outcome", "ck_capture_outcome_canonical"),
        CheckConstraint(
            "outcome IN ('succeeded', 'failed', 'skipped', 'rejected')", name="ck_capture_outcome"
        ),
        CheckConstraint(
            "(outcome = 'succeeded') = (reason_code IS NULL)",
            name="ck_capture_reason_matches_outcome",
        ),
        CheckConstraint(
            "reason_code IS NULL OR reason_code ~ '^[a-z][a-z0-9_]*$'",
            name="ck_capture_reason_code_format",
        ),
        CheckConstraint("isfinite(fetched_at)", name="ck_capture_fetched_at_finite"),
        UniqueConstraint("id", "source_id", name="uq_capture_id_source"),
        Index("ix_capture_source_id", "source_id"),
        Index("ix_capture_source_endpoint_id", "source_endpoint_id"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source.id",
            name="fk_capture_source_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    source_endpoint_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128))
    bundle_path: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(64), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceRecord(Base):
    """One durable source-local entity claim, whether resolved or not."""

    __tablename__ = "source_record"
    __table_args__: Any = (
        UniqueConstraint(
            "source_id",
            "external_key",
            name="uq_source_record_source_external_key",
        ),
        UniqueConstraint("id", "source_id", name="uq_source_record_id_source"),
        _canonical("external_key", "ck_source_record_external_key_canonical"),
        CheckConstraint("isfinite(first_seen_at)", name="ck_source_record_first_seen_finite"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source.id",
            name="fk_source_record_source_id",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    external_key: Mapped[str] = mapped_column(String(512), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class SourceRecordVersion(Base):
    """An immutable observation of what a Source Record asserted."""

    __tablename__ = "source_record_version"
    __table_args__: Any = (
        ForeignKeyConstraint(
            ["source_record_id", "source_id"],
            [
                f"{SCHEMA_BRONZE}.source_record.id",
                f"{SCHEMA_BRONZE}.source_record.source_id",
            ],
            name="fk_source_record_version_record_source",
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["capture_id", "source_id"],
            [
                f"{SCHEMA_BRONZE}.capture.id",
                f"{SCHEMA_BRONZE}.capture.source_id",
            ],
            name="fk_source_record_version_capture_source",
            ondelete="RESTRICT",
        ),
        CheckConstraint(
            f"length(btrim(content_hash, {WHITESPACE})) > 0",
            name="ck_source_record_version_content_hash_not_blank",
        ),
        CheckConstraint(
            "isfinite(observed_at)",
            name="ck_source_record_version_observed_at_finite",
        ),
        ForeignKeyConstraint(
            ["identity_match_endpoint_id", "source_id"],
            [f"{SCHEMA_BRONZE}.source_endpoint.id", f"{SCHEMA_BRONZE}.source_endpoint.source_id"],
            name="fk_source_record_version_match_endpoint_source",
            ondelete="RESTRICT",
        ),
        Index(
            "ix_source_record_version_identity_match_endpoint_id",
            "identity_match_endpoint_id",
            postgresql_where=text("identity_match_endpoint_id IS NOT NULL"),
        ),
        Index("ix_source_record_version_source_record_id", "source_record_id"),
        Index("ix_source_record_version_capture_id", "capture_id"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_record_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    capture_id: Mapped[int | None] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    identity_match_endpoint_id: Mapped[int | None] = mapped_column(BigInteger)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Evidence(Base):
    """An immutable locator into exactly one Capture or Record Version."""

    __tablename__ = "evidence"
    __table_args__: Any = (
        CheckConstraint(
            "(source_record_version_id IS NOT NULL) <> (capture_id IS NOT NULL)",
            name="ck_evidence_exactly_one_target",
        ),
        CheckConstraint(
            f"length(btrim(locator, {WHITESPACE})) > 0",
            name="ck_evidence_locator_not_blank",
        ),
        CheckConstraint(
            f"length(btrim(excerpt_hash, {WHITESPACE})) > 0",
            name="ck_evidence_excerpt_hash_not_blank",
        ),
        CheckConstraint(
            "source_record_version_id IS NULL OR left(locator, 1) = '$'",
            name="ck_evidence_version_locator_jsonpath",
        ),
        Index("ix_evidence_source_record_version_id", "source_record_version_id"),
        Index("ix_evidence_capture_id", "capture_id"),
        {"schema": SCHEMA_BRONZE},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_record_version_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.source_record_version.id",
            name="fk_evidence_source_record_version_id",
            ondelete="RESTRICT",
        ),
    )
    capture_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            f"{SCHEMA_BRONZE}.capture.id",
            name="fk_evidence_capture_id",
            ondelete="RESTRICT",
        ),
    )
    locator: Mapped[str] = mapped_column(Text, nullable=False)
    excerpt_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
