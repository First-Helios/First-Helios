"""
collectors/meal_deals/manual_ingest.py — CSV/JSON ingest for human-sourced deals.

SpiritPool contributors or manual CSV uploads feed through this module.
Accepts CSV or JSON with columns:
    restaurant_name, address, deal_name, deal_description,
    deal_type, price, valid_days, valid_times

CLI usage:
    python -m collectors.meal_deals.manual_ingest --file deals.csv
    python -m collectors.meal_deals.manual_ingest --file deals.json
"""

import csv
import json
import logging
import sys
from pathlib import Path

from collectors.meal_deals.models import DealSignal

logger = logging.getLogger(__name__)


def _to_float(raw: object) -> float | None:
    if raw in (None, ""):
        return None
    return float(raw)


def _to_int(raw: object) -> int | None:
    if raw in (None, ""):
        return None
    return int(raw)


def _build_signal(row: dict) -> DealSignal:
    return DealSignal(
        restaurant_name=row.get("restaurant_name", ""),
        address=row.get("address"),
        lat=_to_float(row.get("lat")),
        lng=_to_float(row.get("lng")),
        local_employer_id=_to_int(row.get("local_employer_id")),
        deal_name=row.get("deal_name", ""),
        deal_description=row.get("deal_description"),
        deal_type=row.get("deal_type", "combo"),
        price=_to_float(row.get("price")),
        valid_days=row.get("valid_days"),
        valid_start_time=row.get("valid_start_time"),
        valid_end_time=row.get("valid_end_time"),
        source="manual",
        source_url=row.get("source_url"),
        raw_scraped_text=row.get("raw_scraped_text"),
        region=row.get("region", "austin_tx"),
    )


def load_from_csv(path: Path) -> list[DealSignal]:
    """Parse a CSV file into DealSignal objects."""
    signals: list[DealSignal] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            signals.append(_build_signal(row))
    return signals


def load_from_json(path: Path) -> list[DealSignal]:
    """Parse a JSON file (array of objects) into DealSignal objects."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        data = [data]

    signals: list[DealSignal] = []
    for row in data:
        signals.append(_build_signal(row))
    return signals


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Ingest meal deals from CSV or JSON")
    parser.add_argument("--file", required=True, help="Path to CSV or JSON file")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    if path.suffix == ".csv":
        signals = load_from_csv(path)
    elif path.suffix == ".json":
        signals = load_from_json(path)
    else:
        print(f"Unsupported file type: {path.suffix} (use .csv or .json)")
        sys.exit(1)

    print(f"Loaded {len(signals)} deal signals from {path.name}")

    if args.dry_run:
        for s in signals:
            print(f"  [{s.deal_type}] {s.restaurant_name}: {s.deal_name} — ${s.price}")
    else:
        from collectors.meal_deals.ingest import ingest_deal_signals
        stats = ingest_deal_signals(signals, region=args.region)
        print(f"Ingested: {stats}")
