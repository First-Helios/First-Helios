"""Reset the meal-deal dataset so collectors can rebuild from scratch.

Deletes canonical and compatibility meal-deal rows in the correct order, with
optional resets for restaurant URL scrape state and website scrape debug cache.

Usage:
  PYTHONPATH=. python scripts/reset_meal_deal_dataset.py
  PYTHONPATH=. python scripts/reset_meal_deal_dataset.py --apply
  PYTHONPATH=. python scripts/reset_meal_deal_dataset.py --apply --reset-url-state --clear-debug-cache
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from sqlalchemy.orm import Session

from config.paths import WEBSITE_SCRAPE_DEBUG_DIR
from core.database import (
    DealApplicability,
    DealMaterialization,
    DealObservation,
    MealDeal,
    RestaurantURL,
    get_engine,
    get_session,
    init_db,
)


logger = logging.getLogger(__name__)


def _count_rows(session: Session) -> dict[str, int]:
    return {
        "deal_materializations": session.query(DealMaterialization).count(),
        "deal_applicability": session.query(DealApplicability).count(),
        "deal_observations": session.query(DealObservation).count(),
        "meal_deals": session.query(MealDeal).count(),
        "restaurant_urls": session.query(RestaurantURL).count(),
    }


def _clear_debug_cache(directory: Path) -> int:
    if not directory.exists():
        return 0

    removed = 0
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
            removed += 1
    return removed


def reset_meal_deal_dataset(
    *,
    apply: bool = False,
    reset_url_state: bool = False,
    clear_debug_cache: bool = False,
) -> dict[str, int]:
    engine = init_db()
    session = get_session(engine)

    before = _count_rows(session)
    stats = {
        **before,
        "deleted_materializations": 0,
        "deleted_applicability": 0,
        "deleted_observations": 0,
        "deleted_meal_deals": 0,
        "reset_restaurant_urls": 0,
        "cleared_debug_cache_files": 0,
    }

    try:
        if not apply:
            return stats

        # Break self-references before deleting observations.
        session.query(DealObservation).update(
            {DealObservation.superseded_by_observation_id: None},
            synchronize_session=False,
        )

        stats["deleted_materializations"] = session.query(DealMaterialization).delete(
            synchronize_session=False,
        )
        stats["deleted_applicability"] = session.query(DealApplicability).delete(
            synchronize_session=False,
        )
        stats["deleted_observations"] = session.query(DealObservation).delete(
            synchronize_session=False,
        )
        stats["deleted_meal_deals"] = session.query(MealDeal).delete(
            synchronize_session=False,
        )

        if reset_url_state:
            stats["reset_restaurant_urls"] = session.query(RestaurantURL).update(
                {
                    RestaurantURL.last_checked: None,
                    RestaurantURL.last_http_status: None,
                    RestaurantURL.has_deals_page: None,
                    RestaurantURL.deals_page_url: None,
                },
                synchronize_session=False,
            )

        session.commit()

        if clear_debug_cache:
            stats["cleared_debug_cache_files"] = _clear_debug_cache(WEBSITE_SCRAPE_DEBUG_DIR)

        return stats
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset meal-deal tables for a clean rebuild")
    parser.add_argument("--apply", action="store_true", help="Actually delete rows and reset state")
    parser.add_argument(
        "--reset-url-state",
        action="store_true",
        help="Also clear restaurant_urls scrape status so future runs start fresh",
    )
    parser.add_argument(
        "--clear-debug-cache",
        action="store_true",
        help="Also delete saved website scrape debug bundles before re-scraping",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stats = reset_meal_deal_dataset(
        apply=args.apply,
        reset_url_state=args.reset_url_state,
        clear_debug_cache=args.clear_debug_cache,
    )

    logger.info("Meal-deal dataset reset summary:")
    logger.info("  existing deal_materializations: %d", stats["deal_materializations"])
    logger.info("  existing deal_applicability: %d", stats["deal_applicability"])
    logger.info("  existing deal_observations: %d", stats["deal_observations"])
    logger.info("  existing meal_deals: %d", stats["meal_deals"])
    if args.apply:
        logger.info("  deleted materializations: %d", stats["deleted_materializations"])
        logger.info("  deleted applicability: %d", stats["deleted_applicability"])
        logger.info("  deleted observations: %d", stats["deleted_observations"])
        logger.info("  deleted meal_deals: %d", stats["deleted_meal_deals"])
        logger.info("  reset restaurant_urls: %d", stats["reset_restaurant_urls"])
        logger.info("  cleared debug cache files: %d", stats["cleared_debug_cache_files"])
    else:
        logger.info("  dry-run only; pass --apply to execute")


if __name__ == "__main__":
    main()