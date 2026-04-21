"""
collectors/meal_deals/routes.py — Flask Blueprint for meal deal endpoints.

Endpoints:
    GET /api/deals              Paginated deal listings with geo/type filters
    GET /api/deals/stats        Summary stats (counts by type, source, brand)
    GET /api/deals/brands       Brands with active deals and counts
"""

import logging
import math
import re
from collections import Counter, defaultdict

from flask import Blueprint, jsonify, request

from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from collectors.meal_deals.temporal import extract_days
from core.database import (
    BrandGroup,
    CanonicalVenue,
    CanonicalVenueAlias,
    DealApplicability,
    DealMaterialization,
    DealObservation,
    LocalEmployer,
    MealDeal,
    SiteAssignment,
    SiteIdentity,
    get_engine,
    get_session,
)
from core.venue_identity import cluster_likely_same_venues, normalize_url_for_identity, pick_canonical_item

logger = logging.getLogger(__name__)

deals_bp = Blueprint("deals", __name__, url_prefix="/api/deals")

_engine = None


def _get_db_session():
    """Return a new Session using a lazily-initialised engine singleton."""
    global _engine
    if _engine is None:
        _engine = get_engine()
    return get_session(_engine)


def _err(e: Exception, status: int = 500):
    logger.error("[deals] %s", e, exc_info=True)
    return jsonify({"status": "error", "message": "An internal error occurred"}), status


def _bad_request(message: str):
    return jsonify({"status": "error", "message": message}), 400


def _coerce_int(value, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer") from exc


def _payload_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


_GENERIC_SUMMARY_NAME_RE = re.compile(
    r"^\s*(?:happy\s*hour|daily\s+specials?|lunch\s+specials?|dinner\s+specials?|specials?|offers?|deals?|promotions?|menu)\s*$",
    re.IGNORECASE,
)
_SPECIFICITY_PRICE_SIGNAL_RE = re.compile(r"(?:\$\d|\d+%\s*off|half\s+(?:off|price)|bogo)", re.IGNORECASE)
_DAY_ORDER = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_DAY_TOKEN_MAP = {
    "monday": "Mon",
    "mon": "Mon",
    "tuesday": "Tue",
    "tue": "Tue",
    "tues": "Tue",
    "wednesday": "Wed",
    "wed": "Wed",
    "weds": "Wed",
    "thursday": "Thu",
    "thu": "Thu",
    "thur": "Thu",
    "thurs": "Thu",
    "friday": "Fri",
    "fri": "Fri",
    "saturday": "Sat",
    "sat": "Sat",
    "sunday": "Sun",
    "sun": "Sun",
}


def _normalize_day_filter(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None

    normalized = extract_days(cleaned)
    if normalized in _DAY_ORDER:
        return normalized
    return _DAY_TOKEN_MAP.get(cleaned.lower())


def _expand_valid_days(valid_days: str | None) -> set[str]:
    if not valid_days:
        return set()

    cleaned = valid_days.strip()
    if not cleaned:
        return set()

    normalized = extract_days(cleaned) or cleaned
    if normalized == "Daily":
        return set(_DAY_ORDER)
    if normalized == "Mon-Fri":
        return set(_DAY_ORDER[:5])
    if normalized == "Sat-Sun":
        return {"Sat", "Sun"}
    if normalized in _DAY_ORDER:
        return {normalized}
    if "-" in normalized:
        start, end = [part.strip() for part in normalized.split("-", 1)]
        if start in _DAY_ORDER and end in _DAY_ORDER:
            start_index = _DAY_ORDER.index(start)
            end_index = _DAY_ORDER.index(end)
            if start_index <= end_index:
                return set(_DAY_ORDER[start_index:end_index + 1])

    expanded: set[str] = set()
    for token in re.split(r",|/|&|\band\b", cleaned, flags=re.IGNORECASE):
        normalized_token = _normalize_day_filter(token)
        if normalized_token is not None:
            expanded.add(normalized_token)
    return expanded


def _materialization_matches_day_filter(deal: DealMaterialization, requested_day: str | None) -> bool:
    if requested_day is None:
        return True
    if not deal.valid_days:
        return False
    return requested_day in _expand_valid_days(deal.valid_days)


def _sub_deal_count(value) -> int:
    return len(value) if isinstance(value, list) else 0


def _materialization_specificity_score(deal: DealMaterialization) -> int:
    score = 0
    name = (deal.deal_name or "").strip()
    description = (deal.deal_description or "").strip()
    combined_text = " ".join(part for part in (name, description) if part)
    sub_deal_count = _sub_deal_count(deal.sub_deals)

    if deal.price is not None:
        score += 4
    if deal.discount_percentage is not None:
        score += 3
    if deal.original_price is not None:
        score += 1
    if deal.valid_days:
        score += 1
    if deal.valid_start_time:
        score += 1
    if deal.valid_end_time:
        score += 1
    score += min(sub_deal_count, 3) * 2

    if combined_text and _SPECIFICITY_PRICE_SIGNAL_RE.search(combined_text):
        score += 2
    if name and not _GENERIC_SUMMARY_NAME_RE.match(name):
        score += 1
    if _GENERIC_SUMMARY_NAME_RE.match(name) and deal.price is None and deal.discount_percentage is None and sub_deal_count == 0:
        score -= 3
    return score


def _materialization_order_key(deal: DealMaterialization) -> tuple[int, float, float, float, int]:
    return (
        _materialization_specificity_score(deal),
        deal.deal_value_score or 0.0,
        deal.signal_quality or 0.0,
        deal.verified_at.timestamp() if deal.verified_at else 0.0,
        deal.id or 0,
    )


def _sort_materialized_deals(deals: list[DealMaterialization]) -> list[DealMaterialization]:
    return sorted(deals, key=_materialization_order_key, reverse=True)


def _deal_signature(deal: MealDeal) -> tuple:
    """Key that identifies the same underlying offer across alias venue rows."""
    return (
        deal.source or "",
        (deal.deal_name or "").strip().casefold(),
        normalize_url_for_identity(deal.source_url) or "",
        deal.valid_days or "",
        deal.valid_start_time or "",
        deal.valid_end_time or "",
        deal.price_type or "",
        round(deal.price, 2) if deal.price is not None else None,
    )


def _collapse_duplicate_deals(
    deals: list[MealDeal],
    employers: dict[int, LocalEmployer],
) -> list[MealDeal]:
    """Collapse duplicate deal rows created by alias local_employer records."""
    by_signature: dict[tuple, list[MealDeal]] = defaultdict(list)
    for deal in deals:
        by_signature[_deal_signature(deal)].append(deal)

    collapsed: list[MealDeal] = []
    for group in by_signature.values():
        if len(group) == 1:
            collapsed.extend(group)
            continue

        clusters = cluster_likely_same_venues(
            group,
            get_name=lambda deal: employers.get(deal.local_employer_id).name if employers.get(deal.local_employer_id) else None,
            get_address=lambda deal: employers.get(deal.local_employer_id).address if employers.get(deal.local_employer_id) else None,
            get_url=lambda deal: deal.source_url,
            get_lat=lambda deal: deal.lat,
            get_lng=lambda deal: deal.lng,
        )

        for cluster in clusters:
            if len(cluster) == 1:
                collapsed.extend(cluster)
                continue

            canonical = pick_canonical_item(
                cluster,
                get_id=lambda deal: deal.id,
                get_brand_group_id=lambda deal: deal.brand_group_id,
                get_address=lambda deal: employers.get(deal.local_employer_id).address if employers.get(deal.local_employer_id) else None,
                extra_rank=lambda deal: (
                    deal.signal_quality or 0.0,
                    deal.verified_at.timestamp() if deal.verified_at else 0.0,
                ),
            )
            collapsed.append(canonical)

    collapsed.sort(
        key=lambda deal: (
            deal.verified_at.timestamp() if deal.verified_at else 0.0,
            deal.id or 0,
        ),
        reverse=True,
    )
    return collapsed


def _build_employer_map(
    session,
    deals: list[MealDeal],
) -> dict[int, LocalEmployer]:
    employer_ids = {deal.local_employer_id for deal in deals if deal.local_employer_id is not None}
    if not employer_ids:
        return {}

    employers = session.query(LocalEmployer).filter(
        LocalEmployer.id.in_(employer_ids)
    ).all()
    return {employer.id: employer for employer in employers}


def _load_deduped_deals(
    session,
    *,
    region: str,
    active_only: bool = True,
    deal_type: str | None = None,
    brand: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_mi: float = 10.0,
) -> tuple[list[MealDeal], dict[int, LocalEmployer]]:
    q = session.query(MealDeal).filter(MealDeal.region == region)

    if active_only:
        q = q.filter(MealDeal.is_active.is_(True))

    if deal_type:
        q = q.filter(MealDeal.deal_type == deal_type)

    if brand:
        q = q.join(BrandGroup, MealDeal.brand_group_id == BrandGroup.id).filter(
            BrandGroup.fingerprint == brand
        )

    if lat is not None and lng is not None:
        lat_delta = radius_mi / 69.0
        cos_lat = max(abs(math.cos(math.radians(lat))), 0.01)
        lng_delta = radius_mi / (69.0 * cos_lat)
        q = q.filter(
            MealDeal.lat.between(lat - lat_delta, lat + lat_delta),
            MealDeal.lng.between(lng - lng_delta, lng + lng_delta),
        )

    deals = q.order_by(MealDeal.verified_at.desc(), MealDeal.id.desc()).all()
    employers = _build_employer_map(session, deals)
    return _collapse_duplicate_deals(deals, employers), employers


def _load_materialized_deals(
    session,
    *,
    region: str,
    active_only: bool = True,
    deal_type: str | None = None,
    day: str | None = None,
    brand: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    radius_mi: float = 10.0,
) -> list[DealMaterialization]:
    q = session.query(DealMaterialization).filter(DealMaterialization.region == region)

    if active_only:
        q = q.filter(DealMaterialization.is_active.is_(True))

    if deal_type:
        q = q.filter(DealMaterialization.deal_type == deal_type)

    if brand:
        q = q.join(BrandGroup, DealMaterialization.brand_group_id == BrandGroup.id).filter(
            BrandGroup.fingerprint == brand
        )

    if lat is not None and lng is not None:
        lat_delta = radius_mi / 69.0
        cos_lat = max(abs(math.cos(math.radians(lat))), 0.01)
        lng_delta = radius_mi / (69.0 * cos_lat)
        q = q.filter(
            DealMaterialization.lat.between(lat - lat_delta, lat + lat_delta),
            DealMaterialization.lng.between(lng - lng_delta, lng + lng_delta),
        )

    deals = q.order_by(
        DealMaterialization.verified_at.desc(),
        DealMaterialization.id.desc(),
    ).all()
    if day is not None:
        deals = [deal for deal in deals if _materialization_matches_day_filter(deal, day)]
    return _sort_materialized_deals(deals)


def _load_site_review_queue(
    session,
    *,
    region: str,
) -> list[dict]:
    rows = session.query(SiteIdentity, SiteAssignment, CanonicalVenue).join(
        SiteAssignment,
        SiteAssignment.site_identity_id == SiteIdentity.id,
    ).join(
        CanonicalVenue,
        SiteAssignment.canonical_venue_id == CanonicalVenue.id,
    ).filter(
        SiteAssignment.assignment_scope == "contested",
        CanonicalVenue.region == region,
    ).order_by(
        SiteIdentity.id.asc(),
        SiteAssignment.match_confidence.asc(),
        CanonicalVenue.canonical_name.asc(),
    ).all()

    grouped: dict[int, dict] = {}
    for site, assignment, venue in rows:
        entry = grouped.setdefault(
            site.id,
            {
                "queue_type": "site",
                "site_identity_id": site.id,
                "canonical_url": site.canonical_url,
                "normalized_url": site.normalized_url,
                "ownership_scope": site.ownership_scope,
                "conflict_state": site.conflict_state,
                "candidates": [],
            },
        )
        entry["candidates"].append(
            {
                "canonical_venue_id": venue.id,
                "restaurant_name": venue.canonical_name,
                "address": venue.address,
                "match_confidence": assignment.match_confidence,
                "match_method": assignment.match_method,
                "is_primary": assignment.is_primary,
            }
        )

    items = list(grouped.values())
    for item in items:
        item["candidate_count"] = len(item["candidates"])

    items.sort(
        key=lambda item: (
            -item["candidate_count"],
            item["normalized_url"],
        )
    )
    return items


def _load_venue_alias_review_queue(
    session,
    *,
    region: str,
    min_confidence: float,
    max_confidence: float,
) -> list[dict]:
    rows = session.query(CanonicalVenueAlias, CanonicalVenue, LocalEmployer).join(
        CanonicalVenue,
        CanonicalVenueAlias.canonical_venue_id == CanonicalVenue.id,
    ).join(
        LocalEmployer,
        CanonicalVenueAlias.local_employer_id == LocalEmployer.id,
    ).filter(
        CanonicalVenue.region == region,
        CanonicalVenueAlias.match_confidence.isnot(None),
        CanonicalVenueAlias.match_confidence >= min_confidence,
        CanonicalVenueAlias.match_confidence < max_confidence,
    ).order_by(
        CanonicalVenueAlias.match_confidence.asc(),
        CanonicalVenue.canonical_name.asc(),
        LocalEmployer.name.asc(),
    ).all()

    return [
        {
            "queue_type": "venue_alias",
            "canonical_venue_id": venue.id,
            "canonical_name": venue.canonical_name,
            "local_employer_id": employer.id,
            "restaurant_name": employer.name,
            "address": employer.address,
            "alias_role": alias.alias_role,
            "match_method": alias.match_method,
            "match_confidence": alias.match_confidence,
            "notes": alias.notes,
        }
        for alias, venue, employer in rows
    ]


def _load_review_queue(
    session,
    *,
    region: str,
    kind: str,
    min_alias_confidence: float,
    max_alias_confidence: float,
) -> dict:
    site_items = _load_site_review_queue(session, region=region) if kind in {"all", "site"} else []
    venue_items = _load_venue_alias_review_queue(
        session,
        region=region,
        min_confidence=min_alias_confidence,
        max_confidence=max_alias_confidence,
    ) if kind in {"all", "venue"} else []

    combined = []
    for item in site_items:
        combined.append(((0, -item["candidate_count"], item["normalized_url"]), item))
    for item in venue_items:
        combined.append(((1, item["match_confidence"], item["canonical_name"].casefold()), item))

    combined.sort(key=lambda item: item[0])
    return {
        "summary": {
            "contested_sites": len(site_items),
            "ambiguous_venue_aliases": len(venue_items),
        },
        "items": [item[1] for item in combined],
    }


def _apply_site_review_action(session, payload: dict) -> dict:
    action = (payload.get("action") or "").strip().lower()
    site_identity_id = _coerce_int(payload.get("site_identity_id"), "site_identity_id")
    site = session.get(SiteIdentity, site_identity_id)
    if site is None:
        raise ValueError("site_identity_id was not found")

    assignments = session.query(SiteAssignment).filter(
        SiteAssignment.site_identity_id == site_identity_id
    ).all()

    if action == "block":
        deleted = len(assignments)
        for assignment in assignments:
            session.delete(assignment)
        site.ownership_scope = "unknown"
        site.conflict_state = "blocked"
        session.flush()
        return {
            "queue_type": "site",
            "action": "block",
            "site_identity_id": site.id,
            "conflict_state": site.conflict_state,
            "assignments_deleted": deleted,
        }

    if action != "resolve":
        raise ValueError("site action must be one of: resolve, block")

    resolution = (payload.get("resolution") or "").strip().lower()
    updated = 0
    created = 0

    if resolution == "venue":
        canonical_venue_id = _coerce_int(payload.get("canonical_venue_id"), "canonical_venue_id")
        venue = session.get(CanonicalVenue, canonical_venue_id)
        if venue is None:
            raise ValueError("canonical_venue_id was not found")

        matched = False
        for assignment in assignments:
            if assignment.canonical_venue_id == canonical_venue_id and assignment.brand_group_id is None:
                assignment.assignment_scope = "venue"
                assignment.match_method = "manual_review"
                assignment.match_confidence = 1.0
                assignment.is_primary = True
                matched = True
            else:
                assignment.assignment_scope = "fallback"
                assignment.is_primary = False
            updated += 1

        if not matched:
            session.add(
                SiteAssignment(
                    site_identity_id=site.id,
                    canonical_venue_id=canonical_venue_id,
                    assignment_scope="venue",
                    match_method="manual_review",
                    match_confidence=1.0,
                    is_primary=True,
                )
            )
            created += 1

        site.ownership_scope = "venue"
        site.conflict_state = "clear"
        session.flush()
        return {
            "queue_type": "site",
            "action": "resolve",
            "resolution": "venue",
            "site_identity_id": site.id,
            "canonical_venue_id": canonical_venue_id,
            "conflict_state": site.conflict_state,
            "assignments_updated": updated,
            "assignments_created": created,
        }

    if resolution == "brand":
        brand_group_id = _coerce_int(payload.get("brand_group_id"), "brand_group_id")
        brand = session.get(BrandGroup, brand_group_id)
        if brand is None:
            raise ValueError("brand_group_id was not found")

        matched = False
        for assignment in assignments:
            if assignment.brand_group_id == brand_group_id and assignment.canonical_venue_id is None:
                assignment.assignment_scope = "brand"
                assignment.match_method = "manual_review"
                assignment.match_confidence = 1.0
                assignment.is_primary = True
                matched = True
            else:
                assignment.assignment_scope = "fallback"
                assignment.is_primary = False
            updated += 1

        if not matched:
            session.add(
                SiteAssignment(
                    site_identity_id=site.id,
                    brand_group_id=brand_group_id,
                    assignment_scope="brand",
                    match_method="manual_review",
                    match_confidence=1.0,
                    is_primary=True,
                )
            )
            created += 1

        site.ownership_scope = "brand"
        site.conflict_state = "clear"
        session.flush()
        return {
            "queue_type": "site",
            "action": "resolve",
            "resolution": "brand",
            "site_identity_id": site.id,
            "brand_group_id": brand_group_id,
            "conflict_state": site.conflict_state,
            "assignments_updated": updated,
            "assignments_created": created,
        }

    raise ValueError("resolution must be one of: venue, brand")


def _repair_venue_applicability_for_local_employer(
    session,
    *,
    local_employer_id: int,
    canonical_venue_id: int | None,
    remove: bool,
) -> dict:
    changed_rows = 0
    observation_ids: list[int] = []

    observations = session.query(DealObservation).all()
    for observation in observations:
        payload = _payload_dict(observation.extraction_payload)
        if payload.get("local_employer_id_hint") != local_employer_id:
            continue

        applicability_rows = session.query(DealApplicability).filter(
            DealApplicability.observation_id == observation.id,
            DealApplicability.applicability_scope == "venue",
        ).all()
        if not applicability_rows:
            continue

        touched = False
        for applicability in applicability_rows:
            if remove:
                applicability.is_active = False
                applicability.confidence = 0.0
                applicability.resolver_method = "manual_review_removed_alias"
                applicability.resolver_notes = f"local_employer_id={local_employer_id}"
            else:
                applicability.canonical_venue_id = canonical_venue_id
                applicability.is_active = True
                applicability.confidence = 1.0
                applicability.resolver_method = "manual_review_alias"
                applicability.resolver_notes = f"local_employer_id={local_employer_id}"
            changed_rows += 1
            touched = True

        if touched:
            observation_ids.append(observation.id)

    materialization_stats = {"deleted": 0, "inserted": 0}
    if observation_ids:
        materialization_stats = refresh_deal_materializations(
            session,
            observation_ids=observation_ids,
        )

    return {
        "applicability_rows_updated": changed_rows,
        "observation_ids": observation_ids,
        "materializations_deleted": materialization_stats["deleted"],
        "materializations_inserted": materialization_stats["inserted"],
    }


def _apply_venue_alias_review_action(session, payload: dict) -> dict:
    action = (payload.get("action") or "").strip().lower()
    local_employer_id = _coerce_int(payload.get("local_employer_id"), "local_employer_id")

    alias = session.query(CanonicalVenueAlias).filter(
        CanonicalVenueAlias.local_employer_id == local_employer_id
    ).first()
    if alias is None:
        raise ValueError("local_employer_id does not have a canonical venue alias")

    if action == "confirm":
        alias.match_confidence = 1.0
        alias.match_method = "manual_review"
        repair_stats = _repair_venue_applicability_for_local_employer(
            session,
            local_employer_id=local_employer_id,
            canonical_venue_id=alias.canonical_venue_id,
            remove=False,
        )
        session.flush()
        return {
            "queue_type": "venue_alias",
            "action": "confirm",
            "local_employer_id": local_employer_id,
            "canonical_venue_id": alias.canonical_venue_id,
            "match_confidence": alias.match_confidence,
            **repair_stats,
        }

    if action == "reassign":
        canonical_venue_id = _coerce_int(payload.get("canonical_venue_id"), "canonical_venue_id")
        venue = session.get(CanonicalVenue, canonical_venue_id)
        if venue is None:
            raise ValueError("canonical_venue_id was not found")

        alias.canonical_venue_id = canonical_venue_id
        alias.match_confidence = 1.0
        alias.match_method = "manual_review"
        repair_stats = _repair_venue_applicability_for_local_employer(
            session,
            local_employer_id=local_employer_id,
            canonical_venue_id=canonical_venue_id,
            remove=False,
        )
        session.flush()
        return {
            "queue_type": "venue_alias",
            "action": "reassign",
            "local_employer_id": local_employer_id,
            "canonical_venue_id": canonical_venue_id,
            "match_confidence": alias.match_confidence,
            **repair_stats,
        }

    if action == "remove":
        repair_stats = _repair_venue_applicability_for_local_employer(
            session,
            local_employer_id=local_employer_id,
            canonical_venue_id=None,
            remove=True,
        )
        session.delete(alias)
        session.flush()
        return {
            "queue_type": "venue_alias",
            "action": "remove",
            "local_employer_id": local_employer_id,
            **repair_stats,
        }

    raise ValueError("venue_alias action must be one of: confirm, reassign, remove")


# ── Deal listings ─────────────────────────────────────────────────────────────

@deals_bp.route("")
def list_deals():
    """Paginated deal listings with optional filters.

    Query params:
        lat         (float)   center latitude
        lng         (float)   center longitude
        radius_mi   (float, default 10)  search radius in miles
        deal_type   (str, optional)  filter by deal type
        day         (str, optional)  filter deals valid on this day
        brand       (str, optional)  filter by brand fingerprint
        active_only (bool, default true)
        limit       (int, default 50, max 200)
        offset      (int, default 0)
        region      (str, default austin_tx)
    """
    region = request.args.get("region", "austin_tx")
    deal_type = request.args.get("deal_type")
    day_param = request.args.get("day")
    day = _normalize_day_filter(day_param)
    brand = request.args.get("brand")
    active_only = request.args.get("active_only", "true").lower() != "false"
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)

    # Geo params
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius_mi = request.args.get("radius_mi", 10.0, type=float)

    if day_param is not None and day is None:
        return _bad_request("day must be a weekday like Mon or Tuesday")

    session = _get_db_session()
    try:
        deals = _load_materialized_deals(
            session,
            region=region,
            active_only=active_only,
            deal_type=deal_type,
            day=day,
            brand=brand,
            lat=lat,
            lng=lng,
            radius_mi=radius_mi,
        )
        total = len(deals)
        deals = deals[offset: offset + limit]

        return jsonify({
            "deals": [deal.to_dict() for deal in deals],
            "count": total,
            "limit": limit,
            "offset": offset,
            "region": region,
        })
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()


# ── Summary stats ─────────────────────────────────────────────────────────────

@deals_bp.route("/stats")
def deal_stats():
    """Summary statistics for active deals.

    Query params:
        region      (str, default austin_tx)
        deal_type   (str, optional)
        day         (str, optional)  filter deals valid on this day
        brand       (str, optional)
        active_only (bool, default true)
        lat         (float, optional)
        lng         (float, optional)
        radius_mi   (float, default 10)
    """
    region = request.args.get("region", "austin_tx")
    deal_type = request.args.get("deal_type")
    day_param = request.args.get("day")
    day = _normalize_day_filter(day_param)
    brand = request.args.get("brand")
    active_only = request.args.get("active_only", "true").lower() != "false"
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius_mi = request.args.get("radius_mi", 10.0, type=float)

    if day_param is not None and day is None:
        return _bad_request("day must be a weekday like Mon or Tuesday")

    session = _get_db_session()
    try:
        deals = _load_materialized_deals(
            session,
            region=region,
            active_only=active_only,
            deal_type=deal_type,
            day=day,
            brand=brand,
            lat=lat,
            lng=lng,
            radius_mi=radius_mi,
        )

        type_counts = dict(Counter(deal.deal_type for deal in deals))
        source_counts = dict(Counter(deal.source for deal in deals))
        restaurant_count = len({deal.canonical_venue_id for deal in deals if deal.canonical_venue_id is not None})
        brand_count = len({deal.brand_group_id for deal in deals if deal.brand_group_id is not None})

        return jsonify({
            "total_deals": len(deals),
            "by_type": type_counts,
            "by_source": source_counts,
            "restaurant_count": restaurant_count,
            "brand_count": brand_count,
            "region": region,
        })
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()


# ── Brand listing ─────────────────────────────────────────────────────────────

@deals_bp.route("/brands")
def deal_brands():
    """Brands with active deals and their deal counts.

    Query params:
        region      (str, default austin_tx)
        deal_type   (str, optional)
        day         (str, optional)  filter deals valid on this day
        active_only (bool, default true)
        lat         (float, optional)
        lng         (float, optional)
        radius_mi   (float, default 10)
    """
    region = request.args.get("region", "austin_tx")
    deal_type = request.args.get("deal_type")
    day_param = request.args.get("day")
    day = _normalize_day_filter(day_param)
    active_only = request.args.get("active_only", "true").lower() != "false"
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius_mi = request.args.get("radius_mi", 10.0, type=float)

    if day_param is not None and day is None:
        return _bad_request("day must be a weekday like Mon or Tuesday")

    session = _get_db_session()
    try:
        deals = _load_materialized_deals(
            session,
            region=region,
            active_only=active_only,
            deal_type=deal_type,
            day=day,
            lat=lat,
            lng=lng,
            radius_mi=radius_mi,
        )
        deal_counts = Counter(
            deal.brand_group_id for deal in deals if deal.brand_group_id is not None
        )
        if not deal_counts:
            return jsonify({"brands": [], "count": 0, "region": region})

        brand_rows = session.query(BrandGroup).filter(
            BrandGroup.id.in_(deal_counts.keys())
        ).all()
        brand_map = {brand.id: brand for brand in brand_rows}

        ordered_brand_ids = sorted(
            deal_counts.keys(),
            key=lambda brand_id: (
                -deal_counts[brand_id],
                brand_map[brand_id].canonical_name.casefold() if brand_id in brand_map and brand_map[brand_id].canonical_name else "",
            ),
        )

        brands = [
            {
                "fingerprint": brand_map[brand_id].fingerprint,
                "name": brand_map[brand_id].canonical_name,
                "location_count": brand_map[brand_id].location_count,
                "deal_count": deal_counts[brand_id],
            }
            for brand_id in ordered_brand_ids
            if brand_id in brand_map
        ]

        return jsonify({"brands": brands, "count": len(brands), "region": region})
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()


@deals_bp.route("/review-queue")
def deal_review_queue():
    """Lightweight review queue for contested sites and ambiguous venue mappings."""
    region = request.args.get("region", "austin_tx")
    kind = request.args.get("kind", "all").strip().lower() or "all"
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)
    min_alias_confidence = request.args.get("min_alias_confidence", 0.8, type=float)
    max_alias_confidence = request.args.get("max_alias_confidence", 0.95, type=float)

    if kind not in {"all", "site", "venue"}:
        return jsonify({"status": "error", "message": "kind must be one of: all, site, venue"}), 400

    session = _get_db_session()
    try:
        queue = _load_review_queue(
            session,
            region=region,
            kind=kind,
            min_alias_confidence=min_alias_confidence,
            max_alias_confidence=max_alias_confidence,
        )
        items = queue["items"]
        paged_items = items[offset: offset + limit]
        return jsonify(
            {
                "items": paged_items,
                "count": len(items),
                "limit": limit,
                "offset": offset,
                "kind": kind,
                "region": region,
                "summary": queue["summary"],
            }
        )
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()


@deals_bp.route("/review-queue/actions", methods=["POST"])
def apply_review_queue_action():
    """Apply a manual review action for contested sites or venue aliases."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _bad_request("JSON object body is required")

    queue_type = (payload.get("queue_type") or "").strip().lower()
    if queue_type not in {"site", "venue_alias"}:
        return _bad_request("queue_type must be one of: site, venue_alias")

    session = _get_db_session()
    try:
        if queue_type == "site":
            result = _apply_site_review_action(session, payload)
        else:
            result = _apply_venue_alias_review_action(session, payload)
        session.commit()
        return jsonify({"status": "ok", "result": result})
    except ValueError as exc:
        session.rollback()
        return _bad_request(str(exc))
    except Exception as exc:
        session.rollback()
        return _err(exc)
    finally:
        session.close()
