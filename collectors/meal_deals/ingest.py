"""
collectors/meal_deals/ingest.py — Single write path for all MealDeal records.

Every deal collector produces list[DealSignal].  This module converts
them into meal_deals rows, handling:
  1. Brand group resolution (fingerprint → brand_group_id)
  2. Fan-out: one chain deal × N locations = N rows
  3. Dedup via (local_employer_id, deal_name, source) — update if exists
  4. Denormalized lat/lng from local_employer

Mirrors events/ingest.py in structure and conventions.

Called by: collectors/meal_deals/chain_deals.py, future collectors
"""

import hashlib
import logging
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as _sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.quality import compute_deal_value_score, compute_signal_quality, gate_decision
from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from collectors.meal_deals.sub_deals import extract_sub_deals
from core.database import (
    BrandGroup,
    CanonicalVenueAlias,
    DealApplicability,
    DealObservation,
    LocalEmployer,
    MealDeal,
    SiteIdentity,
    get_engine,
    get_session,
    init_db,
)
from core.normalizer import make_fingerprint
from core.venue_identity import (
    likely_same_venue,
    normalize_address_for_identity,
    normalize_url_for_identity,
    pick_canonical_item,
)

logger = logging.getLogger(__name__)

# Deal names that are clearly not deals (navigation elements, slogans, etc.)
_JUNK_DEAL_NAMES = {
    "main navigation", "navigation", "values", "what we value",
    "values in action", "menu", "our menu", "view menu",
    "order now", "order online", "sign in", "sign up",
    "download the app", "careers", "about us", "contact us",
    "gift cards", "gift card", "franchise", "locations",
    "wanna save $$?", "rewards", "loyalty",
}

# Substrings that indicate a non-deal name — matched anywhere in the text
_JUNK_SUBSTRINGS = [
    "skip to content", "skip to main", "toggle menu",
    "toggle nav", "cookie", "privacy policy",
    # DB-observed junk (Issue 10, 7)
    "select a location",
    "learn more about",
    "check out how you can save",
    "who doesn't love a good deal",
    "who doesn\u2019t love a good deal",
    "select your nearest",
    "open menu close menu",
    "international sites",
    "all rights reserved",
    "copyright",
]


def _is_junk_deal_name(name: str) -> bool:
    """Return True if the deal name is clearly not a real deal."""
    if not name or len(name.strip()) < 5:
        return True
    lower = name.strip().lower()
    if lower in _JUNK_DEAL_NAMES:
        return True
    return any(sub in lower for sub in _JUNK_SUBSTRINGS)


def _is_postgres(session: Session) -> bool:
    return session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]


def _resolve_brand_group_id(session: Session, fingerprint: str) -> int | None:
    """Return brand_group.id for a given fingerprint, or None."""
    bg = session.query(BrandGroup).filter(
        BrandGroup.fingerprint == fingerprint
    ).first()
    return bg.id if bg else None


def _employer_ref(emp: LocalEmployer) -> dict:
    return {
        "id": emp.id,
        "lat": emp.lat,
        "lng": emp.lng,
        "brand_group_id": emp.brand_group_id,
        "name": emp.name,
    }


def _review_state(decision: str) -> str:
    if decision == "review":
        return "review"
    if decision == "reject":
        return "rejected"
    return "accepted"


def _build_source_observation_key(signal: DealSignal) -> str:
    normalized_url = normalize_url_for_identity(signal.source_url)
    if normalized_url:
        identity = f"url:{normalized_url}"
    else:
        identity = "|".join(
            [
                "venue",
                make_fingerprint(signal.restaurant_name or ""),
                normalize_address_for_identity(signal.address),
                signal.region or "",
            ]
        )

    key_parts = [
        signal.source or "",
        identity,
        (signal.deal_name or "").strip().casefold(),
        signal.deal_type or "",
        signal.valid_days or "",
        signal.valid_start_time or "",
        signal.valid_end_time or "",
        signal.price_type or "",
        f"{signal.price:.2f}" if signal.price is not None else "",
        f"{signal.discount_percentage:.2f}" if signal.discount_percentage is not None else "",
    ]
    return hashlib.sha1("|".join(key_parts).encode("utf-8")).hexdigest()


def _observation_payload(
    signal: DealSignal,
    *,
    site_identity_id: int | None,
    review_state: str,
    source_observation_key: str,
) -> dict:
    return {
        "source": signal.source,
        "collector_run_id": signal.collector_run_id,
        "site_identity_id": site_identity_id,
        "source_url": signal.source_url,
        "source_observation_key": source_observation_key,
        "observed_at": signal.observed_at,
        "deal_name": signal.deal_name,
        "deal_description": signal.deal_description,
        "deal_type": signal.deal_type,
        "price": signal.price,
        "price_type": signal.price_type,
        "discount_percentage": signal.discount_percentage,
        "original_price": signal.original_price,
        "menu_avg_price": signal.menu_avg_price,
        "calories": signal.calories,
        "calorie_price_ratio": signal.calorie_price_ratio,
        "valid_days": signal.valid_days,
        "valid_start_time": signal.valid_start_time,
        "valid_end_time": signal.valid_end_time,
        "is_recurring": signal.is_recurring,
        "start_date": signal.start_date,
        "end_date": signal.end_date,
        "raw_scraped_text": signal.raw_scraped_text,
        "extraction_payload": {
            "restaurant_name": signal.restaurant_name,
            "address": signal.address,
            "lat": signal.lat,
            "lng": signal.lng,
            "brand_fingerprint": signal.brand_fingerprint,
            "brand_group_id_hint": signal.brand_group_id,
            "local_employer_id_hint": signal.local_employer_id,
            "region": signal.region,
            "metadata": deepcopy(signal.metadata),
            "sub_deals_hint": deepcopy(signal.sub_deals),
        },
        "signal_quality": signal.signal_quality,
        "deal_value_score": signal.deal_value_score,
        "review_state": review_state,
    }


def _resolve_site_identity_id(
    session: Session,
    signal: DealSignal,
    cache: dict[str, int | None],
) -> int | None:
    normalized_url = normalize_url_for_identity(signal.source_url)
    if not normalized_url:
        return None
    if normalized_url in cache:
        return cache[normalized_url]

    site = session.query(SiteIdentity).filter(
        SiteIdentity.normalized_url == normalized_url
    ).first()
    cache[normalized_url] = site.id if site else None
    return cache[normalized_url]


def _resolve_canonical_venue_id(
    session: Session,
    local_employer_id: int | None,
    cache: dict[int, int | None],
) -> int | None:
    if local_employer_id is None:
        return None
    if local_employer_id in cache:
        return cache[local_employer_id]

    alias = session.query(CanonicalVenueAlias).filter(
        CanonicalVenueAlias.local_employer_id == local_employer_id
    ).first()
    cache[local_employer_id] = alias.canonical_venue_id if alias else None
    return cache[local_employer_id]


def _upsert_observation(session: Session, payload: dict, *, is_pg: bool) -> int:
    if is_pg:
        stmt = pg_insert(DealObservation).values(**payload)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_deal_observation_source_key",
            set_={
                "collector_run_id": stmt.excluded.collector_run_id,
                "site_identity_id": stmt.excluded.site_identity_id,
                "source_url": stmt.excluded.source_url,
                "observed_at": stmt.excluded.observed_at,
                "deal_name": stmt.excluded.deal_name,
                "deal_description": stmt.excluded.deal_description,
                "deal_type": stmt.excluded.deal_type,
                "price": stmt.excluded.price,
                "price_type": stmt.excluded.price_type,
                "discount_percentage": stmt.excluded.discount_percentage,
                "original_price": stmt.excluded.original_price,
                "menu_avg_price": stmt.excluded.menu_avg_price,
                "calories": stmt.excluded.calories,
                "calorie_price_ratio": stmt.excluded.calorie_price_ratio,
                "valid_days": stmt.excluded.valid_days,
                "valid_start_time": stmt.excluded.valid_start_time,
                "valid_end_time": stmt.excluded.valid_end_time,
                "is_recurring": stmt.excluded.is_recurring,
                "start_date": stmt.excluded.start_date,
                "end_date": stmt.excluded.end_date,
                "raw_scraped_text": stmt.excluded.raw_scraped_text,
                "extraction_payload": stmt.excluded.extraction_payload,
                "signal_quality": stmt.excluded.signal_quality,
                "deal_value_score": stmt.excluded.deal_value_score,
                "review_state": stmt.excluded.review_state,
                "updated_at": datetime.now(timezone.utc),
            },
        ).returning(DealObservation.id)
        return int(session.execute(stmt).scalar_one())

    existing = session.query(DealObservation).filter(
        DealObservation.source == payload["source"],
        DealObservation.source_observation_key == payload["source_observation_key"],
    ).first()
    if existing:
        for key, value in payload.items():
            if key not in ("id", "created_at"):
                setattr(existing, key, value)
        existing.updated_at = datetime.now(timezone.utc)
        session.flush()
        return int(existing.id)

    observation = DealObservation(**payload)
    session.add(observation)
    session.flush()
    return int(observation.id)


def _applicability_identity(row: DealApplicability | dict) -> tuple:
    if isinstance(row, DealApplicability):
        return (
            row.applicability_scope,
            row.canonical_venue_id,
            row.brand_group_id,
        )
    return (
        row["applicability_scope"],
        row.get("canonical_venue_id"),
        row.get("brand_group_id"),
    )


def _sync_observation_applicability(
    session: Session,
    observation_id: int,
    desired_rows: list[dict],
) -> None:
    existing_rows = session.query(DealApplicability).filter(
        DealApplicability.observation_id == observation_id
    ).all()
    existing_map = {
        _applicability_identity(row): row
        for row in existing_rows
    }
    desired_map = {
        _applicability_identity(row): row
        for row in desired_rows
    }

    for identity, existing in existing_map.items():
        if identity not in desired_map:
            existing.is_active = False
            existing.updated_at = datetime.now(timezone.utc)

    for identity, payload in desired_map.items():
        existing = existing_map.get(identity)
        if existing:
            existing.confidence = payload.get("confidence")
            existing.resolver_method = payload["resolver_method"]
            existing.resolver_notes = payload.get("resolver_notes")
            existing.valid_from = payload.get("valid_from")
            existing.valid_to = payload.get("valid_to")
            existing.is_active = payload.get("is_active", True)
            existing.updated_at = datetime.now(timezone.utc)
            continue

        session.add(DealApplicability(
            observation_id=observation_id,
            applicability_scope=payload["applicability_scope"],
            canonical_venue_id=payload.get("canonical_venue_id"),
            brand_group_id=payload.get("brand_group_id"),
            confidence=payload.get("confidence"),
            resolver_method=payload["resolver_method"],
            resolver_notes=payload.get("resolver_notes"),
            valid_from=payload.get("valid_from"),
            valid_to=payload.get("valid_to"),
            is_active=payload.get("is_active", True),
        ))


def _build_deal_data(
    signal: DealSignal,
    now: datetime,
    is_active_flag: bool,
    region: str,
    *,
    local_employer_id: int | None,
    brand_group_id: int | None,
    lat: float | None,
    lng: float | None,
    is_chain_template: bool,
) -> dict:
    """Common builder for the meal_deals row dict."""
    return {
        "local_employer_id": local_employer_id,
        "brand_group_id": brand_group_id,
        "is_chain_template": is_chain_template,
        "deal_name": signal.deal_name,
        "deal_description": signal.deal_description,
        "deal_type": signal.deal_type,
        "price": signal.price,
        "price_type": signal.price_type,
        "discount_percentage": signal.discount_percentage,
        "original_price": signal.original_price,
        "menu_avg_price": signal.menu_avg_price,
        "calories": signal.calories,
        "calorie_price_ratio": signal.calorie_price_ratio,
        "valid_days": signal.valid_days,
        "valid_start_time": signal.valid_start_time,
        "valid_end_time": signal.valid_end_time,
        "is_recurring": signal.is_recurring,
        "start_date": signal.start_date,
        "end_date": signal.end_date,
        "source": signal.source,
        "source_url": signal.source_url,
        "verified_at": now,
        "raw_scraped_text": signal.raw_scraped_text,
        "signal_quality": signal.signal_quality,
        "deal_value_score": signal.deal_value_score,
        "sub_deals": signal.sub_deals,
        "is_active": is_active_flag,
        "lat": lat,
        "lng": lng,
        "region": region,
    }


def _resolve_single_employer(
    session: Session,
    signal: DealSignal,
) -> dict | None:
    """Try to match a DealSignal to a single local_employer."""
    if signal.local_employer_id:
        emp = session.get(LocalEmployer, signal.local_employer_id)
        if emp:
            return _employer_ref(emp)

    if not signal.restaurant_name or not signal.address:
        return None

    base_query = session.query(LocalEmployer).filter(
        LocalEmployer.is_active.is_(True)
    )
    if signal.region:
        base_query = base_query.filter(LocalEmployer.region == signal.region)
    if signal.brand_group_id is not None:
        base_query = base_query.filter(LocalEmployer.brand_group_id == signal.brand_group_id)

    candidate_groups: list[list[LocalEmployer]] = []
    fingerprint = make_fingerprint(signal.restaurant_name)
    if fingerprint:
        candidate_groups.append(
            base_query.filter(LocalEmployer.fingerprint == fingerprint).all()
        )
    candidate_groups.append(base_query.all())

    seen_ids: set[int] = set()
    for candidates in candidate_groups:
        matches: list[LocalEmployer] = []
        for emp in candidates:
            if emp.id in seen_ids:
                continue
            seen_ids.add(emp.id)
            if likely_same_venue(
                name_a=signal.restaurant_name,
                address_a=signal.address,
                url_a=signal.source_url,
                lat_a=signal.lat,
                lng_a=signal.lng,
                name_b=emp.name,
                address_b=emp.address,
                url_b=None,
                lat_b=emp.lat,
                lng_b=emp.lng,
            ):
                matches.append(emp)

        if matches:
            canonical = pick_canonical_item(
                matches,
                get_id=lambda emp: emp.id,
                get_brand_group_id=lambda emp: emp.brand_group_id,
                get_address=lambda emp: emp.address,
                extra_rank=lambda emp: (
                    1 if make_fingerprint(emp.name) == fingerprint else 0,
                    emp.last_seen.timestamp() if emp.last_seen else 0.0,
                ),
            )
            return _employer_ref(canonical)

    return None


def _upsert_deal_pg(session: Session, deal_data: dict) -> None:
    """PostgreSQL upsert: INSERT … ON CONFLICT DO UPDATE."""
    stmt = pg_insert(MealDeal).values(**deal_data)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_meal_deal_employer_name_source",
        set_={
            "deal_description": stmt.excluded.deal_description,
            "deal_type": stmt.excluded.deal_type,
            "price": stmt.excluded.price,
            "price_type": stmt.excluded.price_type,
            "discount_percentage": stmt.excluded.discount_percentage,
            "original_price": stmt.excluded.original_price,
            "menu_avg_price": stmt.excluded.menu_avg_price,
            "calories": stmt.excluded.calories,
            "calorie_price_ratio": stmt.excluded.calorie_price_ratio,
            "valid_days": stmt.excluded.valid_days,
            "valid_start_time": stmt.excluded.valid_start_time,
            "valid_end_time": stmt.excluded.valid_end_time,
            "source_url": stmt.excluded.source_url,
            "verified_at": stmt.excluded.verified_at,
            "raw_scraped_text": stmt.excluded.raw_scraped_text,
            "signal_quality": stmt.excluded.signal_quality,
            "deal_value_score": stmt.excluded.deal_value_score,
            "sub_deals": stmt.excluded.sub_deals,
            "is_active": stmt.excluded.is_active,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def _upsert_chain_template_pg(session: Session, deal_data: dict) -> None:
    """PostgreSQL upsert for chain templates — keys on the partial unique
    index (brand_group_id, deal_name, source) WHERE is_chain_template=TRUE."""
    stmt = pg_insert(MealDeal).values(**deal_data)
    stmt = stmt.on_conflict_do_update(
        index_elements=["brand_group_id", "deal_name", "source"],
        index_where=MealDeal.is_chain_template.is_(True),
        set_={
            "deal_description": stmt.excluded.deal_description,
            "deal_type": stmt.excluded.deal_type,
            "price": stmt.excluded.price,
            "price_type": stmt.excluded.price_type,
            "discount_percentage": stmt.excluded.discount_percentage,
            "original_price": stmt.excluded.original_price,
            "menu_avg_price": stmt.excluded.menu_avg_price,
            "calories": stmt.excluded.calories,
            "calorie_price_ratio": stmt.excluded.calorie_price_ratio,
            "valid_days": stmt.excluded.valid_days,
            "valid_start_time": stmt.excluded.valid_start_time,
            "valid_end_time": stmt.excluded.valid_end_time,
            "source_url": stmt.excluded.source_url,
            "verified_at": stmt.excluded.verified_at,
            "raw_scraped_text": stmt.excluded.raw_scraped_text,
            "signal_quality": stmt.excluded.signal_quality,
            "deal_value_score": stmt.excluded.deal_value_score,
            "sub_deals": stmt.excluded.sub_deals,
            "is_active": stmt.excluded.is_active,
            "updated_at": datetime.now(timezone.utc),
        },
    )
    session.execute(stmt)


def _upsert_deal_sqlite(session: Session, deal_data: dict) -> None:
    """SQLite fallback: query-then-insert/update."""
    existing = session.query(MealDeal).filter(
        MealDeal.local_employer_id == deal_data["local_employer_id"],
        MealDeal.deal_name == deal_data["deal_name"],
        MealDeal.source == deal_data["source"],
    ).first()

    if existing:
        for key, val in deal_data.items():
            if key not in ("id", "created_at"):
                setattr(existing, key, val)
        existing.updated_at = datetime.now(timezone.utc)
    else:
        session.add(MealDeal(**deal_data))


def ingest_deal_signals(
    signals: list[DealSignal],
    region: str = "austin_tx",
) -> dict:
    """Convert DealSignals into meal_deals rows.

    For chain deals (brand_fingerprint set): fans out to all locations.
    For single-location deals: matches by local_employer_id.

    Returns stats dict: {"inserted": N, "updated": N, "skipped": N}.
    """
    engine = init_db()
    session = get_session(engine)
    is_pg = _is_postgres(session)

    stats = {
        "inserted": 0, "updated": 0, "skipped": 0, "total_rows": 0,
        "quality_rejected": 0, "quality_review": 0,
        "observation_rows": 0,
    }
    now = datetime.now(timezone.utc)
    site_identity_cache: dict[str, int | None] = {}
    canonical_venue_cache: dict[int, int | None] = {}
    observation_ids: dict[str, int] = {}
    desired_applicability: dict[int, dict[tuple, dict]] = {}

    try:
        for signal in signals:
            # Skip junk deal names (nav elements, slogans, etc.)
            if _is_junk_deal_name(signal.deal_name):
                logger.debug("[DealIngest] Skipping junk deal name: %r", signal.deal_name)
                stats["skipped"] += 1
                continue

            # Decompose multi-promo text into structured sub_deals if the
            # collector didn't already populate it.  Helps query layer show
            # all offers within a happy-hour block.
            if signal.sub_deals is None:
                source_text = signal.raw_scraped_text or signal.deal_description
                if source_text:
                    subs = extract_sub_deals(source_text)
                    signal.sub_deals = subs or None

            # Compute signal quality once per signal (location-independent fields)
            qscore = compute_signal_quality(
                deal_name=signal.deal_name,
                deal_description=signal.deal_description,
                price=signal.price,
                price_type=signal.price_type,
                valid_days=signal.valid_days,
                valid_start_time=signal.valid_start_time,
                valid_end_time=signal.valid_end_time,
                restaurant_name=signal.restaurant_name,
                raw_scraped_text=signal.raw_scraped_text,
            )
            decision, is_active_flag = gate_decision(qscore.total)
            signal.signal_quality = qscore.total
            signal.deal_value_score = compute_deal_value_score(
                price=signal.price,
                price_type=signal.price_type,
                discount_percentage=signal.discount_percentage,
                deal_name=signal.deal_name,
                deal_description=signal.deal_description,
                raw_scraped_text=signal.raw_scraped_text,
            )

            review_state = _review_state(decision)
            brand_group_id = signal.brand_group_id
            local_resolution: dict | None = None

            if signal.brand_fingerprint:
                brand_group_id = _resolve_brand_group_id(session, signal.brand_fingerprint)
                if brand_group_id is not None:
                    signal.brand_group_id = brand_group_id
            else:
                local_resolution = _resolve_single_employer(session, signal)
                if local_resolution:
                    signal.local_employer_id = local_resolution["id"]
                    signal.brand_group_id = local_resolution.get("brand_group_id")
                    signal.lat = local_resolution.get("lat")
                    signal.lng = local_resolution.get("lng")

            source_observation_key = _build_source_observation_key(signal)
            observation_id = observation_ids.get(source_observation_key)
            if observation_id is None:
                observation_id = _upsert_observation(
                    session,
                    _observation_payload(
                        signal,
                        site_identity_id=_resolve_site_identity_id(session, signal, site_identity_cache),
                        review_state=review_state,
                        source_observation_key=source_observation_key,
                    ),
                    is_pg=is_pg,
                )
                observation_ids[source_observation_key] = observation_id
                stats["observation_rows"] += 1

            desired_rows = desired_applicability.setdefault(observation_id, {})

            if brand_group_id is not None and signal.brand_fingerprint:
                desired_rows[("brand", None, brand_group_id)] = {
                    "applicability_scope": "brand",
                    "brand_group_id": brand_group_id,
                    "confidence": 0.95,
                    "resolver_method": "brand_fingerprint",
                    "is_active": True,
                }

            canonical_venue_id = _resolve_canonical_venue_id(
                session,
                signal.local_employer_id,
                canonical_venue_cache,
            )
            if canonical_venue_id is not None:
                desired_rows[("venue", canonical_venue_id, None)] = {
                    "applicability_scope": "venue",
                    "canonical_venue_id": canonical_venue_id,
                    "confidence": 0.95,
                    "resolver_method": "local_employer_alias",
                    "is_active": True,
                }

            if decision == "reject":
                logger.debug(
                    "[DealIngest] Rejecting %r (quality=%.2f, %s)",
                    signal.deal_name, qscore.total, "; ".join(qscore.reasons),
                )
                stats["skipped"] += 1
                stats["quality_rejected"] += 1
                continue

            if decision == "review":
                stats["quality_review"] += 1

            # Chain deals (brand_fingerprint set) insert ONCE as a template
            # rather than fanning out to every location.  Query layer resolves
            # to per-location rows via brand_group_id JOIN.
            if signal.brand_fingerprint:
                if brand_group_id is None:
                    logger.debug(
                        "[DealIngest] No brand_group for fingerprint=%r",
                        signal.brand_fingerprint,
                    )
                    stats["skipped"] += 1
                    continue

                deal_data = _build_deal_data(
                    signal, now, is_active_flag, region,
                    local_employer_id=None,
                    brand_group_id=brand_group_id,
                    lat=None, lng=None,
                    is_chain_template=True,
                )
                if is_pg:
                    _upsert_chain_template_pg(session, deal_data)
                else:
                    _upsert_deal_sqlite(session, deal_data)
                stats["total_rows"] += 1
                continue

            # Non-chain deals — single location
            if not local_resolution:
                logger.debug(
                    "[DealIngest] Skipping signal with no matched employer: %s",
                    signal.deal_name,
                )
                stats["skipped"] += 1
                continue

            deal_data = _build_deal_data(
                signal, now, is_active_flag, region,
                local_employer_id=local_resolution["id"],
                brand_group_id=local_resolution.get("brand_group_id"),
                lat=local_resolution.get("lat"),
                lng=local_resolution.get("lng"),
                is_chain_template=False,
            )
            if is_pg:
                _upsert_deal_pg(session, deal_data)
            else:
                _upsert_deal_sqlite(session, deal_data)
            stats["total_rows"] += 1

        for observation_id, rows in desired_applicability.items():
            _sync_observation_applicability(session, observation_id, list(rows.values()))

        refresh_deal_materializations(
            session,
            observation_ids=list(desired_applicability.keys()),
        )

        session.commit()
        logger.info(
            "[DealIngest] Committed %d deal rows and %d observations from %d signals "
            "(skipped %d, quality_rejected %d, quality_review %d)",
            stats["total_rows"],
            stats["observation_rows"],
            len(signals),
            stats["skipped"],
            stats["quality_rejected"],
            stats["quality_review"],
        )
    except Exception as exc:
        session.rollback()
        logger.error("[DealIngest] Failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()

    return stats


def deactivate_stale_deals(
    source: str,
    region: str = "austin_tx",
    max_age_days: int = 14,
) -> int:
    """Mark deals as inactive if they haven't been verified recently.

    Returns count of deactivated deals.
    """
    engine = init_db()
    session = get_session(engine)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    try:
        count = session.query(MealDeal).filter(
            MealDeal.source == source,
            MealDeal.region == region,
            MealDeal.is_active.is_(True),
            MealDeal.verified_at < cutoff,
        ).update({"is_active": False, "updated_at": datetime.now(timezone.utc)})

        session.commit()
        logger.info("[DealIngest] Deactivated %d stale %s deals in %s", count, source, region)
        return count
    except Exception as exc:
        session.rollback()
        logger.error("[DealIngest] Deactivation failed: %s", exc)
        return 0
    finally:
        session.close()
