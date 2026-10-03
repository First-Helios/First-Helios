"""Price-index read endpoint (ADR-0007 Amendment 2; ROADMAP Phase 7).

Serves ``gold.price_index`` through
:mod:`packages.helios_core.gold.price_index_read` (ADR-0008 §9): the 0.01° grid
cell containing a point, one bounded response with a row per category and
currency. Every row carries its sample size and ``low_sample`` flag, so an
aggregate over four venues is never served as though it were an index.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session  # noqa: TC002 - FastAPI resolves this at runtime for Depends

from apps.api.db import get_session
from apps.api.schemas import (
    CategoryKind,
    CurrencyCode,
    ErrorResponse,
    PriceIndexGroupResponse,
    PriceIndexResponse,
)
from packages.helios_core.gold.price_index import GRID_STEP
from packages.helios_core.gold.price_index_read import price_index_cell

if TYPE_CHECKING:
    from packages.helios_core.gold.price_index_read import PriceIndexRow

router = APIRouter(prefix="/price-index", tags=["price-index"])

_RESPONSES: dict[int | str, dict[str, Any]] = {
    422: {
        "model": ErrorResponse,
        "description": "lat/lon is missing or out of range, or a filter value is unknown.",
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
    category_kind: Annotated[CategoryKind | None, Query()] = None,
    currency: Annotated[CurrencyCode | None, Query()] = None,
) -> PriceIndexResponse:
    """Return the venue-weighted price statistics of the 0.01° cell containing ``lat``/``lon``.

    One item per category and currency the index holds for the cell, narrowed
    by ``category_kind`` and ``currency`` when given. Groups below ``min_venues``
    venues are served with ``low_sample: true``. A cell the index has no row for
    is ``200`` with ``items: []`` and ``as_of: null``.
    """
    # repr() round-trips, so 30.26 floors to the 30.26 cell, not 30.25.
    cell = price_index_cell(
        session,
        Decimal(repr(lat)),
        Decimal(repr(lon)),
        category_kind=category_kind,
        currency_code=currency,
    )
    now = datetime.now(UTC)
    return PriceIndexResponse(
        area_kind=cell.area_kind,
        area_key=cell.area_key,
        cell_lat=float(cell.cell_lat),
        cell_lon=float(cell.cell_lon),
        cell_size_degrees=float(GRID_STEP),
        as_of=min((row.effective_instant for row in cell.rows), default=None),
        items=[_group(row, now) for row in cell.rows],
    )
