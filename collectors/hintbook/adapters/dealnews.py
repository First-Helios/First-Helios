"""DealNews — restaurants category. High-volume editorial."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "dealnews"
HOMEPAGE = "https://www.dealnews.com/"
SEED_URLS = [
    "https://www.dealnews.com/c377/Food-Drink/Restaurants/",
    "https://www.dealnews.com/c377/Food-Drink/Restaurants/?sort=3",
]
AGG_HOST = "dealnews.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=40,
    )
