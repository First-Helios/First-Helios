"""Nine immutable Menu tables. Admission and aggregate checks live in the migration."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    FetchedValue,
    ForeignKeyConstraint,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from packages.helios_core.db.base import SCHEMA_MENU, Base


def _fk(
    columns: list[str], target: str, targets: list[str], name: str, *, deferred: bool = False
) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        columns,
        [f"{target}.{c}" for c in targets],
        name=name,
        ondelete="RESTRICT",
        onupdate="NO ACTION",
        deferrable=True if deferred else None,
        initially="DEFERRED" if deferred else None,
    )


def _text(column: str, limit: int = 512) -> str:
    return (
        f"({column} IS NULL OR (length({column}) BETWEEN 1 AND {limit} "
        f"AND {column} = btrim({column}, menu.whitespace()) AND {column} !~ '^[[:space:]]*$'))"
    )


def _member(table: str) -> tuple[Any, ...]:
    return (
        UniqueConstraint("id", "page_id", name=f"uq_{table}_id_page"),
        _fk(["page_id"], "menu.menu_page", ["id"], f"fk_{table}_page"),
    )


def _ref(table: str, column: str, target: str) -> tuple[Any, ...]:
    return (
        _fk(
            [column, "page_id"],
            f"menu.{target}",
            ["id", "page_id"],
            f"fk_{table}_{column}",
            deferred=True,
        ),
        Index(f"ix_{table}_{column}", column, "page_id"),
    )


def _node(
    table: str, kind: str, payload: tuple[str, ...], required: tuple[str, ...]
) -> tuple[Any, ...]:
    base = f"base_{kind}_id"
    absent = " AND ".join(
        f"{c} IS NULL" for c in (*payload, "position", "source_native_key", "applicability_id")
    )
    present = " AND ".join(f"{c} IS NOT NULL" for c in (*required, "position"))
    shape = (
        f"(effect = 'replace' AND support_kind = 'direct' AND {present}) OR "
        f"(effect = 'inherit' AND support_kind = 'inherited' AND {base} IS NOT NULL AND {absent}) OR "
        f"(effect = 'suppress' AND support_kind = 'direct' AND {base} IS NOT NULL AND {absent})"
    )
    if kind == "section":
        shape += (
            " OR (effect = 'replace' AND support_kind = 'structural' "
            "AND section_key = 'Unsectioned' AND name = 'Unsectioned' AND position = 0 "
            "AND base_section_id IS NULL AND parent_section_id IS NULL AND course IS NULL "
            "AND source_native_key IS NULL AND applicability_id IS NULL)"
        )
    return (
        *_member(table),
        *_ref(table, "applicability_id", "menu_applicability"),
        _fk([base], f"menu.{table}", ["id"], f"fk_{table}_base"),
        Index(
            f"uq_{table}_base",
            "page_id",
            base,
            unique=True,
            postgresql_where=text(f"{base} IS NOT NULL"),
        ),
        Index(f"ix_{table}_base", base),
        CheckConstraint(shape, name=f"ck_{table}_shape"),
        CheckConstraint("position >= 0", name=f"ck_{table}_position"),
        CheckConstraint(
            _text(f"{kind}_key") + " AND " + _text("source_native_key"), name=f"ck_{table}_keys"
        ),
    )


class Currency(Base):
    __tablename__ = "currency"
    __table_args__: Any = (
        CheckConstraint(
            "code ~ '^[A-Z]{3}$' AND minor_unit BETWEEN 0 AND 4", name="ck_menu_currency"
        ),
        {"schema": SCHEMA_MENU},
    )
    code: Mapped[str] = mapped_column(String(3), primary_key=True)
    minor_unit: Mapped[int] = mapped_column(SmallInteger)


class MenuPage(Base):
    __tablename__ = "menu_page"
    __table_args__: Any = (
        UniqueConstraint(
            "source_record_id",
            "root_key",
            "source_kind",
            "stream_revision",
            name="uq_menu_stream_revision",
        ),
        UniqueConstraint(
            "source_record_version_id",
            "root_key",
            "source_kind",
            "interpretation_revision",
            name="uq_menu_version_revision",
        ),
        Index(
            "uq_menu_successor",
            "supersedes_page_id",
            unique=True,
            postgresql_where=text("supersedes_page_id IS NOT NULL"),
        ),
        _fk(
            ["subject_id", "subject_kind"],
            "identity.subject",
            ["id", "kind"],
            "fk_menu_page_subject",
        ),
        _fk(["source_record_id"], "bronze.source_record", ["id"], "fk_menu_page_record"),
        _fk(
            ["source_record_version_id"],
            "bronze.source_record_version",
            ["id"],
            "fk_menu_page_version",
        ),
        _fk(["resolution_event_id"], "identity.resolution_event", ["id"], "fk_menu_page_event"),
        _fk(["supersedes_page_id"], "menu.menu_page", ["id"], "fk_menu_page_predecessor"),
        _fk(["base_organization_page_id"], "menu.menu_page", ["id"], "fk_menu_page_base"),
        Index("ix_menu_page_subject", "subject_id", "subject_kind", "root_key", "observed_at"),
        Index("ix_menu_page_event", "resolution_event_id"),
        Index("ix_menu_page_base", "base_organization_page_id"),
        Index(
            "ix_menu_page_operation",
            "source_record_id",
            "root_key",
            "source_kind",
            "operation",
            "stream_revision",
        ),
        CheckConstraint(
            "subject_kind IN ('organization', 'establishment')", name="ck_menu_page_scope"
        ),
        CheckConstraint("source_kind IN ('jsonld', 'dom', 'pdf', 'llm')", name="ck_menu_page_kind"),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_menu_page_confidence"),
        CheckConstraint(
            "stream_revision > 0 AND interpretation_revision > 0", name="ck_menu_page_revisions"
        ),
        CheckConstraint(
            "isfinite(observed_at) AND isfinite(accepted_at)", name="ck_menu_page_times"
        ),
        CheckConstraint(
            "(operation = 'withdrawal' AND state = 'withdrawn' AND base_organization_page_id IS NULL) OR (operation IN ('initial','observation','correction','restoration') AND state = 'published')",
            name="ck_menu_page_operation",
        ),
        CheckConstraint(
            "subject_kind = 'establishment' OR base_organization_page_id IS NULL",
            name="ck_menu_page_base_scope",
        ),
        CheckConstraint(
            _text("root_key")
            + " AND "
            + _text("method", 128)
            + " AND "
            + _text("method_version", 128),
            name="ck_menu_page_keys",
        ),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    subject_id: Mapped[int] = mapped_column(BigInteger)
    subject_kind: Mapped[str] = mapped_column(String(32))
    source_record_id: Mapped[int] = mapped_column(BigInteger)
    source_record_version_id: Mapped[int] = mapped_column(BigInteger)
    resolution_event_id: Mapped[int] = mapped_column(BigInteger)
    root_key: Mapped[str] = mapped_column(String(512))
    source_kind: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(128))
    method_version: Mapped[str] = mapped_column(String(128))
    stream_revision: Mapped[int] = mapped_column(BigInteger)
    interpretation_revision: Mapped[int] = mapped_column(BigInteger)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=FetchedValue()
    )
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    operation: Mapped[str] = mapped_column(String(16))
    state: Mapped[str] = mapped_column(String(16))
    base_organization_page_id: Mapped[int | None] = mapped_column(BigInteger)
    supersedes_page_id: Mapped[int | None] = mapped_column(BigInteger)
    created_transaction_id: Mapped[int] = mapped_column(BigInteger, server_default=FetchedValue())


class MenuApplicability(Base):
    __tablename__ = "menu_applicability"
    __table_args__: Any = (
        *_member("menu_applicability"),
        UniqueConstraint("page_id", "applicability_key", name="uq_menu_applicability_key"),
        UniqueConstraint(
            "page_id",
            "channel",
            "service_period",
            "valid_from",
            "valid_to",
            name="uq_menu_context",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "channel IN ('unspecified', 'dine_in', 'takeaway')", name="ck_menu_context_channel"
        ),
        CheckConstraint(
            "(valid_from IS NULL OR isfinite(valid_from)) AND (valid_to IS NULL OR isfinite(valid_to)) AND (valid_from IS NULL OR valid_to IS NULL OR valid_from < valid_to)",
            name="ck_menu_context_window",
        ),
        CheckConstraint(
            _text("applicability_key") + " AND " + _text("service_period", 128),
            name="ck_menu_context_keys",
        ),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    applicability_key: Mapped[str] = mapped_column(String(512))
    channel: Mapped[str] = mapped_column(String(16))
    service_period: Mapped[str | None] = mapped_column(String(128))
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MenuSection(Base):
    __tablename__ = "menu_section"
    __table_args__: Any = (
        *_node("menu_section", "section", ("name", "course"), ("name",)),
        UniqueConstraint("page_id", "section_key", name="uq_menu_section_key"),
        *_ref("menu_section", "parent_section_id", "menu_section"),
        Index(
            "uq_menu_section_native",
            "page_id",
            "parent_section_id",
            "source_native_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("source_native_key IS NOT NULL"),
        ),
        CheckConstraint(
            _text("name", 512) + " AND " + _text("course", 512), name="ck_menu_section_text"
        ),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    section_key: Mapped[str] = mapped_column(String(512))
    source_native_key: Mapped[str | None] = mapped_column(String(512))
    parent_section_id: Mapped[int | None] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(512))
    course: Mapped[str | None] = mapped_column(String(128))
    position: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int | None] = mapped_column(BigInteger)
    base_section_id: Mapped[int | None] = mapped_column(BigInteger)
    effect: Mapped[str] = mapped_column(String(16))
    support_kind: Mapped[str] = mapped_column(String(16))


class MenuItem(Base):
    __tablename__ = "menu_item"
    __table_args__: Any = (
        *_node(
            "menu_item",
            "item",
            ("name", "description", "calories", "dietary_tags"),
            ("name", "dietary_tags"),
        ),
        UniqueConstraint("page_id", "item_key", name="uq_menu_item_key"),
        *_ref("menu_item", "section_id", "menu_section"),
        Index(
            "uq_menu_item_native",
            "page_id",
            "section_id",
            "source_native_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("source_native_key IS NOT NULL"),
        ),
        CheckConstraint(
            _text("name", 512) + " AND " + _text("description", 8192), name="ck_menu_item_text"
        ),
        CheckConstraint(
            "calories >= 0 AND (dietary_tags IS NULL OR menu.valid_tags(dietary_tags))",
            name="ck_menu_item_values",
        ),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    item_key: Mapped[str] = mapped_column(String(512))
    source_native_key: Mapped[str | None] = mapped_column(String(512))
    section_id: Mapped[int] = mapped_column(BigInteger)
    name: Mapped[str | None] = mapped_column(String(512))
    description: Mapped[str | None] = mapped_column(Text)
    calories: Mapped[int | None] = mapped_column(BigInteger)
    dietary_tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    position: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int | None] = mapped_column(BigInteger)
    base_item_id: Mapped[int | None] = mapped_column(BigInteger)
    effect: Mapped[str] = mapped_column(String(16))
    support_kind: Mapped[str] = mapped_column(String(16))


class MenuVariant(Base):
    __tablename__ = "menu_variant"
    __table_args__: Any = (
        *_node("menu_variant", "variant", ("label",), ("label",)),
        UniqueConstraint("page_id", "item_id", "variant_key", name="uq_menu_variant_key"),
        *_ref("menu_variant", "item_id", "menu_item"),
        Index(
            "uq_menu_variant_native",
            "page_id",
            "item_id",
            "source_native_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("source_native_key IS NOT NULL"),
        ),
        CheckConstraint(_text("label", 512), name="ck_menu_variant_text"),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    variant_key: Mapped[str] = mapped_column(String(512))
    source_native_key: Mapped[str | None] = mapped_column(String(512))
    item_id: Mapped[int] = mapped_column(BigInteger)
    label: Mapped[str | None] = mapped_column(String(512))
    position: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int | None] = mapped_column(BigInteger)
    base_variant_id: Mapped[int | None] = mapped_column(BigInteger)
    effect: Mapped[str] = mapped_column(String(16))
    support_kind: Mapped[str] = mapped_column(String(16))


class MenuModifier(Base):
    __tablename__ = "menu_modifier"
    __table_args__: Any = (
        *_node("menu_modifier", "modifier", ("label", "required"), ("label", "required")),
        UniqueConstraint("page_id", "modifier_key", name="uq_menu_modifier_key"),
        *_ref("menu_modifier", "item_id", "menu_item"),
        *_ref("menu_modifier", "section_id", "menu_section"),
        Index(
            "uq_menu_modifier_native",
            "page_id",
            "item_id",
            "section_id",
            "source_native_key",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("source_native_key IS NOT NULL"),
        ),
        CheckConstraint(_text("label", 512), name="ck_menu_modifier_text"),
        CheckConstraint("num_nonnulls(item_id, section_id) = 1", name="ck_menu_modifier_parent"),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    modifier_key: Mapped[str] = mapped_column(String(512))
    source_native_key: Mapped[str | None] = mapped_column(String(512))
    item_id: Mapped[int | None] = mapped_column(BigInteger)
    section_id: Mapped[int | None] = mapped_column(BigInteger)
    label: Mapped[str | None] = mapped_column(String(512))
    required: Mapped[bool | None] = mapped_column(Boolean)
    position: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int | None] = mapped_column(BigInteger)
    base_modifier_id: Mapped[int | None] = mapped_column(BigInteger)
    effect: Mapped[str] = mapped_column(String(16))
    support_kind: Mapped[str] = mapped_column(String(16))


class PriceObservation(Base):
    __tablename__ = "price_observation"
    __table_args__: Any = (
        *_member("price_observation"),
        UniqueConstraint("page_id", "observation_key", name="uq_menu_price_key"),
        *_ref("price_observation", "section_id", "menu_section"),
        *_ref("price_observation", "item_id", "menu_item"),
        *_ref("price_observation", "variant_id", "menu_variant"),
        *_ref("price_observation", "modifier_id", "menu_modifier"),
        *_ref("price_observation", "applicability_id", "menu_applicability"),
        _fk(["currency_code"], "menu.currency", ["code"], "fk_menu_price_currency"),
        Index("ix_menu_price_currency", "currency_code"),
        CheckConstraint(
            "num_nonnulls(section_id, item_id, variant_id, modifier_id) = 1",
            name="ck_menu_price_target",
        ),
        CheckConstraint(
            "(price_state = 'priced' AND amount_minor IS NOT NULL) OR (price_state IN ('unknown','unavailable') AND amount_minor IS NULL)",
            name="ck_menu_price_state",
        ),
        CheckConstraint(
            "(modifier_id IS NOT NULL AND price_kind = 'delta') OR (modifier_id IS NULL AND price_kind = 'absolute' AND (amount_minor IS NULL OR amount_minor >= 0))",
            name="ck_menu_price_shape",
        ),
        CheckConstraint("confidence BETWEEN 0 AND 1", name="ck_menu_price_confidence"),
        CheckConstraint(_text("observation_key"), name="ck_menu_price_key"),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    observation_key: Mapped[str] = mapped_column(String(512))
    section_id: Mapped[int | None] = mapped_column(BigInteger)
    item_id: Mapped[int | None] = mapped_column(BigInteger)
    variant_id: Mapped[int | None] = mapped_column(BigInteger)
    modifier_id: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int] = mapped_column(BigInteger)
    price_kind: Mapped[str] = mapped_column(String(16))
    price_state: Mapped[str] = mapped_column(String(16))
    amount_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency_code: Mapped[str] = mapped_column(String(3))
    confidence: Mapped[Decimal] = mapped_column(Numeric(5, 4))


class EvidenceLink(Base):
    __tablename__ = "evidence_link"
    __table_args__: Any = (
        *_member("evidence_link"),
        _fk(["evidence_id"], "bronze.evidence", ["id"], "fk_menu_evidence"),
        Index("ix_menu_evidence", "evidence_id"),
        Index("ix_menu_evidence_page", "page_id"),
        CheckConstraint(
            "page_target::int + num_nonnulls(section_id, item_id, variant_id, modifier_id, applicability_id, price_id) = 1",
            name="ck_menu_evidence_target",
        ),
        Index(
            "uq_menu_evidence_page",
            "page_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("page_target"),
        ),
        *_ref("evidence_link", "section_id", "menu_section"),
        Index(
            "uq_menu_evidence_section",
            "section_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("section_id IS NOT NULL"),
        ),
        *_ref("evidence_link", "item_id", "menu_item"),
        Index(
            "uq_menu_evidence_item",
            "item_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("item_id IS NOT NULL"),
        ),
        *_ref("evidence_link", "variant_id", "menu_variant"),
        Index(
            "uq_menu_evidence_variant",
            "variant_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("variant_id IS NOT NULL"),
        ),
        *_ref("evidence_link", "modifier_id", "menu_modifier"),
        Index(
            "uq_menu_evidence_modifier",
            "modifier_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("modifier_id IS NOT NULL"),
        ),
        *_ref("evidence_link", "applicability_id", "menu_applicability"),
        Index(
            "uq_menu_evidence_applicability",
            "applicability_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("applicability_id IS NOT NULL"),
        ),
        *_ref("evidence_link", "price_id", "price_observation"),
        Index(
            "uq_menu_evidence_price",
            "price_id",
            "evidence_id",
            unique=True,
            postgresql_where=text("price_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_MENU},
    )
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    page_id: Mapped[int] = mapped_column(BigInteger)
    evidence_id: Mapped[int] = mapped_column(BigInteger)
    page_target: Mapped[bool] = mapped_column(Boolean)
    section_id: Mapped[int | None] = mapped_column(BigInteger)
    item_id: Mapped[int | None] = mapped_column(BigInteger)
    variant_id: Mapped[int | None] = mapped_column(BigInteger)
    modifier_id: Mapped[int | None] = mapped_column(BigInteger)
    applicability_id: Mapped[int | None] = mapped_column(BigInteger)
    price_id: Mapped[int | None] = mapped_column(BigInteger)
