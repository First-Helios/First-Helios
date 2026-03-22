"""
QCEW (Quarterly Census of Employment & Wages) adapter.

Fetches county-level establishment counts, employment, and wages by NAICS
from the BLS QCEW public data files.  This is **Tier 1 ground truth** —
the authoritative denominator for all posting-based metrics.

Release cycle: Quarterly, ~6 month lag.
  Q1 (Jan-Mar) → released ~September
  Q2 (Apr-Jun) → released ~December
  Q3 (Jul-Sep) → released ~March
  Q4 (Oct-Dec) → released ~June

API: https://data.bls.gov/cew/data/api/
  GET /YEAR/QUARTER/area/FIPS.csv
  GET /YEAR/QUARTER/industry/NAICS.csv

No API key required.  No rate limit documented but we pace at 1 req/sec.

Depends on: requests, config.loader, backend.database
Called by: backend/scheduler.py
"""

import argparse
import csv
import io
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import (
    get_http_config,
    get_qcew_config,
    get_qcew_county_fips,
    get_qcew_naics_codes,
    get_rate_limit,
)
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

QCEW_BASE_URL = "https://data.bls.gov/cew/data/api"


class QCEWAdapter(BaseScraper):
    """Fetches QCEW establishment/employment data by county and NAICS.

    Strategy: For each county FIPS in the Austin MSA, fetch the area CSV
    and extract rows matching our target NAICS codes.  This gives us:
      - Number of establishments
      - Monthly employment (months 1-3 of the quarter)
      - Total and average wages
    """

    name = "QCEW"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limit = get_rate_limit("bls")
        self.http_cfg = get_http_config()
        self.qcew_cfg = get_qcew_config()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch QCEW data for all configured counties and NAICS codes.

        Returns ScraperSignal objects with signal_type='establishment_count'.
        The real data goes into the qcew_data table via ingest_qcew().
        """
        try:
            county_fips = self.qcew_cfg["county_fips"]
            naics_codes = self.qcew_cfg["naics_codes"]
            ownership = self.qcew_cfg.get("ownership_code", "5")

            # Determine which quarter to fetch.
            # QCEW has ~6 month lag, so look back 2 quarters.
            now = datetime.utcnow()
            target_year, target_quarter = self._latest_available_quarter(now)

            all_signals: list[ScraperSignal] = []
            all_records: list[dict[str, Any]] = []

            for county_name, fips in county_fips.items():
                logger.info(
                    "[%s] Fetching %s (FIPS %s) for %dQ%d",
                    self.name, county_name, fips, target_year, target_quarter,
                )

                rows = self._fetch_area_csv(fips, target_year, target_quarter)
                if not rows:
                    # Try one quarter earlier
                    y2, q2 = self._prev_quarter(target_year, target_quarter)
                    logger.info("[%s] Trying fallback %dQ%d", self.name, y2, q2)
                    rows = self._fetch_area_csv(fips, y2, q2)
                    if rows:
                        target_year, target_quarter = y2, q2

                if not rows:
                    logger.warning("[%s] No data for %s", self.name, county_name)
                    continue

                # Filter to target NAICS codes and private ownership
                for naics_key, naics_code in naics_codes.items():
                    matching = [
                        r for r in rows
                        if r.get("industry_code", "").startswith(naics_code)
                        and r.get("own_code") == ownership
                    ]

                    for row in matching:
                        record = self._parse_row(row, fips, region, target_year, target_quarter)
                        if record:
                            all_records.append(record)

                            # Also produce a ScraperSignal for the standard pipeline
                            est_count = record.get("establishments", 0) or 0
                            signal = ScraperSignal(
                                store_num=f"QCEW-{fips}-{record['naics_code']}",
                                chain="bls",
                                source="qcew",
                                signal_type="establishment_count",
                                value=float(est_count),
                                metadata={
                                    "fips_code": fips,
                                    "county_name": county_name,
                                    "naics_code": record["naics_code"],
                                    "naics_title": record.get("naics_title", ""),
                                    "year": target_year,
                                    "quarter": target_quarter,
                                    "establishments": est_count,
                                    "avg_employment": record.get("avg_employment"),
                                    "avg_weekly_wage": record.get("avg_weekly_wage"),
                                    "avg_annual_pay": record.get("avg_annual_pay"),
                                },
                                observed_at=datetime.utcnow(),
                            )
                            all_signals.append(signal)

                time.sleep(self.rate_limit.get("delay_seconds", 1.0))

            # Write to qcew_data table
            if all_records:
                self._write_qcew_records(all_records, region)

            logger.info(
                "[%s] Fetched %d QCEW records, %d signals for %dQ%d",
                self.name, len(all_records), len(all_signals),
                target_year, target_quarter,
            )
            return all_signals

        except Exception as e:
            logger.error("[%s] Failed: %s", self.name, e)
            return []

    def _fetch_area_csv(
        self, fips: str, year: int, quarter: int
    ) -> list[dict[str, str]]:
        """Fetch QCEW CSV for a county-quarter from BLS API."""
        from backend.tracked_request import check_budget, tracked_get

        if not check_budget("bls_v1"):
            logger.warning("[%s] BLS budget exhausted", self.name)
            return []

        # QCEW API: /YEAR/Q/area/FIPS.csv
        url = f"{QCEW_BASE_URL}/{year}/{quarter}/area/{fips}.csv"
        try:
            resp = tracked_get(
                "bls_v1", "qcew_area_fetch",
                url,
                headers={"User-Agent": self.http_cfg["user_agent"]},
                timeout=self.http_cfg["timeout_seconds"],
            )
            if resp.status_code == 404:
                logger.info("[%s] No data at %s", self.name, url)
                return []
            resp.raise_for_status()

            # Parse CSV
            reader = csv.DictReader(io.StringIO(resp.text))
            return list(reader)

        except Exception as e:
            logger.error("[%s] Failed to fetch %s: %s", self.name, url, e)
            return []

    def _parse_row(
        self,
        row: dict[str, str],
        fips: str,
        region: str,
        year: int,
        quarter: int,
    ) -> dict[str, Any] | None:
        """Parse a QCEW CSV row into a record dict."""
        try:
            return {
                "fips_code": fips,
                "naics_code": row.get("industry_code", "").strip(),
                "naics_title": row.get("industry_title", "").strip(),
                "year": year,
                "quarter": quarter,
                "ownership_code": row.get("own_code", "5"),
                "establishments": _safe_int(row.get("qtrly_estabs")),
                "month1_employment": _safe_int(row.get("month1_emplvl")),
                "month2_employment": _safe_int(row.get("month2_emplvl")),
                "month3_employment": _safe_int(row.get("month3_emplvl")),
                "total_wages": _safe_float(row.get("total_qtrly_wages")),
                "avg_weekly_wage": _safe_float(row.get("avg_wkly_wage")),
                "avg_annual_pay": _safe_float(row.get("avg_annual_pay")),
                "region": region,
            }
        except Exception as e:
            logger.warning("[%s] Failed to parse row: %s", self.name, e)
            return None

    def _write_qcew_records(self, records: list[dict[str, Any]], region: str) -> None:
        """Write QCEW records to the qcew_data table (upsert)."""
        from backend.database import QCEWRecord, init_db, get_session

        engine = init_db()
        session = get_session(engine)
        try:
            for rec in records:
                existing = (
                    session.query(QCEWRecord)
                    .filter_by(
                        fips_code=rec["fips_code"],
                        naics_code=rec["naics_code"],
                        year=rec["year"],
                        quarter=rec["quarter"],
                        ownership_code=rec.get("ownership_code", "5"),
                    )
                    .first()
                )
                if existing:
                    existing.establishments = rec.get("establishments")
                    existing.month1_employment = rec.get("month1_employment")
                    existing.month2_employment = rec.get("month2_employment")
                    existing.month3_employment = rec.get("month3_employment")
                    existing.total_wages = rec.get("total_wages")
                    existing.avg_weekly_wage = rec.get("avg_weekly_wage")
                    existing.avg_annual_pay = rec.get("avg_annual_pay")
                    existing.fetched_at = datetime.utcnow()
                else:
                    session.add(QCEWRecord(
                        fips_code=rec["fips_code"],
                        naics_code=rec["naics_code"],
                        naics_title=rec.get("naics_title"),
                        year=rec["year"],
                        quarter=rec["quarter"],
                        ownership_code=rec.get("ownership_code", "5"),
                        establishments=rec.get("establishments"),
                        month1_employment=rec.get("month1_employment"),
                        month2_employment=rec.get("month2_employment"),
                        month3_employment=rec.get("month3_employment"),
                        total_wages=rec.get("total_wages"),
                        avg_weekly_wage=rec.get("avg_weekly_wage"),
                        avg_annual_pay=rec.get("avg_annual_pay"),
                        region=region,
                        fetched_at=datetime.utcnow(),
                    ))
            session.commit()
            logger.info("[%s] Wrote %d QCEW records", self.name, len(records))
        except Exception as e:
            session.rollback()
            logger.error("[%s] DB write failed: %s", self.name, e)
        finally:
            session.close()

    @staticmethod
    def _latest_available_quarter(now: datetime) -> tuple[int, int]:
        """Estimate the most recent QCEW quarter likely available (~6mo lag)."""
        # Subtract ~6 months
        month = now.month - 6
        year = now.year
        if month <= 0:
            month += 12
            year -= 1
        quarter = (month - 1) // 3 + 1
        return year, quarter

    @staticmethod
    def _prev_quarter(year: int, quarter: int) -> tuple[int, int]:
        """Return the quarter before the given one."""
        if quarter == 1:
            return year - 1, 4
        return year, quarter - 1


def _safe_int(val: str | None) -> int | None:
    """Safely convert a string to int, returning None on failure."""
    if val is None:
        return None
    try:
        # QCEW values can have commas
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_float(val: str | None) -> float | None:
    """Safely convert a string to float."""
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def scrape_qcew(region: str = "austin_tx", ingest: bool = True) -> list[ScraperSignal]:
    """Convenience function to fetch QCEW data and optionally ingest signals."""
    adapter = QCEWAdapter()
    signals = adapter.scrape(region)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain="bls", source="qcew")
        logger.info("[QCEW] Ingested %d signals", count)

    return signals


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Fetch QCEW establishment data")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_qcew(region=args.region, ingest=not args.no_ingest)
    logger.info("Fetched %d QCEW signals", len(signals))


if __name__ == "__main__":
    main()
