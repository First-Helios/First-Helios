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

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text as _sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.quality import compute_signal_quality, gate_decision
from core.database import (
    BrandGroup,
    LocalEmployer,
    MealDeal,
    get_engine,
    get_session,
    init_db,
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
        "is_active": is_active_flag,
        "lat": lat,
        "lng": lng,
        "region": region,
    }


def _resolve_single_employer(
    session: Session,
    signal: DealSignal,
) -> dict | None:
    """Try to match a DealSignal to a single local_employer by name/location."""
    if signal.local_employer_id:
        emp = session.get(LocalEmployer, signal.local_employer_id)
        if emp:
            return {
                "id": emp.id,
                "lat": emp.lat,
                "lng": emp.lng,
                "brand_group_id": emp.brand_group_id,
                "name": emp.name,
            }
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
    }
    now = datetime.now(timezone.utc)

    try:
        for signal in signals:
            # Skip junk deal names (nav elements, slogans, etc.)
            if _is_junk_deal_name(signal.deal_name):
                logger.debug("[DealIngest] Skipping junk deal name: %r", signal.deal_name)
                stats["skipped"] += 1
                continue

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
                brand_group_id = _resolve_brand_group_id(session, signal.brand_fingerprint)
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
            if not signal.local_employer_id:
                logger.debug(
                    "[DealIngest] Skipping signal with no brand or employer: %s",
                    signal.deal_name,
                )
                stats["skipped"] += 1
                continue

            loc = _resolve_single_employer(session, signal)
            if not loc:
                stats["skipped"] += 1
                continue

            deal_data = _build_deal_data(
                signal, now, is_active_flag, region,
                local_employer_id=loc["id"],
                brand_group_id=loc.get("brand_group_id"),
                lat=loc.get("lat"),
                lng=loc.get("lng"),
                is_chain_template=False,
            )
            if is_pg:
                _upsert_deal_pg(session, deal_data)
            else:
                _upsert_deal_sqlite(session, deal_data)
            stats["total_rows"] += 1

        session.commit()
        logger.info(
            "[DealIngest] Committed %d deal rows from %d signals "
            "(skipped %d, quality_rejected %d, quality_review %d)",
            stats["total_rows"],
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
