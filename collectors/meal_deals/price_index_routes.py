"""Flask Blueprint for Food Price Index endpoints."""

from __future__ import annotations

import logging
import math
from statistics import median

from flask import Blueprint, jsonify, request
from sqlalchemy import or_

from core.database import (
    BrandGroup,
    LocalEmployer,
    MenuItem,
    MenuPage,
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
    logger.error("[price-index] %s", e, exc_info=True)
    return jsonify({"status": "error", "message": "An internal error occurred"}), status


def _bad_request(message: str):
    return jsonify({"status": "error", "message": message}), 400


def _coerce_int(value, *, default: int | None = None) -> int | None:
    if value in (None, ""):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError("invalid integer")


def _coerce_float(value, *, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError("invalid float")


def _distance_miles(
    lat_a: float | None,
    lng_a: float | None,
    lat_b: float | None,
    lng_b: float | None,
) -> float | None:
    if None in (lat_a, lng_a, lat_b, lng_b):
        return None

    lat1 = math.radians(float(lat_a))
    lng1 = math.radians(float(lng_a))
    lat2 = math.radians(float(lat_b))
    lng2 = math.radians(float(lng_b))

    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 3958.7613 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def _clamp_limit(value: int | None) -> int:
    if value is None:
        return 50
    return max(1, min(value, 100))


def _clamp_radius(value: float | None) -> float:
    if value is None:
        return 10.0
    return max(0.1, min(value, 25.0))


def _sort_key(sort: str, item: dict) -> tuple:
    price = item.get("price")
    calories = item.get("calories")
    ppc = item.get("price_per_calorie")
    name = (item.get("item_name") or "").casefold()
    distance = item.get("distance_mi")

    if sort == "calories":
        return (calories is None, calories or 0, name)
    if sort == "name":
        return (name, price or 0)
    if sort == "price_per_calorie":
        return (ppc is None, ppc or 0, price or 0, name)
    if sort == "distance":
        return (distance is None, distance or 0, price or 0, name)
    return (price is None, price or 0, name)


def _serialize_row(row, *, lat: float | None = None, lng: float | None = None) -> dict:
    item, price_point, section, page, employer, brand = row
    distance_mi = _distance_miles(lat, lng, employer.lat, employer.lng)
    price_per_calorie = None
    if item.calories and item.calories > 0 and price_point.price is not None:
        price_per_calorie = round(float(price_point.price) / float(item.calories), 3)

    return {
        "restaurant_id": employer.id,
        "restaurant_name": employer.name,
        "address": employer.address,
        "lat": employer.lat,
        "lng": employer.lng,
        "distance_mi": round(distance_mi, 2) if distance_mi is not None else None,
        "brand_fingerprint": brand.fingerprint if brand else None,
        "industry": employer.industry,
        "item_id": item.id,
        "item_name": item.name,
        "description": item.description,
        "course": item.course,
        "calories": item.calories,
        "dietary_tags": item.dietary_tags or [],
        "price": round(price_point.price, 2) if price_point.price is not None else None,
        "price_per_calorie": price_per_calorie,
        "variant": price_point.variant,
        "confidence": price_point.confidence,
        "section_name": section.name if section else None,
        "service_period": section.service_period if section else None,
        "source_url": page.url if page else None,
    }


def _base_query(session):
    return (
        session.query(MenuItem, MenuPricePoint, MenuSection, MenuPage, LocalEmployer, BrandGroup)
        .join(MenuPricePoint, MenuPricePoint.item_id == MenuItem.id)
        .join(LocalEmployer, LocalEmployer.id == MenuItem.restaurant_id)
        .outerjoin(MenuSection, MenuSection.id == MenuItem.section_id)
        .outerjoin(MenuPage, MenuPage.id == MenuSection.page_id)
        .outerjoin(BrandGroup, BrandGroup.id == LocalEmployer.brand_group_id)
        .filter(LocalEmployer.is_active.is_(True))
        .filter(MenuPricePoint.price.isnot(None))
    )


def _apply_common_filters(
    query,
    *,
    q: str | None = None,
    brand: str | None = None,
    cuisine: str | None = None,
    course: str | None = None,
    service_period: str | None = None,
    region: str | None = None,
    min_price: float | None = None,
    max_price: float | None = None,
    min_calories: int | None = None,
    max_calories: int | None = None,
    min_confidence: float = 0.55,
    lat: float | None = None,
    lng: float | None = None,
    radius_mi: float | None = None,
):
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(
            or_(
                MenuItem.name.ilike(like),
                MenuItem.description.ilike(like),
                MenuSection.name.ilike(like),
            )
        )
    if brand:
        query = query.filter(BrandGroup.fingerprint == brand)
    if cuisine:
        query = query.filter(LocalEmployer.industry.ilike(f"%{cuisine}%"))
    if course:
        query = query.filter(MenuItem.course == course)
    if service_period:
        query = query.filter(MenuSection.service_period == service_period)
    if region:
        query = query.filter(LocalEmployer.region == region)
    if min_price is not None:
        query = query.filter(MenuPricePoint.price >= min_price)
    if max_price is not None:
        query = query.filter(MenuPricePoint.price <= max_price)
    if min_calories is not None:
        query = query.filter(MenuItem.calories.isnot(None), MenuItem.calories >= min_calories)
    if max_calories is not None:
        query = query.filter(MenuItem.calories.isnot(None), MenuItem.calories <= max_calories)
    if min_confidence is not None:
        query = query.filter(MenuPricePoint.confidence.isnot(None), MenuPricePoint.confidence >= min_confidence)
    if lat is not None and lng is not None and radius_mi is not None:
        lat_delta = radius_mi / 69.0
        cos_lat = max(abs(math.cos(math.radians(lat))), 0.01)
        lng_delta = radius_mi / (69.0 * cos_lat)
        query = query.filter(
            LocalEmployer.lat.isnot(None),
            LocalEmployer.lng.isnot(None),
            LocalEmployer.lat.between(lat - lat_delta, lat + lat_delta),
            LocalEmployer.lng.between(lng - lng_delta, lng + lng_delta),
        )
    return query


def _parse_search_args():
    try:
        lat = _coerce_float(request.args.get("lat"))
        lng = _coerce_float(request.args.get("lng"))
        radius_mi = _clamp_radius(_coerce_float(request.args.get("radius_mi"), default=10.0))
        limit = _clamp_limit(_coerce_int(request.args.get("limit"), default=50))
        offset = max(0, _coerce_int(request.args.get("offset"), default=0) or 0)
        min_price = _coerce_float(request.args.get("min_price"))
        max_price = _coerce_float(request.args.get("max_price"))
        min_calories = _coerce_int(request.args.get("min_calories"))
        max_calories = _coerce_int(request.args.get("max_calories"))
        min_confidence = _coerce_float(request.args.get("min_confidence"), default=0.55) or 0.55
    except ValueError:
        return None, _bad_request("Invalid numeric parameter")

    sort = (request.args.get("sort") or "price").strip().lower()
    if sort not in {"price", "price_per_calorie", "calories", "name", "distance"}:
        return None, _bad_request("sort must be one of price, price_per_calorie, calories, name, distance")

    return {
        "q": (request.args.get("q") or "").strip() or None,
        "brand": (request.args.get("brand") or "").strip() or None,
        "cuisine": (request.args.get("cuisine") or "").strip() or None,
        "course": (request.args.get("course") or "").strip() or None,
        "service_period": (request.args.get("service_period") or "").strip() or None,
        "region": (request.args.get("region") or "").strip() or None,
        "lat": lat,
        "lng": lng,
        "radius_mi": radius_mi,
        "limit": limit,
        "offset": offset,
        "min_price": min_price,
        "max_price": max_price,
        "min_calories": min_calories,
        "max_calories": max_calories,
        "min_confidence": min_confidence,
        "sort": sort,
    }, None


def _filter_kwargs(params: dict) -> dict:
    return {
        "q": params.get("q"),
        "brand": params.get("brand"),
        "cuisine": params.get("cuisine"),
        "course": params.get("course"),
        "service_period": params.get("service_period"),
        "region": params.get("region"),
        "min_price": params.get("min_price"),
        "max_price": params.get("max_price"),
        "min_calories": params.get("min_calories"),
        "max_calories": params.get("max_calories"),
        "min_confidence": params.get("min_confidence"),
        "lat": params.get("lat"),
        "lng": params.get("lng"),
        "radius_mi": params.get("radius_mi"),
    }


@price_index_bp.get("")
def get_price_index():
    params, error = _parse_search_args()
    if error is not None:
        return error

    session = _get_db_session()
    try:
        query = _apply_common_filters(_base_query(session), **_filter_kwargs(params))

        needs_python_sort = params["sort"] in {"price_per_calorie", "distance"} or (
            params["lat"] is not None and params["lng"] is not None
        )

        if needs_python_sort:
            rows = query.all()
            items = []
            for row in rows:
                payload = _serialize_row(row, lat=params["lat"], lng=params["lng"])
                if params["lat"] is not None and params["lng"] is not None:
                    distance = payload.get("distance_mi")
                    if distance is None or distance > params["radius_mi"]:
                        continue
                items.append(payload)

            items.sort(key=lambda item: _sort_key(params["sort"], item))
            total = len(items)
            items = items[params["offset"]: params["offset"] + params["limit"]]
            return jsonify({
                "items": items,
                "total": total,
                "limit": params["limit"],
                "offset": params["offset"],
            })

        total = query.order_by(None).count()
        if params["sort"] == "calories":
            rows = query.order_by(MenuItem.calories.asc(), MenuItem.name.asc())
        elif params["sort"] == "name":
            rows = query.order_by(MenuItem.name.asc(), MenuPricePoint.price.asc())
        else:
            rows = query.order_by(MenuPricePoint.price.asc(), MenuItem.name.asc())

        rows = rows.offset(params["offset"]).limit(params["limit"]).all()
        items = [_serialize_row(row, lat=params["lat"], lng=params["lng"]) for row in rows]
        return jsonify({
            "items": items,
            "total": total,
            "limit": params["limit"],
            "offset": params["offset"],
        })
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()


@price_index_bp.get("/facets")
def get_price_index_facets():
    try:
        lat = _coerce_float(request.args.get("lat"))
        lng = _coerce_float(request.args.get("lng"))
        radius_mi = _clamp_radius(_coerce_float(request.args.get("radius_mi"), default=10.0))
        min_confidence = _coerce_float(request.args.get("min_confidence"), default=0.55) or 0.55
    except ValueError:
        return _bad_request("Invalid numeric parameter")

    region = (request.args.get("region") or "").strip() or None

    session = _get_db_session()
    try:
        rows = _apply_common_filters(
            _base_query(session),
            region=region,
            lat=lat,
            lng=lng,
            radius_mi=radius_mi,
            min_confidence=min_confidence,
        ).all()

        cuisine_counts: dict[str, set[int]] = {}
        brand_counts: dict[tuple[str, str], set[int]] = {}
        course_counts: dict[str, set[str]] = {}
        prices: list[float] = []
        calories: list[int] = []

        for row in rows:
            payload = _serialize_row(row, lat=lat, lng=lng)
            if lat is not None and lng is not None:
                distance = payload.get("distance_mi")
                if distance is None or distance > radius_mi:
                    continue

            restaurant_id = payload["restaurant_id"]
            item_id = payload["item_id"]
            cuisine = payload.get("industry")
            brand = payload.get("brand_fingerprint")
            brand_name = row[5].canonical_name if row[5] else None
            course = payload.get("course")
            price = payload.get("price")
            calorie_value = payload.get("calories")

            if cuisine:
                cuisine_counts.setdefault(cuisine, set()).add(restaurant_id)
            if brand and brand_name:
                brand_counts.setdefault((brand, brand_name), set()).add(restaurant_id)
            if course:
                course_counts.setdefault(course, set()).add(item_id)
            if price is not None:
                prices.append(price)
            if calorie_value is not None:
                calories.append(calorie_value)

        cuisines = [
            {"key": key, "count": len(ids)}
            for key, ids in sorted(cuisine_counts.items(), key=lambda item: (-len(item[1]), item[0].casefold()))
        ]
        courses = [
            {"key": key, "count": len(ids)}
            for key, ids in sorted(course_counts.items(), key=lambda item: (-len(item[1]), item[0]))
        ]
        brands = [
            {"fingerprint": fingerprint, "canonical_name": canonical_name, "count": len(ids)}
            for (fingerprint, canonical_name), ids in sorted(
                brand_counts.items(),
                key=lambda item: (-len(item[1]), item[0][1].casefold()),
            )
        ]

        return jsonify({
            "cuisines": cuisines,
            "courses": courses,
            "brands": brands,
            "price_range": {
                "min": round(min(prices), 2) if prices else None,
                "max": round(max(prices), 2) if prices else None,
                "p50": round(float(median(prices)), 2) if prices else None,
            },
            "calorie_range": {
                "min": min(calories) if calories else None,
                "max": max(calories) if calories else None,
                "p50": int(median(calories)) if calories else None,
            },
        })
    except Exception as exc:
        return _err(exc)
    finally:
        session.close()