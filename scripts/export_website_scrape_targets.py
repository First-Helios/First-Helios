"""Export the exact deduplicated website list the website scraper will process.

Writes a CSV with metadata and a plain-text URL list in the same order used by
the website scraper query. This is intended for long manual runs outside the
agent environment.

Usage:
  PYTHONPATH=. python scripts/export_website_scrape_targets.py --all --skip-checked-days 0
  PYTHONPATH=. python scripts/export_website_scrape_targets.py --max-sites 10 --skip-checked-days 0
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import logging
from pathlib import Path
from typing import Any

from core.database import get_session, init_db


logger = logging.getLogger(__name__)


def _load_target_group_loader():
    try:
        from collectors.meal_deals.website_scraper import load_website_scrape_target_groups

        return load_website_scrape_target_groups
    except (ImportError, AttributeError):
        overlay_scraper = Path(__file__).resolve().parents[1] / "collectors" / "meal_deals" / "website_scraper.py"
        spec = importlib.util.spec_from_file_location("overlay_website_scraper", overlay_scraper)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load website scraper helper from {overlay_scraper}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.load_website_scrape_target_groups


load_website_scrape_target_groups = _load_target_group_loader()


def _serialize_timestamp(value: Any) -> str:
    return value.isoformat() if value else ""


def export_website_scrape_targets(
    *,
    region: str = "austin_tx",
    max_sites: int = 100,
    skip_checked_days: int | None = 3,
    output_prefix: Path | None = None,
) -> dict[str, object]:
    engine = init_db()
    session = get_session(engine)

    try:
        group_items, total_rows = load_website_scrape_target_groups(
            session,
            region=region,
            max_sites=max_sites,
            skip_checked_days=skip_checked_days,
        )

        prefix = output_prefix or Path("data/cache") / f"website_scrape_targets_{region}"
        prefix.parent.mkdir(parents=True, exist_ok=True)
        csv_path = prefix.with_suffix(".csv")
        txt_path = prefix.with_suffix(".txt")

        fieldnames = [
            "position",
            "url",
            "normalized_url",
            "restaurant_url_rows",
            "unique_employer_count",
            "local_employer_ids",
            "restaurant_names",
            "brand_group_ids",
            "sources",
            "has_permanent_url",
            "oldest_last_checked",
            "newest_last_checked",
        ]

        with csv_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
            writer.writeheader()

            for position, (normalized_url, group) in enumerate(group_items, start=1):
                employers_by_id: dict[int, Any] = {}
                brand_group_ids: set[int] = set()
                sources: set[str] = set()
                checked_times = []
                has_permanent_url = False

                for rurl, emp in group:
                    employers_by_id.setdefault(emp.id, emp)
                    if emp.brand_group_id is not None:
                        brand_group_ids.add(emp.brand_group_id)
                    if rurl.source:
                        sources.add(rurl.source)
                    if rurl.last_checked is not None:
                        checked_times.append(rurl.last_checked)
                    if rurl.is_permanent:
                        has_permanent_url = True

                unique_employers = list(employers_by_id.values())
                writer.writerow(
                    {
                        "position": position,
                        "url": group[0][0].url,
                        "normalized_url": normalized_url,
                        "restaurant_url_rows": len(group),
                        "unique_employer_count": len(unique_employers),
                        "local_employer_ids": "|".join(str(emp.id) for emp in unique_employers),
                        "restaurant_names": " | ".join(emp.name for emp in unique_employers),
                        "brand_group_ids": "|".join(str(brand_id) for brand_id in sorted(brand_group_ids)),
                        "sources": "|".join(sorted(sources)),
                        "has_permanent_url": str(has_permanent_url).lower(),
                        "oldest_last_checked": _serialize_timestamp(min(checked_times) if checked_times else None),
                        "newest_last_checked": _serialize_timestamp(max(checked_times) if checked_times else None),
                    }
                )

        with txt_path.open("w", encoding="utf-8") as txt_file:
            for _position, (_normalized_url, group) in enumerate(group_items, start=1):
                txt_file.write(f"{group[0][0].url}\n")

        preview = [group[0][0].url for _, group in group_items[:10]]
        return {
            "csv_path": str(csv_path),
            "txt_path": str(txt_path),
            "restaurant_url_rows": total_rows,
            "unique_urls": len(group_items),
            "preview_urls": preview,
        }
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the website scraper target list")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--max-sites", type=int, default=100, help="Maximum restaurant_url rows to consider")
    parser.add_argument("--all", action="store_true", help="Export every eligible website target")
    parser.add_argument(
        "--skip-checked-days",
        type=int,
        default=3,
        help="Mirror the website scraper skip window. Use 0 to include all sites.",
    )
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=None,
        help="Output path prefix without extension. Defaults to data/cache/website_scrape_targets_<region>",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    max_sites = 999999 if args.all else args.max_sites
    summary = export_website_scrape_targets(
        region=args.region,
        max_sites=max_sites,
        skip_checked_days=args.skip_checked_days,
        output_prefix=args.output_prefix,
    )

    logger.info("Website scraper target export complete:")
    logger.info("  restaurant_url rows considered: %d", summary["restaurant_url_rows"])
    logger.info("  unique urls exported: %d", summary["unique_urls"])
    logger.info("  csv: %s", summary["csv_path"])
    logger.info("  urls: %s", summary["txt_path"])
    preview_urls = summary["preview_urls"]
    if preview_urls:
        logger.info("  first urls:")
        for url in preview_urls:
            logger.info("    %s", url)


if __name__ == "__main__":
    main()