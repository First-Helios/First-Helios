"""Backfill menu graph tables from cached website scrape debug bundles."""

from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collectors.meal_deals.menu_db_writer import upsert_menu_shape
from collectors.meal_deals.menu_persistence_schema import check_foreign_keys
from collectors.meal_deals.website_scrape_audit_utils import DEFAULT_DEBUG_DIR, load_debug_bundles
from core.database import get_engine, get_session


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    return parser.parse_args()


def _empty_totals() -> dict[str, dict[str, int]]:
    return {
        "pages": {"inserted": 0, "updated": 0},
        "sections": {"inserted": 0, "updated": 0},
        "items": {"inserted": 0, "updated": 0},
        "price_points": {"inserted": 0, "updated": 0},
        "modifiers": {"inserted": 0, "updated": 0},
    }


def _empty_filtered_totals() -> dict[str, int]:
    return {
        "price_points_non_positive": 0,
    }


def main() -> int:
    args = _parse_args()
    bundles, invalid_json = load_debug_bundles(args.debug_dir)
    bundle_items = sorted(bundles.items())
    if args.limit is not None:
        bundle_items = bundle_items[: args.limit]

    totals = _empty_totals()
    filtered_totals = _empty_filtered_totals()
    skip_reasons: Counter[str] = Counter()
    processed = 0
    failures = 0
    shapes_found = 0

    engine = None if args.dry_run else get_engine()

    for site_key, bundle in bundle_items:
        processed += 1
        shape = bundle.get("menu_persistence_shape")
        if not isinstance(shape, dict):
            skip_reasons["missing_shape"] += 1
            continue

        shapes_found += 1
        if args.dry_run:
            fk_violations = check_foreign_keys(shape)
            if fk_violations:
                failures += 1
                skip_reasons["shape_fk_violations"] += 1
                print(f"[backfill_menu_tables] fk violations for {site_key}: {len(fk_violations)}")
                continue

            totals["pages"]["inserted"] += len(shape.get("pages", []))
            totals["sections"]["inserted"] += len(shape.get("sections", []))
            totals["items"]["inserted"] += len(shape.get("items", []))
            totals["price_points"]["inserted"] += len(shape.get("price_points", []))
            totals["modifiers"]["inserted"] += len(shape.get("modifiers", []))
            continue

        session = get_session(engine)
        try:
            result = upsert_menu_shape(session, shape)
            if result.skipped:
                skip_reasons[result.skip_reason or "skipped"] += 1
                session.rollback()
                continue

            for table_name, counts in result.tables.items():
                totals[table_name]["inserted"] += counts["inserted"]
                totals[table_name]["updated"] += counts["updated"]
            for key, count in result.filtered.items():
                filtered_totals[key] = filtered_totals.get(key, 0) + count

            if args.dry_run:
                session.rollback()
            else:
                session.commit()
        except Exception as exc:
            failures += 1
            session.rollback()
            print(f"[backfill_menu_tables] failed for {site_key}: {exc}")
        finally:
            session.close()

    print(f"processed_bundles={processed}")
    print(f"bundles_with_shapes={shapes_found}")
    print(f"invalid_bundle_json={invalid_json}")
    print(f"dry_run={args.dry_run}")
    print(f"failures={failures}")
    for table_name, counts in totals.items():
        print(
            f"{table_name}: inserted={counts['inserted']} updated={counts['updated']}"
        )
    if any(filtered_totals.values()):
        print("filtered:")
        for key, count in sorted(filtered_totals.items()):
            print(f"  {key}={count}")
    if skip_reasons:
        print("skip_reasons:")
        for reason, count in sorted(skip_reasons.items()):
            print(f"  {reason}={count}")

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())