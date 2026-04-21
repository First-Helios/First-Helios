"""BiteHunter — local-venue deal search aggregator.

BiteHunter is partially JS-rendered. The listing pages below are what we can
statically observe; per-deal cards frequently require a renderer. We record
whatever is statically parseable and log the rest as adapter failures so the
harvest report makes the rendering gap visible.
"""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "bitehunter"
HOMEPAGE = "https://www.bitehunter.com/"
SEED_URLS = [
    "https://www.bitehunter.com/",
    "https://www.bitehunter.com/happy-hour",
    "https://www.bitehunter.com/daily-deals",
]
AGG_HOST = "bitehunter.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=20,
    )
