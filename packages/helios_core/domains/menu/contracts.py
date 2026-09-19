"""Frozen Menu write contracts over committed Bronze/Identity input.

These are accepted claims, not source-truth certificates. No selector, fallback
price, operating-state reconstruction, or commit-time audit is provided here.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from datetime import datetime
from decimal import Decimal
from typing import Literal

SourceKind = Literal["jsonld", "dom", "pdf", "llm"]
Operation = Literal["initial", "observation", "correction", "withdrawal", "restoration"]
NodeKind = Literal["section", "item", "variant", "modifier"]
Effect = Literal["replace", "inherit", "suppress"]
SupportKind = Literal["direct", "inherited", "structural"]


class MenuConflictError(ValueError):
    """An existing revision or replay key has different aggregate content."""


class _Input:
    __slots__ = ()

    def __post_init__(self) -> None:
        # Dataclasses do not coerce; explicitly reject bool/float money and IDs.
        for field in fields(self):  # type: ignore[arg-type]
            value = getattr(self, field.name)
            if value is None:
                continue
            if field.name.endswith("_id") or field.name in {
                "position",
                "calories",
                "amount_minor",
                "stream_revision",
                "interpretation_revision",
            }:
                if type(value) is not int or not -(2**63) <= value < 2**63:
                    raise ValueError(f"{field.name} requires an exact BIGINT integer")
                if field.name.endswith("_id") or field.name.endswith("revision"):
                    if value <= 0:
                        raise ValueError(f"{field.name} must be positive")
                elif field.name != "amount_minor" and value < 0:
                    raise ValueError(f"{field.name} cannot be negative")
            if isinstance(value, str) and (not value or value != value.strip()):
                raise ValueError(f"{field.name} must be nonblank and trimmed")
            if isinstance(value, datetime) and value.utcoffset() is None:
                raise ValueError(f"{field.name} requires an aware timestamp")
            if field.name == "confidence" and (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or not 0 <= value <= 1
                or value != value.quantize(Decimal("0.0001"))
            ):
                raise ValueError(
                    "confidence requires a finite exact Decimal with at most four places"
                )
            if field.name == "evidence_ids" and (
                not isinstance(value, tuple) or any(type(i) is not int or i <= 0 for i in value)
            ):
                raise ValueError("Evidence IDs require a tuple of positive integers")
            if field.name == "dietary_tags" and (
                not isinstance(value, tuple)
                or any(
                    not isinstance(tag, str) or not tag or tag != tag.strip().lower()
                    for tag in value
                )
                or len(value) != len(set(value))
            ):
                raise ValueError("dietary tags must be normalized, unique strings")


@dataclass(frozen=True, slots=True, kw_only=True)
class PageInput(_Input):
    subject_id: int
    subject_kind: Literal["organization", "establishment"]
    source_record_version_id: int
    resolution_event_id: int
    root_key: str
    source_kind: SourceKind
    method: str
    method_version: str
    stream_revision: int
    interpretation_revision: int
    confidence: Decimal
    operation: Operation
    evidence_ids: tuple[int, ...]
    base_organization_page_id: int | None = None
    supersedes_page_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ApplicabilityInput(_Input):
    applicability_key: str
    channel: Literal["unspecified", "dine_in", "takeaway"]
    evidence_ids: tuple[int, ...]
    service_period: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class SectionInput(_Input):
    section_key: str
    effect: Effect
    support_kind: SupportKind
    evidence_ids: tuple[int, ...] = ()
    source_native_key: str | None = None
    parent_section_key: str | None = None
    name: str | None = None
    course: str | None = None
    position: int | None = None
    applicability_key: str | None = None
    base_section_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ItemInput(_Input):
    item_key: str
    section_key: str
    effect: Effect
    support_kind: SupportKind
    evidence_ids: tuple[int, ...] = ()
    source_native_key: str | None = None
    name: str | None = None
    description: str | None = None
    calories: int | None = None
    dietary_tags: tuple[str, ...] | None = None
    position: int | None = None
    applicability_key: str | None = None
    base_item_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VariantInput(_Input):
    variant_key: str
    item_key: str
    effect: Effect
    support_kind: SupportKind
    evidence_ids: tuple[int, ...] = ()
    source_native_key: str | None = None
    label: str | None = None
    position: int | None = None
    applicability_key: str | None = None
    base_variant_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ModifierInput(_Input):
    modifier_key: str
    effect: Effect
    support_kind: SupportKind
    evidence_ids: tuple[int, ...] = ()
    item_key: str | None = None
    section_key: str | None = None
    source_native_key: str | None = None
    label: str | None = None
    required: bool | None = None
    position: int | None = None
    applicability_key: str | None = None
    base_modifier_id: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Target(_Input):
    kind: NodeKind
    key: str
    # A variant key is scoped to its item. Other target types leave this absent.
    item_key: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class PriceInput(_Input):
    observation_key: str
    target: Target
    applicability_key: str
    price_kind: Literal["absolute", "delta"]
    price_state: Literal["priced", "unknown", "unavailable"]
    amount_minor: int | None
    currency_code: str
    confidence: Decimal
    evidence_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class MenuAggregate:
    page: PageInput
    sections: tuple[SectionInput, ...] = ()
    items: tuple[ItemInput, ...] = ()
    variants: tuple[VariantInput, ...] = ()
    modifiers: tuple[ModifierInput, ...] = ()
    applicability: tuple[ApplicabilityInput, ...] = ()
    prices: tuple[PriceInput, ...] = ()


@dataclass(frozen=True, slots=True)
class MemberIdentity:
    table: str
    key: tuple[str, ...]
    id: int


@dataclass(frozen=True, slots=True)
class PersistedMenu:
    page_id: int
    members: tuple[MemberIdentity, ...]
    replayed: bool
