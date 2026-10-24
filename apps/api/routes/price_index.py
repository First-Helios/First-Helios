"""Price-index read endpoints (ADR-0007 Amendments 2 and 3, ADR-0020; ROADMAP Phase 7).

Serves ``gold.price_index`` through
:mod:`packages.helios_core.gold.price_index_read` (ADR-0008 §9): the grid cell
containing a point, one bounded response with a row per category and currency;
every row of one area kind (0.01°, 0.05° or the citywide ``all``), a keyset
page at a time; and a drawn boundary's statistics and the priced items behind
them, computed from the stored placements. Every row carries its sample size
and ``low_sample`` flag, so an aggregate over four venues is never served as
though it were an index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any, cast

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this at runtime for Depends

from apps.api.boundaries import BoundaryQuery, boundary_param
from apps.api.db import get_session
from apps.api.item_ids import ItemId, encode_item_id
from apps.api.pagination import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    decode_area_item_cursor,
    decode_cell_cursor,
    encode_area_item_cursor,
    encode_cell_cursor,
)
from apps.api.schemas import (
    AreaItemList,
    AreaItemResponse,
    AreaKind,
    CategoryKind,
    CurrencyCode,
    ErrorResponse,
    GridAreaKind,
    PriceIndexAreaResponse,
    PriceIndexCellList,
    PriceIndexCellResponse,
    PriceIndexGroupResponse,
    PriceIndexResponse,
)
from packages.helios_core.gold.price_index import GRID_STEPS
from packages.helios_core.gold.price_index_read import (
    price_index_area,
    price_index_area_items,
    price_index_cell,
    price_index_cells,
)
from packages.helios_core.identity.models import Establishment, Organization

if TYPE_CHECKING:
    from apps.api.schemas import Channel, MenuScope, SourceKind
    from packages.helios_core.gold.price_index_read import AreaItemRow, PriceIndexRow

router = APIRouter(prefix="/price-index", tags=["price-index"])

_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "lat/lon is missing or out of range, or a filter value is unknown.",
    },
}
_CELLS_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "The cursor is malformed."},
    422: {
        "model": ErrorResponse,
        "description": "limit is out of range, or a filter value is unknown.",
    },
}


def _group(row: PriceIndexRow, now: datetime) -> PriceIndexGroupResponse:
    oldest = row.oldest_observed_at
    return PriceIndexGroupResponse(
        category_kind=row.category_kind,
        category_key=row.category_key,
        currency_code=row.currency_code,
        venue_count=row.venue_count,
        organization_venue_count=row.organization_venue_count,
        priced_count=row.priced_count,
        unpriced_count=row.unpriced_count,
        min_venues=row.min_venues,
        low_sample=row.low_sample,
        p25_minor=row.p25_minor,
        median_minor=row.median_minor,
        p75_minor=row.p75_minor,
        min_minor=row.min_minor,
        max_minor=row.max_minor,
        oldest_observed_at=oldest,
        newest_observed_at=row.newest_observed_at,
        # An age: an observation after the request instant is fresh, not negative.
        age_seconds=max(0, int((now - oldest).total_seconds())) if oldest else None,
    )


@router.get(
    "",
    response_model=PriceIndexResponse,
    summary="Get the price index for the grid cell containing a point",
    responses=_RESPONSES,
)
def get_price_index(
    session: Annotated[Session, Depends(get_session)],
    lat: Annotated[float, Query(ge=-90, le=90, description="Latitude, WGS 84 degrees.")],
    lon: Annotated[float, Query(ge=-180, le=180, description="Longitude, WGS 84 degrees.")],
    area_kind: Annotated[
        GridAreaKind,
        Query(
            description="The grid the point is floored on. The citywide row is read from "
            "/v1/price-index/cells?area_kind=all."
        ),
    ] = "latlon_grid_0p01",
    category_kind: Annotated[CategoryKind | None, Query()] = None,
    currency: Annotated[CurrencyCode | None, Query()] = None,
) -> PriceIndexResponse:
    """Return the venue-weighted price statistics of the cell containing ``lat``/``lon``.

    The cell is the ``area_kind`` grid's (0.01° by default). One item per
    category and currency the index holds for the cell, narrowed by
    ``category_kind`` and ``currency`` when given. Groups below ``min_venues``
    venues are served with ``low_sample: true``. A cell the index has no row for
    is ``200`` with ``items: []`` and ``as_of: null``.
    """
    # repr() round-trips, so 30.26 floors to the 30.26 cell, not 30.25.
    cell = price_index_cell(
        session,
        Decimal(repr(lat)),
        Decimal(repr(lon)),
        area_kind=area_kind,
        category_kind=category_kind,
        currency_code=currency,
    )
    now = datetime.now(UTC)
    return PriceIndexResponse(
        area_kind=cell.area_kind,
        area_key=cell.area_key,
        cell_lat=float(cell.cell_lat),
        cell_lon=float(cell.cell_lon),
        cell_size_degrees=float(GRID_STEPS[area_kind]),
        as_of=min((row.effective_instant for row in cell.rows), default=None),
        items=[_group(row, now) for row in cell.rows],
    )


@router.get(
    "/cells",
    response_model=PriceIndexCellList,
    summary="List every price-index row of one area kind (cursor-paginated)",
    responses=_CELLS_RESPONSES,
)
def list_price_index_cells(
    session: Annotated[Session, Depends(get_session)],
    area_kind: Annotated[
        AreaKind,
        Query(description="The grid to list (0.01° or 0.05° cells), or the citywide all row."),
    ] = "latlon_grid_0p01",
    category_kind: Annotated[CategoryKind | None, Query()] = None,
    currency: Annotated[CurrencyCode | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> PriceIndexCellList:
    """Return one page of the ``area_kind`` rows, ordered by area key, category, currency.

    The order is text order, not map order. The cursor does not carry the
    filters: send the same ones with every page. It names the last row's key, not
    a row id, so it survives a refresh; each page's ``as_of`` says which
    snapshot it came from. A filter that matches nothing is ``200`` with
    ``items: []``.
    """
    after = decode_cell_cursor(cursor) if cursor is not None else None
    rows = price_index_cells(
        session,
        area_kind,
        category_kind=category_kind,
        currency_code=currency,
        after=after,
        limit=limit + 1,
    )
    page = rows[:limit]
    now = datetime.now(UTC)
    step = GRID_STEPS.get(area_kind)
    return PriceIndexCellList(
        area_kind=area_kind,
        cell_size_degrees=float(step) if step is not None else None,
        as_of=min((row.group.effective_instant for row in page), default=None),
        items=[
            PriceIndexCellResponse(
                area_key=row.area_key,
                cell_lat=float(row.cell_lat) if row.cell_lat is not None else None,
                cell_lon=float(row.cell_lon) if row.cell_lon is not None else None,
                **dict(_group(row.group, now)),  # the field values, unserialized
            )
            for row in page
        ],
        next_cursor=encode_cell_cursor(page[-1].key) if len(rows) > limit else None,
    )


_AREA_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "boundary is missing or breaks a rule (the detail names it), or a "
        "filter value is unknown.",
    },
}
_AREA_ITEMS_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse, "description": "The cursor is malformed."},
    422: {
        "model": ErrorResponse,
        "description": "boundary is missing or breaks a rule (the detail names it), q or "
        "limit is out of range, or a filter value is unknown.",
    },
}


@router.get(
    "/area",
    response_model=PriceIndexAreaResponse,
    summary="Get the price index of the venues inside a drawn boundary",
    responses=_AREA_RESPONSES,
)
def get_price_index_area(
    session: Annotated[Session, Depends(get_session)],
    boundary: BoundaryQuery,
    category_kind: Annotated[CategoryKind | None, Query()] = None,
    currency: Annotated[CurrencyCode | None, Query()] = None,
) -> PriceIndexAreaResponse:
    """Return the venue-weighted price statistics of the placed venues inside ``boundary``.

    Computed as every price-index row is (ADR-0020 §3): each venue's median,
    then percentiles over those medians; groups below ``min_venues`` venues are
    served with ``low_sample: true``. Only the venues the index places count,
    so shared chain menus are left out. One item per category and currency,
    narrowed by ``category_kind`` and ``currency`` when given. A boundary with
    no placed venue is ``200`` with ``items: []`` and ``as_of: null``.
    """
    shape = boundary_param(boundary)
    area = price_index_area(session, shape, category_kind=category_kind, currency_code=currency)
    now = datetime.now(UTC)
    return PriceIndexAreaResponse(
        boundary=[(float(lat), float(lon)) for lat, lon in shape.corners],
        as_of=area.effective_instant,
        items=[_group(row, now) for row in area.rows],
    )


def _venue_names(session: Session, venue_ids: set[int]) -> dict[int, str | None]:
    """Each venue's name: its operating Organization's, as on ``GET /v1/venues``."""
    if not venue_ids:
        return {}
    rows = session.execute(
        select(Establishment.subject_id, Organization.canonical_name)
        .join(Organization, Organization.subject_id == Establishment.organization_subject_id)
        .where(Establishment.subject_id.in_(sorted(venue_ids)))
    ).tuples()
    return dict(rows.all())


def _area_item(row: AreaItemRow, venue_name: str | None, now: datetime) -> AreaItemResponse:
    observed = row.price_observed_at
    variant = row.target_kind == "variant"
    return AreaItemResponse(
        venue_id=row.venue_id,
        venue_name=venue_name,
        item_id=encode_item_id(
            ItemId(
                subject_kind=cast("MenuScope", row.subject_kind),
                subject_id=row.subject_id,
                source_record_id=row.source_record_id,
                root_key=row.root_key,
                target_path=row.native_path,
            )
        ),
        section_name=row.section_name,
        item_name=row.item_name,
        variant_name=row.content_name if variant else None,
        amount_minor=row.amount_minor,
        currency_code=row.currency_code,
        channel=cast("Channel", row.channel),
        service_period=row.service_period,
        observed_at=observed,
        # An age: an observation after the request instant is fresh, not negative.
        age_seconds=max(0, int((now - observed).total_seconds())) if observed else None,
        source_kind=cast("SourceKind | None", row.price_source_kind),
    )


@router.get(
    "/area/items",
    response_model=AreaItemList,
    summary="List the priced items behind a drawn boundary's price index (cursor-paginated)",
    responses=_AREA_ITEMS_RESPONSES,
)
def list_price_index_area_items(
    session: Annotated[Session, Depends(get_session)],
    boundary: BoundaryQuery,
    currency: Annotated[CurrencyCode | None, Query()] = None,
    q: Annotated[
        str | None,
        Query(
            min_length=2,
            max_length=100,
            description="Only rows whose item or variant name contains this text, "
            "case-insensitively (section names are not matched).",
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query()] = None,
) -> AreaItemList:
    """Return one page of the priced item and variant rows behind ``/v1/price-index/area``.

    The rows of the venues the index places inside ``boundary`` (shared chain
    menus left out, as from the median), cheapest first (ADR-0020 §4). Without
    ``q``, walking every page gives ``priced_count`` rows. The cursor names the
    last row's price and business key, not a row id, so it survives a refresh;
    it does not carry ``boundary`` or the filters: send the same ones with
    every page. A boundary or ``q`` that matches nothing is ``200`` with
    ``items: []``.
    """
    shape = boundary_param(boundary)
    after = decode_area_item_cursor(cursor) if cursor is not None else None
    rows = price_index_area_items(
        session, shape, currency_code=currency, name=q, after=after, limit=limit + 1
    )
    page = rows[:limit]
    names = _venue_names(session, {row.venue_id for row in page})
    now = datetime.now(UTC)
    return AreaItemList(
        as_of=min((row.effective_instant for row in page), default=None),
        items=[_area_item(row, names.get(row.venue_id), now) for row in page],
        next_cursor=encode_area_item_cursor(page[-1].key) if len(rows) > limit else None,
    )
