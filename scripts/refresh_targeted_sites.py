"""Targeted website recollection + ingest for a small list of employer IDs.

Usage:
    python scripts/refresh_targeted_sites.py --ids 18354 7047 26123 ...

For each id:
  • snapshots current (pages, sections, items, price_points) from menu_* tables
  • fetches the primary active restaurant_url, runs scrape_restaurant_website()
    (which upserts menu_sidecar into menu_* tables)
  • ingests any produced DealSignals via ingest_deal_signals()
  • re-snapshots and prints a diff

This is intended for small audit/refresh runs, not bulk collection.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import (  # noqa: E402
    LocalEmployer,
    MenuItem,
    MenuPage,
    MenuPricePoint,
    MenuSection,
    RestaurantURL,
    get_engine,
    get_session,
)
from collectors.meal_deals.website_scraper import scrape_restaurant_website  # noqa: E402
from collectors.meal_deals.ingest import ingest_deal_signals  # noqa: E402


def _snapshot(session, emp_id: int) -> dict[str, int]:
    from sqlalchemy import text

    row = session.execute(
        text(
            """
            SELECT
              (SELECT COUNT(*) FROM menu_pages WHERE restaurant_id = :eid) AS pages,
              (SELECT COUNT(*) FROM menu_sections WHERE restaurant_id = :eid) AS sections,
              (SELECT COUNT(*) FROM menu_items WHERE restaurant_id = :eid) AS items,
              (SELECT COUNT(*) FROM menu_price_points pp
                 JOIN menu_items mi ON mi.id = pp.item_id
                WHERE mi.restaurant_id = :eid) AS prices
            """
        ),
        {"eid": emp_id},
    ).mappings().one()
    return {k: int(row[k]) for k in ("pages", "sections", "items", "prices")}


def _diff(before: dict[str, int], after: dict[str, int]) -> str:
    parts = []
    for k in ("pages", "sections", "items", "prices"):
        delta = after[k] - before[k]
        arrow = "→"
        sign = f"+{delta}" if delta > 0 else str(delta)
        parts.append(f"{k} {before[k]} {arrow} {after[k]} ({sign})")
    return " | ".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ids", type=int, nargs="+", required=True, help="local_employers.id values")
    ap.add_argument("--region", default="austin_tx")
    ap.add_argument("--no-ingest", action="store_true", help="skip deal_observations ingest")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logger = logging.getLogger("refresh_targeted_sites")

    engine = get_engine()
    session = get_session(engine)

    targets: list[tuple[LocalEmployer, RestaurantURL]] = []
    for eid in args.ids:
        emp = session.query(LocalEmployer).filter(LocalEmployer.id == eid).one_or_none()
        if emp is None:
            logger.warning("employer %s not found", eid)
            continue
        rurl = (
            session.query(RestaurantURL)
            .filter(RestaurantURL.local_employer_id == eid, RestaurantURL.is_active.is_(True))
            .order_by(RestaurantURL.confidence.desc().nullslast())
            .first()
        )
        if rurl is None:
            logger.warning("%s (id=%s) has no active restaurant_url", emp.name, eid)
            continue
        targets.append((emp, rurl))

    if not targets:
        logger.error("no targets")
        return 1

    all_signals = []
    results: list[dict] = []

    for emp, rurl in targets:
        logger.info("=== %s (id=%s) %s ===", emp.name, emp.id, rurl.url)
        before = _snapshot(session, emp.id)
        session.close()  # scrape opens its own session; avoid stale state

        try:
            signals = scrape_restaurant_website(
                url=rurl.url,
                restaurant_name=emp.name,
                local_employer_id=emp.id,
                brand_group_id=emp.brand_group_id,
                region=args.region,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("scrape failed for %s: %s", emp.name, exc)
            signals = []

        session = get_session(engine)
        after = _snapshot(session, emp.id)
        sig_count = len(signals)
        all_signals.extend(signals)
        diff = _diff(before, after)
        logger.info("  signals=%d  %s", sig_count, diff)
        results.append({
            "id": emp.id,
            "name": emp.name,
            "url": rurl.url,
            "signals": sig_count,
            "before": before,
            "after": after,
        })

    session.close()

    if all_signals and not args.no_ingest:
        logger.info("Ingesting %d signals …", len(all_signals))
        stats = ingest_deal_signals(all_signals, region=args.region)
        logger.info("ingest stats: %s", stats)

    print("\n=== SUMMARY ===")
    total_items_gain = 0
    total_prices_gain = 0
    sites_with_gain = 0
    for r in results:
        gi = r["after"]["items"] - r["before"]["items"]
        gp = r["after"]["prices"] - r["before"]["prices"]
        total_items_gain += gi
        total_prices_gain += gp
        if gi > 0 or gp > 0 or r["signals"] > 0:
            sites_with_gain += 1
        print(
            f"  {r['id']:>6}  {r['name'][:35]:<35}  "
            f"signals={r['signals']:>2}  items {r['before']['items']}→{r['after']['items']}  "
            f"prices {r['before']['prices']}→{r['after']['prices']}"
        )
    print(
        f"  ---- total sites={len(results)} sites_with_gain={sites_with_gain} "
        f"Δitems={total_items_gain} Δprices={total_prices_gain}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
