"""Read contract over ``gold.price_index`` for one grid cell (ROADMAP Phase 7).

The read API serves the price index from this table only (ADR-0008 §9). A caller
names a point; the point is floored to its 0.01° cell with the refresh's own
:func:`~packages.helios_core.gold.price_index.grid_cell`, so the API and the
refresh can never disagree on which cell a point is in. The cell's rows come back
as plain values in a fixed order; no ORM object leaves this module.

Every stored row is served, ``low_sample`` and all-unpriced ones included, so a
reader always sees how many venues stand behind a statistic (ADR-0007 Amendment
1 §4). The query is index-backed by ``uq_gold_price_index``, whose leading
columns are ``(area_kind, area_key)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.helios_core.gold.models import PriceIndex
from packages.helios_core.gold.price_index import AREA_KIND, grid_cell

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class PriceIndexRow:
    """One ``gold.price_index`` group of a cell: a category and currency."""

    category_kind: str
    category_key: str
    currency_code: str
    effective_instant: datetime
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


@dataclass(frozen=True, slots=True)
class PriceIndexCell:
    """The grid cell containing a point, and its index rows (none if no coverage)."""

    area_kind: str
    area_key: str
    cell_lat: Decimal  # south-west corner
    cell_lon: Decimal
    rows: list[PriceIndexRow]


def price_index_cell(
    session: Session,
    latitude: Decimal,
    longitude: Decimal,
    *,
    category_kind: str | None = None,
    currency_code: str | None = None,
) -> PriceIndexCell:
    """The cell containing ``(latitude, longitude)`` and its rows.

    ``category_kind`` and ``currency_code`` narrow the rows when given. Rows are
    ordered by category kind, category key, then currency, so a response built
    from them is deterministic. Read-only; takes no locks.
    """
    area_key, cell_lat, cell_lon = grid_cell(latitude, longitude)
    statement = select(
        PriceIndex.category_kind,
        PriceIndex.category_key,
        PriceIndex.currency_code,
        PriceIndex.effective_instant,
        PriceIndex.venue_count,
        PriceIndex.organization_venue_count,
        PriceIndex.priced_count,
        PriceIndex.unpriced_count,
        PriceIndex.min_venues,
        PriceIndex.low_sample,
        PriceIndex.p25_minor,
        PriceIndex.median_minor,
        PriceIndex.p75_minor,
        PriceIndex.min_minor,
        PriceIndex.max_minor,
        PriceIndex.oldest_observed_at,
        PriceIndex.newest_observed_at,
    ).where(PriceIndex.area_kind == AREA_KIND, PriceIndex.area_key == area_key)
    if category_kind is not None:
        statement = statement.where(PriceIndex.category_kind == category_kind)
    if currency_code is not None:
        statement = statement.where(PriceIndex.currency_code == currency_code)
    statement = statement.order_by(
        PriceIndex.category_kind, PriceIndex.category_key, PriceIndex.currency_code
    )
    rows = [
        PriceIndexRow(
            category_kind=row.category_kind,
            category_key=row.category_key,
            currency_code=row.currency_code,
            effective_instant=row.effective_instant,
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
            oldest_observed_at=row.oldest_observed_at,
            newest_observed_at=row.newest_observed_at,
        )
        for row in session.execute(statement)
    ]
    return PriceIndexCell(AREA_KIND, area_key, cell_lat, cell_lon, rows)
