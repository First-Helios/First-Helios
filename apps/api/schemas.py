"""Pydantic v2 wire models for the read API (ADR-0008).

The wire format is a contract, kept deliberately separate from the SQLAlchemy
ORM: a column rename must not silently become a breaking API change. Field names
are ``snake_case``; timestamps serialize as ISO-8601 UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, WithJsonSchema, field_serializer

#: A custom serializer's own return-type annotation drives the published
#: schema for that field in serialization mode (pydantic ignores the field's
#: declared type there), so a bare ``str``/``str | None`` return type would
#: drop the ``format: date-time`` hint OpenAPI consumers rely on. Carry it on
#: the return annotation instead so the documented schema doesn't regress
#: (R37).
_DateTimeStr = Annotated[str, WithJsonSchema({"type": "string", "format": "date-time"})]

#: Stable, documented error codes clients switch on (ADR-0008 SS4). Declared as
#: a Literal (not a bare ``str``) so both runtime validation and the published
#: OpenAPI schema enumerate the exact set (R37).
ErrorCode = Literal[
    "not_found",
    "validation_error",
    "invalid_cursor",
    "method_not_allowed",
    "service_unavailable",
    "internal_error",
]


def _utc_iso(value: datetime) -> str:
    """Render a datetime as ISO-8601 UTC with a literal ``Z`` offset.

    Naive datetimes are treated as already UTC (the DB stores UTC); aware
    datetimes are converted. Either way the wire format is always UTC,
    regardless of the DB session's ``TimeZone`` setting (R50).
    """
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")


class VenueResponse(BaseModel):
    """A venue: one Organization operating at one Place (an Establishment)."""

    id: int
    name: str | None
    organization_kind: str
    address: str | None
    latitude: float | None
    longitude: float | None
    operating_status: str
    valid_from: datetime
    valid_to: datetime | None

    @field_serializer("valid_from")
    def _serialize_valid_from(self, value: datetime) -> _DateTimeStr:
        return _utc_iso(value)

    @field_serializer("valid_to")
    def _serialize_valid_to(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class VenueList(BaseModel):
    """A cursor-paginated page of venues; ``next_cursor`` is null on the last."""

    items: list[VenueResponse]
    next_cursor: str | None


#: Source-asserted price states served on the wire; the selector's derived
#: no-value reasons stay internal (``gold.menu_read.SERVED_PRICE_STATES``).
PriceState = Literal["priced", "unknown", "unavailable"]
#: How the price was read (ADR-0005 §11 interpretation kinds).
SourceKind = Literal["jsonld", "dom", "pdf", "llm"]
Channel = Literal["unspecified", "dine_in", "takeaway"]
MenuScope = Literal["establishment", "organization"]


class MenuPriceResponse(BaseModel):
    """One price of a menu node in one effective context.

    ``amount_minor`` is null unless ``state`` is ``priced``. ``age_seconds`` is
    the observation's age at request time (``observed_at`` to now, never
    negative); null when there is no observation time.
    """

    state: PriceState
    amount_minor: int | None
    currency_code: str
    channel: Channel
    service_period: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    observed_at: datetime | None
    age_seconds: int | None
    source_kind: SourceKind | None
    confidence: float | None

    @field_serializer("valid_from", "valid_to", "observed_at")
    def _serialize_times(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class MenuOptionResponse(BaseModel):
    """A variant (e.g. a size) or a modifier (an add-on) and its prices."""

    key: str
    name: str | None
    prices: list[MenuPriceResponse]


class MenuItemResponse(BaseModel):
    """A dish. ``name`` is null when Gold holds no row for the item itself
    (only its variants are priced)."""

    key: str
    name: str | None
    description: str | None
    prices: list[MenuPriceResponse]
    variants: list[MenuOptionResponse]
    modifiers: list[MenuOptionResponse]


class MenuSectionResponse(BaseModel):
    """A named section of a menu. ``name`` is null unless the section itself is
    priced: Gold carries no section names yet."""

    key: str
    name: str | None
    prices: list[MenuPriceResponse]
    items: list[MenuItemResponse]
    modifiers: list[MenuOptionResponse]


class MenuResponse(BaseModel):
    """One source menu (a source record's page stream) and the scope it was
    claimed for. ``organization`` prices are the operator's shared claims,
    never merged into this venue's own (ADR-0005 §11)."""

    scope: MenuScope
    sections: list[MenuSectionResponse]


class VenueMenuResponse(BaseModel):
    """A venue's current menu from Gold. ``as_of`` is the oldest refresh
    instant behind the served rows; null when there is no current menu."""

    venue_id: int
    as_of: datetime | None
    menus: list[MenuResponse]

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


#: Request filters on ``GET /v1/price-index``: the values the index holds today.
#: ``course`` joins ``CategoryKind`` additively (ADR-0016 §6).
CategoryKind = Literal["all"]
CurrencyCode = Literal["USD"]


class PriceIndexGroupResponse(BaseModel):
    """Venue-weighted price statistics for one category and currency of a cell.

    Each venue weighs one: its sample is the median of its priced rows, and the
    statistics are over those venue medians, in integer currency minor units.
    ``low_sample`` is true when ``venue_count`` is below ``min_venues``; the
    statistics are null when ``venue_count`` is 0. ``organization_venue_count``
    venues were placed through their Organization's own menu. ``priced_count``
    and ``unpriced_count`` count the item/variant rows behind the group.
    ``age_seconds`` is the oldest observation's age at request time, never
    negative; null when nothing is priced.
    """

    category_kind: str
    category_key: str
    currency_code: str
    venue_count: int
    organization_venue_count: int
    priced_count: int
    unpriced_count: int
    min_venues: int
    low_sample: bool
    p25_minor: int | None
    median_minor: int | None
    p75_minor: int | None
    min_minor: int | None
    max_minor: int | None
    oldest_observed_at: datetime | None
    newest_observed_at: datetime | None
    age_seconds: int | None

    @field_serializer("oldest_observed_at", "newest_observed_at")
    def _serialize_times(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class PriceIndexResponse(BaseModel):
    """The price index for the lat/lon grid cell containing the requested point.

    The cell is named by its south-west corner (``cell_lat``, ``cell_lon``) and
    spans ``cell_size_degrees`` north and east. ``as_of`` is the index's
    refresh instant; null, with ``items: []``, when the index has no row for
    the cell.
    """

    area_kind: str
    area_key: str
    cell_lat: float
    cell_lon: float
    cell_size_degrees: float
    as_of: datetime | None
    items: list[PriceIndexGroupResponse]

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class ErrorResponse(BaseModel):
    """The uniform error body returned by every non-2xx response."""

    detail: str
    code: ErrorCode
    trace_id: str
