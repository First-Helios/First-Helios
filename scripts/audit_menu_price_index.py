"""Audit persisted menu graph quality for the Food Price Index.

Examples:
  PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx
  PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --store chaat --show-rows 20
  PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --json > menu_audit.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.database import LocalEmployer, MenuItem, MenuPage, MenuPricePoint, MenuSection, get_engine, get_session

_UNNAMED_SECTION_NAMES = {"(unnamed)", "(unsectioned)"}
_SIZE_ONLY_NAME_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)?\s*(?:oz|ounce|ounces|lb|lbs|gal|gallon|qt|quart|pt|pint|cup|cups|liter|liters|l|ml)"
    r"|small|regular|large|x-large|xl|double|triple|single"
    r")\.?\s*$",
    re.IGNORECASE,
)
_PROMO_ROW_RE = re.compile(
    r"\b(?:\d{1,2}\s*%\s*off|half\s+off|bogo|buy\s+one|get\s+one|"
    r"\$\s*\d{1,3}(?:\.\d{1,2})?\s*off|happy\s*hour|daily\s+specials?|promo|promotion|offer)\b",
    re.IGNORECASE,
)
_ZERO_PRICE_ALLOWLIST_RE = re.compile(
    r"\b(?:water|cup\s+of\s+water|napkin|napkins|utensils?|cutlery|fork|spoon|knife|plate|plates|straw|condiments?)\b",
    re.IGNORECASE,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--store", default=None, help="Case-insensitive store-name substring filter")
    parser.add_argument("--limit", type=int, default=25, help="Number of stores to print")
    parser.add_argument("--show-rows", type=int, default=5, help="Detailed anomaly rows to show per store")
    parser.add_argument("--min-rows", type=int, default=1, help="Minimum persisted price-point rows per store")
    parser.add_argument("--include-clean", action="store_true", help="Include stores with zero detected anomalies")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    return parser.parse_args()


def _safe_median(prices: list[float]) -> float | None:
    return round(float(median(prices)), 2) if prices else None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _looks_like_size_only_name(value: str | None) -> bool:
    if not value:
        return False
    return _SIZE_ONLY_NAME_RE.match(value.strip()) is not None


def _looks_like_promo_row(*parts: str | None) -> bool:
    text = " ".join(part for part in parts if part)
    if not text:
        return False
    return _PROMO_ROW_RE.search(text) is not None


def _is_zero_allowlist(*parts: str | None) -> bool:
    text = " ".join(part for part in parts if part)
    if not text:
        return False
    return _ZERO_PRICE_ALLOWLIST_RE.search(text) is not None


def _bundle_scale_issue(prices: list[float]) -> bool:
    positive = [price for price in prices if price > 0]
    if len(positive) < 6:
        return False
    if max(positive) > 1:
        return False
    subunit_count = sum(1 for price in positive if 0 < price < 1)
    return subunit_count >= max(4, int(len(positive) * 0.6))


def _severity(bucket: dict[str, Any]) -> int:
    return (
        bucket["zero_suspect_count"] * 100
        + bucket["subunit_count"] * 10
        + bucket["unnamed_section_count"] * 4
        + bucket["size_name_count"] * 4
        + bucket["promo_row_count"] * 3
    )


def _query_rows(region: str, store_filter: str | None):
    engine = get_engine()
    session = get_session(engine)
    try:
        query = (
            session.query(
                LocalEmployer.id,
                LocalEmployer.name,
                MenuItem.id,
                MenuItem.name,
                MenuPricePoint.price,
                MenuPricePoint.evidence,
                MenuPricePoint.variant,
                MenuSection.name,
                MenuPage.source_bundle,
                MenuPage.url,
            )
            .join(MenuItem, MenuItem.restaurant_id == LocalEmployer.id)
            .join(MenuPricePoint, MenuPricePoint.item_id == MenuItem.id)
            .outerjoin(MenuSection, MenuSection.id == MenuItem.section_id)
            .outerjoin(MenuPage, MenuPage.id == MenuSection.page_id)
            .filter(LocalEmployer.region == region, LocalEmployer.is_active.is_(True))
        )
        if store_filter:
            query = query.filter(LocalEmployer.name.ilike(f"%{store_filter}%"))
        return query.all()
    finally:
        session.close()


def _build_report(rows, *, min_rows: int, include_clean: bool) -> dict[str, Any]:
    stores: dict[tuple[int, str], dict[str, Any]] = {}
    bundle_prices: dict[str, list[float]] = defaultdict(list)
    bundle_meta: dict[str, dict[str, Any]] = defaultdict(lambda: {"stores": set(), "urls": set()})

    for store_id, store_name, item_id, item_name, price, evidence, variant, section_name, source_bundle, page_url in rows:
        key = (int(store_id), store_name)
        bucket = stores.setdefault(key, {
            "restaurant_id": int(store_id),
            "restaurant_name": store_name,
            "row_count": 0,
            "item_ids": set(),
            "prices": [],
            "zero_suspect_count": 0,
            "zero_allowlist_count": 0,
            "subunit_count": 0,
            "unnamed_section_count": 0,
            "size_name_count": 0,
            "promo_row_count": 0,
            "sample_rows": [],
        })
        bucket["row_count"] += 1
        bucket["item_ids"].add(item_id)

        price_value = _float_or_none(price)
        if price_value is not None:
            bucket["prices"].append(price_value)
            if source_bundle:
                bundle_prices[source_bundle].append(price_value)
                bundle_meta[source_bundle]["stores"].add(store_name)
                if page_url:
                    bundle_meta[source_bundle]["urls"].add(page_url)

        if section_name in _UNNAMED_SECTION_NAMES:
            bucket["unnamed_section_count"] += 1
        if _looks_like_size_only_name(item_name):
            bucket["size_name_count"] += 1
        if _looks_like_promo_row(item_name, evidence, section_name):
            bucket["promo_row_count"] += 1

        reason = None
        if price_value is not None and price_value <= 0:
            if _is_zero_allowlist(item_name, evidence, section_name, variant):
                bucket["zero_allowlist_count"] += 1
            else:
                bucket["zero_suspect_count"] += 1
                reason = "zero_price"
        elif price_value is not None and 0 < price_value < 1:
            bucket["subunit_count"] += 1
            reason = "subunit_price"
        elif section_name in _UNNAMED_SECTION_NAMES:
            reason = "unnamed_section"
        elif _looks_like_size_only_name(item_name):
            reason = "size_only_item_name"
        elif _looks_like_promo_row(item_name, evidence, section_name):
            reason = "promo_row"

        if reason and len(bucket["sample_rows"]) < 20:
            bucket["sample_rows"].append({
                "reason": reason,
                "item_name": item_name,
                "price": price_value,
                "section_name": section_name,
                "variant": variant,
                "evidence": evidence,
                "source_bundle": source_bundle,
                "page_url": page_url,
            })

    store_rows: list[dict[str, Any]] = []
    for bucket in stores.values():
        if bucket["row_count"] < min_rows:
            continue
        bucket["item_count"] = len(bucket.pop("item_ids"))
        prices = bucket.pop("prices")
        bucket["min_price"] = round(min(prices), 2) if prices else None
        bucket["median_price"] = _safe_median(prices)
        bucket["max_price"] = round(max(prices), 2) if prices else None
        bucket["severity_score"] = _severity(bucket)
        if include_clean or bucket["severity_score"] > 0:
            store_rows.append(bucket)

    store_rows.sort(
        key=lambda row: (
            -row["severity_score"],
            -row["zero_suspect_count"],
            -row["subunit_count"],
            -row["row_count"],
            row["restaurant_name"].casefold(),
        )
    )

    bundle_rows: list[dict[str, Any]] = []
    for bundle, prices in bundle_prices.items():
        if not _bundle_scale_issue(prices):
            continue
        meta = bundle_meta[bundle]
        bundle_rows.append({
            "source_bundle": bundle,
            "store_count": len(meta["stores"]),
            "stores": sorted(meta["stores"]),
            "row_count": len(prices),
            "min_price": round(min(prices), 2),
            "median_price": _safe_median(prices),
            "max_price": round(max(prices), 2),
            "sample_urls": sorted(meta["urls"])[:3],
        })
    bundle_rows.sort(key=lambda row: (-row["row_count"], row["source_bundle"]))

    totals = {
        "stores_analyzed": len(store_rows),
        "price_point_rows": sum(row["row_count"] for row in store_rows),
        "zero_suspect_rows": sum(row["zero_suspect_count"] for row in store_rows),
        "zero_allowlist_rows": sum(row["zero_allowlist_count"] for row in store_rows),
        "subunit_rows": sum(row["subunit_count"] for row in store_rows),
        "unnamed_section_rows": sum(row["unnamed_section_count"] for row in store_rows),
        "size_name_rows": sum(row["size_name_count"] for row in store_rows),
        "promo_rows": sum(row["promo_row_count"] for row in store_rows),
        "bundle_scale_suspects": len(bundle_rows),
    }
    return {
        "totals": totals,
        "stores": store_rows,
        "bundle_scale_suspects": bundle_rows,
    }


def _print_text(report: dict[str, Any], *, limit: int, show_rows: int) -> None:
    totals = report["totals"]
    print("SUMMARY")
    for key, value in totals.items():
        print(f"{key}={value}")

    print("\nTOP_STORES")
    for row in report["stores"][:limit]:
        print(
            "\t".join([
                row["restaurant_name"],
                str(row["restaurant_id"]),
                f"rows={row['row_count']}",
                f"items={row['item_count']}",
                f"zero={row['zero_suspect_count']}",
                f"subunit={row['subunit_count']}",
                f"unnamed={row['unnamed_section_count']}",
                f"size_names={row['size_name_count']}",
                f"promo={row['promo_row_count']}",
                f"severity={row['severity_score']}",
                f"min={row['min_price']}",
                f"p50={row['median_price']}",
                f"max={row['max_price']}",
            ])
        )
        for sample in row["sample_rows"][:show_rows]:
            print(
                "  ROW\t"
                + "\t".join([
                    sample["reason"],
                    str(sample.get("item_name") or ""),
                    str(sample.get("price") if sample.get("price") is not None else ""),
                    str(sample.get("section_name") or ""),
                    str(sample.get("variant") or ""),
                    str(sample.get("evidence") or "")[:120],
                    str(sample.get("source_bundle") or ""),
                ])
            )

    if report["bundle_scale_suspects"]:
        print("\nBUNDLE_SCALE_SUSPECTS")
        for row in report["bundle_scale_suspects"][:limit]:
            print(
                "\t".join([
                    row["source_bundle"],
                    f"rows={row['row_count']}",
                    f"stores={row['store_count']}",
                    f"min={row['min_price']}",
                    f"p50={row['median_price']}",
                    f"max={row['max_price']}",
                    ", ".join(row["stores"][:3]),
                ])
            )


def main() -> int:
    args = _parse_args()
    rows = _query_rows(args.region, args.store)
    report = _build_report(rows, min_rows=args.min_rows, include_clean=args.include_clean)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_text(report, limit=args.limit, show_rows=args.show_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())