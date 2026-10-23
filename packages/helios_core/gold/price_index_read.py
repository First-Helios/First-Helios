"""Read contract over ``gold.price_index``: one grid cell, or a page of one area kind.

The read API serves the price index from this table only (ADR-0008 §9). A caller
names a point and a grid kind; the point is floored to its cell with the
refresh's own :func:`~packages.helios_core.gold.price_index.grid_cell` at that
kind's step, so the API and the refresh can never disagree on which cell a
point is in. Or a caller lists every row of one area kind (ADR-0007 Amendment
3), a keyset page at a time. Rows come back as plain values in a fixed order; no
ORM object leaves this module.

Every stored row is served, ``low_sample`` and all-unpriced ones included, so a
reader always sees how many venues stand behind a statistic (ADR-0007 Amendment
1 §4). Both queries are index-backed by ``uq_gold_price_index``, whose columns
are ``(area_kind, area_key, category_kind, category_key, currency_code)``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import literal, select, tuple_

from packages.helios_core.gold.models import PriceIndex
from packages.helios_core.gold.price_index import AREA_KIND, GRID_STEPS, grid_cell

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

#: A row's position in a page of one area kind: ``(area_key, category_kind,
#: category_key, currency_code)``, the unique grain under a fixed ``area_kind``.
CellRowKey = tuple[str, str, str, str]


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


@dataclass(frozen=True, slots=True)
class PriceIndexCellRow:
    """One row of a page of an area kind: its area, and its group."""

    area_key: str
    cell_lat: Decimal | None  # south-west corner; None for ``all``
    cell_lon: Decimal | None
    group: PriceIndexRow

    @property
    def key(self) -> CellRowKey:
        return (
            self.area_key,
            self.group.category_kind,
            self.group.category_key,
            self.group.currency_code,
        )


_GROUP_COLUMNS = (
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
)


def _group(row: Any) -> PriceIndexRow:
    return PriceIndexRow(
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


def _filtered(
    statement: Select[Any], category_kind: str | None, currency_code: str | None
) -> Select[Any]:
    if category_kind is not None:
        statement = statement.where(PriceIndex.category_kind == category_kind)
    if currency_code is not None:
        statement = statement.where(PriceIndex.currency_code == currency_code)
    return statement


def price_index_cell(
    session: Session,
    latitude: Decimal,
    longitude: Decimal,
    *,
    area_kind: str = AREA_KIND,
    category_kind: str | None = None,
    currency_code: str | None = None,
) -> PriceIndexCell:
    """The ``area_kind`` grid cell containing ``(latitude, longitude)`` and its rows.

    ``area_kind`` is a grid kind (``all`` has no cell). ``category_kind`` and
    ``currency_code`` narrow the rows when given. Rows are ordered by category
    kind, category key, then currency, so a response built from them is
    deterministic. Read-only; takes no locks.
    """
    area_key, cell_lat, cell_lon = grid_cell(latitude, longitude, GRID_STEPS[area_kind])
    statement = _filtered(
        select(*_GROUP_COLUMNS).where(
            PriceIndex.area_kind == area_kind, PriceIndex.area_key == area_key
        ),
        category_kind,
        currency_code,
    ).order_by(PriceIndex.category_kind, PriceIndex.category_key, PriceIndex.currency_code)
    rows = [_group(row) for row in session.execute(statement)]
    return PriceIndexCell(area_kind, area_key, cell_lat, cell_lon, rows)


def price_index_cells(
    session: Session,
    area_kind: str,
    *,
    category_kind: str | None = None,
    currency_code: str | None = None,
    after: CellRowKey | None = None,
    limit: int,
) -> list[PriceIndexCellRow]:
    """Up to ``limit`` rows of ``area_kind`` after the key ``after``, in key order.

    The order is ``(area_key, category_kind, category_key, currency_code)``, the
    unique grain under a fixed kind, so a page boundary is total: text order,
    not map order. ``after`` is a business key, not a row id, so it survives a
    refresh. A range scan on ``uq_gold_price_index``. Read-only; takes no locks.
    """
    key = tuple_(
        PriceIndex.area_key,
        PriceIndex.category_kind,
        PriceIndex.category_key,
        PriceIndex.currency_code,
    )
    statement = select(PriceIndex.area_key, PriceIndex.cell_lat, PriceIndex.cell_lon).add_columns(
        *_GROUP_COLUMNS
    )
    statement = _filtered(
        statement.where(PriceIndex.area_kind == area_kind), category_kind, currency_code
    )
    if after is not None:
        statement = statement.where(key > tuple_(*(literal(value) for value in after)))
    statement = statement.order_by(
        PriceIndex.area_key,
        PriceIndex.category_kind,
        PriceIndex.category_key,
        PriceIndex.currency_code,
    ).limit(limit)
    return [
        PriceIndexCellRow(row.area_key, row.cell_lat, row.cell_lon, _group(row))
        for row in session.execute(statement)
    ]
