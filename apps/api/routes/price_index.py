"""Price-index read endpoints (ADR-0007 Amendments 2 and 3; ROADMAP Phase 7).

Serves ``gold.price_index`` through
:mod:`packages.helios_core.gold.price_index_read` (ADR-0008 §9): the grid cell
containing a point, one bounded response with a row per category and currency;
and every row of one area kind (0.01°, 0.05° or the citywide ``all``), a keyset
page at a time. Every row carries its sample size and ``low_sample`` flag, so an
aggregate over four venues is never served as though it were an index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this at runtime for Depends

from apps.api.db import get_session
from apps.api.pagination import DEFAULT_LIMIT, MAX_LIMIT, decode_cell_cursor, encode_cell_cursor
from apps.api.schemas import (
    AreaKind,
    CategoryKind,
    CurrencyCode,
    ErrorResponse,
    GridAreaKind,
    PriceIndexCellList,
    PriceIndexCellResponse,
    PriceIndexGroupResponse,
    PriceIndexResponse,
)
from packages.helios_core.gold.price_index import GRID_STEPS
from packages.helios_core.gold.price_index_read import price_index_cell, price_index_cells

if TYPE_CHECKING:
    from packages.helios_core.gold.price_index_read import PriceIndexRow

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
