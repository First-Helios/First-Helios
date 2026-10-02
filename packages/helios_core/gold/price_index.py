"""Full deterministic rebuild of ``gold.price_index`` over ``gold.current_menu`` (ADR-0007).

The index reads only the accepted ``current_menu`` projection, so "current" stays
defined once, by the Menu selector. Item and variant rows count; modifiers (add-on
amounts) and section-level prices do not. Rules (ADR-0007 Amendment 1):

* **Placement.** Each ``(scope subject, source record)`` family is placed at one
  venue's lat/lon grid cell or left out. An Establishment-scoped family is placed
  at that Establishment. An Organization-scoped family (own-site pages, and
  platform pages several venues share) is placed at its Organization's only
  current operating Establishment, unless the menu URL its prices were read from
  is also the menu URL of another placed venue's Organization family (a shared
  chain or platform menu): those are left out, never fanned out (ADR-0005 §11).
* **Weighting.** Each venue weighs one. Per group, a venue's sample is the median
  of its priced rows; the percentiles are over those venue medians. Both use
  ``percentile_disc``, so every statistic is an observed integer amount (the
  lower middle value for an even count); no float touches a price.
* **Categories.** Only ``all`` today; ``course`` arrives as another
  ``category_kind`` once a course label exists (ADR-0007 Amendment 1).
* **Honesty.** Groups below :data:`MIN_VENUES` venues are kept and flagged
  ``low_sample``. Non-priced rows are counted, never in a percentile.

The rebuild replaces the whole table. Business columns are a deterministic
function of ``current_menu`` and Identity at ``effective_instant``;
``refreshed_at`` is run metadata. Nothing outside ``gold.price_index`` is
written; the caller owns the commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_FLOOR, Decimal
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select, text

from packages.helios_core.gold.models import CurrentMenu, PriceIndex
from packages.helios_core.identity.contracts import current_venue_locations
from packages.helios_core.provenance.contracts import source_endpoint_for_evidence

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

AREA_KIND = "latlon_grid_0p01"
GRID_STEP = Decimal("0.01")  # ~1.1 km north-south, ~1.0 km east-west in Austin
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
class _Placement:
    subject_id: int
    source_record_id: int
    venue_id: int
    area_key: str
    cell_lat: Decimal
    cell_lon: Decimal
    via_organization: bool


def grid_cell(latitude: Decimal, longitude: Decimal) -> tuple[str, Decimal, Decimal]:
    """The 0.01° cell containing a point, keyed by its south-west corner."""
    # + 0 turns a -0 input (a float query parameter) into 0: Postgres numeric has
    # no negative zero, so the refresh never keys a "-0.00" cell.
    latitude, longitude = latitude + 0, longitude + 0
    # quantize: a whole-degree input would otherwise print as "2.2E+1", not "22.00"
    cell_lat = ((latitude / GRID_STEP).to_integral_value(ROUND_FLOOR) * GRID_STEP).quantize(
        GRID_STEP
    )
    cell_lon = ((longitude / GRID_STEP).to_integral_value(ROUND_FLOOR) * GRID_STEP).quantize(
        GRID_STEP
    )
    return f"{cell_lat},{cell_lon}", cell_lat, cell_lon


def _place(
    session: Session, effective_instant: datetime, report: PriceIndexReport
) -> list[_Placement]:
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
    placements: list[_Placement] = []
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
        area_key, cell_lat, cell_lon = grid_cell(location.latitude, location.longitude)
        placements.append(
            _Placement(
                subject_id,
                source_record_id,
                location.establishment_subject_id,
                area_key,
                cell_lat,
                cell_lon,
                via_organization,
            )
        )
    venues_by_url: dict[str, set[int]] = {}
    for placement in placements:
        url = org_urls.get((placement.subject_id, placement.source_record_id))
        if url is not None:
            venues_by_url.setdefault(url, set()).add(placement.venue_id)
    kept: list[_Placement] = []
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
# currency). ``groups`` also yields rows whose only item/variant rows are
# non-priced (venue_count 0, statistics NULL), so coverage gaps stay visible.
_INSERT_SQL = text("""
    WITH placed AS (
        SELECT * FROM unnest(
            CAST(:subjects AS bigint[]), CAST(:records AS bigint[]),
            CAST(:venues AS bigint[]), CAST(:area_keys AS text[]),
            CAST(:cell_lats AS numeric[]), CAST(:cell_lons AS numeric[]),
            CAST(:via_organization AS boolean[])
        ) AS p(subject_id, source_record_id, venue_id, area_key, cell_lat, cell_lon,
               via_organization)
    ),
    indexed AS (
        SELECT p.venue_id, p.area_key, p.cell_lat, p.cell_lon, p.via_organization,
               'all'::text AS category_kind, 'all'::text AS category_key,
               c.currency_code, c.price_state, c.amount_minor, c.price_observed_at
        FROM gold.current_menu c
        JOIN placed p
          ON p.subject_id = c.subject_id AND p.source_record_id = c.source_record_id
        WHERE c.target_kind IN ('item', 'variant')
    ),
    venue AS (
        SELECT area_key, category_kind, category_key, currency_code, venue_id,
               bool_or(via_organization) AS via_organization,
               percentile_disc(0.5) WITHIN GROUP (ORDER BY amount_minor) AS venue_median,
               count(*) AS priced_count,
               min(price_observed_at) AS oldest_observed_at,
               max(price_observed_at) AS newest_observed_at
        FROM indexed
        WHERE price_state = 'priced'
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
    INSERT INTO gold.price_index (
        area_kind, area_key, cell_lat, cell_lon, category_kind, category_key,
        currency_code, effective_instant, venue_count, organization_venue_count,
        priced_count, unpriced_count, min_venues, low_sample, p25_minor, median_minor,
        p75_minor, min_minor, max_minor, oldest_observed_at, newest_observed_at,
        refreshed_at
    )
    SELECT :area_kind, g.area_key, g.cell_lat, g.cell_lon, g.category_kind,
           g.category_key, g.currency_code, :effective_instant,
           coalesce(p.venue_count, 0), coalesce(p.organization_venue_count, 0),
           coalesce(p.priced_count, 0), g.unpriced_count, :min_venues,
           coalesce(p.venue_count, 0) < :min_venues, p.p25_minor, p.median_minor,
           p.p75_minor, p.min_minor, p.max_minor, p.oldest_observed_at,
           p.newest_observed_at, :refreshed_at
    FROM groups g
    LEFT JOIN priced p USING (area_key, category_kind, category_key, currency_code)
    ORDER BY g.area_key, g.category_kind, g.category_key, g.currency_code
""")


def refresh_price_index(
    session: Session,
    *,
    effective_instant: datetime,
    refreshed_at: datetime | None = None,
) -> PriceIndexReport:
    """Rebuild the whole ``gold.price_index`` from ``gold.current_menu`` as of ``E``.

    ``effective_instant`` is when venues are placed (current, operating) and is
    stored as the index's as-of; run :func:`refresh_full_catalog` at the same
    instant first so ``current_menu`` answers for it too. Returns the report;
    the command flushes and the caller owns the commit.
    """
    report = PriceIndexReport()
    placements = _place(session, effective_instant, report)
    session.execute(delete(PriceIndex))
    if placements:
        session.execute(
            _INSERT_SQL,
            {
                "subjects": [p.subject_id for p in placements],
                "records": [p.source_record_id for p in placements],
                "venues": [p.venue_id for p in placements],
                "area_keys": [p.area_key for p in placements],
                "cell_lats": [p.cell_lat for p in placements],
                "cell_lons": [p.cell_lon for p in placements],
                "via_organization": [p.via_organization for p in placements],
                "area_kind": AREA_KIND,
                "effective_instant": effective_instant,
                "min_venues": MIN_VENUES,
                "refreshed_at": refreshed_at if refreshed_at is not None else datetime.now(UTC),
            },
        )
    session.flush()
    report.rows = session.scalar(select(func.count()).select_from(PriceIndex)) or 0
    return report
