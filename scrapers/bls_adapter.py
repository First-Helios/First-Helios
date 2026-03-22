"""
BLS (Bureau of Labor Statistics) adapter for ChainStaffingTracker.

Pulls regional wage baselines, turnover benchmarks, occupation wages,
and unemployment from the BLS Public Data API (v1, no key required).

Data categories handled:
  CES  — Current Employment Statistics (MSA employment & wages)
  JOLTS — Job Openings & Labor Turnover (quits/openings/hires rates)
  LAUS  — Local Area Unemployment Statistics (county unemployment)

OEWS (Occupational Employment & Wage Statistics) uses a separate flat-file
download, handled by the companion oews_adapter if needed.

Depends on: requests, config.loader, scrapers.base
Called by: backend/scheduler.py, CLI
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import (
    get_bls_series,
    get_bls_series_by_category,
    get_http_config,
    get_rate_limit,
    get_region,
)
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

BLS_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


class BLSAdapter(BaseScraper):
    """Fetches BLS data across multiple programs (CES, JOLTS, LAUS).

    Uses V1 API (no registration required). Rate limited to 1 req/sec.
    Each program's data is stored in its appropriate table.
    """

    name = "BLS"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limit = get_rate_limit("bls")
        self.http_cfg = get_http_config()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch all BLS data for the region (CES + JOLTS + LAUS).

        Returns ScraperSignal objects for the standard pipeline.
        Also writes to specialized tables (jolts_data, laus_data).
        """
        try:
            all_signals: list[ScraperSignal] = []

            # CES — MSA employment & wage trends (existing behavior)
            ces_signals = self._fetch_ces_series(region)
            all_signals.extend(ces_signals)

            # JOLTS — turnover benchmarks (national, by industry)
            jolts_signals = self._fetch_jolts_series(region)
            all_signals.extend(jolts_signals)

            # LAUS — county unemployment rates
            laus_signals = self._fetch_laus_series(region)
            all_signals.extend(laus_signals)

            logger.info(
                "[%s] Total: %d signals (CES=%d, JOLTS=%d, LAUS=%d) for region=%s",
                self.name, len(all_signals),
                len(ces_signals), len(jolts_signals), len(laus_signals),
                region,
            )
            return all_signals

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_ces_series(self, region: str) -> list[ScraperSignal]:
        """Fetch CES (Current Employment Statistics) series — wages & employment."""
        region_cfg = get_region(region)
        ces_series = get_bls_series_by_category("ces")
        signals: list[ScraperSignal] = []

        for series_key, series_cfg in ces_series.items():
            series_id = series_cfg["series_id"]
            description = series_cfg.get("description", series_key)

            logger.info("[%s] CES: Fetching %s", self.name, description)
            data_points = self._fetch_series(series_id)
            if not data_points:
                continue

            latest = data_points[0]
            value = float(latest.get("value", 0))
            year = latest.get("year", "")
            period = latest.get("period", "")

            signal = ScraperSignal(
                store_num=f"REGIONAL-{region}",
                chain="bls",
                source="bls",
                signal_type="wage",
                value=value,
                metadata={
                    "series_id": series_id,
                    "description": description,
                    "category": "ces",
                    "year": year,
                    "period": period,
                    "all_data": data_points[:12],
                    "store_name": f"BLS {description}",
                    "address": region_cfg["location_string"],
                    "employer": "BLS Regional Average",
                    "is_chain": False,
                    "industry": "food_service",
                    "wage_min": value,
                    "wage_max": value,
                    "wage_period": "hourly" if value < 100 else "yearly",
                },
                observed_at=datetime.utcnow(),
                wage_min=value if value < 100 else None,
                wage_max=value if value < 100 else None,
                wage_period="hourly" if value < 100 else "yearly",
                role_title="Food Service Worker (BLS Average)",
                source_url=f"https://data.bls.gov/timeseries/{series_id}",
            )
            signals.append(signal)
            time.sleep(self.rate_limit.get("delay_seconds", 1.0))

        return signals

    def _fetch_jolts_series(self, region: str) -> list[ScraperSignal]:
        """Fetch JOLTS turnover data and write to jolts_data table.

        JOLTS gives us the expected turnover rate by industry — the benchmark
        that distinguishes normal replacement hiring from staffing stress.
        """
        jolts_series = get_bls_series_by_category("jolts")
        signals: list[ScraperSignal] = []
        jolts_records: list[dict[str, Any]] = []

        for series_key, series_cfg in jolts_series.items():
            series_id = series_cfg["series_id"]
            description = series_cfg.get("description", series_key)
            metric = series_cfg.get("metric", "unknown")
            industry_code = series_cfg.get("industry_code", "")

            logger.info("[%s] JOLTS: Fetching %s", self.name, description)
            data_points = self._fetch_series(series_id)
            if not data_points:
                continue

            # Store last 12 months in the jolts_data table
            for dp in data_points[:12]:
                year = int(dp.get("year", 0))
                period = dp.get("period", "M00")
                month = int(period.replace("M", "")) if period.startswith("M") else 0
                value = float(dp.get("value", 0))

                if month > 0:
                    jolts_records.append({
                        "series_id": series_id,
                        "series_description": description,
                        "metric": metric,
                        "industry_code": industry_code,
                        "year": year,
                        "month": month,
                        "value": value,
                    })

            # Latest value as a signal
            latest = data_points[0]
            latest_val = float(latest.get("value", 0))

            signal = ScraperSignal(
                store_num=f"JOLTS-{industry_code}-{metric}",
                chain="bls",
                source="bls_jolts",
                signal_type="turnover_rate",
                value=latest_val,
                metadata={
                    "series_id": series_id,
                    "description": description,
                    "category": "jolts",
                    "metric": metric,
                    "industry_code": industry_code,
                    "year": latest.get("year"),
                    "period": latest.get("period"),
                    "historical": [
                        {"year": dp["year"], "period": dp["period"], "value": dp["value"]}
                        for dp in data_points[:12]
                    ],
                },
                observed_at=datetime.utcnow(),
                source_url=f"https://data.bls.gov/timeseries/{series_id}",
            )
            signals.append(signal)
            time.sleep(self.rate_limit.get("delay_seconds", 1.0))

        # Write to jolts_data table
        if jolts_records:
            self._write_jolts_records(jolts_records)

        return signals

    def _fetch_laus_series(self, region: str) -> list[ScraperSignal]:
        """Fetch LAUS county unemployment data and write to laus_data table."""
        laus_series = get_bls_series_by_category("laus")
        signals: list[ScraperSignal] = []
        laus_records: list[dict[str, Any]] = []

        for series_key, series_cfg in laus_series.items():
            series_id = series_cfg["series_id"]
            description = series_cfg.get("description", series_key)
            fips_code = series_cfg.get("fips_code", "")

            logger.info("[%s] LAUS: Fetching %s", self.name, description)
            data_points = self._fetch_series(series_id)
            if not data_points:
                continue

            for dp in data_points[:12]:
                year = int(dp.get("year", 0))
                period = dp.get("period", "M00")
                month = int(period.replace("M", "")) if period.startswith("M") else 0
                value = float(dp.get("value", 0))

                if month > 0:
                    laus_records.append({
                        "fips_code": fips_code,
                        "area_title": description,
                        "year": year,
                        "month": month,
                        "unemployment_rate": value,
                        "region": region,
                    })

            latest = data_points[0]
            latest_val = float(latest.get("value", 0))

            signal = ScraperSignal(
                store_num=f"LAUS-{fips_code}",
                chain="bls",
                source="bls_laus",
                signal_type="unemployment_rate",
                value=latest_val,
                metadata={
                    "series_id": series_id,
                    "description": description,
                    "category": "laus",
                    "fips_code": fips_code,
                    "year": latest.get("year"),
                    "period": latest.get("period"),
                },
                observed_at=datetime.utcnow(),
                source_url=f"https://data.bls.gov/timeseries/{series_id}",
            )
            signals.append(signal)
            time.sleep(self.rate_limit.get("delay_seconds", 1.0))

        if laus_records:
            self._write_laus_records(laus_records)

        return signals

    def _fetch_series(self, series_id: str) -> list[dict]:
        """Fetch time series data from BLS V1 API."""
        from backend.tracked_request import check_budget, tracked_get

        if not check_budget("bls_v1"):
            logger.warning("[%s] BLS daily budget exhausted — skipping %s", self.name, series_id)
            return []

        try:
            url = f"{BLS_V1_URL}{series_id}"
            resp = tracked_get(
                "bls_v1", "series_fetch",
                url,
                headers={"User-Agent": self.http_cfg["user_agent"]},
                timeout=self.http_cfg["timeout_seconds"],
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "REQUEST_SUCCEEDED":
                messages = data.get("message", [])
                logger.warning("[%s] BLS API status: %s — %s", self.name, data.get("status"), messages)
                # Detect server-side rate limit hit
                if any("threshold" in str(m).lower() for m in messages):
                    logger.error("[%s] BLS daily limit reached server-side", self.name)
                return []

            series_data = data.get("Results", {}).get("series", [])
            if not series_data:
                return []

            return series_data[0].get("data", [])

        except Exception as e:
            logger.error("[%s] Failed to fetch series %s: %s", self.name, series_id, e)
            return []

    def _write_jolts_records(self, records: list[dict[str, Any]]) -> None:
        """Write JOLTS records to the jolts_data table (upsert)."""
        from backend.database import JOLTSRecord, init_db, get_session

        engine = init_db()
        session = get_session(engine)
        try:
            for rec in records:
                existing = (
                    session.query(JOLTSRecord)
                    .filter_by(
                        series_id=rec["series_id"],
                        year=rec["year"],
                        month=rec["month"],
                    )
                    .first()
                )
                if existing:
                    existing.value = rec["value"]
                    existing.fetched_at = datetime.utcnow()
                else:
                    session.add(JOLTSRecord(
                        series_id=rec["series_id"],
                        series_description=rec.get("series_description"),
                        metric=rec["metric"],
                        industry_code=rec.get("industry_code"),
                        year=rec["year"],
                        month=rec["month"],
                        value=rec["value"],
                        fetched_at=datetime.utcnow(),
                    ))
            session.commit()
            logger.info("[%s] Wrote %d JOLTS records", self.name, len(records))
        except Exception as e:
            session.rollback()
            logger.error("[%s] JOLTS DB write failed: %s", self.name, e)
        finally:
            session.close()

    def _write_laus_records(self, records: list[dict[str, Any]]) -> None:
        """Write LAUS records to the laus_data table (upsert)."""
        from backend.database import LAUSRecord, init_db, get_session

        engine = init_db()
        session = get_session(engine)
        try:
            for rec in records:
                existing = (
                    session.query(LAUSRecord)
                    .filter_by(
                        fips_code=rec["fips_code"],
                        year=rec["year"],
                        month=rec["month"],
                    )
                    .first()
                )
                if existing:
                    existing.unemployment_rate = rec.get("unemployment_rate")
                    existing.fetched_at = datetime.utcnow()
                else:
                    session.add(LAUSRecord(
                        fips_code=rec["fips_code"],
                        area_title=rec.get("area_title"),
                        year=rec["year"],
                        month=rec["month"],
                        unemployment_rate=rec.get("unemployment_rate"),
                        region=rec.get("region"),
                        fetched_at=datetime.utcnow(),
                    ))
            session.commit()
            logger.info("[%s] Wrote %d LAUS records", self.name, len(records))
        except Exception as e:
            session.rollback()
            logger.error("[%s] LAUS DB write failed: %s", self.name, e)
        finally:
            session.close()


def scrape_bls(
    region: str = "austin_tx",
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape BLS and optionally ingest."""
    adapter = BLSAdapter()
    signals = adapter.scrape(region)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain="bls", source="bls")
        logger.info("[BLS] Ingested %d signals", count)

    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Fetch BLS wage data")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_bls(region=args.region, ingest=not args.no_ingest)
    logger.info("Fetched %d BLS signals", len(signals))


if __name__ == "__main__":
    main()
