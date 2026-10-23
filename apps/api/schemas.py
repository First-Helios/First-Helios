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
    """A venue: one Organization operating at one Place (an Establishment).

    ``organization_id`` is the operating Organization's id, the value the
    list's ``organization`` filter takes.
    """

    id: int
    name: str | None
    organization_id: int
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
    """A variant (e.g. a size) or a modifier (an add-on) and its prices.

    ``id`` is the node's ``item_id`` for ``GET /v1/items/{item_id}/price-history``.
    """

    id: str
    key: str
    name: str | None
    prices: list[MenuPriceResponse]


class MenuItemResponse(BaseModel):
    """A dish. ``name`` is null when the source names no item. ``id`` is the
    node's ``item_id`` for ``GET /v1/items/{item_id}/price-history``; null when
    the item has no prices of its own (only its variants or modifiers are)."""

    id: str | None
    key: str
    name: str | None
    description: str | None
    prices: list[MenuPriceResponse]
    variants: list[MenuOptionResponse]
    modifiers: list[MenuOptionResponse]


class MenuSectionResponse(BaseModel):
    """A named section of a menu. ``name`` is null when the source names no
    section. ``id`` is the section's ``item_id`` for its price history; null
    unless the section is priced."""

    id: str | None
    key: str
    name: str | None
    prices: list[MenuPriceResponse]
    items: list[MenuItemResponse]
    modifiers: list[MenuOptionResponse]


class MenuResponse(BaseModel):
    """One source menu (a source record's page stream) and the scope it was
    claimed for. ``organization`` prices are the operator's shared claims,
    never merged into this venue's own (ADR-0005 §11). ``source_url`` is the
    page its most recent price was read from (ADR-0008 Amendment 4); null when
    no price's provenance reaches a fetched page."""

    scope: MenuScope
    source_url: str | None
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
#: Price-index area kinds (ADR-0007 Amendment 3): two lat/lon grids and the
#: citywide ``all`` row. A point names a cell only on a grid.
AreaKind = Literal["latlon_grid_0p01", "latlon_grid_0p05", "all"]
GridAreaKind = Literal["latlon_grid_0p01", "latlon_grid_0p05"]


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


class PriceIndexCellResponse(PriceIndexGroupResponse):
    """One price-index row of the listed area kind: its area and its group.

    ``area_key`` is the value ``GET /v1/venues`` takes as ``area`` with the same
    ``area_kind``. ``cell_lat``/``cell_lon`` are the cell's south-west corner;
    null for the citywide ``all`` row.
    """

    area_key: str
    cell_lat: float | None
    cell_lon: float | None


class PriceIndexCellList(BaseModel):
    """A cursor-paginated page of every price-index row of one area kind.

    Items are ordered by ``(area_key, category_kind, category_key,
    currency_code)``: text order, not map order. Every cell of the kind spans
    ``cell_size_degrees`` north and east of its corner; null for ``all``.
    ``as_of`` is the earliest refresh instant on the page; null when ``items``
    is empty. ``next_cursor`` is null on the last page.
    """

    area_kind: str
    cell_size_degrees: float | None
    as_of: datetime | None
    items: list[PriceIndexCellResponse]
    next_cursor: str | None

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class PriceIndexAreaResponse(BaseModel):
    """The price index of the placed venues inside a drawn boundary (ADR-0020 §3).

    ``boundary`` is the normalized corners as ``[lat, lon]`` pairs, without a
    closing repeat. Each item is computed exactly as a stored price-index row
    is, over the venues the index places inside the boundary: shared chain
    menus and multi-venue organizations are left out, so ``venue_count`` can
    be lower than the number of venues with a menu there. ``as_of`` is the
    refresh instant of those placements; null, with ``items: []``, when the
    boundary holds no placed venue.
    """

    boundary: list[tuple[float, float]]
    as_of: datetime | None
    items: list[PriceIndexGroupResponse]

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class AreaItemResponse(BaseModel):
    """One priced item or variant row behind a drawn area's price index.

    ``item_id`` is the node's id for ``GET /v1/items/{item_id}/price-history``.
    ``item_name`` is the item's name; ``variant_name`` the variant's (e.g. a
    size), null on an item's own price. ``age_seconds`` is the observation's age
    at request time, never negative; null when there is no observation time.
    """

    venue_id: int
    venue_name: str | None
    item_id: str
    section_name: str | None
    item_name: str | None
    variant_name: str | None
    amount_minor: int
    currency_code: str
    channel: Channel
    service_period: str | None
    observed_at: datetime | None
    age_seconds: int | None
    source_kind: SourceKind | None

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class AreaItemList(BaseModel):
    """A cursor-paginated page of the priced rows behind a drawn area's price index.

    Items are ordered by ``amount_minor`` (cheapest first), then by the row's
    business key, so the order is total. ``as_of`` is the earliest refresh
    instant on the page; null when ``items`` is empty. ``next_cursor`` is null
    on the last page.
    """

    as_of: datetime | None
    items: list[AreaItemResponse]
    next_cursor: str | None

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


#: Accepted history states (ADR-0018 §B6): the served states plus the derived
#: no-value reasons history mode can return.
HistoryState = Literal["priced", "unknown", "unavailable", "absent", "withdrawn", "unresolved_base"]


class PriceHistoryPointResponse(BaseModel):
    """The accepted answer from ``known_from`` until the next point.

    ``known_from`` is the acceptance instant of the page that made this the
    answer. ``amount_minor`` is null unless ``state`` is ``priced``;
    ``observed_at``, ``source_kind`` and ``confidence`` are null for a derived
    state (``absent``, ``withdrawn``, ``unresolved_base``).
    """

    known_from: datetime
    state: HistoryState
    amount_minor: int | None
    observed_at: datetime | None
    source_kind: SourceKind | None
    confidence: float | None

    @field_serializer("known_from")
    def _serialize_known_from(self, value: datetime) -> _DateTimeStr:
        return _utc_iso(value)

    @field_serializer("observed_at")
    def _serialize_observed_at(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class PriceTrailResponse(BaseModel):
    """The points of one effective context and currency, oldest first."""

    channel: Channel
    service_period: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    currency_code: str
    points: list[PriceHistoryPointResponse]

    @field_serializer("valid_from", "valid_to")
    def _serialize_times(self, value: datetime | None) -> _DateTimeStr | None:
        return _utc_iso(value) if value is not None else None


class PriceHistoryResponse(BaseModel):
    """The accepted observation trail behind one menu node's prices.

    Computed live from committed Menu, so ``as_of`` is the request instant.
    """

    item_id: str
    as_of: datetime
    trails: list[PriceTrailResponse]

    @field_serializer("as_of")
    def _serialize_as_of(self, value: datetime) -> _DateTimeStr:
        return _utc_iso(value)


class ErrorResponse(BaseModel):
    """The uniform error body returned by every non-2xx response."""

    detail: str
    code: ErrorCode
    trace_id: str
