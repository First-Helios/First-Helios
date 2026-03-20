"""
BLS (Bureau of Labor Statistics) adapter for ChainStaffingTracker.

Pulls regional wage baseline data from the BLS Public Data API (v1, no key required).
Produces ScraperSignal objects with wage data that feeds into the wage_index table.

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

from config.loader import get_bls_series, get_http_config, get_rate_limit, get_region
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)

BLS_V1_URL = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


class BLSAdapter(BaseScraper):
    """Fetches BLS wage data for regional labor market context.

    Uses V1 API (no registration required). Rate limited to 1 req/sec.
    """

    name = "BLS"

    def __init__(self) -> None:
        super().__init__()
        self.rate_limit = get_rate_limit("bls")
        self.http_cfg = get_http_config()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Fetch BLS wage data for the region.

        Args:
            region: Region key from config.
            radius_mi: Not used for BLS, included for interface compatibility.

        Returns:
            List of ScraperSignal objects. Empty on failure.
        """
        try:
            region_cfg = get_region(region)
            bls_series = get_bls_series()
            all_signals: list[ScraperSignal] = []

            for series_key, series_cfg in bls_series.items():
                series_id = series_cfg["series_id"]
                description = series_cfg.get("description", series_key)

                logger.info("[%s] Fetching series %s: %s", self.name, series_id, description)

                data_points = self._fetch_series(series_id)
                if not data_points:
                    continue

                # Get most recent data point
                latest = data_points[0]  # BLS returns newest first
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
                        "year": year,
                        "period": period,
                        "all_data": data_points[:12],  # last 12 months
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
                all_signals.append(signal)

                time.sleep(self.rate_limit.get("delay_seconds", 1.0))

            logger.info("[%s] Fetched %d BLS signals for region=%s", self.name, len(all_signals), region)
            return all_signals

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_series(self, series_id: str) -> list[dict]:
        """Fetch time series data from BLS V1 API."""
        try:
            url = f"{BLS_V1_URL}{series_id}"
            resp = requests.get(
                url,
                headers={"User-Agent": self.http_cfg["user_agent"]},
                timeout=self.http_cfg["timeout_seconds"],
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") != "REQUEST_SUCCEEDED":
                logger.warning("[%s] BLS API status: %s", self.name, data.get("status"))
                return []

            series_data = data.get("Results", {}).get("series", [])
            if not series_data:
                return []

            return series_data[0].get("data", [])

        except Exception as e:
            logger.error("[%s] Failed to fetch series %s: %s", self.name, series_id, e)
            return []


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
