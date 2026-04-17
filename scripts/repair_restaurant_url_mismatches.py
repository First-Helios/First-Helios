#!/usr/bin/env python3
"""Purge mismatched restaurant URLs and re-resolve affected employers.

This script extends the existing URL-identity audit by handling isolated bad URL
assignments like a restaurant pointing at another business's website. It can:

1. Detect mismatches from shared-URL conflicts and fetched site identity text.
2. Purge the bad `restaurant_urls` rows.
3. Purge contaminated `website_scrape` legacy and semantic rows for the same employer/url.
4. Re-resolve websites for the cleaned employers via OSM first, then targeted Google Places.

Usage:
  PYTHONPATH=. python scripts/repair_restaurant_url_mismatches.py
  PYTHONPATH=. python scripts/repair_restaurant_url_mismatches.py --fix --recollect
  PYTHONPATH=. python scripts/repair_restaurant_url_mismatches.py --fix --recollect --target-local-employer-id 14732
"""

from __future__ import annotations

import argparse
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from collectors.meal_deals.google_places_resolver import resolve_local_urls
from collectors.meal_deals.osm_url_resolver import fetch_osm_restaurant_websites, match_and_store_urls
from core.database import (
    DealApplicability,
    DealMaterialization,
    DealObservation,
    GooglePlacesFailure,
    LocalEmployer,
    MealDeal,
    RestaurantURL,
    get_session,
    init_db,
)
from core.normalizer import make_fingerprint
from scripts.audit_url_identity import (
    _compact_name,
    _name_tokens,
    _url_identity_text,
    _url_match_score,
    audit_cross_brand_urls,
    audit_name_mismatch_urls,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_SITE_FETCH_HEADERS = {
    "User-Agent": "FirstHelios/1.0 (community labor research)",
}


def _normalize_url_key(url: str | None) -> str:
    if not url:
        return ""
    return url.rstrip("/").lower()


def _identity_match_score(name: str, text: str) -> int:
    """Score how strongly arbitrary identity text matches a business name."""
    if not name or not text:
        return 0

    name_tokens = _name_tokens(name)
    text_tokens = _name_tokens(text)
    compact_name = _compact_name(name)
    compact_text = _compact_name(text)

    score = 0
    if compact_name and compact_name in compact_text:
        score += 2
    overlap = len(name_tokens & text_tokens)
    if overlap:
        score += min(2, overlap)
    return score


def _fetch_site_identity_snapshot(url: str, timeout: int = 12) -> dict[str, str] | None:
    """Fetch homepage identity text that can be compared against employer names."""
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers=_SITE_FETCH_HEADERS,
            allow_redirects=True,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.debug("[URL-Repair] Failed to fetch %s: %s", url, exc)
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    identity_parts: list[str] = []

    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    if title:
        identity_parts.append(title)

    meta_specs = [
        ("property", "og:site_name"),
        ("property", "og:title"),
        ("name", "application-name"),
        ("name", "twitter:title"),
    ]
    for attr_name, attr_value in meta_specs:
        meta = soup.find("meta", attrs={attr_name: attr_value})
        content = meta.get("content", "").strip() if meta else ""
        if content:
            identity_parts.append(content)

    heading = soup.find(["h1", "h2"])
    heading_text = heading.get_text(" ", strip=True) if heading else ""
    if heading_text:
        identity_parts.append(heading_text)

    final_url = response.url or url
    identity_text = " ".join(part for part in identity_parts if part).strip()
    return {
        "final_url": final_url,
        "identity_text": identity_text,
        "display_text": " | ".join(identity_parts[:4])[:200],
        "host": (urlparse(final_url).netloc or "").lower(),
    }


def _build_employer_identity_index(
    session: Any,
    *,
    region: str = "austin_tx",
) -> tuple[dict[int, dict[str, Any]], dict[str, set[int]]]:
    employers = (
        session.query(LocalEmployer)
        .filter(
            LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
        )
        .all()
    )

    by_id: dict[int, dict[str, Any]] = {}
    token_index: dict[str, set[int]] = defaultdict(set)

    for emp in employers:
        fingerprint = emp.fingerprint or make_fingerprint(emp.name)
        record = {
            "id": emp.id,
            "name": emp.name,
            "brand_group_id": emp.brand_group_id,
            "fingerprint": fingerprint,
        }
        by_id[emp.id] = record
        for token in _name_tokens(emp.name):
            token_index[token].add(emp.id)

    return by_id, token_index


def _candidate_employer_ids(identity_basis: str, token_index: dict[str, set[int]]) -> set[int]:
    candidate_ids: set[int] = set()
    for token in _name_tokens(identity_basis):
        candidate_ids.update(token_index.get(token, set()))
    return candidate_ids


def audit_site_identity_mismatches(
    session: Any,
    *,
    region: str = "austin_tx",
    target_employer_ids: set[int] | None = None,
    max_fetches: int | None = None,
) -> list[dict[str, Any]]:
    """Detect isolated bad URL assignments by comparing fetched site identity text."""
    query = (
        session.query(RestaurantURL, LocalEmployer)
        .join(LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id)
        .filter(
            RestaurantURL.is_active.is_(True),
            RestaurantURL.source.in_(["google_places", "osm"]),
            LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
            LocalEmployer.region == region,
            LocalEmployer.is_active.is_(True),
        )
    )
    if target_employer_ids:
        query = query.filter(LocalEmployer.id.in_(sorted(target_employer_ids)))

    rows = query.all()
    url_groups: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    for rurl, emp in rows:
        url_groups[_normalize_url_key(rurl.url)].append((rurl, emp))

    employers_by_id, token_index = _build_employer_identity_index(session, region=region)
    mismatches: list[dict[str, Any]] = []
    fetch_count = 0

    for _normalized_url, group in url_groups.items():
        if max_fetches is not None and fetch_count >= max_fetches:
            break

        if not any(_url_match_score(emp.name, rurl.url) == 0 for rurl, emp in group):
            continue

        snapshot = _fetch_site_identity_snapshot(group[0][0].url)
        fetch_count += 1
        if not snapshot:
            continue

        identity_basis = f"{_url_identity_text(snapshot['final_url'])} {snapshot['identity_text']}".strip()
        if not identity_basis:
            continue

        candidate_ids = _candidate_employer_ids(identity_basis, token_index)
        if not candidate_ids:
            continue

        for rurl, emp in group:
            owner_score = max(
                _url_match_score(emp.name, snapshot["final_url"]),
                _identity_match_score(emp.name, identity_basis),
            )

            best_alt: dict[str, Any] | None = None
            owner_fingerprint = emp.fingerprint or make_fingerprint(emp.name)
            for candidate_id in candidate_ids:
                candidate = employers_by_id.get(candidate_id)
                if not candidate or candidate_id == emp.id:
                    continue
                if candidate["fingerprint"] == owner_fingerprint:
                    continue
                if emp.brand_group_id is not None and candidate["brand_group_id"] == emp.brand_group_id:
                    continue

                candidate_score = max(
                    _url_match_score(candidate["name"], snapshot["final_url"]),
                    _identity_match_score(candidate["name"], identity_basis),
                )
                if best_alt is None or candidate_score > best_alt["score"]:
                    best_alt = {
                        "id": candidate_id,
                        "name": candidate["name"],
                        "score": candidate_score,
                    }

            if not best_alt or best_alt["score"] < 3 or owner_score > 0:
                continue

            mismatches.append(
                {
                    "rurl_id": rurl.id,
                    "emp_id": emp.id,
                    "emp_name": emp.name,
                    "url": rurl.url,
                    "source": rurl.source,
                    "likely_owner_names": [best_alt["name"]],
                    "evidence": snapshot["display_text"] or snapshot["final_url"],
                    "evidence_url": snapshot["final_url"],
                }
            )

    return mismatches


def merge_actionable_mismatches(*mismatch_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[int, dict[str, Any]] = {}
    for group in mismatch_groups:
        for mismatch in group:
            merged.setdefault(mismatch["rurl_id"], mismatch)
    return list(merged.values())


def find_contaminated_scrape_counts(session: Any, actionable_mismatches: list[dict[str, Any]]) -> dict[str, int]:
    bad_pairs = {
        (mismatch["emp_id"], _normalize_url_key(mismatch["url"]))
        for mismatch in actionable_mismatches
    }

    legacy_count = 0
    materialization_count = 0

    if bad_pairs:
        bad_emp_ids = sorted({emp_id for emp_id, _url in bad_pairs})
        for row in (
            session.query(MealDeal.local_employer_id, MealDeal.source_url)
            .filter(
                MealDeal.local_employer_id.in_(bad_emp_ids),
                MealDeal.is_active.is_(True),
                MealDeal.source == "website_scrape",
            )
            .all()
        ):
            if (row.local_employer_id, _normalize_url_key(row.source_url)) in bad_pairs:
                legacy_count += 1

        for row in (
            session.query(DealMaterialization.local_employer_id, DealMaterialization.source_url)
            .filter(
                DealMaterialization.local_employer_id.in_(bad_emp_ids),
                DealMaterialization.is_active.is_(True),
                DealMaterialization.source == "website_scrape",
            )
            .all()
        ):
            if (row.local_employer_id, _normalize_url_key(row.source_url)) in bad_pairs:
                materialization_count += 1

    return {
        "legacy_meal_deals": legacy_count,
        "materializations": materialization_count,
    }


def purge_restaurant_url_mismatches(
    session: Any,
    actionable_mismatches: list[dict[str, Any]],
) -> tuple[dict[str, int], set[int]]:
    """Delete bad URL rows and purge contaminated website-scrape data."""
    mismatches = merge_actionable_mismatches(actionable_mismatches)
    stats = {
        "restaurant_urls_deleted": 0,
        "meal_deals_deleted": 0,
        "materializations_deleted": 0,
        "applicability_deleted": 0,
        "observations_deleted": 0,
        "google_failures_cleared": 0,
    }
    cleaned_employer_ids: set[int] = set()

    if not mismatches:
        return stats, cleaned_employer_ids

    bad_pairs = {
        (mismatch["emp_id"], _normalize_url_key(mismatch["url"]))
        for mismatch in mismatches
    }
    bad_rurl_ids = {mismatch["rurl_id"] for mismatch in mismatches}
    cleaned_employer_ids = {mismatch["emp_id"] for mismatch in mismatches}

    meal_deal_ids = [
        row.id
        for row in session.query(MealDeal.id, MealDeal.local_employer_id, MealDeal.source_url)
        .filter(
            MealDeal.local_employer_id.in_(sorted(cleaned_employer_ids)),
            MealDeal.source == "website_scrape",
        )
        .all()
        if (row.local_employer_id, _normalize_url_key(row.source_url)) in bad_pairs
    ]

    materialization_rows = [
        row
        for row in session.query(
            DealMaterialization.id,
            DealMaterialization.local_employer_id,
            DealMaterialization.source_url,
            DealMaterialization.applicability_id,
            DealMaterialization.observation_id,
        )
        .filter(
            DealMaterialization.local_employer_id.in_(sorted(cleaned_employer_ids)),
            DealMaterialization.source == "website_scrape",
        )
        .all()
        if (row.local_employer_id, _normalize_url_key(row.source_url)) in bad_pairs
    ]

    if meal_deal_ids:
        stats["meal_deals_deleted"] = (
            session.query(MealDeal)
            .filter(MealDeal.id.in_(meal_deal_ids))
            .delete(synchronize_session=False)
        )

    materialization_ids = [row.id for row in materialization_rows]
    applicability_ids = {row.applicability_id for row in materialization_rows}
    observation_ids = {row.observation_id for row in materialization_rows}

    if materialization_ids:
        stats["materializations_deleted"] = (
            session.query(DealMaterialization)
            .filter(DealMaterialization.id.in_(materialization_ids))
            .delete(synchronize_session=False)
        )

    orphan_applicability_ids = [
        applicability_id
        for applicability_id in applicability_ids
        if session.query(DealMaterialization.id)
        .filter(DealMaterialization.applicability_id == applicability_id)
        .first()
        is None
    ]
    if orphan_applicability_ids:
        stats["applicability_deleted"] = (
            session.query(DealApplicability)
            .filter(DealApplicability.id.in_(orphan_applicability_ids))
            .delete(synchronize_session=False)
        )

    orphan_observation_ids = [
        observation_id
        for observation_id in observation_ids
        if session.query(DealMaterialization.id)
        .filter(DealMaterialization.observation_id == observation_id)
        .first()
        is None
        and session.query(DealApplicability.id)
        .filter(DealApplicability.observation_id == observation_id)
        .first()
        is None
    ]
    if orphan_observation_ids:
        stats["observations_deleted"] = (
            session.query(DealObservation)
            .filter(DealObservation.id.in_(orphan_observation_ids))
            .delete(synchronize_session=False)
        )

    stats["restaurant_urls_deleted"] = (
        session.query(RestaurantURL)
        .filter(RestaurantURL.id.in_(sorted(bad_rurl_ids)))
        .delete(synchronize_session=False)
    )

    stats["google_failures_cleared"] = (
        session.query(GooglePlacesFailure)
        .filter(
            GooglePlacesFailure.entity_type == "local_employer",
            GooglePlacesFailure.entity_id.in_(sorted(cleaned_employer_ids)),
        )
        .delete(synchronize_session=False)
    )

    session.commit()
    return stats, cleaned_employer_ids


def _employers_without_active_urls(session: Any, employer_ids: set[int]) -> set[int]:
    if not employer_ids:
        return set()

    active_ids = {
        employer_id
        for employer_id, in session.query(RestaurantURL.local_employer_id)
        .filter(
            RestaurantURL.local_employer_id.in_(sorted(employer_ids)),
            RestaurantURL.is_active.is_(True),
            RestaurantURL.url.isnot(None),
        )
        .distinct()
        .all()
    }
    return set(employer_ids) - active_ids


def recollect_cleaned_employers(
    *,
    region: str,
    cleaned_employer_ids: set[int],
) -> dict[str, Any]:
    """Try to refill cleaned restaurant URLs via OSM first, then targeted Google Places."""
    stats: dict[str, Any] = {
        "cleaned_employers": len(cleaned_employer_ids),
        "initial_unresolved": 0,
        "remaining_after_osm": 0,
        "final_unresolved": 0,
        "osm": None,
        "google_local": None,
    }
    if not cleaned_employer_ids:
        return stats

    engine = init_db()
    session = get_session(engine)
    try:
        unresolved = _employers_without_active_urls(session, cleaned_employer_ids)
    finally:
        session.close()

    stats["initial_unresolved"] = len(unresolved)
    if not unresolved:
        return stats

    osm_pois = fetch_osm_restaurant_websites()
    stats["osm"] = match_and_store_urls(
        osm_pois,
        region=region,
        dry_run=False,
        target_employer_ids=unresolved,
    )

    engine = init_db()
    session = get_session(engine)
    try:
        unresolved = _employers_without_active_urls(session, cleaned_employer_ids)
    finally:
        session.close()

    stats["remaining_after_osm"] = len(unresolved)
    if unresolved:
        try:
            stats["google_local"] = resolve_local_urls(
                region=region,
                max_calls=len(unresolved),
                dry_run=False,
                retry_failed=True,
                target_employer_ids=unresolved,
            )
        except Exception as exc:
            stats["google_local"] = {"error": str(exc)}

    engine = init_db()
    session = get_session(engine)
    try:
        final_unresolved = _employers_without_active_urls(session, cleaned_employer_ids)
    finally:
        session.close()

    stats["final_unresolved"] = len(final_unresolved)
    return stats


def _filter_targeted_mismatches(
    mismatches: list[dict[str, Any]],
    target_employer_ids: set[int] | None,
) -> list[dict[str, Any]]:
    if not target_employer_ids:
        return mismatches
    return [mismatch for mismatch in mismatches if mismatch["emp_id"] in target_employer_ids]


def _filter_targeted_problems(
    problems: list[dict[str, Any]],
    target_employer_ids: set[int] | None,
) -> list[dict[str, Any]]:
    if not target_employer_ids:
        return problems

    filtered: list[dict[str, Any]] = []
    for problem in problems:
        if any(entry["emp_id"] in target_employer_ids for entries in problem["brands"].values() for entry in entries):
            filtered.append(problem)
    return filtered


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Purge mismatched restaurant_urls and re-resolve cleaned employers"
    )
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--fix", action="store_true", help="Delete mismatched URL rows and contaminated scrape rows")
    parser.add_argument("--recollect", action="store_true", help="After cleanup, try to re-resolve URLs for the cleaned employers")
    parser.add_argument(
        "--target-local-employer-id",
        type=int,
        action="append",
        default=[],
        help="Limit the repair run to one or more specific local_employer IDs",
    )
    parser.add_argument(
        "--site-fetch-limit",
        type=int,
        default=None,
        help="Optional cap on site-identity fetches during mismatch detection",
    )
    args = parser.parse_args()

    if args.recollect and not args.fix:
        parser.error("--recollect requires --fix")

    target_employer_ids = set(args.target_local_employer_id or [])

    engine = init_db()
    session = get_session(engine)

    try:
        print("\n" + "=" * 70)
        print("  RESTAURANT URL MISMATCH REPAIR")
        print("=" * 70)

        cross_brand_problems = _filter_targeted_problems(
            audit_cross_brand_urls(session),
            target_employer_ids,
        )
        shared_url_mismatches = _filter_targeted_mismatches(
            audit_name_mismatch_urls(session),
            target_employer_ids,
        )
        site_identity_mismatches = audit_site_identity_mismatches(
            session,
            region=args.region,
            target_employer_ids=target_employer_ids or None,
            max_fetches=args.site_fetch_limit,
        )
        actionable_mismatches = merge_actionable_mismatches(
            shared_url_mismatches,
            site_identity_mismatches,
        )
        contaminated_counts = find_contaminated_scrape_counts(session, actionable_mismatches)

        print("\n── Summary ─────────────────────────────────────────────────")
        print(f"  Cross-brand URL conflicts:     {len(cross_brand_problems)}")
        print(f"  Shared-URL mismatches:         {len(shared_url_mismatches)}")
        print(f"  Site-identity mismatches:      {len(site_identity_mismatches)}")
        print(f"  Actionable mismatch rows:      {len(actionable_mismatches)}")
        print(f"  Contaminated meal_deals rows:  {contaminated_counts['legacy_meal_deals']}")
        print(f"  Contaminated materializations: {contaminated_counts['materializations']}")

        if actionable_mismatches:
            print("\n── First Mismatches ───────────────────────────────────────")
            for mismatch in actionable_mismatches[:25]:
                print(f"  URL row #{mismatch['rurl_id']}: {mismatch['emp_name']} -> {mismatch['url']}")
                print(f"    likely owner: {', '.join(mismatch['likely_owner_names'])}")
                evidence = mismatch.get("evidence")
                if evidence:
                    print(f"    evidence: {evidence}")
            if len(actionable_mismatches) > 25:
                print(f"  ... and {len(actionable_mismatches) - 25} more")

        if not args.fix:
            print("\n  Run with --fix to purge the bad URL rows. Add --recollect to refill them afterward.\n")
            return

        print("\n── Purging Bad URL Rows ───────────────────────────────────")
        purge_stats, cleaned_employer_ids = purge_restaurant_url_mismatches(session, actionable_mismatches)
        print(f"  restaurant_urls deleted:  {purge_stats['restaurant_urls_deleted']}")
        print(f"  meal_deals deleted:       {purge_stats['meal_deals_deleted']}")
        print(f"  materializations deleted: {purge_stats['materializations_deleted']}")
        print(f"  applicability deleted:    {purge_stats['applicability_deleted']}")
        print(f"  observations deleted:     {purge_stats['observations_deleted']}")
        print(f"  failure rows cleared:     {purge_stats['google_failures_cleared']}")

    finally:
        session.close()

    if not args.recollect:
        print("\n  Cleanup committed. Run again with --recollect to refill cleaned employers.\n")
        return

    print("\n── Recollecting Cleaned Employers ─────────────────────────")
    recollect_stats = recollect_cleaned_employers(
        region=args.region,
        cleaned_employer_ids=cleaned_employer_ids,
    )
    print(f"  cleaned employers:    {recollect_stats['cleaned_employers']}")
    print(f"  unresolved at start:  {recollect_stats['initial_unresolved']}")
    print(f"  unresolved after OSM: {recollect_stats['remaining_after_osm']}")
    print(f"  unresolved final:     {recollect_stats['final_unresolved']}")
    if recollect_stats.get("osm"):
        print(f"  OSM recollect stats:  {recollect_stats['osm']}")
    if recollect_stats.get("google_local"):
        print(f"  Google recollect:     {recollect_stats['google_local']}")
    print()


if __name__ == "__main__":
    main()