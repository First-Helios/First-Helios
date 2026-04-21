"""
collectors/meal_deals/price_index_routes.py — Food Price Index API blueprint.

Endpoints:
    GET /api/price-index           Paginated menu item listings with filters
    GET /api/price-index/facets    Lightweight filter population (cuisines, courses, etc.)
"""

from __future__ import annotations

import logging
import math

from flask import Blueprint, jsonify, request
from sqlalchemy import func, or_

from core.database import (
    BrandGroup,
    LocalEmployer,
    MenuItem,
    MenuPricePoint,
    MenuSection,
    get_engine,
    get_session,
)

logger = logging.getLogger(__name__)

price_index_bp = Blueprint("price_index", __name__, url_prefix="/api/price-index")

_engine = None


def _get_db_session():
    global _engine
    if _engine is None:
        _engine = get_engine()
    return get_session(_engine)


def _err(e: Exception, status: int = 500):
    logger.error("[price_index] %s", e, exc_info=True)
    return jsonify({"status": "error", "message": "An internal error occurred"}), status


def _bad_request(msg: str):
    return jsonify({"status": "error", "message": msg}), 400


# ── Geo helpers ───────────────────────────────────────────────────────────────

_EARTH_MI = 3958.8


def _haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return approximate distance in miles between two lat/lng points."""
    import math as _m
    r = _EARTH_MI
    phi1, phi2 = _m.radians(lat1), _m.radians(lat2)
    dphi = _m.radians(lat2 - lat1)
    dlam = _m.radians(lng2 - lng1)
    a = _m.sin(dphi / 2) ** 2 + _m.cos(phi1) * _m.cos(phi2) * _m.sin(dlam / 2) ** 2
    return r * 2 * _m.atan2(_m.sqrt(a), _m.sqrt(1 - a))


def _approx_lat_delta(radius_mi: float) -> float:
    return radius_mi / _EARTH_MI * (180 / math.pi)


def _approx_lng_delta(lat: float, radius_mi: float) -> float:
    import math as _m
    if abs(lat) >= 89.9:
        return 180.0
    return radius_mi / (_EARTH_MI * _m.cos(_m.radians(lat))) * (180 / _m.pi)


# ── Main listing endpoint ─────────────────────────────────────────────────────


@price_index_bp.route("", methods=["GET"])
def price_index():
    """GET /api/price-index — paginated menu item results with geo + filters."""
    try:
        # ── Pagination ────────────────────────────────────────────────────────
        try:
            limit = min(int(request.args.get("limit", 50)), 100)
            offset = max(int(request.args.get("offset", 0)), 0)
        except (TypeError, ValueError):
            return _bad_request("limit and offset must be integers")

        # ── Filter params ─────────────────────────────────────────────────────
        q           = (request.args.get("q") or "").strip()
        brand       = (request.args.get("brand") or "").strip()
        cuisine     = (request.args.get("cuisine") or "").strip()
        course      = (request.args.get("course") or "").strip()
        svc_period  = (request.args.get("service_period") or "").strip()
        region      = (request.args.get("region") or "").strip()
        sort        = request.args.get("sort", "price")

        try:
            min_price   = float(request.args["min_price"]) if "min_price" in request.args else None
            max_price   = float(request.args["max_price"]) if "max_price" in request.args else None
            min_cals    = int(request.args["min_calories"]) if "min_calories" in request.args else None
            max_cals    = int(request.args["max_calories"]) if "max_calories" in request.args else None
            min_conf    = float(request.args.get("min_confidence", 0.55))
        except (TypeError, ValueError):
            return _bad_request("Numeric filter params are invalid")

        # ── Geo params ────────────────────────────────────────────────────────
        lat_str = request.args.get("lat")
        lng_str = request.args.get("lng")
        try:
            radius_mi = min(float(request.args.get("radius_mi", 10)), 25)
        except (TypeError, ValueError):
            radius_mi = 10.0
        use_geo = lat_str is not None and lng_str is not None
        if use_geo:
            try:
                center_lat = float(lat_str)
                center_lng = float(lng_str)
            except (TypeError, ValueError):
                return _bad_request("lat and lng must be numeric")
        else:
            center_lat = center_lng = None

        # ── Query ─────────────────────────────────────────────────────────────
        session = _get_db_session()
        try:
            query = (
                session.query(MenuItem, MenuPricePoint, LocalEmployer, BrandGroup, MenuSection)
                .join(MenuPricePoint, MenuPricePoint.item_id == MenuItem.id)
                .join(LocalEmployer, LocalEmployer.id == MenuItem.restaurant_id)
                .outerjoin(BrandGroup, BrandGroup.id == LocalEmployer.brand_group_id)
                .outerjoin(MenuSection, MenuSection.id == MenuItem.section_id)
                .filter(MenuPricePoint.price.isnot(None))
                .filter(MenuPricePoint.confidence >= min_conf)
            )

            # Keyword search on item name, description, and section name
            if q:
                like_q = f"%{q}%"
                query = query.filter(
                    or_(
                        MenuItem.name.ilike(like_q),
                        MenuItem.description.ilike(like_q),
                        MenuSection.name.ilike(like_q),
                    )
                )

            if course:
                query = query.filter(MenuItem.course == course)

            if svc_period:
                query = query.filter(MenuSection.service_period == svc_period)

            if cuisine:
                query = query.filter(LocalEmployer.industry.ilike(f"%{cuisine}%"))

            if brand:
                query = query.filter(BrandGroup.fingerprint == brand)

            if region:
                query = query.filter(LocalEmployer.region == region)

            if min_price is not None:
                query = query.filter(MenuPricePoint.price >= min_price)
            if max_price is not None:
                query = query.filter(MenuPricePoint.price <= max_price)

            if min_cals is not None:
                query = query.filter(MenuItem.calories >= min_cals)
            if max_cals is not None:
                query = query.filter(MenuItem.calories <= max_cals)

            # Rough geo bounding box filter (post-processed to exact distance below)
            if use_geo:
                lat_delta = _approx_lat_delta(radius_mi)
                lng_delta = _approx_lng_delta(center_lat, radius_mi)
                query = query.filter(
                    LocalEmployer.lat.between(center_lat - lat_delta, center_lat + lat_delta),
                    LocalEmployer.lng.between(center_lng - lng_delta, center_lng + lng_delta),
                )

            # Sort
            if sort == "price_per_calorie":
                # computed post-fetch; sort by price as proxy then re-order
                query = query.order_by(MenuPricePoint.price)
            elif sort == "calories":
                query = query.order_by(MenuItem.calories)
            elif sort == "name":
                query = query.order_by(MenuItem.name)
            else:
                query = query.order_by(MenuPricePoint.price)

            # Fetch a window large enough to support exact geo filter + pagination
            fetch_limit = (offset + limit) * 5 if use_geo else limit + offset
            rows = query.limit(fetch_limit).all()

            # ── Post-process: compute distance, apply exact geo, build response ──
            items_out = []
            for item, pp, emp, bg, sec in rows:
                distance_mi = None
                if use_geo and emp.lat is not None and emp.lng is not None:
                    distance_mi = _haversine_mi(center_lat, center_lng, emp.lat, emp.lng)
                    if distance_mi > radius_mi:
                        continue  # outside exact radius

                cal = item.calories
                price_per_cal = None
                if cal and cal > 0 and pp.price:
                    price_per_cal = round(pp.price / cal, 5)

                items_out.append({
                    "restaurant_id": emp.id,
                    "restaurant_name": emp.name,
                    "address": emp.address,
                    "lat": emp.lat,
                    "lng": emp.lng,
                    "distance_mi": round(distance_mi, 2) if distance_mi is not None else None,
                    "brand_fingerprint": bg.fingerprint if bg else None,
                    "industry": emp.industry,
                    "item_id": item.id,
                    "item_name": item.name,
                    "description": item.description,
                    "course": item.course,
                    "calories": cal,
                    "dietary_tags": item.dietary_tags or [],
                    "price": pp.price,
                    "price_per_calorie": price_per_cal,
                    "variant": pp.variant,
                    "confidence": pp.confidence,
                    "section_name": sec.name if sec else None,
                    "service_period": sec.service_period if sec else None,
                    "source_url": pp.evidence,  # evidence holds the source URL
                })

            # Sort price_per_calorie after compute
            if sort == "price_per_calorie":
                items_out.sort(key=lambda r: (r["price_per_calorie"] or 9999))

            total = len(items_out)
            page = items_out[offset: offset + limit]

            return jsonify({
                "items": page,
                "total": total,
                "limit": limit,
                "offset": offset,
            })
        finally:
            session.close()

    except Exception as exc:
        return _err(exc)


# ── Facets endpoint ───────────────────────────────────────────────────────────


@price_index_bp.route("/facets", methods=["GET"])
def price_index_facets():
    """GET /api/price-index/facets — filter population data for UI dropdowns."""
    try:
        region  = (request.args.get("region") or "").strip()
        lat_str = request.args.get("lat")
        lng_str = request.args.get("lng")
        try:
            radius_mi = min(float(request.args.get("radius_mi", 10)), 25)
        except (TypeError, ValueError):
            radius_mi = 10.0

        use_geo = lat_str is not None and lng_str is not None
        if use_geo:
            try:
                center_lat = float(lat_str)
                center_lng = float(lng_str)
            except (TypeError, ValueError):
                return _bad_request("lat and lng must be numeric")
        else:
            center_lat = center_lng = None

        session = _get_db_session()
        try:
            base = (
                session.query(MenuItem, MenuPricePoint, LocalEmployer, BrandGroup)
                .join(MenuPricePoint, MenuPricePoint.item_id == MenuItem.id)
                .join(LocalEmployer, LocalEmployer.id == MenuItem.restaurant_id)
                .outerjoin(BrandGroup, BrandGroup.id == LocalEmployer.brand_group_id)
                .filter(MenuPricePoint.price.isnot(None))
            )
            if region:
                base = base.filter(LocalEmployer.region == region)
            if use_geo:
                lat_delta = _approx_lat_delta(radius_mi)
                lng_delta = _approx_lng_delta(center_lat, radius_mi)
                base = base.filter(
                    LocalEmployer.lat.between(center_lat - lat_delta, center_lat + lat_delta),
                    LocalEmployer.lng.between(center_lng - lng_delta, center_lng + lng_delta),
                )

            rows = base.all()

            cuisine_counts: dict[str, int] = {}
            course_counts: dict[str, int] = {}
            brand_info: dict[str, dict] = {}
            prices: list[float] = []
            calories: list[int] = []

            for item, pp, emp, bg in rows:
                if emp.industry:
                    cuisine_counts[emp.industry] = cuisine_counts.get(emp.industry, 0) + 1
                if item.course:
                    course_counts[item.course] = course_counts.get(item.course, 0) + 1
                if bg:
                    if bg.fingerprint not in brand_info:
                        brand_info[bg.fingerprint] = {"fingerprint": bg.fingerprint,
                                                       "canonical_name": bg.canonical_name,
                                                       "count": 0}
                    brand_info[bg.fingerprint]["count"] += 1
                if pp.price is not None:
                    prices.append(pp.price)
                if item.calories is not None:
                    calories.append(item.calories)

            def _percentile(lst: list[float], pct: float) -> float | None:
                if not lst:
                    return None
                s = sorted(lst)
                idx = int(len(s) * pct / 100)
                return round(s[min(idx, len(s) - 1)], 2)

            price_range = {
                "min": round(min(prices), 2) if prices else None,
                "max": round(max(prices), 2) if prices else None,
                "p50": _percentile(prices, 50),
            }
            cal_range = {
                "min": min(calories) if calories else None,
                "max": max(calories) if calories else None,
                "p50": _percentile(calories, 50),
            }

            cuisines_sorted = sorted(
                [{"key": k, "count": v} for k, v in cuisine_counts.items()],
                key=lambda x: -x["count"]
            )
            courses_sorted = sorted(
                [{"key": k, "count": v} for k, v in course_counts.items()],
                key=lambda x: -x["count"]
            )
            brands_sorted = sorted(brand_info.values(), key=lambda x: -x["count"])

            return jsonify({
                "cuisines": cuisines_sorted,
                "courses": courses_sorted,
                "brands": brands_sorted,
                "price_range": price_range,
                "calorie_range": cal_range,
            })
        finally:
            session.close()

    except Exception as exc:
        return _err(exc)
