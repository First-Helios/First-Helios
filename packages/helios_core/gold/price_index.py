"""Full deterministic rebuild of ``gold.price_index`` over ``gold.current_menu`` (ADR-0007).

The index reads only the accepted ``current_menu`` projection, so "current" stays
defined once, by the Menu selector. Item and variant rows count; modifiers (add-on
amounts) and section-level prices do not. Rules (ADR-0007 Amendment 1):

* **Placement.** Each ``(scope subject, source record)`` family is placed at one
  venue's point or left out. An Establishment-scoped family is placed
  at that Establishment. An Organization-scoped family (own-site pages, and
  platform pages several venues share) is placed at its Organization's only
  current operating Establishment, unless the menu URL its prices were read from
  is also the menu URL of another placed venue's Organization family (a shared
  chain or platform menu): those are left out, never fanned out (ADR-0005 §11).
* **Weighting.** Each venue weighs one. Per group, a venue's sample is the median
  of its printed prices: priced rows of one source record that cite the same
  Evidence (a choice line's variants, one dish filed under two sections) count
  once (ADR-0007 Amendment 4). ``priced_count`` still counts rows, so a drawn
  area's items walk returns ``priced_count`` rows (ADR-0020). The percentiles are
  over those venue medians. Both use
  ``percentile_disc``, so every statistic is an observed integer amount (the
  lower middle value for an even count); no float touches a price.
* **Categories.** Only ``all`` today; ``course`` arrives as another
  ``category_kind`` once a course label exists (ADR-0007 Amendment 1).
* **Honesty.** Groups below :data:`MIN_VENUES` venues are kept and flagged
  ``low_sample``. Non-priced rows are counted, never in a percentile.
* **Area kinds** (ADR-0007 Amendment 3). Each kept placement counts once per
  kind: in its 0.01° cell, its 0.05° cell and the citywide ``all`` row. The
  aggregate is the same for every kind, so ``all``'s counts are the sums over
  either grid's rows and a 0.05° row's counts the sums over the 0.01° rows
  inside it; the percentiles are over each row's own venue medians.
* **Drawn areas** (ADR-0020). The kept placements are stored in
  ``gold.price_index_placement``, so a reader's boundary is aggregated by the
  same :data:`AGGREGATE_SQL` over the placements inside it
  (:func:`parse_boundary`, :meth:`Boundary.contains`).

The rebuild replaces both tables, every kind at one instant. Business columns
are a deterministic function of ``current_menu`` and Identity at
``effective_instant``; ``refreshed_at`` is run metadata. Nothing outside
``gold.price_index`` and ``gold.price_index_placement`` is written; the caller
owns the commit.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal, localcontext
from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, func, insert, select, text

from packages.helios_core.gold.models import CurrentMenu, PriceIndex, PriceIndexPlacement
from packages.helios_core.identity.contracts import current_venue_locations
from packages.helios_core.provenance.contracts import source_endpoint_for_evidence

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.orm import Session

AREA_KIND = "latlon_grid_0p01"  # the default kind of the point and area reads
GRID_STEP = Decimal("0.01")  # ~1.1 km north-south, ~1.0 km east-west in Austin
# Grid kinds and their steps. 0.05 is a multiple of 0.01 and both floor from 0,
# so each 0.01° cell lies in exactly one 0.05° cell.
GRID_STEPS = {AREA_KIND: GRID_STEP, "latlon_grid_0p05": Decimal("0.05")}
ALL_AREA = "all"  # the citywide kind, and its one area_key
MIN_VENUES = 5
INDEXED_TARGET_KINDS = ("item", "variant")


@dataclass(slots=True)
class PriceIndexReport:
    """Counts from one rebuild; families are ``(scope subject, source record)`` pairs."""

    rows: int = 0
    families: int = 0
    placed: int = 0
    organization_placed: int = 0
    no_single_venue: int = 0  # not current/operating, several Establishments, or no point
    no_evidence: int = 0  # Organization family without Evidence to read its menu URL from
    shared_menu_url: int = 0  # Organization family whose menu URL another venue shares

    def summary(self) -> dict[str, int]:
        return {
            "rows": self.rows,
            "families": self.families,
            "placed": self.placed,
            "organization_placed": self.organization_placed,
            "no_single_venue": self.no_single_venue,
            "no_evidence": self.no_evidence,
            "shared_menu_url": self.shared_menu_url,
        }


@dataclass(frozen=True, slots=True)
class Placement:
    """One kept ``(scope subject, source record)`` family and the venue point it counts at."""

    subject_id: int
    subject_kind: str
    source_record_id: int
    venue_id: int
    latitude: Decimal
    longitude: Decimal
    via_organization: bool


# Drawn-area limits (ADR-0020 §1, OQ2).
BOUNDARY_MAX_LENGTH = 1200  # 50 x "-90.123456,-180.123456;"
BOUNDARY_MIN_CORNERS = 3
BOUNDARY_MAX_CORNERS = 50
BOUNDARY_MAX_SPAN = Decimal(2)  # degrees, of latitude and of longitude
# Plain decimal: no sign but "-", no exponent, at most 6 decimals (Numeric(9, 6)).
_COORDINATE = re.compile(r"-?[0-9]{1,3}(?:\.[0-9]{1,6})?")
_EXACT_DIGITS = 64  # well above any product of two differences of 6-decimal coordinates


class BoundaryError(ValueError):
    """A ``boundary`` that breaks a rule of ADR-0020 §1; the message names the rule."""


@dataclass(frozen=True, slots=True)
class Boundary:
    """A drawn area: 3-50 ``(latitude, longitude)`` corners, without a closing repeat."""

    corners: tuple[tuple[Decimal, Decimal], ...]

    @property
    def south(self) -> Decimal:
        return min(lat for lat, _ in self.corners)

    @property
    def north(self) -> Decimal:
        return max(lat for lat, _ in self.corners)

    @property
    def west(self) -> Decimal:
        return min(lon for _, lon in self.corners)

    @property
    def east(self) -> Decimal:
        return max(lon for _, lon in self.corners)

    def contains(self, latitude: Decimal, longitude: Decimal) -> bool:
        """Even-odd ray casting, longitude as x, in exact decimal arithmetic.

        An edge counts when it straddles the point's latitude (one end above,
        the other at or below) and crosses east of the point. On an
        axis-aligned rectangle that is the half-open range ``[south, north) x
        [west, east)``, the range :func:`grid_cell` floors into. A point wrapped
        an odd number of times is inside; a zero-area boundary holds nothing.
        """
        inside = False
        previous = self.corners[-1]
        # longitude < lon_i + (lon_j - lon_i) * (latitude - lat_i) / (lat_j - lat_i),
        # multiplied through by (lat_j - lat_i) so no division rounds; the
        # comparison flips when that factor is negative. The context is wide
        # enough that every difference and product is exact.
        with localcontext(prec=_EXACT_DIGITS):
            for corner in self.corners:
                (lat_i, lon_i), (lat_j, lon_j) = corner, previous
                if (lat_i > latitude) != (lat_j > latitude):
                    left = (longitude - lon_i) * (lat_j - lat_i)
                    right = (lon_j - lon_i) * (latitude - lat_i)
                    if (left < right) if lat_j > lat_i else (left > right):
                        inside = not inside
                previous = corner
        return inside


def _coordinate(text: str, low: int, high: int, name: str) -> Decimal:
    if not _COORDINATE.fullmatch(text):
        raise BoundaryError(
            f"each {name} must be a plain decimal with at most 6 decimals, got {text!r}"
        )
    value = Decimal(text) + 0  # + 0: "-0" is 0, as in grid_cell
    if not low <= value <= high:
        raise BoundaryError(f"each {name} must be in [{low}, {high}], got {text!r}")
    return value


def parse_boundary(text: str) -> Boundary:
    """Parse ``lat,lon;lat,lon;…`` (ADR-0020 §1), or raise :class:`BoundaryError`.

    3-50 corners in any order or orientation; a final corner equal to the first
    is dropped. At most 1,200 characters, and a bounding box of at most 2° of
    latitude and of longitude. A boundary that crosses itself is accepted.
    """
    if len(text) > BOUNDARY_MAX_LENGTH:
        raise BoundaryError(f"boundary must be at most {BOUNDARY_MAX_LENGTH} characters")
    corners: list[tuple[Decimal, Decimal]] = []
    for corner in text.split(";"):
        parts = corner.split(",")
        if len(parts) != 2:
            raise BoundaryError(f"each corner must be lat,lon, got {corner!r}")
        corners.append(
            (
                _coordinate(parts[0], -90, 90, "latitude"),
                _coordinate(parts[1], -180, 180, "longitude"),
            )
        )
    if len(corners) > 1 and corners[-1] == corners[0]:
        corners.pop()
    if not BOUNDARY_MIN_CORNERS <= len(corners) <= BOUNDARY_MAX_CORNERS:
        raise BoundaryError(
            f"boundary must have {BOUNDARY_MIN_CORNERS}-{BOUNDARY_MAX_CORNERS} corners, "
            f"got {len(corners)}"
        )
    boundary = Boundary(tuple(corners))
    if (
        boundary.north - boundary.south > BOUNDARY_MAX_SPAN
        or boundary.east - boundary.west > BOUNDARY_MAX_SPAN
    ):
        raise BoundaryError(
            f"boundary's bounding box must span at most {BOUNDARY_MAX_SPAN}° of latitude "
            "and of longitude"
        )
    return boundary


def grid_cell(
    latitude: Decimal, longitude: Decimal, step: Decimal = GRID_STEP
) -> tuple[str, Decimal, Decimal]:
    """The ``step``° cell containing a point, keyed by its south-west corner."""
    # + 0 turns a -0 input (a float query parameter) into 0: Postgres numeric has
    # no negative zero, so the refresh never keys a "-0.00" cell.
    latitude, longitude = latitude + 0, longitude + 0
    # quantize: a whole-degree input would otherwise print as "2.2E+1", not "22.00".
    # Both steps have two decimals, so every key prints with two.
    cell_lat = ((latitude / step).to_integral_value(ROUND_FLOOR) * step).quantize(step)
    cell_lon = ((longitude / step).to_integral_value(ROUND_FLOOR) * step).quantize(step)
    return f"{cell_lat},{cell_lon}", cell_lat, cell_lon


def _place(
    session: Session, effective_instant: datetime, report: PriceIndexReport
) -> list[Placement]:
    families = session.execute(
        select(
            CurrentMenu.subject_id,
            CurrentMenu.subject_kind,
            CurrentMenu.source_record_id,
            func.min(CurrentMenu.price_evidence_ids[1]),
        )
        .where(CurrentMenu.target_kind.in_(INDEXED_TARGET_KINDS))
        .group_by(CurrentMenu.subject_id, CurrentMenu.subject_kind, CurrentMenu.source_record_id)
        .order_by(CurrentMenu.subject_id, CurrentMenu.source_record_id)
    ).all()
    report.families = len(families)
    locations = current_venue_locations(
        session, {subject_id for subject_id, *_ in families}, at=effective_instant
    )
    placements: list[Placement] = []
    org_urls: dict[tuple[int, int], str] = {}
    for subject_id, subject_kind, source_record_id, evidence_id in families:
        location = locations.get(subject_id)
        if location is None:
            report.no_single_venue += 1
            continue
        via_organization = subject_kind == "organization"
        if via_organization:
            if evidence_id is None:
                report.no_evidence += 1
                continue
            org_urls[subject_id, source_record_id] = source_endpoint_for_evidence(
                session, evidence_id
            ).source_url
        placements.append(
            Placement(
                subject_id,
                subject_kind,
                source_record_id,
                location.establishment_subject_id,
                location.latitude,
                location.longitude,
                via_organization,
            )
        )
    venues_by_url: dict[str, set[int]] = {}
    for placement in placements:
        url = org_urls.get((placement.subject_id, placement.source_record_id))
        if url is not None:
            venues_by_url.setdefault(url, set()).add(placement.venue_id)
    kept: list[Placement] = []
    for placement in placements:
        url = org_urls.get((placement.subject_id, placement.source_record_id))
        if url is not None and len(venues_by_url[url]) > 1:
            report.shared_menu_url += 1
            continue
        kept.append(placement)
    report.placed = len(kept)
    report.organization_placed = sum(placement.via_organization for placement in kept)
    return kept


# Venue medians first, then percentiles across venues, per (area, category,
# currency); ``:area_keys`` and the cell arrays carry each placement's area (a
# cell of one kind, ``all``, or one drawn area). ``groups`` also yields rows
# whose only item/variant rows are non-priced (venue_count 0, statistics NULL),
# so coverage gaps stay visible. The refresh inserts these rows and a drawn area
# (ADR-0020) reads them, so cells and drawn areas can't drift.
_AGGREGATE = """
    WITH placed AS (
        SELECT * FROM unnest(
            CAST(:subjects AS bigint[]), CAST(:subject_kinds AS text[]),
            CAST(:records AS bigint[]), CAST(:venues AS bigint[]),
            CAST(:area_keys AS text[]), CAST(:cell_lats AS numeric[]),
            CAST(:cell_lons AS numeric[]), CAST(:via_organization AS boolean[])
        ) AS p(subject_id, subject_kind, source_record_id, venue_id, area_key, cell_lat,
               cell_lon, via_organization)
    ),
    indexed AS (
        SELECT p.venue_id, p.area_key, p.cell_lat, p.cell_lon, p.via_organization,
               'all'::text AS category_kind, 'all'::text AS category_key,
               c.currency_code, c.price_state, c.amount_minor, c.price_observed_at,
               c.source_record_id, c.price_evidence_ids
        FROM gold.current_menu c
        JOIN placed p
          ON p.subject_id = c.subject_id AND p.subject_kind = c.subject_kind
         AND p.source_record_id = c.source_record_id
        WHERE c.target_kind IN ('item', 'variant')
    ),
    spans AS (
        -- One printed price once: a record's priced rows citing the same Evidence (a
        -- choice line's variants). Their amounts are the one printed amount.
        SELECT area_key, category_kind, category_key, currency_code, venue_id,
               bool_or(via_organization) AS via_organization,
               min(amount_minor) AS amount_minor, count(*) AS row_count,
               min(price_observed_at) AS oldest_observed_at,
               max(price_observed_at) AS newest_observed_at
        FROM indexed
        WHERE price_state = 'priced'
        GROUP BY area_key, category_kind, category_key, currency_code, venue_id,
                 source_record_id, price_evidence_ids
    ),
    venue AS (
        SELECT area_key, category_kind, category_key, currency_code, venue_id,
               bool_or(via_organization) AS via_organization,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY amount_minor) AS venue_median,
               sum(row_count) AS priced_count,
               min(oldest_observed_at) AS oldest_observed_at,
               max(newest_observed_at) AS newest_observed_at
        FROM spans
        GROUP BY area_key, category_kind, category_key, currency_code, venue_id
    ),
    priced AS (
        SELECT area_key, category_kind, category_key, currency_code,
               count(*) AS venue_count,
               count(*) FILTER (WHERE via_organization) AS organization_venue_count,
               sum(priced_count) AS priced_count,
               percentile_disc(0.25) WITHIN GROUP (ORDER BY venue_median) AS p25_minor,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY venue_median) AS median_minor,
               percentile_disc(0.75) WITHIN GROUP (ORDER BY venue_median) AS p75_minor,
               min(venue_median) AS min_minor,
               max(venue_median) AS max_minor,
               min(oldest_observed_at) AS oldest_observed_at,
               max(newest_observed_at) AS newest_observed_at
        FROM venue
        GROUP BY area_key, category_kind, category_key, currency_code
    ),
    groups AS (
        SELECT area_key, min(cell_lat) AS cell_lat, min(cell_lon) AS cell_lon,
               category_kind, category_key, currency_code,
               count(*) FILTER (WHERE price_state <> 'priced') AS unpriced_count
        FROM indexed
        GROUP BY area_key, category_kind, category_key, currency_code
    )
    SELECT g.area_key, g.cell_lat, g.cell_lon, g.category_kind, g.category_key,
           g.currency_code, CAST(coalesce(p.venue_count, 0) AS integer) AS venue_count,
           CAST(coalesce(p.organization_venue_count, 0) AS integer)
               AS organization_venue_count,
           CAST(coalesce(p.priced_count, 0) AS integer) AS priced_count,
           CAST(g.unpriced_count AS integer) AS unpriced_count,
           CAST(:min_venues AS integer) AS min_venues,
           coalesce(p.venue_count, 0) < :min_venues AS low_sample, p.p25_minor,
           p.median_minor, p.p75_minor, p.min_minor, p.max_minor, p.oldest_observed_at,
           p.newest_observed_at
    FROM groups g
    LEFT JOIN priced p USING (area_key, category_kind, category_key, currency_code)
"""
_ORDER = " ORDER BY area_key, category_kind, category_key, currency_code"

#: The aggregate over given placements: one row per (area, category,
#: currency), in that order. Bind :func:`aggregate_params`.
# S608: both fragments are module constants; every value is a bound parameter.
AGGREGATE_SQL = text(f"SELECT * FROM ({_AGGREGATE}) AS a{_ORDER}")  # noqa: S608

_INSERT_SQL = text(f"""
    INSERT INTO gold.price_index (
        area_kind, area_key, cell_lat, cell_lon, category_kind, category_key,
        currency_code, effective_instant, venue_count, organization_venue_count,
        priced_count, unpriced_count, min_venues, low_sample, p25_minor, median_minor,
        p75_minor, min_minor, max_minor, oldest_observed_at, newest_observed_at,
        refreshed_at
    )
    SELECT :area_kind, area_key, cell_lat, cell_lon, category_kind, category_key,
           currency_code, :effective_instant, venue_count, organization_venue_count,
           priced_count, unpriced_count, min_venues, low_sample, p25_minor, median_minor,
           p75_minor, min_minor, max_minor, oldest_observed_at, newest_observed_at,
           :refreshed_at
    FROM ({_AGGREGATE}) AS a{_ORDER}
""")  # noqa: S608

#: A placement's area for the aggregate: ``(area_key, cell_lat, cell_lon)``.
type Area = tuple[str, Decimal | None, Decimal | None]


def aggregate_params(placements: Sequence[Placement], areas: Sequence[Area]) -> dict[str, Any]:
    """:data:`AGGREGATE_SQL`'s parameters: each placement, counted in its area."""
    return {
        "subjects": [p.subject_id for p in placements],
        "subject_kinds": [p.subject_kind for p in placements],
        "records": [p.source_record_id for p in placements],
        "venues": [p.venue_id for p in placements],
        "area_keys": [area[0] for area in areas],
        "cell_lats": [area[1] for area in areas],
        "cell_lons": [area[2] for area in areas],
        "via_organization": [p.via_organization for p in placements],
        "min_venues": MIN_VENUES,
    }


def refresh_price_index(
    session: Session,
    *,
    effective_instant: datetime,
    refreshed_at: datetime | None = None,
) -> PriceIndexReport:
    """Rebuild ``gold.price_index`` and its placements from ``gold.current_menu`` as of ``E``.

    ``effective_instant`` is when venues are placed (current, operating) and is
    stored as the index's as-of; run :func:`refresh_full_catalog` at the same
    instant first so ``current_menu`` answers for it too. The kept placements
    are written to ``gold.price_index_placement`` at the same instant, one row
    each (ADR-0020 §2). Returns the report; the command flushes and the caller
    owns the commit.
    """
    report = PriceIndexReport()
    placements = _place(session, effective_instant, report)
    session.execute(delete(PriceIndex))
    session.execute(delete(PriceIndexPlacement))
    refreshed_at = refreshed_at if refreshed_at is not None else datetime.now(UTC)
    if placements:
        session.execute(
            insert(PriceIndexPlacement),
            [
                {
                    "subject_id": p.subject_id,
                    "subject_kind": p.subject_kind,
                    "source_record_id": p.source_record_id,
                    "venue_id": p.venue_id,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "via_organization": p.via_organization,
                    "effective_instant": effective_instant,
                    "refreshed_at": refreshed_at,
                }
                for p in placements
            ],
        )
    for area_kind in (*GRID_STEPS, ALL_AREA) if placements else ():
        step = GRID_STEPS.get(area_kind)
        areas: list[Area] = [
            (ALL_AREA, None, None) if step is None else grid_cell(p.latitude, p.longitude, step)
            for p in placements
        ]
        session.execute(
            _INSERT_SQL,
            {
                **aggregate_params(placements, areas),
                "area_kind": area_kind,
                "effective_instant": effective_instant,
                "refreshed_at": refreshed_at,
            },
        )
    session.flush()
    report.rows = session.scalar(select(func.count()).select_from(PriceIndex)) or 0
    return report
