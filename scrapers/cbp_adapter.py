"""
Census County Business Patterns (CBP) adapter.

Fetches ZIP-code level establishment counts and employment by NAICS
from the Census Bureau API.  This is **Tier 1 ground truth** that gives
sub-metro geographic granularity for density metrics.

Release cycle: Annual, ~18 month lag.
  2023 data released mid-2025.

API: https://api.census.gov/data/2023/cbp
  GET ?get=ESTAB,EMP,PAYANN&for=zipcode:78701&NAICS2017=722515&key=YOUR_KEY

Free API key required: https://api.census.gov/data/key_signup.html
Can also be passed via CBP_API_KEY environment variable.

Depends on: requests, config.loader, backend.database
Called by: backend/scheduler.py
"""

import argparse
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
    get_cbp_config,
    get_cbp_naics_codes,
    get_cbp_zip_codes,
    get_http_config,
    get_rate_limit,
)
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

CBP_BASE_URL = "https://api.census.gov/data"


class CBPAdapter(BaseScraper):
    """Fetches Census County Business Patterns data by ZIP and NAICS.

    Provides establishment counts at ZIP-code level — much finer than
    QCEW's county level.  Used for sub-metro density analysis.
    """

    name = "CBP"

    def __init__(self) -> None:
        super().__init__()
        self.cbp_cfg = get_cbp_config()
        self.http_cfg = get_http_config()
        self.rate_limit = get_rate_limit("bls")

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch CBP data for configured ZIP codes and NAICS codes.

        Returns ScraperSignal objects with signal_type='zip_establishments'.
        """
        try:
            api_key = self.cbp_cfg.get("api_key")
            if not api_key:
                logger.warning("[%s] No Census API key configured — skipping CBP fetch", self.name)
                return []

            zip_codes = get_cbp_zip_codes()
            naics_codes = get_cbp_naics_codes()

            # Determine latest CBP dataset year (~18 month lag)
            now = datetime.utcnow()
            dataset_year = self._latest_available_year(now)

            all_signals: list[ScraperSignal] = []
            all_records: list[dict[str, Any]] = []

            for naics_key, naics_code in naics_codes.items():
                logger.info(
                    "[%s] Fetching NAICS %s (%s) for %d, %d ZIPs",
                    self.name, naics_code, naics_key, dataset_year, len(zip_codes),
                )

                # Census API allows batching ZIPs
                records = self._fetch_cbp_batch(
                    zip_codes, naics_code, dataset_year, api_key
                )

                for rec in records:
                    all_records.append(rec)

                    est_count = rec.get("establishments", 0) or 0
                    signal = ScraperSignal(
                        store_num=f"CBP-{rec['zip_code']}-{naics_code}",
                        chain="census",
                        source="cbp",
                        signal_type="zip_establishments",
                        value=float(est_count),
                        metadata={
                            "zip_code": rec["zip_code"],
                            "naics_code": naics_code,
                            "naics_key": naics_key,
                            "year": dataset_year,
                            "establishments": est_count,
                            "employment": rec.get("employment"),
                            "annual_payroll_k": rec.get("annual_payroll_k"),
                        },
                        observed_at=datetime.utcnow(),
                    )
                    all_signals.append(signal)

                time.sleep(self.rate_limit.get("delay_seconds", 1.0))

            # Write to cbp_data table
            if all_records:
                self._write_cbp_records(all_records, region, dataset_year)

            logger.info(
                "[%s] Fetched %d CBP records, %d signals for year %d",
                self.name, len(all_records), len(all_signals), dataset_year,
            )
            return all_signals

        except Exception as e:
            logger.error("[%s] Failed: %s", self.name, e)
            return []

    def _fetch_cbp_batch(
        self,
        zip_codes: list[str],
        naics_code: str,
        year: int,
        api_key: str,
    ) -> list[dict[str, Any]]:
        """Fetch CBP for a batch of ZIP codes via Census API.

        The Census API accepts comma-separated ZIP codes in the 'for' param.
        We batch in groups of 50 to stay within URL length limits.
        """
        from backend.tracked_request import check_budget, tracked_get

        records: list[dict[str, Any]] = []
        batch_size = 50

        for i in range(0, len(zip_codes), batch_size):
            batch = zip_codes[i:i + batch_size]
            zip_str = ",".join(batch)

            if not check_budget("census_cbp"):
                logger.warning("[%s] Census budget exhausted", self.name)
                break

            url = f"{CBP_BASE_URL}/{year}/cbp"
            params = {
                "get": "ESTAB,EMP,PAYANN,EMP_NF",
                "for": f"zipcode:{zip_str}",
                "NAICS2017": naics_code,
                "key": api_key,
            }

            try:
                resp = tracked_get(
                    "census_cbp", "cbp_zip_fetch",
                    url, params=params,
                    headers={"User-Agent": self.http_cfg["user_agent"]},
                    timeout=self.http_cfg["timeout_seconds"],
                )
                if resp.status_code == 204:
                    continue  # no data for this NAICS/ZIP combo
                if resp.status_code == 404:
                    # Try previous year
                    logger.info("[%s] Year %d not available, trying %d", self.name, year, year - 1)
                    params_prev = dict(params)
                    url_prev = f"{CBP_BASE_URL}/{year - 1}/cbp"
                    resp = tracked_get(
                        "census_cbp", "cbp_zip_fetch",
                        url_prev, params=params_prev,
                        headers={"User-Agent": self.http_cfg["user_agent"]},
                        timeout=self.http_cfg["timeout_seconds"],
                    )
                    if not resp.ok:
                        continue

                resp.raise_for_status()
                data = resp.json()

                # Census API returns [header_row, data_row1, data_row2, ...]
                if not data or len(data) < 2:
                    continue

                headers = data[0]
                for row in data[1:]:
                    row_dict = dict(zip(headers, row))
                    records.append({
                        "zip_code": row_dict.get("zipcode", ""),
                        "naics_code": naics_code,
                        "year": year,
                        "establishments": _safe_int(row_dict.get("ESTAB")),
                        "employment": _safe_int(row_dict.get("EMP")),
                        "employment_noise_flag": row_dict.get("EMP_NF", ""),
                        "annual_payroll_k": _safe_float(row_dict.get("PAYANN")),
                    })

            except Exception as e:
                logger.error("[%s] Batch fetch failed: %s", self.name, e)

            time.sleep(self.rate_limit.get("delay_seconds", 1.0))

        return records

    def _write_cbp_records(
        self, records: list[dict[str, Any]], region: str, year: int
    ) -> None:
        """Write CBP records to the cbp_data table (upsert)."""
        from backend.database import CBPRecord, init_db, get_session

        engine = init_db()
        session = get_session(engine)
        try:
            for rec in records:
                existing = (
                    session.query(CBPRecord)
                    .filter_by(
                        zip_code=rec["zip_code"],
                        naics_code=rec["naics_code"],
                        year=rec["year"],
                    )
                    .first()
                )
                if existing:
                    existing.establishments = rec.get("establishments")
                    existing.employment = rec.get("employment")
                    existing.employment_noise_flag = rec.get("employment_noise_flag")
                    existing.annual_payroll_k = rec.get("annual_payroll_k")
                    existing.fetched_at = datetime.utcnow()
                else:
                    session.add(CBPRecord(
                        zip_code=rec["zip_code"],
                        naics_code=rec["naics_code"],
                        year=rec["year"],
                        establishments=rec.get("establishments"),
                        employment=rec.get("employment"),
                        employment_noise_flag=rec.get("employment_noise_flag"),
                        annual_payroll_k=rec.get("annual_payroll_k"),
                        region=region,
                        fetched_at=datetime.utcnow(),
                    ))
            session.commit()
            logger.info("[%s] Wrote %d CBP records", self.name, len(records))
        except Exception as e:
            session.rollback()
            logger.error("[%s] DB write failed: %s", self.name, e)
        finally:
            session.close()

    @staticmethod
    def _latest_available_year(now: datetime) -> int:
        """Estimate the latest available CBP year (~18 month lag)."""
        # If we're past June, the previous year's data is likely available
        if now.month >= 6:
            return now.year - 1
        return now.year - 2


def _safe_int(val: str | None) -> int | None:
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def _safe_float(val: str | None) -> float | None:
    if val is None:
        return None
    try:
        return float(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def scrape_cbp(region: str = "austin_tx", ingest: bool = True) -> list[ScraperSignal]:
    """Convenience function to fetch CBP data."""
    adapter = CBPAdapter()
    signals = adapter.scrape(region)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain="census", source="cbp")
        logger.info("[CBP] Ingested %d signals", count)

    return signals


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Fetch Census CBP establishment data")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_cbp(region=args.region, ingest=not args.no_ingest)
    logger.info("Fetched %d CBP signals", len(signals))


if __name__ == "__main__":
    main()
