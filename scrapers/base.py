"""
Base scraper interface and ScraperSignal dataclass.

Every scraper in the project inherits from BaseScraper and returns
list[ScraperSignal]. No scraper writes directly to the database —
backend/ingest.py handles all DB writes.

Depends on: config.loader
Called by: each concrete scraper adapter, backend/ingest.py
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScraperSignal:
    """A single observation from any public data source.

    Normalized container that all scrapers produce and the ingestion
    pipeline consumes.
    """

    store_num: str              # "SB-03347" or "REGIONAL-austin_tx" if no specific store
    chain: str                  # "starbucks", "dutch_bros", etc.
    source: str                 # "careers_api", "jobspy", "reddit", "google_maps"
    signal_type: str            # "listing", "wage", "sentiment", "review_score"
    value: float                # normalized 0-1 or raw numeric
    metadata: dict[str, Any] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=datetime.utcnow)

    # Optional fields
    wage_min: float | None = None
    wage_max: float | None = None
    wage_period: str | None = None      # "hourly" or "yearly"
    role_title: str | None = None
    source_url: str | None = None


class BaseScraper(ABC):
    """Abstract base class for all scrapers.

    Concrete implementations must provide:
      - name: str  — human-readable name for logs
      - scrape(region, radius_mi) -> list[ScraperSignal]

    The scrape() method must catch all exceptions internally and return
    an empty list on failure. The server must stay up even if every
    scraper is down.
    """

    name: str = "BaseScraper"

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"scrapers.{self.name}")

    @abstractmethod
    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape public data and return normalized signals.

        Args:
            region: Region key from config, e.g. 'austin_tx'.
            radius_mi: Search radius in miles.

        Returns:
            List of ScraperSignal objects. Empty list on failure.
        """
        ...
