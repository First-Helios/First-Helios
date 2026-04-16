#!/usr/bin/env python3
"""Re-audit canonical meal-deal observations against current quality rules.

This repairs the live canonical layer rather than only legacy meal_deals rows.
It recomputes signal quality, updates review_state, and refreshes any affected
deal_materializations so the API immediately reflects the new gating.

Usage:
  PYTHONPATH=. python scripts/reaudit_deal_observations.py
  PYTHONPATH=. python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx
  PYTHONPATH=. python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx --apply
"""

from __future__ import annotations

import argparse
import logging

from collectors.meal_deals.quality import compute_signal_quality, gate_decision
from collectors.meal_deals.semantic_layer import refresh_deal_materializations
from core.database import DealObservation, get_session, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _payload_dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def _review_state_from_decision(decision: str) -> str:
    if decision == "reject":
        return "rejected"
    if decision == "review":
        return "review"
    return "accepted"


def reaudit_deal_observations(
    session,
    *,
    source: str | None = None,
    region: str | None = None,
    backfill_source: str | None = None,
    allow_promotions: bool = False,
) -> dict[str, int]:
    query = session.query(DealObservation)
    if source:
        query = query.filter(DealObservation.source == source)

    stats: dict[str, int] = {
        "observations_scanned": 0,
        "quality_updated": 0,
        "review_state_updated": 0,
        "changed_observations": 0,
        "materializations_deleted": 0,
        "materializations_inserted": 0,
        "accepted_to_review": 0,
        "accepted_to_rejected": 0,
        "review_to_rejected": 0,
        "review_to_accepted": 0,
        "rejected_to_review": 0,
        "rejected_to_accepted": 0,
    }
    changed_ids: list[int] = []

    for observation in query.all():
        payload = _payload_dict(observation.extraction_payload)
        metadata = _payload_dict(payload.get("metadata"))
        payload_region = payload.get("region")

        if region and payload_region not in (None, region):
            continue
        if backfill_source and metadata.get("backfill_source") != backfill_source:
            continue

        stats["observations_scanned"] += 1
        qscore = compute_signal_quality(
            deal_name=observation.deal_name,
            deal_description=observation.deal_description,
            price=observation.price,
            price_type=observation.price_type,
            discount_percentage=observation.discount_percentage,
            valid_days=observation.valid_days,
            valid_start_time=observation.valid_start_time,
            valid_end_time=observation.valid_end_time,
            restaurant_name=payload.get("restaurant_name"),
            raw_scraped_text=observation.raw_scraped_text,
        )
        decision, _is_active = gate_decision(qscore.total)
        new_review_state = _review_state_from_decision(decision)
        if not allow_promotions:
            if observation.review_state == "review" and new_review_state == "accepted":
                new_review_state = "review"
            elif observation.review_state == "rejected" and new_review_state in {"review", "accepted"}:
                new_review_state = "rejected"

        changed = False
        if observation.signal_quality != qscore.total:
            observation.signal_quality = qscore.total
            stats["quality_updated"] += 1
            changed = True

        if observation.review_state != new_review_state:
            transition_key = f"{observation.review_state}_to_{new_review_state}"
            if transition_key in stats:
                stats[transition_key] += 1
            observation.review_state = new_review_state
            stats["review_state_updated"] += 1
            changed = True

        if changed:
            changed_ids.append(observation.id)

    stats["changed_observations"] = len(changed_ids)
    if changed_ids:
        materialization_stats = refresh_deal_materializations(
            session,
            observation_ids=changed_ids,
        )
        stats["materializations_deleted"] = materialization_stats["deleted"]
        stats["materializations_inserted"] = materialization_stats["inserted"]

    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-audit canonical meal-deal observations")
    parser.add_argument("--source", default=None)
    parser.add_argument("--region", default=None)
    parser.add_argument("--backfill-source", default=None)
    parser.add_argument("--allow-promotions", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)
    try:
        stats = reaudit_deal_observations(
            session,
            source=args.source,
            region=args.region,
            backfill_source=args.backfill_source,
            allow_promotions=args.allow_promotions,
        )
        if args.apply:
            session.commit()
            logger.info("[DealObservationReaudit] Applied: %s", stats)
        else:
            session.rollback()
            logger.info("[DealObservationReaudit] Dry run complete: %s", stats)
        return 0
    except Exception as exc:
        session.rollback()
        logger.error("[DealObservationReaudit] Failed: %s", exc, exc_info=True)
        return 1
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())