"""Read contract over ``gold.price_index``: a grid cell, a page of one area kind, a drawn area.

The read API serves the price index from Gold only (ADR-0008 §9). A caller
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

A drawn area (ADR-0020) is aggregated at request time from the stored
placements inside it: a bbox range on ``ix_gold_price_index_placement_point``,
exact ray casting in Python (:meth:`Boundary.contains`), then the refresh's own
:data:`AGGREGATE_SQL` over ``gold.current_menu``. Its items are the priced rows
behind that aggregate, a keyset page at a time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from sqlalchemy import literal, select, text, tuple_

from packages.helios_core.gold.categories import (
    DRINK_LED_PLACE_TYPES,
    CategoryFilters,
    category_predicates,
)
from packages.helios_core.gold.models import PriceIndex, PriceIndexPlacement
from packages.helios_core.gold.price_index import (
    AGGREGATE_SQL,
    AREA_KIND,
    GRID_STEPS,
    Placement,
    aggregate_params,
    grid_cell,
)

if TYPE_CHECKING:
    from datetime import datetime
    from decimal import Decimal

    from sqlalchemy import Select
    from sqlalchemy.orm import Session

    from packages.helios_core.gold.price_index import Boundary

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


# --------------------------------------------------------------------------- #
# Drawn areas (ADR-0020).
# --------------------------------------------------------------------------- #

_DRAWN_AREA = "boundary"  # the one area key a drawn area's aggregate groups by


@dataclass(frozen=True, slots=True)
class PriceIndexArea:
    """A drawn area's groups; ``effective_instant`` is None when there are none."""

    effective_instant: datetime | None
    rows: list[PriceIndexRow]


def _placements_inside(
    session: Session, boundary: Boundary
) -> tuple[list[Placement], datetime | None]:
    """The stored placements inside ``boundary``, and their refresh instant.

    A bbox range on ``ix_gold_price_index_placement_point``, then exact ray
    casting over the candidates.
    """
    rows = session.execute(
        select(
            PriceIndexPlacement.subject_id,
            PriceIndexPlacement.subject_kind,
            PriceIndexPlacement.source_record_id,
            PriceIndexPlacement.venue_id,
            PriceIndexPlacement.latitude,
            PriceIndexPlacement.longitude,
            PriceIndexPlacement.via_organization,
            PriceIndexPlacement.effective_instant,
        ).where(
            PriceIndexPlacement.latitude.between(boundary.south, boundary.north),
            PriceIndexPlacement.longitude.between(boundary.west, boundary.east),
        )
    ).all()
    inside = [row for row in rows if boundary.contains(row.latitude, row.longitude)]
    placements = [Placement(*row[:7]) for row in inside]
    return placements, min((row.effective_instant for row in inside), default=None)


def price_index_area(
    session: Session,
    boundary: Boundary,
    *,
    category_kind: str | None = None,
    currency_code: str | None = None,
) -> PriceIndexArea:
    """The price index of the placed venues inside ``boundary``, per category and currency.

    The same venue-median -> percentile aggregate, ``MIN_VENUES`` and honesty
    fields as every stored row, over the stored placements inside the
    boundary, so a boundary drawn on a cell gives that cell's row. Rows are
    ordered by category kind, category key, then currency; none when no
    placement is inside. Read-only; takes no locks.
    """
    placements, effective_instant = _placements_inside(session, boundary)
    if not placements:
        return PriceIndexArea(None, [])
    areas = [(_DRAWN_AREA, None, None)] * len(placements)
    rows = [
        _group(SimpleNamespace(**row, effective_instant=effective_instant))
        for row in session.execute(AGGREGATE_SQL, aggregate_params(placements, areas)).mappings()
        if (category_kind is None or row["category_kind"] == category_kind)
        and (currency_code is None or row["currency_code"] == currency_code)
    ]
    return PriceIndexArea(effective_instant if rows else None, rows)


#: An area item's position: ``amount_minor``, then the ``uq_gold_current_menu``
#: grain ``(subject_id, subject_kind, source_record_id, root_key, target_path,
#: channel, service_period, valid_from, valid_to, currency_code)``.
type AreaItemKey = tuple[
    int, int, str, int, str, str, str, str | None, datetime | None, datetime | None, str
]
#: An area item's position in the ``typical`` order (ADR-0020 Amendment 1
#: item 2): the walk's ``pivot``, the course group, the distance
#: ``|amount_minor - pivot|``, ``amount_minor``, the venue round, ``venue_id``,
#: then the same grain.
type TypicalAreaItemKey = tuple[
    int,
    int,
    int,
    int,
    int,
    int,
    int,
    str,
    int,
    str,
    str,
    str,
    str | None,
    datetime | None,
    datetime | None,
    str,
]


@dataclass(frozen=True, slots=True)
class AreaItemRow:
    """One priced item or variant row behind a drawn area's aggregate."""

    venue_id: int
    subject_id: int
    subject_kind: str
    source_record_id: int
    root_key: str
    target_kind: str
    target_path: str  # the stored canonical encoding; see ``native_path``
    channel: str
    service_period: str | None
    valid_from: datetime | None
    valid_to: datetime | None
    currency_code: str
    effective_instant: datetime
    amount_minor: int
    price_observed_at: datetime | None
    price_source_kind: str | None
    content_name: str | None
    section_name: str | None
    item_name: str | None
    #: The row's round in the ``typical`` order: its rank among its venue's
    #: rows in the same course group at the same price, by the grain. None in
    #: the ``price`` order.
    venue_round: int | None = None
    #: The row's course group in the ``typical`` order (:data:`COURSE_GROUPS`).
    #: None in the ``price`` order.
    course_group: int | None = None

    @property
    def native_path(self) -> tuple[tuple[str, str], ...]:
        return tuple((kind, key) for kind, key in json.loads(self.target_path))

    @property
    def key(self) -> AreaItemKey:
        return (
            self.amount_minor,
            self.subject_id,
            self.subject_kind,
            self.source_record_id,
            self.root_key,
            self.target_path,
            self.channel,
            self.service_period,
            self.valid_from,
            self.valid_to,
            self.currency_code,
        )

    def typical_key(self, pivot: int) -> TypicalAreaItemKey:
        """The row's :data:`TypicalAreaItemKey` in a walk around ``pivot``."""
        if self.venue_round is None or self.course_group is None:
            raise ValueError("not a typical-order row")
        return (
            pivot,
            self.course_group,
            abs(self.amount_minor - pivot),
            self.amount_minor,
            self.venue_round,
            self.venue_id,
            self.subject_id,
            self.subject_kind,
            self.source_record_id,
            self.root_key,
            self.target_path,
            self.channel,
            self.service_period,
            self.valid_from,
            self.valid_to,
            self.currency_code,
        )


def _grain_order(a: str) -> str:
    """The ``uq_gold_current_menu`` grain as a NULL-safe sort key, on table alias ``a``."""
    return (
        f"{a}.subject_id, {a}.subject_kind, {a}.source_record_id, {a}.root_key, "
        f"{a}.target_path, {a}.channel, "
        f"{a}.service_period IS NOT NULL, coalesce({a}.service_period, ''), "
        f"{a}.valid_from IS NOT NULL, coalesce({a}.valid_from, '-infinity'), "
        f"{a}.valid_to IS NOT NULL, coalesce({a}.valid_to, '-infinity'), {a}.currency_code"
    )


# The keyset, NULL-safe: each nullable grain column sorts by "is not null"
# first (NULLs lowest), then by its value with NULL replaced by a constant, so
# ORDER BY and the row comparison agree and a NULL never makes it unknown.
_ITEM_ORDER = "c.amount_minor, " + _grain_order("c")
_GRAIN_AFTER = (
    "CAST(:a_subject AS bigint), "
    "CAST(:a_kind AS text), CAST(:a_record AS bigint), CAST(:a_root AS text), "
    "CAST(:a_path AS text), CAST(:a_channel AS text), "
    "CAST(:a_period AS text) IS NOT NULL, coalesce(CAST(:a_period AS text), ''), "
    "CAST(:a_from AS timestamptz) IS NOT NULL, "
    "coalesce(CAST(:a_from AS timestamptz), '-infinity'), "
    "CAST(:a_to AS timestamptz) IS NOT NULL, "
    "coalesce(CAST(:a_to AS timestamptz), '-infinity'), CAST(:a_currency AS text)"
)
_ITEM_AFTER = f"AND ({_ITEM_ORDER}) > (CAST(:a_amount AS bigint), {_GRAIN_AFTER})"
_GRAIN_PARAMS = (
    "a_subject",
    "a_kind",
    "a_record",
    "a_root",
    "a_path",
    "a_channel",
    "a_period",
    "a_from",
    "a_to",
    "a_currency",
)
_AFTER_PARAMS = ("a_amount", *_GRAIN_PARAMS)
#: The ``typical`` order's course groups (ADR-0020 Amendment 1 item 2.1, the groups
#: of ADR-0022 Amendment 2): food (every course but the ones below, and null),
#: drink, alcohol, then side and other. A drink-led venue's drink and alcohol rows
#: stay in the food group.
COURSE_GROUPS = {"food": 0, "drink": 1, "alcohol": 2, "extras": 3}
# A row's course group, on aliases ``c`` (gold.current_menu) and ``p`` (placed).
# The drink-led venues are one uncorrelated subquery on ix_gold_venue_category_filter.
_COURSE_GROUP = (
    "CASE WHEN c.course IN ('side', 'other') THEN 3 "
    "WHEN p.venue_id IN (SELECT vc.venue_id FROM gold.venue_category vc "
    "WHERE vc.category_group = 'place_type' "
    "AND vc.category_key = ANY(CAST(:drink_led AS text[]))) THEN 0 "
    "WHEN c.course = 'drink' THEN 1 WHEN c.course = 'alcohol' THEN 2 ELSE 0 END"
)
# The typical order (ADR-0020 Amendment 1 item 2) over the windowed rows ``r``:
# the course group, distance from the pivot (numeric, so no stored amount or
# cursor pivot can overflow), the cheaper of two equally distant rows, the venue
# round, then the venue and the grain.
_TYPICAL_DISTANCE = "abs(CAST(r.amount_minor AS numeric) - CAST(:pivot AS numeric))"
_TYPICAL_ORDER = (
    f"r.course_group, {_TYPICAL_DISTANCE}, r.amount_minor, r.venue_round, r.venue_id, "
    + _grain_order("r")
)
_TYPICAL_AFTER = (
    f"AND ({_TYPICAL_ORDER}) > (CAST(:a_group AS integer), CAST(:a_distance AS numeric), "
    f"CAST(:a_amount AS bigint), CAST(:a_round AS bigint), CAST(:a_venue AS bigint), "
    f"{_GRAIN_AFTER})"
)
_TYPICAL_AFTER_PARAMS = (
    "a_group",
    "a_distance",
    "a_amount",
    "a_round",
    "a_venue",
    *_GRAIN_PARAMS,
)
# A venue's k-th row in one course group at one price comes in round k, so one
# venue's rows at the pivot don't fill a page. Equal price means equal distance,
# so the partition holds exactly the rows equal on every earlier key.
_VENUE_ROUND = (
    f",\n           {_COURSE_GROUP} AS course_group"
    f",\n           row_number() OVER (PARTITION BY p.venue_id, {_COURSE_GROUP}, c.amount_minor "
    f"ORDER BY {_grain_order('c')}) AS venue_round"
)
# Item and variant names only (ADR-0020 OQ6): a row's item_name is its item's
# name (its own, on an item row); a variant row's own name is its content_name.
_ITEM_NAME = (
    "AND (c.item_name ILIKE :pattern ESCAPE '\\' "
    "OR (c.target_kind = 'variant' AND c.content_name ILIKE :pattern ESCAPE '\\'))"
)
_ITEMS_SQL = """
    WITH placed AS (
        SELECT * FROM unnest(
            CAST(:subjects AS bigint[]), CAST(:subject_kinds AS text[]),
            CAST(:records AS bigint[]), CAST(:venues AS bigint[])
        ) AS p(subject_id, subject_kind, source_record_id, venue_id)
    )
    SELECT p.venue_id, c.subject_id, c.subject_kind, c.source_record_id, c.root_key,
           c.target_kind, c.target_path, c.channel, c.service_period, c.valid_from,
           c.valid_to, c.currency_code, c.effective_instant, c.amount_minor,
           c.price_observed_at, c.price_source_kind, c.content_name, c.section_name,
           c.item_name{extra}
    FROM gold.current_menu c
    JOIN placed p
      ON p.subject_id = c.subject_id AND p.subject_kind = c.subject_kind
     AND p.source_record_id = c.source_record_id
    WHERE c.target_kind IN ('item', 'variant') AND c.price_state = 'priced'
"""


def like_pattern(fragment: str) -> str:
    """``%fragment%`` with ILIKE's ``\\``, ``%`` and ``_`` escaped, so each matches itself."""
    escaped = fragment.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def price_index_area_items(
    session: Session,
    boundary: Boundary,
    *,
    currency_code: str | None = None,
    name: str | None = None,
    categories: CategoryFilters | None = None,
    after: AreaItemKey | None = None,
    limit: int,
) -> list[AreaItemRow]:
    """Up to ``limit`` priced rows behind ``boundary``'s aggregate after ``after``, cheapest first.

    The item and variant rows of the placed families inside the boundary
    (shared menus are left out, as from the median), in :data:`AreaItemKey`
    order: total, and a business key that survives a refresh. ``name``
    narrows them to rows whose item or variant name contains it,
    case-insensitively. Bounded by the placements inside the boundary; no
    index on names. Read-only; takes no locks.
    """
    query = _area_items_query(
        session, boundary, currency_code=currency_code, name=name, categories=categories
    )
    if query is None:
        return []
    sql, params = query
    if after is not None:
        sql += _ITEM_AFTER + "\n"
        params |= dict(zip(_AFTER_PARAMS, after, strict=True))
    sql += f"ORDER BY {_ITEM_ORDER}\nLIMIT :limit"
    params["limit"] = limit
    return [AreaItemRow(**row) for row in session.execute(text(sql), params).mappings()]


def area_pivot(
    session: Session, boundary: Boundary, *, currency_code: str | None = None
) -> int | None:
    """The ``typical`` order's pivot: ``boundary``'s headline (``all``) median.

    The figure ``/v1/price-index/area`` serves for the same currency
    (ADR-0020 Amendment 1 Q1); with no currency, the first currency's (Gold
    holds USD only). None when the boundary has no priced placed row.
    """
    area = price_index_area(session, boundary, category_kind="all", currency_code=currency_code)
    return next((row.median_minor for row in area.rows if row.median_minor is not None), None)


def price_index_area_items_typical(
    session: Session,
    boundary: Boundary,
    *,
    pivot: int,
    currency_code: str | None = None,
    name: str | None = None,
    categories: CategoryFilters | None = None,
    after: TypicalAreaItemKey | None = None,
    limit: int,
) -> list[AreaItemRow]:
    """Up to ``limit`` of :func:`price_index_area_items`' rows after ``after``, typical first.

    In :data:`TypicalAreaItemKey` order (ADR-0020 Amendment 1 item 2): by
    course group (:data:`COURSE_GROUPS`), then nearest ``pivot``, the cheaper
    of two equally near rows first, a venue's k-th row in one group at one
    price in round k, then the venue and the grain. Total, so the keyset works. ``after`` carries the walk's pivot,
    which must be ``pivot``. The rounds are counted over every filtered row,
    so the window runs over all of them on every page. Read-only; takes no
    locks.
    """
    if after is not None and after[0] != pivot:
        raise ValueError("a typical cursor continues the walk around its own pivot")
    query = _area_items_query(
        session,
        boundary,
        currency_code=currency_code,
        name=name,
        categories=categories,
        extra=_VENUE_ROUND,
    )
    if query is None:
        return []
    inner, params = query
    sql = f"SELECT * FROM ({inner}) r\nWHERE true\n"  # noqa: S608 - static fragments; values are bound
    if after is not None:
        sql += _TYPICAL_AFTER + "\n"
        params |= dict(zip(_TYPICAL_AFTER_PARAMS, after[1:], strict=True))
    sql += f"ORDER BY {_TYPICAL_ORDER}\nLIMIT :limit"
    params |= {"pivot": pivot, "limit": limit, "drink_led": list(DRINK_LED_PLACE_TYPES)}
    return [AreaItemRow(**row) for row in session.execute(text(sql), params).mappings()]


def _area_items_query(
    session: Session,
    boundary: Boundary,
    *,
    currency_code: str | None,
    name: str | None,
    categories: CategoryFilters | None,
    extra: str = "",
) -> tuple[str, dict[str, Any]] | None:
    """The filtered rows behind ``boundary``'s aggregate, unordered; None when none are placed."""
    placements, _ = _placements_inside(session, boundary)
    if categories and placements:
        allowed = set(
            session.scalars(
                select(PriceIndexPlacement.venue_id).where(
                    PriceIndexPlacement.venue_id.in_({p.venue_id for p in placements}),
                    *category_predicates(PriceIndexPlacement.venue_id, categories),
                )
            )
        )
        placements = [p for p in placements if p.venue_id in allowed]
    if not placements:
        return None
    params: dict[str, Any] = {
        "subjects": [p.subject_id for p in placements],
        "subject_kinds": [p.subject_kind for p in placements],
        "records": [p.source_record_id for p in placements],
        "venues": [p.venue_id for p in placements],
    }
    sql = _ITEMS_SQL.format(extra=extra)
    if currency_code is not None:
        sql += "AND c.currency_code = :currency\n"
        params["currency"] = currency_code
    if name is not None:
        sql += _ITEM_NAME + "\n"
        params["pattern"] = like_pattern(name)
    return sql, params


def indexed_area_venue_ids(
    session: Session, boundary: Boundary, *, name: str | None = None
) -> set[int]:
    """Complete placed venue set with a priced item matching the optional name."""
    placements, _ = _placements_inside(session, boundary)
    if not placements:
        return set()
    sql = _ITEMS_SQL.format(extra="") + (_ITEM_NAME if name is not None else "")
    sql = "SELECT DISTINCT venue_id FROM (" + sql + ") matching"  # noqa: S608 - static fragments; name is bound
    params: dict[str, Any] = {
        "subjects": [p.subject_id for p in placements],
        "subject_kinds": [p.subject_kind for p in placements],
        "records": [p.source_record_id for p in placements],
        "venues": [p.venue_id for p in placements],
    }
    if name is not None:
        params["pattern"] = like_pattern(name)
    return set(session.scalars(text(sql), params))
