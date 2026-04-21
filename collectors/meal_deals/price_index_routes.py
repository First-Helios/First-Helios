"""Flask Blueprint for Food Price Index endpoints."""

from __future__ import annotations

import logging
import math
import re
from functools import lru_cache
from html import unescape
from statistics import median

from flask import Blueprint, jsonify, request
from sqlalchemy import or_

from collectors.geocoding import geocode
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

try:
    import h3
except Exception:  # pragma: no cover - optional runtime dependency guard
    h3 = None

logger = logging.getLogger(__name__)

price_index_bp = Blueprint("price_index", __name__, url_prefix="/api/price-index")

_engine = None

_ZIP_RE = re.compile(r"^\d{5}$")
_INLINE_DIETARY_BLOCK_RE = re.compile(
    r"<\s*([a-z][a-z0-9_-]*)\b[^>]*>(.*?)<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_HTML_TAG_RE = re.compile(r"<[^>]+>")
_UNNAMED_SECTION_NAMES = {"(unnamed)", "(unsectioned)"}
_SIZE_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)?\s*(?:oz|ounce|ounces|lb|lbs|gal|gallon|qt|quart|pt|pint|cup|cups|liter|liters|l|ml)"
    r"|small|regular|large|x-large|xl|double|triple|single"
    r")\.?\s*$",
    re.IGNORECASE,
)
_PROMOTIONAL_CONTEXT_RE = re.compile(
    r"\b(?:happy\s*hour|daily\s+specials?|deals?|offers?|promotions?)\b",
    re.IGNORECASE,
)
_MEAL_PERIOD_RE = re.compile(r"\b(?:breakfast|brunch|lunch|dinner)\b", re.IGNORECASE)
_PROMOTIONAL_ROW_RE = re.compile(
    r"\b(?:\d{1,2}\s*%\s*off|half\s+off|bogo|buy\s+one|get\s+one|"
    r"\$\s*\d{1,3}(?:\.\d{1,2})?\s*off|all\s+day|open\s+to\s+close|"
    r"until\s+\d|daily\s+specials?|happy\s*hour)\b",
    re.IGNORECASE,
)
_DIETARY_TOKEN_MAP: dict[str, str] = {
    "v": "vegetarian",
    "veg": "vegetarian",
    "veggie": "vegetarian",
    "vegetarian": "vegetarian",
    "vegeterian": "vegetarian",
    "vegetariandiet": "vegetarian",
    "vg": "vegan",
    "vegan": "vegan",
    "vegandiet": "vegan",
    "gluten": "gluten_free",
    "glutenfree": "gluten_free",
    "gluten-free": "gluten_free",
    "gf": "gluten_free",
    "glutenfreediet": "gluten_free",
    "halal": "halal",
    "halaldiet": "halal",
    "kosher": "kosher",
    "kosherstyle": "kosher",
    "kosherdiet": "kosher",
    "df": "dairy_free",
    "dairyfree": "dairy_free",
    "dairy-free": "dairy_free",
    "dairyfreediet": "dairy_free",
    "n": "contains_nuts",
    "nut": "contains_nuts",
    "nuts": "contains_nuts",
    "seed": "contains_nuts",
    "seeds": "contains_nuts",
}
_TEXTUAL_DIETARY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bvegan\b|\bvg\b", re.IGNORECASE), "vegan"),
    (re.compile(r"\bvegetarian\b|\bveggie\b", re.IGNORECASE), "vegetarian"),
    (re.compile(r"\bgluten[\s-]*free\b|\bgf\b", re.IGNORECASE), "gluten_free"),
    (re.compile(r"\bhalal\b", re.IGNORECASE), "halal"),
    (re.compile(r"\bkosher\b", re.IGNORECASE), "kosher"),
    (re.compile(r"\bdairy[\s-]*free\b|\bdf\b", re.IGNORECASE), "dairy_free"),
    (re.compile(r"\bcontains?\s+nuts?(?:/seeds?)?\b|\bnuts?/seeds?\b", re.IGNORECASE), "contains_nuts"),
)


def _parse_multi_value_arg(name: str) -> list[str]:
    values = request.args.getlist(name)
    if len(values) == 1 and "," in values[0]:
        values = values[0].split(",")
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = (value or "").strip().casefold()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _dedupe_tags(tags: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        cleaned = (tag or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _canonicalize_dietary_token(token: str | None) -> str | None:
    if not token:
        return None
    token = token.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    cleaned = re.sub(r"[^a-z]+", "", token.casefold())
    if not cleaned:
        return None
    return _DIETARY_TOKEN_MAP.get(cleaned)


def _clean_display_text(value: str | None) -> str | None:
    if not value:
        return None
    text = unescape(value)
    text = _INLINE_DIETARY_BLOCK_RE.sub(" ", text)
    text = _INLINE_HTML_TAG_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", text).strip(" .-–—")
    return cleaned or None


def _extract_inline_dietary_tags(value: str | None) -> list[str]:
    if not value:
        return []
    text = unescape(value)
    tags: list[str] = []
    for match in _INLINE_DIETARY_BLOCK_RE.finditer(text):
        for raw in (match.group(1), match.group(2)):
            tag = _canonicalize_dietary_token(raw)
            if tag:
                tags.append(tag)
    cleaned = re.sub(r"\s+", " ", _INLINE_HTML_TAG_RE.sub(" ", text)).strip()
    for pattern, label in _TEXTUAL_DIETARY_PATTERNS:
        if pattern.search(cleaned):
            tags.append(label)
    return _dedupe_tags(tags)


def _normalize_dietary_tags(tags: list[str]) -> list[str]:
    normalized: list[str] = []
    for tag in tags:
        canonical = _canonicalize_dietary_token(tag) or (tag or "").strip().casefold()
        if canonical:
            normalized.append(canonical)
    return _dedupe_tags(normalized)


def _looks_like_variant_label(value: str | None) -> bool:
    if not value:
        return False
    return _SIZE_LABEL_RE.match(value.strip()) is not None


def _normalize_variant_label(value: str | None) -> str | None:
    cleaned = _clean_display_text(value)
    if not cleaned or not _looks_like_variant_label(cleaned):
        return None
    return cleaned


@lru_cache(maxsize=256)
def _resolve_zip_coordinates(zip_code: str) -> tuple[float, float] | None:
    if not _ZIP_RE.fullmatch(zip_code):
        return None
    lat, lng = geocode(zip_code)
    if lat is None or lng is None:
        lat, lng = geocode(f"{zip_code}, USA")
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def _candidate_h3_cells(lat: float, lng: float, radius_mi: float) -> list[str]:
    if h3 is None:
        return []
    try:
        center = h3.latlng_to_cell(lat, lng, 7)
    except Exception:
        return []

    if radius_mi <= 2.5:
        ring = 1
    elif radius_mi <= 5:
        ring = 2
    elif radius_mi <= 10:
        ring = 3
    elif radius_mi <= 15:
        ring = 4
    elif radius_mi <= 20:
        ring = 5
    else:
        ring = 6

    try:
        return list(h3.grid_disk(center, ring))
    except Exception:
        return []


def _apply_h3_prefilter(query, *, lat: float | None, lng: float | None, radius_mi: float | None):
    if lat is None or lng is None or radius_mi is None:
        return query
    cells = _candidate_h3_cells(lat, lng, radius_mi)
    if not cells:
        return query
    return query.filter(or_(LocalEmployer.h3_r7.in_(cells), LocalEmployer.h3_r7.is_(None)))


def _resolve_search_location(params: dict) -> tuple[float | None, float | None, bool]:
    lat = params.get("lat")
    lng = params.get("lng")
    if lat is not None and lng is not None:
        return lat, lng, True
    zip_code = params.get("zip_code")
    if not zip_code:
        return None, None, False
    coords = _resolve_zip_coordinates(zip_code)
    if coords is None:
        return None, None, False
    return coords[0], coords[1], True


def _build_bundle_price_scales(rows) -> dict[str, float]:
    prices_by_bundle: dict[str, list[float]] = {}
    for item, price_point, section, page, employer, brand in rows:
        bundle = getattr(page, "source_bundle", None) if page else None
        price = getattr(price_point, "price", None)
        if not bundle or price is None or price <= 0:
            continue
        prices_by_bundle.setdefault(bundle, []).append(float(price))

    scales: dict[str, float] = {}
    for bundle, prices in prices_by_bundle.items():
        if len(prices) < 6:
            continue
        if max(prices) > 1:
            continue
        subunit_count = sum(1 for price in prices if 0 < price < 1)
        if subunit_count < max(4, int(len(prices) * 0.6)):
            continue
        scales[bundle] = 100.0
    return scales


def _matches_dietary_filters(item_tags: list[str], selected_tags: list[str]) -> bool:
    if not selected_tags:
        return True
    tag_set = {tag.casefold() for tag in item_tags}
    return all(tag.casefold() in tag_set for tag in selected_tags)


def _is_promotional_context(section_name: str | None, service_period: str | None, source_url: str | None) -> bool:
    if service_period == "happy_hour":
        return True
    combined = " ".join(part for part in [section_name, source_url] if part)
    if not combined:
        return False
    return bool(_PROMOTIONAL_CONTEXT_RE.search(combined) and not _MEAL_PERIOD_RE.search(combined))


def _should_exclude_payload(payload: dict, row) -> bool:
    item, price_point, section, page, employer, brand = row
    price = payload.get("price")
    if price is None or price <= 0:
        return True

    evidence = _clean_display_text(getattr(price_point, "evidence", None))
    text = " ".join(part for part in [payload.get("item_name"), payload.get("description"), payload.get("section_name"), evidence] if part)
    if _PROMOTIONAL_ROW_RE.search(text):
        return True
    if _is_promotional_context(payload.get("section_name"), payload.get("service_period"), payload.get("source_url")):
        return True
    return False


def _payload_dedupe_key(payload: dict) -> tuple:
    return (
        payload.get("restaurant_id"),
        (payload.get("item_name") or "").casefold(),
        (payload.get("variant") or "").casefold(),
        payload.get("price"),
    )


def _pick_preferred_payload(existing: dict | None, candidate: dict) -> dict:
    if existing is None:
        return candidate
    existing_score = (
        existing.get("confidence") or 0,
        int(bool(existing.get("section_name"))),
        int(bool(existing.get("description"))),
    )
    candidate_score = (
        candidate.get("confidence") or 0,
        int(bool(candidate.get("section_name"))),
        int(bool(candidate.get("description"))),
    )
    return candidate if candidate_score > existing_score else existing


def _dedupe_payloads(items: list[dict]) -> list[dict]:
    selected: dict[tuple, dict] = {}
    order: list[tuple] = []
    for item in items:
        key = _payload_dedupe_key(item)
        if key not in selected:
            order.append(key)
        selected[key] = _pick_preferred_payload(selected.get(key), item)
    return [selected[key] for key in order]


def _materialize_rows(rows, *, lat: float | None, lng: float | None, has_location: bool, radius_mi: float | None, dietary_filters: list[str]) -> list[dict]:
    bundle_scales = _build_bundle_price_scales(rows)
    items: list[dict] = []
    for row in rows:
        page = row[3]
        bundle = getattr(page, "source_bundle", None) if page else None
        price_scale = bundle_scales.get(bundle, 1.0)
        payload = _serialize_row(
            row,
            lat=lat,
            lng=lng,
            has_location=has_location,
            price_scale=price_scale,
        )
        if payload is None:
            continue
        if has_location:
            distance = payload.get("distance_mi")
            if distance is None or (radius_mi is not None and distance > radius_mi):
                continue
        if not _matches_dietary_filters(payload.get("dietary_tags") or [], dietary_filters):
            continue
        if _should_exclude_payload(payload, row):
            continue
        items.append(payload)
    return _dedupe_payloads(items)


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


def _serialize_row(
    row,
    *,
    lat: float | None = None,
    lng: float | None = None,
    has_location: bool = False,
    price_scale: float = 1.0,
) -> dict | None:
    item, price_point, section, page, employer, brand = row
    item_name = _clean_display_text(item.name)
    description = _clean_display_text(item.description)
    section_name = _clean_display_text(section.name if section else None)
    if section_name in _UNNAMED_SECTION_NAMES:
        section_name = None

    variant = _normalize_variant_label(price_point.variant)
    evidence_variant = _normalize_variant_label(getattr(price_point, "evidence", None))
    if not variant:
        variant = evidence_variant
    if item_name and _looks_like_variant_label(item_name) and section_name:
        variant = variant or item_name
        item_name = section_name
        section_name = None
    if not item_name:
        return None

    raw_tags = list(item.dietary_tags or [])
    raw_tags.extend(_extract_inline_dietary_tags(item.name))
    raw_tags.extend(_extract_inline_dietary_tags(item.description))
    dietary_tags = _normalize_dietary_tags(raw_tags)

    scaled_price = round(float(price_point.price) * float(price_scale), 2) if price_point.price is not None else None
    distance_mi = _distance_miles(lat, lng, employer.lat, employer.lng) if has_location else None
    price_per_calorie = None
    if item.calories and item.calories > 0 and scaled_price is not None:
        price_per_calorie = round(float(scaled_price) / float(item.calories), 3)

    if description and item_name and description.casefold() == item_name.casefold():
        description = None

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
        "item_name": item_name,
        "description": description,
        "course": item.course,
        "calories": item.calories,
        "dietary_tags": dietary_tags,
        "price": scaled_price,
        "price_per_calorie": price_per_calorie,
        "variant": variant,
        "confidence": price_point.confidence,
        "section_name": section_name,
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

    zip_code = (request.args.get("zip_code") or "").strip()
    if zip_code and not _ZIP_RE.fullmatch(zip_code):
        return None, _bad_request("zip_code must be a 5-digit ZIP code")

    return {
        "q": (request.args.get("q") or "").strip() or None,
        "brand": (request.args.get("brand") or "").strip() or None,
        "cuisine": (request.args.get("cuisine") or "").strip() or None,
        "course": (request.args.get("course") or "").strip() or None,
        "dietary": _parse_multi_value_arg("dietary"),
        "service_period": (request.args.get("service_period") or "").strip() or None,
        "region": (request.args.get("region") or "").strip() or None,
        "zip_code": zip_code or None,
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

    resolved_lat, resolved_lng, has_location = _resolve_search_location(params)
    params["lat"] = resolved_lat
    params["lng"] = resolved_lng

    session = _get_db_session()
    try:
        query = _apply_common_filters(_base_query(session), **_filter_kwargs(params))
        query = _apply_h3_prefilter(
            query,
            lat=resolved_lat,
            lng=resolved_lng,
            radius_mi=params["radius_mi"],
        )
        rows = query.all()
        items = _materialize_rows(
            rows,
            lat=resolved_lat,
            lng=resolved_lng,
            has_location=has_location,
            radius_mi=params["radius_mi"],
            dietary_filters=params.get("dietary") or [],
        )
        if params.get("min_price") is not None:
            items = [item for item in items if item.get("price") is not None and item["price"] >= params["min_price"]]
        if params.get("max_price") is not None:
            items = [item for item in items if item.get("price") is not None and item["price"] <= params["max_price"]]
        items.sort(key=lambda item: _sort_key(params["sort"], item))
        total = len(items)
        items = items[params["offset"]: params["offset"] + params["limit"]]
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
    zip_code = (request.args.get("zip_code") or "").strip() or None
    if zip_code and not _ZIP_RE.fullmatch(zip_code):
        return _bad_request("zip_code must be a 5-digit ZIP code")

    resolved_lat = lat
    resolved_lng = lng
    has_location = lat is not None and lng is not None
    if not has_location and zip_code:
        coords = _resolve_zip_coordinates(zip_code)
        if coords is not None:
            resolved_lat, resolved_lng = coords
            has_location = True

    session = _get_db_session()
    try:
        query = _apply_common_filters(
            _base_query(session),
            region=region,
            lat=resolved_lat,
            lng=resolved_lng,
            radius_mi=radius_mi,
            min_confidence=min_confidence,
        )
        query = _apply_h3_prefilter(query, lat=resolved_lat, lng=resolved_lng, radius_mi=radius_mi)
        rows = query.all()
        items = _materialize_rows(
            rows,
            lat=resolved_lat,
            lng=resolved_lng,
            has_location=has_location,
            radius_mi=radius_mi,
            dietary_filters=[],
        )
        brand_name_by_item_id = {
            row[0].id: (row[5].canonical_name if row[5] else None)
            for row in rows
        }

        cuisine_counts: dict[str, set[int]] = {}
        brand_counts: dict[tuple[str, str], set[int]] = {}
        course_counts: dict[str, set[str]] = {}
        dietary_counts: dict[str, set[str]] = {}
        prices: list[float] = []
        calories: list[int] = []

        for payload in items:
            restaurant_id = payload["restaurant_id"]
            item_id = payload["item_id"]
            cuisine = payload.get("industry")
            brand = payload.get("brand_fingerprint")
            course = payload.get("course")
            price = payload.get("price")
            calorie_value = payload.get("calories")
            tags = payload.get("dietary_tags") or []
            brand_name = brand_name_by_item_id.get(item_id)

            if cuisine:
                cuisine_counts.setdefault(cuisine, set()).add(restaurant_id)
            if brand and brand_name:
                brand_counts.setdefault((brand, brand_name), set()).add(restaurant_id)
            if course:
                course_counts.setdefault(course, set()).add(item_id)
            for tag in tags:
                dietary_counts.setdefault(tag, set()).add(item_id)
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
        dietary_tags = [
            {"key": key, "count": len(ids)}
            for key, ids in sorted(dietary_counts.items(), key=lambda item: (-len(item[1]), item[0]))
        ]

        return jsonify({
            "cuisines": cuisines,
            "courses": courses,
            "brands": brands,
            "dietary_tags": dietary_tags,
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