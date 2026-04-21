#!/usr/bin/env python3
"""Backfill canonical deal observations from existing meal_deals rows.

This script is idempotent. It preserves any existing observation rows keyed by
`(source, source_observation_key)` and focuses on filling the new canonical
tables plus rebuilding the consumer-facing `deal_materializations` layer.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from collectors.meal_deals.ingest import (
    _build_source_observation_key,
    _observation_payload,
    _resolve_canonical_venue_id,
    _resolve_site_identity_id,
    _sync_observation_applicability,
    _upsert_observation,
)
from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from core.database import (
    BrandGroup,
    DealObservation,
    LocalEmployer,
    MealDeal,
    get_session,
    init_db,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _row_rank(row: tuple[MealDeal, str | None, str | None, str | None]) -> tuple:
    deal = row[0]
    verified_at = deal.verified_at or deal.updated_at or deal.created_at or datetime.min
    return (
        deal.signal_quality if deal.signal_quality is not None else -1.0,
        verified_at.timestamp() if hasattr(verified_at, "timestamp") else 0.0,
        deal.id or 0,
    )


def _review_state_from_deal(deal: MealDeal) -> str:
    return "accepted" if deal.is_active else "review"


def _build_signal(
    deal: MealDeal,
    *,
    brand_fingerprint: str | None,
    fallback_name: str | None,
    fallback_address: str | None,
) -> DealSignal:
    return DealSignal(
        restaurant_name=fallback_name or "Unknown",
        address=fallback_address,
        lat=deal.lat,
        lng=deal.lng,
        brand_fingerprint=brand_fingerprint,
        brand_group_id=deal.brand_group_id,
        local_employer_id=deal.local_employer_id,
        deal_name=deal.deal_name,
        deal_description=deal.deal_description,
        deal_type=deal.deal_type,
        price=deal.price,
        price_type=deal.price_type,
        discount_percentage=deal.discount_percentage,
        original_price=deal.original_price,
        menu_avg_price=deal.menu_avg_price,
        calories=deal.calories,
        calorie_price_ratio=deal.calorie_price_ratio,
        valid_days=deal.valid_days,
        valid_start_time=deal.valid_start_time,
        valid_end_time=deal.valid_end_time,
        is_recurring=deal.is_recurring,
        start_date=deal.start_date,
        end_date=deal.end_date,
        source=deal.source,
        source_url=deal.source_url,
        region=deal.region,
        raw_scraped_text=deal.raw_scraped_text,
        signal_quality=deal.signal_quality,
        deal_value_score=deal.deal_value_score,
        sub_deals=deal.sub_deals,
        metadata={"backfill_source": "meal_deals", "meal_deal_id": deal.id},
        observed_at=deal.verified_at or deal.updated_at or deal.created_at or datetime.utcnow(),
    )


def backfill_deal_observation_history(session, *, region: str = "austin_tx") -> dict[str, int]:
    is_pg = session.bind.dialect.name == "postgresql"  # type: ignore[union-attr]
    rows = session.query(
        MealDeal,
        BrandGroup.fingerprint,
        BrandGroup.canonical_name,
        LocalEmployer.name,
        LocalEmployer.address,
    ).outerjoin(
        BrandGroup,
        MealDeal.brand_group_id == BrandGroup.id,
    ).outerjoin(
        LocalEmployer,
        MealDeal.local_employer_id == LocalEmployer.id,
    ).filter(
        MealDeal.region == region,
    ).all()

    ordered_rows = sorted(rows, key=_row_rank, reverse=True)

    site_identity_cache: dict[str, int | None] = {}
    canonical_venue_cache: dict[int, int | None] = {}
    observation_ids: dict[str, int] = {}
    existing_observation_ids: dict[tuple[str, str], int | None] = {}
    desired_applicability: dict[int, dict[tuple, dict]] = {}
    stats = {
        "meal_deals_scanned": len(ordered_rows),
        "observations_inserted": 0,
        "observations_reused": 0,
        "applicability_targets": 0,
        "unresolved_venue_targets": 0,
        "unresolved_brand_targets": 0,
        "materializations_deleted": 0,
        "materializations_inserted": 0,
    }

    for deal, brand_fingerprint, brand_name, employer_name, employer_address in ordered_rows:
        signal = _build_signal(
            deal,
            brand_fingerprint=brand_fingerprint,
            fallback_name=employer_name or brand_name,
            fallback_address=employer_address,
        )
        source_observation_key = _build_source_observation_key(signal)
        observation_id = observation_ids.get(source_observation_key)

        if observation_id is None:
            cache_key = (signal.source, source_observation_key)
            if cache_key not in existing_observation_ids:
                existing = session.query(DealObservation).filter(
                    DealObservation.source == signal.source,
                    DealObservation.source_observation_key == source_observation_key,
                ).first()
                existing_observation_ids[cache_key] = existing.id if existing else None

            observation_id = existing_observation_ids[cache_key]
            if observation_id is None:
                observation_id = _upsert_observation(
                    session,
                    _observation_payload(
                        signal,
                        site_identity_id=_resolve_site_identity_id(session, signal, site_identity_cache),
                        review_state=_review_state_from_deal(deal),
                        source_observation_key=source_observation_key,
                    ),
                    is_pg=is_pg,
                )
                stats["observations_inserted"] += 1
                existing_observation_ids[cache_key] = observation_id
            else:
                stats["observations_reused"] += 1

            observation_ids[source_observation_key] = observation_id

        desired_rows = desired_applicability.setdefault(observation_id, {})

        if deal.is_chain_template:
            if deal.brand_group_id is not None:
                desired_rows[("brand", None, deal.brand_group_id)] = {
                    "applicability_scope": "brand",
                    "brand_group_id": deal.brand_group_id,
                    "confidence": 0.9,
                    "resolver_method": "meal_deals_history_backfill",
                    "resolver_notes": f"meal_deal_id={deal.id}",
                    "is_active": True,
                }
            else:
                stats["unresolved_brand_targets"] += 1

        if deal.local_employer_id is not None:
            canonical_venue_id = _resolve_canonical_venue_id(
                session,
                deal.local_employer_id,
                canonical_venue_cache,
            )
            if canonical_venue_id is not None:
                desired_rows[("venue", canonical_venue_id, None)] = {
                    "applicability_scope": "venue",
                    "canonical_venue_id": canonical_venue_id,
                    "confidence": 0.92,
                    "resolver_method": "meal_deals_history_backfill",
                    "resolver_notes": f"meal_deal_id={deal.id}",
                    "is_active": True,
                }
            else:
                stats["unresolved_venue_targets"] += 1

    for observation_id, rows_for_observation in desired_applicability.items():
        stats["applicability_targets"] += len(rows_for_observation)
        _sync_observation_applicability(session, observation_id, list(rows_for_observation.values()))

    materialization_stats = refresh_deal_materializations(session, region=region)
    stats["materializations_deleted"] = materialization_stats["deleted"]
    stats["materializations_inserted"] = materialization_stats["inserted"]
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill deal observations/applicability from meal_deals history")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)
    try:
        stats = backfill_deal_observation_history(session, region=args.region)
        if args.dry_run:
            session.rollback()
            logger.info("[DealHistoryBackfill] Dry run complete: %s", stats)
        else:
            session.commit()
            logger.info("[DealHistoryBackfill] Backfill complete: %s", stats)
        return 0
    except Exception as exc:
        session.rollback()
        logger.error("[DealHistoryBackfill] Failed: %s", exc, exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())