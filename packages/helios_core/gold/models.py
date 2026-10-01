"""The ``gold.current_menu`` read model (ADR-0006) and ``gold.price_index`` (ADR-0007).

One row per projected ``(scope subject, source record, root key, target native
path, effective context, currency)`` (``uq_gold_current_menu``): the
deterministic ``select_price`` result materialized for fast reads. Business
columns are a pure function of committed Bronze/Identity/Menu; ``refreshed_at``
is refresh-run metadata and is excluded from rebuild-equality.
FKs point only at ``identity``, ``menu`` and ``bronze`` with ``RESTRICT``; no
authoritative table references Gold, and Gold is never a write target for them.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from packages.helios_core.db.base import SCHEMA_GOLD, Base

_PRICE_STATES = (
    "priced",
    "unknown",
    "unavailable",
    "absent",
    "withdrawn",
    "unresolved_base",
    "unresolved_scope",
    "not_operating",
)


class CurrentMenu(Base):
    __tablename__ = "current_menu"
    __table_args__: Any = (
        UniqueConstraint(
            "subject_id",
            "subject_kind",
            "source_record_id",
            "root_key",
            "target_kind",
            "target_path",
            "channel",
            "service_period",
            "valid_from",
            "valid_to",
            "currency_code",
            name="uq_gold_current_menu",
            postgresql_nulls_not_distinct=True,
        ),
        ForeignKeyConstraint(
            ["subject_id", "subject_kind"],
            ["identity.subject.id", "identity.subject.kind"],
            name="fk_gold_current_menu_subject",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["source_record_id"],
            ["bronze.source_record.id"],
            name="fk_gold_current_menu_record",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["currency_code"],
            ["menu.currency.code"],
            name="fk_gold_current_menu_currency",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["price_page_id"],
            ["menu.menu_page.id"],
            name="fk_gold_current_menu_price_page",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        ForeignKeyConstraint(
            ["content_page_id"],
            ["menu.menu_page.id"],
            name="fk_gold_current_menu_content_page",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        Index("ix_gold_current_menu_scope", "subject_id", "subject_kind"),
        Index("ix_gold_current_menu_record", "source_record_id"),
        Index("ix_gold_current_menu_currency", "currency_code"),
        Index("ix_gold_current_menu_price_page", "price_page_id"),
        Index("ix_gold_current_menu_content_page", "content_page_id"),
        CheckConstraint(
            "subject_kind IN ('organization', 'establishment')", name="ck_gold_scope_kind"
        ),
        CheckConstraint(
            "target_kind IN ('section', 'item', 'variant', 'modifier')", name="ck_gold_target_kind"
        ),
        CheckConstraint(
            "channel IN ('unspecified', 'dine_in', 'takeaway')", name="ck_gold_channel"
        ),
        CheckConstraint(
            "price_state IN (" + ", ".join(f"'{state}'" for state in _PRICE_STATES) + ")",
            name="ck_gold_price_state",
        ),
        CheckConstraint(
            "(price_state = 'priced') = (amount_minor IS NOT NULL)", name="ck_gold_amount"
        ),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="ck_gold_currency"),
        CheckConstraint(
            "staleness_seconds IS NULL OR staleness_seconds >= 0", name="ck_gold_staleness"
        ),
        CheckConstraint(
            "content_scope IS NULL OR content_scope IN ('local', 'organization')",
            name="ck_gold_content_scope",
        ),
        CheckConstraint(
            "price_confidence IS NULL OR price_confidence BETWEEN 0 AND 1",
            name="ck_gold_price_confidence",
        ),
        CheckConstraint(
            "isfinite(effective_instant) AND isfinite(refreshed_at) "
            "AND (price_observed_at IS NULL OR isfinite(price_observed_at)) "
            "AND (content_observed_at IS NULL OR isfinite(content_observed_at))",
            name="ck_gold_times",
        ),
        CheckConstraint("organization_claim_count >= 0", name="ck_gold_org_claims"),
        {"schema": SCHEMA_GOLD},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Projection identity / grain.
    subject_id: Mapped[int] = mapped_column(BigInteger)
    subject_kind: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[int] = mapped_column(BigInteger)
    root_key: Mapped[str] = mapped_column(String(512))
    target_kind: Mapped[str] = mapped_column(String(16))
    target_path: Mapped[str] = mapped_column(Text)
    channel: Mapped[str] = mapped_column(String(16))
    service_period: Mapped[str | None] = mapped_column(String(128))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    currency_code: Mapped[str] = mapped_column(String(3))
    effective_instant: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Local price outcome (mirrors selection.PriceResult).
    price_state: Mapped[str] = mapped_column(String(16))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    price_scope_subject_id: Mapped[int | None] = mapped_column(BigInteger)
    price_source_kind: Mapped[str | None] = mapped_column(String(16))
    price_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    price_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    price_page_id: Mapped[int | None] = mapped_column(BigInteger)
    price_evidence_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    staleness_seconds: Mapped[int | None] = mapped_column(BigInteger)
    # Selected content (mirrors selection.ContentResult).
    content_scope: Mapped[str | None] = mapped_column(String(16))
    content_name: Mapped[str | None] = mapped_column(String(512))
    content_description: Mapped[str | None] = mapped_column(Text)
    content_source_kind: Mapped[str | None] = mapped_column(String(16))
    content_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    content_scope_subject_id: Mapped[int | None] = mapped_column(BigInteger)
    content_page_id: Mapped[int | None] = mapped_column(BigInteger)
    content_evidence_ids: Mapped[list[int]] = mapped_column(ARRAY(BigInteger))
    # Shared Organization claims are acknowledged but never merged as local.
    organization_claim_count: Mapped[int] = mapped_column(Integer)
    # Refresh-run metadata: excluded from rebuild-equality comparison.
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


# Policy vocabularies (ADR-0007 Amendment 1). A new grid resolution or category
# scheme (e.g. ``course``) is a new value here, not a new table or grain.
AREA_KINDS = ("latlon_grid_0p01",)
CATEGORY_KINDS = ("all",)

_STATS = (
    "p25_minor",
    "median_minor",
    "p75_minor",
    "min_minor",
    "max_minor",
    "oldest_observed_at",
    "newest_observed_at",
)


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


class PriceIndex(Base):
    """``gold.price_index``: venue-weighted price percentiles per area and category (ADR-0007).

    One row per ``(area, category, currency)`` (``uq_gold_price_index``),
    aggregated from ``gold.current_menu`` only. Each contributing venue weighs
    one: its median priced item/variant amount in the group is one sample, and
    the percentiles are over those venue medians (``percentile_disc``, so every
    statistic is an observed integer amount). ``low_sample`` flags groups below
    the stored ``min_venues`` policy; such rows are kept so coverage stays
    measurable. Business columns are a pure function of ``current_menu`` and
    Identity at ``effective_instant``; ``refreshed_at`` is run metadata.
    """

    __tablename__ = "price_index"
    __table_args__: Any = (
        UniqueConstraint(
            "area_kind",
            "area_key",
            "category_kind",
            "category_key",
            "currency_code",
            name="uq_gold_price_index",
        ),
        ForeignKeyConstraint(
            ["currency_code"],
            ["menu.currency.code"],
            name="fk_gold_price_index_currency",
            ondelete="RESTRICT",
            onupdate="NO ACTION",
        ),
        Index("ix_gold_price_index_currency", "currency_code"),
        CheckConstraint(_in("area_kind", AREA_KINDS), name="ck_gold_price_index_area_kind"),
        CheckConstraint(
            _in("category_kind", CATEGORY_KINDS), name="ck_gold_price_index_category_kind"
        ),
        CheckConstraint(
            "cell_lat BETWEEN -90 AND 90 AND cell_lon BETWEEN -180 AND 180",
            name="ck_gold_price_index_cell",
        ),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="ck_gold_price_index_currency"),
        CheckConstraint(
            "venue_count >= 0 AND organization_venue_count BETWEEN 0 AND venue_count "
            "AND priced_count >= venue_count AND unpriced_count >= 0 "
            "AND priced_count + unpriced_count > 0 AND min_venues >= 1",
            name="ck_gold_price_index_counts",
        ),
        CheckConstraint(
            f"(venue_count = 0 AND num_nulls({', '.join(_STATS)}) = {len(_STATS)}) "
            f"OR (venue_count > 0 AND num_nulls({', '.join(_STATS)}) = 0 "
            "AND 0 <= min_minor AND min_minor <= p25_minor AND p25_minor <= median_minor "
            "AND median_minor <= p75_minor AND p75_minor <= max_minor "
            "AND oldest_observed_at <= newest_observed_at)",
            name="ck_gold_price_index_stats",
        ),
        CheckConstraint("low_sample = (venue_count < min_venues)", name="ck_gold_price_index_low"),
        CheckConstraint(
            "isfinite(effective_instant) AND isfinite(refreshed_at) "
            "AND (oldest_observed_at IS NULL OR isfinite(oldest_observed_at)) "
            "AND (newest_observed_at IS NULL OR isfinite(newest_observed_at))",
            name="ck_gold_price_index_times",
        ),
        {"schema": SCHEMA_GOLD},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Grain: area x category x currency.
    area_kind: Mapped[str] = mapped_column(String(32))
    area_key: Mapped[str] = mapped_column(String(64))  # "<cell_lat>,<cell_lon>"
    cell_lat: Mapped[Decimal] = mapped_column(Numeric(9, 6))  # south-west corner
    cell_lon: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    category_kind: Mapped[str] = mapped_column(String(32))
    category_key: Mapped[str] = mapped_column(String(128))
    currency_code: Mapped[str] = mapped_column(String(3))
    effective_instant: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Sample honesty.
    venue_count: Mapped[int] = mapped_column(Integer)
    organization_venue_count: Mapped[int] = mapped_column(Integer)
    priced_count: Mapped[int] = mapped_column(Integer)
    unpriced_count: Mapped[int] = mapped_column(Integer)
    min_venues: Mapped[int] = mapped_column(Integer)
    low_sample: Mapped[bool] = mapped_column()
    # Venue-weighted statistics, integer currency minor units.
    p25_minor: Mapped[int | None] = mapped_column(BigInteger)
    median_minor: Mapped[int | None] = mapped_column(BigInteger)
    p75_minor: Mapped[int | None] = mapped_column(BigInteger)
    min_minor: Mapped[int | None] = mapped_column(BigInteger)
    max_minor: Mapped[int | None] = mapped_column(BigInteger)
    oldest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    newest_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Refresh-run metadata: excluded from rebuild-equality comparison.
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
