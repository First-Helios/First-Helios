"""Discovery-owned append-only completion evidence and lifecycle checkpoints."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.helios_core.db.base import Base


class DiscoveryReleaseCompletion(Base):
    __tablename__ = "discovery_release_completion"
    __table_args__: Any = (
        UniqueConstraint(
            "release_endpoint",
            "coverage_key",
            "release_at",
            "poi_count",
            "predecessor",
            name="uq_discovery_completion_retry",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint("poi_count >= 0", name="ck_discovery_completion_count"),
        CheckConstraint("isfinite(release_at)", name="ck_discovery_completion_time"),
        Index("ix_discovery_completion_coverage_release", "coverage_key", "release_at"),
        {"schema": "bronze"},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    release_endpoint: Mapped[str] = mapped_column(Text)
    release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    coverage_key: Mapped[str] = mapped_column(Text)
    coverage: Mapped[dict[str, Any]] = mapped_column(JSONB)
    poi_count: Mapped[int] = mapped_column(BigInteger)
    predecessor: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )


class DiscoveryLifecycleState(Base):
    """Projection watermark or inferred closure origin; never rewrites Bronze."""

    __tablename__ = "discovery_lifecycle_state"
    __table_args__: Any = (
        CheckConstraint(
            "action IN ('projected', 'closed', 'reopened')", name="ck_discovery_lifecycle_action"
        ),
        CheckConstraint(
            "(action = 'closed') = (first_missing_at IS NOT NULL)",
            name="ck_discovery_lifecycle_closure",
        ),
        CheckConstraint("isfinite(release_at)", name="ck_discovery_lifecycle_time"),
        Index("ix_discovery_lifecycle_record", "source_record_id", "release_at"),
        Index("ix_discovery_lifecycle_subject", "subject_id", "id"),
        {"schema": "bronze"},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_record_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bronze.source_record.id", ondelete="RESTRICT")
    )
    version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("bronze.source_record_version.id", ondelete="RESTRICT")
    )
    # An identifier in the discovery journal, not an upward Bronze FK.
    subject_id: Mapped[int] = mapped_column(BigInteger)
    release_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    action: Mapped[str] = mapped_column(Text)
    first_missing_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.clock_timestamp()
    )
