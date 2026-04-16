#!/usr/bin/env python3
"""Rebuild canonical meal-deal venue and site identity scaffolding.

This is an initial backfill step for the canonical venue/site model. It is
rebuild-oriented: the script clears the canonical identity tables and
repopulates them from the current `local_employers` + `restaurant_urls`
state using the same conservative venue-identity helper already used by the
website scraper and API dedupe path.
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from urllib.parse import urlparse

from core.database import (
    CanonicalVenue,
    CanonicalVenueAlias,
    LocalEmployer,
    RestaurantURL,
    SiteAssignment,
    SiteIdentity,
    get_session,
    init_db,
)
from core.normalizer import make_fingerprint
from core.venue_identity import (
    cluster_likely_same_venues,
    normalize_address_for_identity,
    normalize_url_for_identity,
    pick_canonical_item,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_FOOD_INDUSTRIES = ("food_full_service", "fast_food", "bar_nightlife")


def _restaurant_url_rank(row: RestaurantURL) -> tuple:
    return (
        1 if row.is_permanent else 0,
        row.confidence or 0.0,
        1 if row.source == "manual" else 0,
        row.id or 0,
    )


def _load_scope(session, region: str) -> tuple[list[LocalEmployer], dict[int, list[RestaurantURL]]]:
    employers = session.query(LocalEmployer).filter(
        LocalEmployer.region == region,
        LocalEmployer.is_active.is_(True),
        LocalEmployer.industry.in_(_FOOD_INDUSTRIES),
    ).all()
    employer_ids = [emp.id for emp in employers]
    if not employer_ids:
        return [], {}

    url_rows = session.query(RestaurantURL).filter(
        RestaurantURL.local_employer_id.in_(employer_ids),
        RestaurantURL.is_active.is_(True),
    ).all()
    urls_by_employer: dict[int, list[RestaurantURL]] = defaultdict(list)
    for row in url_rows:
        urls_by_employer[row.local_employer_id].append(row)
    return employers, urls_by_employer


def _best_url(urls: list[RestaurantURL]) -> RestaurantURL | None:
    if not urls:
        return None
    return max(urls, key=_restaurant_url_rank)


def rebuild_meal_deal_identity(session, *, region: str = "austin_tx") -> dict[str, int]:
    employers, urls_by_employer = _load_scope(session, region)
    if not employers:
        return {
            "canonical_venues": 0,
            "venue_aliases": 0,
            "site_identities": 0,
            "site_assignments": 0,
            "employers_scanned": 0,
            "shared_url_groups": 0,
        }

    session.query(SiteAssignment).delete()
    session.query(SiteIdentity).delete()
    session.query(CanonicalVenueAlias).delete()
    session.query(CanonicalVenue).delete()
    session.flush()

    primary_url_by_employer = {
        emp.id: _best_url(urls_by_employer.get(emp.id, []))
        for emp in employers
    }

    grouped: dict[str, list[LocalEmployer]] = defaultdict(list)
    for emp in employers:
        primary_url = primary_url_by_employer.get(emp.id)
        normalized_url = normalize_url_for_identity(primary_url.url) if primary_url else None
        grouped[normalized_url or f"emp:{emp.id}"].append(emp)

    employer_to_canonical: dict[int, int] = {}
    canonical_count = 0
    alias_count = 0
    shared_url_groups = 0

    for group_key, group in grouped.items():
        normalized_url = None if group_key.startswith("emp:") else group_key
        if normalized_url and len(group) > 1:
            shared_url_groups += 1

        clusters = cluster_likely_same_venues(
            group,
            get_name=lambda emp: emp.name,
            get_address=lambda emp: emp.address,
            get_url=lambda emp: primary_url_by_employer.get(emp.id).url if primary_url_by_employer.get(emp.id) else None,
            get_lat=lambda emp: emp.lat,
            get_lng=lambda emp: emp.lng,
        )

        multiple_clusters = len(clusters) > 1
        for cluster in clusters:
            canonical_emp = pick_canonical_item(
                cluster,
                get_id=lambda emp: emp.id,
                get_brand_group_id=lambda emp: emp.brand_group_id,
                get_address=lambda emp: emp.address,
            )
            if not normalized_url:
                site_status = "no_site"
            elif multiple_clusters:
                site_status = "disputed_site"
            elif len(cluster) > 1:
                site_status = "shared_site"
            else:
                site_status = "single_site"

            venue = CanonicalVenue(
                canonical_name=canonical_emp.name,
                normalized_name=make_fingerprint(canonical_emp.name),
                normalized_address=normalize_address_for_identity(canonical_emp.address),
                address=canonical_emp.address,
                lat=canonical_emp.lat,
                lng=canonical_emp.lng,
                region=canonical_emp.region or region,
                brand_group_id=canonical_emp.brand_group_id,
                site_status=site_status,
                is_active=True,
            )
            session.add(venue)
            session.flush()
            canonical_count += 1

            for emp in cluster:
                employer_to_canonical[emp.id] = venue.id
                session.add(CanonicalVenueAlias(
                    canonical_venue_id=venue.id,
                    local_employer_id=emp.id,
                    alias_role="primary" if emp.id == canonical_emp.id else "alias",
                    match_method="url_geo" if normalized_url else "address_name",
                    match_confidence=1.0 if emp.id == canonical_emp.id else 0.92,
                ))
                alias_count += 1

    site_identity_count = 0
    site_assignment_count = 0
    all_urls = [row for rows in urls_by_employer.values() for row in rows]
    url_groups: dict[str, list[RestaurantURL]] = defaultdict(list)
    for row in all_urls:
        normalized = normalize_url_for_identity(row.url)
        if normalized:
            url_groups[normalized].append(row)

    for normalized_url, rows in url_groups.items():
        chosen = _best_url(rows)
        if chosen is None:
            continue
        parsed = urlparse(chosen.url)

        canonical_ids = {
            employer_to_canonical[row.local_employer_id]
            for row in rows
            if row.local_employer_id in employer_to_canonical
        }
        brand_ids = {
            row.brand_group_id
            for row in rows
            if row.brand_group_id is not None
        }

        if len(canonical_ids) == 1:
            ownership_scope = "venue"
            conflict_state = "clear"
        elif len(brand_ids) == 1 and brand_ids:
            ownership_scope = "brand"
            conflict_state = "clear"
        elif canonical_ids:
            ownership_scope = "mixed"
            conflict_state = "needs_review"
        else:
            ownership_scope = "unknown"
            conflict_state = "needs_review"

        site_identity = SiteIdentity(
            normalized_url=normalized_url,
            canonical_url=chosen.url,
            host=(parsed.netloc or "").lower().removeprefix("www."),
            path=(parsed.path or "").lower().rstrip("/") or "/",
            ownership_scope=ownership_scope,
            conflict_state=conflict_state,
        )
        session.add(site_identity)
        session.flush()
        site_identity_count += 1

        if ownership_scope == "venue":
            session.add(SiteAssignment(
                site_identity_id=site_identity.id,
                canonical_venue_id=next(iter(canonical_ids)),
                assignment_scope="venue",
                match_method="restaurant_url_backfill",
                match_confidence=0.95,
                is_primary=True,
            ))
            site_assignment_count += 1
        elif ownership_scope == "brand":
            session.add(SiteAssignment(
                site_identity_id=site_identity.id,
                brand_group_id=next(iter(brand_ids)),
                assignment_scope="brand",
                match_method="restaurant_url_backfill",
                match_confidence=0.9,
                is_primary=True,
            ))
            site_assignment_count += 1
        else:
            for canonical_id in sorted(canonical_ids):
                session.add(SiteAssignment(
                    site_identity_id=site_identity.id,
                    canonical_venue_id=canonical_id,
                    assignment_scope="contested",
                    match_method="restaurant_url_backfill",
                    match_confidence=0.5,
                    is_primary=False,
                ))
                site_assignment_count += 1

    return {
        "canonical_venues": canonical_count,
        "venue_aliases": alias_count,
        "site_identities": site_identity_count,
        "site_assignments": site_assignment_count,
        "employers_scanned": len(employers),
        "shared_url_groups": shared_url_groups,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild canonical meal-deal identity tables")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        stats = rebuild_meal_deal_identity(session, region=args.region)
        if args.dry_run:
            session.rollback()
            logger.info("[MealDealIdentity] Dry run complete: %s", stats)
        else:
            session.commit()
            logger.info("[MealDealIdentity] Rebuilt canonical identity tables: %s", stats)
        return 0
    except Exception as exc:
        session.rollback()
        logger.error("[MealDealIdentity] Failed: %s", exc, exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())