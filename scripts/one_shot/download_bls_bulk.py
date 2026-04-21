"""
BLS Bulk Historical Download — 2020 to 2026
============================================

Downloads all configured BLS series (CES + JOLTS + LAUS) from 2020 through
the most recent available data. Each series is saved independently to
data/cache/bls/{series_id}.json before writing to the DB, so:
  - A failed series never crashes the run
  - Already-downloaded series are skipped (resume on restart)
  - Raw JSON is preserved for inspection / re-import without API calls

Strategy:
  1. Try to batch all remaining series in one POST (fewest API calls)
  2. If batch partially fails, retry failed series individually (GET)
  3. After each successful fetch, immediately write that series to disk
  4. Write to DB only after disk cache is confirmed saved

BLS API v2 limits (with free registered key):
  - 50 series per POST request
  - 500 requests / day
  - 20 year window per request
  Set BLS_API_KEY env var to use v2; falls back to v1 (10yr, 25 series, shared 500/day)

Usage:
    BLS_API_KEY=your_key python scripts/one_shot/download_bls_bulk.py
    BLS_API_KEY=your_key python scripts/one_shot/download_bls_bulk.py --start 2015 --end 2026
    BLS_API_KEY=your_key python scripts/one_shot/download_bls_bulk.py --force   # re-fetch even if cached
    python scripts/one_shot/download_bls_bulk.py --db-only   # skip fetch, just (re)import from cache
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_bls_series, get_http_config
from config.paths import BLS_CACHE_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("bls_bulk")

BLS_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"
BLS_V2_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

# Per-series cache directory — see config/paths.py
CACHE_DIR = BLS_CACHE_DIR


# ── API helpers ───────────────────────────────────────────────────────────────

def _api_key() -> str | None:
    return os.environ.get("BLS_API_KEY") or None


def _post_batch(
    series_ids: list[str],
    start_year: str,
    end_year: str,
) -> dict[str, list[dict]]:
    """POST multiple series in one call. Returns {series_id: [data_points]}."""
    key = _api_key()
    url = BLS_V2_URL if key else BLS_V1_URL
    payload: dict[str, Any] = {
        "seriesid": series_ids,
        "startyear": start_year,
        "endyear": end_year,
    }
    if key:
        payload["registrationkey"] = key

    http_cfg = get_http_config()
    resp = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json", "User-Agent": http_cfg["user_agent"]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    for msg in data.get("message", []):
        logger.info("  BLS: %s", msg)

    if data.get("status") != "REQUEST_SUCCEEDED":
        raise RuntimeError(f"Batch failed: {data.get('status')} — {data.get('message')}")

    return {
        s["seriesID"]: s.get("data", [])
        for s in data.get("Results", {}).get("series", [])
    }


def _get_single(series_id: str, start_year: str, end_year: str) -> list[dict]:
    """GET a single series via v1 URL (fallback). Returns data_points list."""
    key = _api_key()
    url = BLS_V2_URL if key else BLS_V1_URL
    payload: dict[str, Any] = {
        "seriesid": [series_id],
        "startyear": start_year,
        "endyear": end_year,
    }
    if key:
        payload["registrationkey"] = key

    http_cfg = get_http_config()
    resp = requests.post(
        url,
        json=payload,
        headers={"Content-Type": "application/json", "User-Agent": http_cfg["user_agent"]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()

    for msg in data.get("message", []):
        logger.info("  BLS: %s", msg)

    series_list = data.get("Results", {}).get("series", [])
    if not series_list:
        return []
    return series_list[0].get("data", [])


# ── Cache helpers ─────────────────────────────────────────────────────────────

def cache_path(series_id: str) -> Path:
    return CACHE_DIR / f"{series_id}.json"


def is_cached(series_id: str) -> bool:
    return cache_path(series_id).exists()


def save_cache(series_id: str, data_points: list[dict]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(cache_path(series_id), "w") as f:
        json.dump({"series_id": series_id, "fetched_at": datetime.utcnow().isoformat(), "data": data_points}, f, indent=2)


def load_cache(series_id: str) -> list[dict]:
    with open(cache_path(series_id)) as f:
        return json.load(f).get("data", [])


# ── Main fetch loop ───────────────────────────────────────────────────────────

def fetch_series(
    series_config: dict[str, dict],
    start_year: str,
    end_year: str,
    force: bool = False,
) -> dict[str, list[dict]]:
    """Fetch all series, caching each independently. Returns {series_id: data_points}.

    Strategy:
      1. Skip already-cached series (unless --force)
      2. Batch the remaining uncached series in one POST
      3. Save each result to disk immediately
      4. For any series missing from batch response, retry individually
    """
    all_ids = {cfg["series_id"]: key for key, cfg in series_config.items()}
    results: dict[str, list[dict]] = {}

    # Load already-cached
    cached_ids = []
    needed_ids = []
    for sid in all_ids:
        if not force and is_cached(sid):
            results[sid] = load_cache(sid)
            cached_ids.append(sid)
        else:
            needed_ids.append(sid)

    if cached_ids:
        logger.info("Loaded %d series from cache (skipping API call)", len(cached_ids))
    if not needed_ids:
        logger.info("All series already cached.")
        return results

    logger.info("Fetching %d series from BLS API (%s→%s) ...", len(needed_ids), start_year, end_year)
    key = _api_key()
    max_per_batch = 50 if key else 25

    # Split into batches respecting API limits
    batches = [needed_ids[i:i+max_per_batch] for i in range(0, len(needed_ids), max_per_batch)]

    for batch_num, batch in enumerate(batches, 1):
        logger.info("  Batch %d/%d — %d series", batch_num, len(batches), len(batch))
        batch_result: dict[str, list[dict]] = {}

        try:
            batch_result = _post_batch(batch, start_year, end_year)
            logger.info("  Batch succeeded — %d series returned", len(batch_result))
        except Exception as e:
            logger.warning("  Batch %d failed (%s) — falling back to individual fetches", batch_num, e)

        # Save whatever came back from the batch
        for sid, pts in batch_result.items():
            save_cache(sid, pts)
            results[sid] = pts
            logger.info("    Saved %-42s  %d pts", sid, len(pts))

        # Retry any series the batch didn't return
        missing = [sid for sid in batch if sid not in batch_result]
        for sid in missing:
            logger.info("  Retrying individually: %s", sid)
            try:
                pts = _get_single(sid, start_year, end_year)
                save_cache(sid, pts)
                results[sid] = pts
                logger.info("    OK  %-42s  %d pts", sid, len(pts))
            except Exception as e:
                logger.error("    FAILED %-42s  %s", sid, e)
                results[sid] = []  # empty — will be skipped in processing

            time.sleep(1.5)  # polite gap between individual retries

        if batch_num < len(batches):
            time.sleep(2)

    return results


# ── DB writers ────────────────────────────────────────────────────────────────

def write_jolts(records: list[dict]) -> int:
    from core.database import JOLTSRecord, init_db, get_session
    engine = init_db()
    session = get_session(engine)
    written = 0
    try:
        for rec in records:
            existing = session.query(JOLTSRecord).filter_by(
                series_id=rec["series_id"], year=rec["year"], month=rec["month"]
            ).first()
            if existing:
                existing.value = rec["value"]
                existing.fetched_at = datetime.utcnow()
            else:
                session.add(JOLTSRecord(
                    series_id=rec["series_id"],
                    series_description=rec.get("series_description", ""),
                    metric=rec.get("metric", ""),
                    industry_code=rec.get("industry_code", ""),
                    year=rec["year"], month=rec["month"], value=rec["value"],
                    fetched_at=datetime.utcnow(),
                ))
                written += 1
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("JOLTS write failed: %s", e)
    finally:
        session.close()
    return written


def write_laus(records: list[dict], region: str = "austin_tx") -> int:
    from core.database import LAUSRecord, init_db, get_session
    engine = init_db()
    session = get_session(engine)
    written = 0
    try:
        for rec in records:
            existing = session.query(LAUSRecord).filter_by(
                fips_code=rec["fips_code"], year=rec["year"], month=rec["month"]
            ).first()
            if existing:
                existing.unemployment_rate = rec["unemployment_rate"]
                existing.fetched_at = datetime.utcnow()
            else:
                session.add(LAUSRecord(
                    fips_code=rec["fips_code"],
                    area_title=rec.get("area_title", ""),
                    year=rec["year"], month=rec["month"],
                    unemployment_rate=rec["unemployment_rate"],
                    region=region, fetched_at=datetime.utcnow(),
                ))
                written += 1
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("LAUS write failed: %s", e)
    finally:
        session.close()
    return written


def write_wage_index(records: list[dict]) -> int:
    from core.database import WageIndex, init_db, get_session
    engine = init_db()
    session = get_session(engine)
    written = 0
    try:
        for rec in records:
            session.add(WageIndex(
                employer=rec["employer"], is_chain=False, chain_key=None,
                industry=rec["industry"], role_title=rec["role_title"],
                wage_min=rec.get("wage_min"), wage_max=rec.get("wage_max"),
                wage_period=rec.get("wage_period", "hourly"),
                location=rec["location"], zip_code=None,
                source=rec["source"], observed_at=rec["observed_at"],
                source_url=rec.get("source_url", ""),
            ))
            written += 1
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("WageIndex write failed: %s", e)
    finally:
        session.close()
    return written


def write_signals(records: list[dict]) -> int:
    """Write CPI/ECI indicator records directly to the signals table."""
    from core.database import Signal, Store, init_db, get_session
    engine = init_db()
    session = get_session(engine)
    written = 0
    try:
        for rec in records:
            store_num = rec["store_num"]
            # Ensure a minimal store row exists for this indicator bucket
            if not session.query(Store).filter_by(store_num=store_num).first():
                session.add(Store(
                    store_num=store_num,
                    chain="bls",
                    industry="economic_indicator",
                    store_name=rec.get("description", store_num),
                    address="",
                    region=rec.get("region", "austin_tx"),
                    is_active=True,
                ))
            sig = Signal(
                store_num=store_num,
                source=rec["source"],
                signal_type=rec["signal_type"],
                value=rec["value"],
                observed_at=rec["observed_at"],
                created_at=datetime.utcnow(),
            )
            sig.set_metadata({
                "series_id": rec["series_id"],
                "description": rec.get("description", ""),
                "category": rec.get("category", ""),
            })
            session.add(sig)
            written += 1
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error("Signals write failed: %s", e)
    finally:
        session.close()
    return written


# ── Processing ────────────────────────────────────────────────────────────────

def process_and_write(
    series_data: dict[str, list[dict]],
    series_config: dict[str, dict],
    region: str,
) -> dict[str, int]:
    jolts_records: list[dict] = []
    laus_records: list[dict] = []
    ces_records: list[dict] = []
    indicator_records: list[dict] = []   # CPI + ECI

    for series_key, cfg in series_config.items():
        sid = cfg["series_id"]
        category = cfg.get("category", "")
        description = cfg.get("description", series_key)
        data_points = series_data.get(sid, [])

        if not data_points:
            logger.warning("  Skipping %-44s no data returned", sid)
            continue

        logger.info("  Processing [%-5s] %s — %d pts", category.upper(), sid, len(data_points))

        for dp in data_points:
            try:
                year = int(dp.get("year", 0))
                period = str(dp.get("period", ""))
                value_str = str(dp.get("value", "")).strip()
                if not value_str or value_str == "-":
                    continue
                value = float(value_str)
            except (ValueError, TypeError):
                continue

            # ECI uses quarterly periods (Q01–Q04); CPI and others use monthly (M01–M12)
            if period.startswith("M"):
                try:
                    month = int(period[1:])
                except ValueError:
                    continue
                obs_dt = datetime(year, month, 1)
            elif period.startswith("Q") and category == "eci":
                # Map Q01→month 3, Q02→6, Q03→9, Q04→12
                try:
                    qnum = int(period[1:])
                    month = qnum * 3
                    obs_dt = datetime(year, month, 1)
                except ValueError:
                    continue
            else:
                continue  # skip annual or unrecognized periods

            if category == "jolts":
                jolts_records.append({
                    "series_id": sid, "series_description": description,
                    "metric": cfg.get("metric", ""),
                    "industry_code": cfg.get("industry_code", ""),
                    "year": year, "month": month, "value": value,
                })

            elif category == "laus":
                laus_records.append({
                    "fips_code": cfg.get("fips_code", ""),
                    "area_title": description,
                    "year": year, "month": month,
                    "unemployment_rate": value,
                })

            elif category == "ces":
                is_wage = value < 5000  # employment in thousands is > 5000 nationally
                ces_records.append({
                    "employer": "BLS Regional Average", "industry": "food_service",
                    "role_title": description[:100],
                    "wage_min": value if is_wage else None,
                    "wage_max": value if is_wage else None,
                    "wage_period": "hourly_or_weekly" if is_wage else "employment_thousands",
                    "location": region,
                    "source": f"bls_ces_{sid}",
                    "source_url": f"https://data.bls.gov/timeseries/{sid}",
                    "observed_at": obs_dt,
                })

            elif category in ("cpi", "eci"):
                indicator_records.append({
                    "store_num": f"BLS-{sid}",
                    "source": f"bls_{category}",
                    "signal_type": f"{category}_index",
                    "value": value,
                    "observed_at": obs_dt,
                    "series_id": sid,
                    "description": description,
                    "category": category,
                    "region": region,
                })

    counts: dict[str, int] = {"jolts": 0, "laus": 0, "ces": 0, "cpi_eci": 0}

    if jolts_records:
        counts["jolts"] = write_jolts(jolts_records)
        logger.info("  JOLTS:   %d new rows (prepared %d)", counts["jolts"], len(jolts_records))

    if laus_records:
        counts["laus"] = write_laus(laus_records, region)
        logger.info("  LAUS:    %d new rows (prepared %d)", counts["laus"], len(laus_records))

    if ces_records:
        counts["ces"] = write_wage_index(ces_records)
        logger.info("  CES:     %d new rows (prepared %d)", counts["ces"], len(ces_records))

    if indicator_records:
        counts["cpi_eci"] = write_signals(indicator_records)
        logger.info("  CPI/ECI: %d new rows (prepared %d)", counts["cpi_eci"], len(indicator_records))

    return counts


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Bulk-download BLS series 2020-2026 → tracker.db")
    parser.add_argument("--start",   default="2020")
    parser.add_argument("--end",     default="2026")
    parser.add_argument("--region",  default="austin_tx")
    parser.add_argument("--force",   action="store_true", help="Re-fetch even if cached")
    parser.add_argument("--db-only", action="store_true", help="Skip fetch; (re)import from cache only")
    args = parser.parse_args()

    series_config = get_bls_series()

    logger.info("BLS Bulk Download  %s → %s  (%d series)", args.start, args.end, len(series_config))
    for key, cfg in series_config.items():
        cached = "✓ cached" if is_cached(cfg["series_id"]) else "  needs fetch"
        logger.info("  [%-6s] %s  %s", cfg.get("category","?").upper(), cfg["series_id"], cached)

    if args.db_only:
        logger.info("\nDB-only mode — loading from cache, skipping API")
        series_data = {
            cfg["series_id"]: load_cache(cfg["series_id"]) if is_cached(cfg["series_id"]) else []
            for cfg in series_config.values()
        }
    else:
        series_data = fetch_series(series_config, args.start, args.end, force=args.force)

    logger.info("\n── Writing to DB ──")
    counts = process_and_write(series_data, series_config, args.region)

    total_pts = sum(len(v) for v in series_data.values())
    logger.info(
        "\n✓ Done. %d total data points across %d series.\n"
        "  New DB rows → JOLTS: %d  LAUS: %d  CES: %d  CPI/ECI: %d",
        total_pts, len(series_data),
        counts["jolts"], counts["laus"], counts["ces"], counts.get("cpi_eci", 0),
    )

    if counts["jolts"] or counts["laus"]:
        logger.info("\nRecommended next step:")
        logger.info("  python -c \"from core.baseline import compute_baselines; compute_baselines('austin_tx')\"")


if __name__ == "__main__":
    main()
