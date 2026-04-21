"""Hip2Save — restaurants / food section."""

from collectors.hintbook.listing_walker import run_listing_walk
from collectors.hintbook.models import HarvestReport

NAME = "hip2save"
HOMEPAGE = "https://hip2save.com/"
SEED_URLS = [
    "https://hip2save.com/sales-deals/restaurants/",
    "https://hip2save.com/category/restaurants/",
    "https://hip2save.com/category/food-deals/",
]
AGG_HOST = "hip2save.com"


def collect(report: HarvestReport) -> None:
    run_listing_walk(
        report=report,
        adapter_name=NAME,
        aggregator_host=AGG_HOST,
        seeds=SEED_URLS,
        industry="food",
        max_articles=30,
    )
