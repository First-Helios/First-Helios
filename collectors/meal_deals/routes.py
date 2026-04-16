"""
collectors/meal_deals/routes.py — Flask Blueprint for meal deal endpoints.

Endpoints:
    GET /api/deals              Paginated deal listings with geo/type filters
    GET /api/deals/stats        Summary stats (counts by type, source, brand)
    GET /api/deals/brands       Brands with active deals and counts
"""

import logging
from collections import defaultdict
from datetime import datetime

from flask import Blueprint, jsonify, request
from sqlalchemy import func as sqlfunc

from core.database import BrandGroup, LocalEmployer, MealDeal, get_engine, get_session
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
    brand = request.args.get("brand")
    active_only = request.args.get("active_only", "true").lower() != "false"
    limit = min(request.args.get("limit", 50, type=int), 200)
    offset = request.args.get("offset", 0, type=int)

    # Geo params
    lat = request.args.get("lat", type=float)
    lng = request.args.get("lng", type=float)
    radius_mi = request.args.get("radius_mi", 10.0, type=float)

    session = _get_db_session()
    try:
        q = session.query(MealDeal).filter(MealDeal.region == region)

        if active_only:
            q = q.filter(MealDeal.is_active.is_(True))

        if deal_type:
            q = q.filter(MealDeal.deal_type == deal_type)

        if brand:
            # Join to brand_groups to filter by fingerprint
            q = q.join(BrandGroup, MealDeal.brand_group_id == BrandGroup.id).filter(
                BrandGroup.fingerprint == brand
            )

        # Geo filter: bounding box approximation (1° lat ≈ 69 mi)
        if lat is not None and lng is not None:
            lat_delta = radius_mi / 69.0
            lng_delta = radius_mi / (69.0 * abs(__import__("math").cos(__import__("math").radians(lat))))
            q = q.filter(
                MealDeal.lat.between(lat - lat_delta, lat + lat_delta),
                MealDeal.lng.between(lng - lng_delta, lng + lng_delta),
            )

        deals = q.order_by(MealDeal.verified_at.desc(), MealDeal.id.desc()).all()

        # Enrich with restaurant name from local_employers
        employer_ids = {d.local_employer_id for d in deals if d.local_employer_id is not None}
        employers = {}
        if employer_ids:
            emp_rows = session.query(LocalEmployer).filter(
                LocalEmployer.id.in_(employer_ids)
            ).all()
            employers = {e.id: e for e in emp_rows}

        deals = _collapse_duplicate_deals(deals, employers)
        total = len(deals)
        deals = deals[offset: offset + limit]

        result = []
        for d in deals:
            row = d.to_dict()
            emp = employers.get(d.local_employer_id)
            if emp:
                row["restaurant_name"] = emp.name
                row["address"] = emp.address
            result.append(row)

        return jsonify({
            "deals": result,
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
        region  (str, default austin_tx)
    """
    region = request.args.get("region", "austin_tx")
    session = _get_db_session()
    try:
        base = session.query(MealDeal).filter(
            MealDeal.region == region,
            MealDeal.is_active.is_(True),
        )

        total = base.count()

        # By deal type
        type_counts = dict(
            base.with_entities(
                MealDeal.deal_type, sqlfunc.count()
            ).group_by(MealDeal.deal_type).all()
        )

        # By source
        source_counts = dict(
            base.with_entities(
                MealDeal.source, sqlfunc.count()
            ).group_by(MealDeal.source).all()
        )

        # Distinct restaurants with deals
        restaurant_count = base.with_entities(
            sqlfunc.count(sqlfunc.distinct(MealDeal.local_employer_id))
        ).scalar()

        # Distinct brands with deals
        brand_count = base.filter(
            MealDeal.brand_group_id.isnot(None)
        ).with_entities(
            sqlfunc.count(sqlfunc.distinct(MealDeal.brand_group_id))
        ).scalar()

        return jsonify({
            "total_deals": total,
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
        region  (str, default austin_tx)
    """
    region = request.args.get("region", "austin_tx")
    session = _get_db_session()
    try:
        rows = (
            session.query(
                BrandGroup.fingerprint,
                BrandGroup.canonical_name,
                BrandGroup.location_count,
                sqlfunc.count(MealDeal.id).label("deal_count"),
            )
            .join(MealDeal, MealDeal.brand_group_id == BrandGroup.id)
            .filter(
                MealDeal.region == region,
                MealDeal.is_active.is_(True),
            )
            .group_by(BrandGroup.id)
            .order_by(sqlfunc.count(MealDeal.id).desc())
            .all()
        )

        brands = [
            {
                "fingerprint": r.fingerprint,
                "name": r.canonical_name,
                "location_count": r.location_count,
                "deal_count": r.deal_count,
            }
            for r in rows
        ]

        return jsonify({"brands": brands, "count": len(brands), "region": region})
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()
