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
from datetime import datetime

from sqlalchemy import text as _sa_text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from collectors.meal_deals.models import DealSignal
from core.database import (
    BrandGroup,
    LocalEmployer,
    MealDeal,
    get_engine,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)


def _is_postgres(session: Session) -> bool:
    return session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]


def _resolve_brand_locations(
    session: Session,
    fingerprint: str,
    region: str,
) -> list[dict]:
    """Find all local_employer rows matching a brand fingerprint in the region.

    Returns list of dicts with id, lat, lng, brand_group_id.
    """
    # Find the brand_group
    bg = session.query(BrandGroup).filter(
        BrandGroup.fingerprint == fingerprint
    ).first()

    if not bg:
        logger.debug("[DealIngest] No brand_group for fingerprint=%r", fingerprint)
        return []

    # Find all locations for this brand in the region
    employers = session.query(LocalEmployer).filter(
        LocalEmployer.brand_group_id == bg.id,
        LocalEmployer.region == region,
        LocalEmployer.is_active.is_(True),
    ).all()

    return [
        {
            "id": emp.id,
            "lat": emp.lat,
            "lng": emp.lng,
            "brand_group_id": bg.id,
            "name": emp.name,
        }
        for emp in employers
    ]


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
            "original_price": stmt.excluded.original_price,
            "valid_days": stmt.excluded.valid_days,
            "valid_start_time": stmt.excluded.valid_start_time,
            "valid_end_time": stmt.excluded.valid_end_time,
            "source_url": stmt.excluded.source_url,
            "verified_at": stmt.excluded.verified_at,
            "is_active": True,
            "updated_at": datetime.utcnow(),
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
        existing.updated_at = datetime.utcnow()
        existing.is_active = True
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

    stats = {"inserted": 0, "updated": 0, "skipped": 0, "total_rows": 0}
    now = datetime.utcnow()

    try:
        for signal in signals:
            # Resolve target locations
            if signal.brand_fingerprint:
                locations = _resolve_brand_locations(
                    session, signal.brand_fingerprint, region
                )
            elif signal.local_employer_id:
                loc = _resolve_single_employer(session, signal)
                locations = [loc] if loc else []
            else:
                logger.debug(
                    "[DealIngest] Skipping signal with no brand or employer: %s",
                    signal.deal_name,
                )
                stats["skipped"] += 1
                continue

            if not locations:
                logger.debug(
                    "[DealIngest] No locations for %s (%s)",
                    signal.restaurant_name,
                    signal.brand_fingerprint,
                )
                stats["skipped"] += 1
                continue

            # Fan out: one DealSignal → N rows (one per location)
            for loc in locations:
                deal_data = {
                    "local_employer_id": loc["id"],
                    "brand_group_id": loc.get("brand_group_id"),
                    "deal_name": signal.deal_name,
                    "deal_description": signal.deal_description,
                    "deal_type": signal.deal_type,
                    "price": signal.price,
                    "original_price": signal.original_price,
                    "valid_days": signal.valid_days,
                    "valid_start_time": signal.valid_start_time,
                    "valid_end_time": signal.valid_end_time,
                    "is_recurring": signal.is_recurring,
                    "start_date": signal.start_date,
                    "end_date": signal.end_date,
                    "source": signal.source,
                    "source_url": signal.source_url,
                    "verified_at": now,
                    "is_active": True,
                    "lat": loc.get("lat"),
                    "lng": loc.get("lng"),
                    "region": region,
                }

                if is_pg:
                    _upsert_deal_pg(session, deal_data)
                else:
                    _upsert_deal_sqlite(session, deal_data)

                stats["total_rows"] += 1

        session.commit()
        logger.info(
            "[DealIngest] Committed %d deal rows from %d signals "
            "(skipped %d)",
            stats["total_rows"],
            len(signals),
            stats["skipped"],
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
    cutoff = datetime.utcnow() - __import__("datetime").timedelta(days=max_age_days)

    try:
        count = session.query(MealDeal).filter(
            MealDeal.source == source,
            MealDeal.region == region,
            MealDeal.is_active.is_(True),
            MealDeal.verified_at < cutoff,
        ).update({"is_active": False, "updated_at": datetime.utcnow()})

        session.commit()
        logger.info("[DealIngest] Deactivated %d stale %s deals in %s", count, source, region)
        return count
    except Exception as exc:
        session.rollback()
        logger.error("[DealIngest] Deactivation failed: %s", exc)
        return 0
    finally:
        session.close()
